import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from app.services.cache import build_cache_key, crawl_cache
from app.services.job_store import find_companies, find_job_by_id, find_jobs
from app.services.security import is_safe_url
from app.services.go_crawler import crawl_with_go
from app.schemas.job import Job, JobDetailResponse, JobListResponse, canonicalize_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["jobs"])

_WEBHOOKS: list[dict[str, Any]] = []

_CLIENT_LOGS: list[dict[str, Any]] = []


async def _notify_webhooks(target: str, count: int) -> None:
    if not _WEBHOOKS:
        return
    payload = {"target": target, "jobs_count": count, "timestamp": datetime.utcnow().isoformat()}
    async with httpx.AsyncClient(timeout=10) as c:
        for wh in _WEBHOOKS:
            try:
                await c.post(wh["url"], json=payload)
            except Exception:
                pass

_MAX_SEARCH_LENGTH = 200



def _validate_search_param(value: Optional[str], name: str) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) > _MAX_SEARCH_LENGTH:
        raise HTTPException(status_code=400, detail=f"{name} exceeds maximum length")
    return stripped


async def _validate_company_url(url: Optional[str]) -> Optional[str]:
    if url is None:
        return None
    if len(url) > 2048:
        raise HTTPException(status_code=400, detail="company_url exceeds maximum length")
    safe, reason = await is_safe_url(url)
    if not safe:
        raise HTTPException(status_code=400, detail=f"Invalid company_url: {reason}")
    return url


@router.get("/companies")
async def get_companies() -> dict:
    try:
        companies = await find_companies()

    except RuntimeError:
        logger.warning("find_companies failed; MongoDB unavailable")
        raise HTTPException(status_code=503, detail="Job database is not available")
    logger.info("GET /companies returned %d companies", len(companies))
    return {"companies": companies}


async def _cache_response(key: str, payload: dict) -> dict:
    await crawl_cache.set(key, payload)
    return payload


@router.get("/jobs", response_model=JobListResponse)
async def get_jobs(
    company: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    company_url: Optional[str] = Query(default=None, max_length=2048),
    keyword: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    location: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    employment_type: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    experience: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    company_valid = _validate_search_param(company, "Company")
    company_url_valid = await _validate_company_url(company_url)
    keyword_valid = _validate_search_param(keyword, "Keyword")
    location_valid = _validate_search_param(location, "Location")
    employment_type_valid = _validate_search_param(employment_type, "EmploymentType")
    experience_valid = _validate_search_param(experience, "Experience")

    cache_key = build_cache_key(
        route="jobs",
        company=company_valid,
        company_url=company_url_valid,
        keyword=keyword_valid,
        location=location_valid,
        employment_type=employment_type_valid,
        experience=experience_valid,
        page=page,
        limit=limit,
    )

    cached = await crawl_cache.get(cache_key)
    if cached is not None:
        logger.info("GET /jobs cache hit for key=%s", cache_key)
        return {**cached, "cache": "memory"}

    # Preserve the legacy company_url workflow, but delegate all fetching to Go.
    if company_url_valid:
        await crawl_with_go(url=company_url_valid, company=company_valid, save=True)

    try:
        jobs, total = await find_jobs(
            company=company_valid,
            keyword=keyword_valid,
            location=location_valid,
            employment_type=employment_type_valid,
            experience=experience_valid,
            page=page,
            limit=limit,
            fresh_only=False,
        )
    except RuntimeError:
        logger.warning("GET /jobs DB unavailable for key=%s", cache_key)
        raise HTTPException(status_code=503, detail="Job database is not available")

    logger.info("GET /jobs query resolved: total=%d returned=%d (key=%s)", total, len(jobs), cache_key)
    return await _cache_response(cache_key, {
        "total": total,
        "latest_jobs": jobs,
        "jobs": jobs,
        "page": page,
        "limit": limit,
        "cache": "live",
    })


@router.get("/jobs/{company}", response_model=JobListResponse)
async def get_company_jobs(
    company: str,
    company_url: Optional[str] = Query(default=None, max_length=2048),
    keyword: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    location: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    employment_type: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    experience: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    company_key = _validate_search_param(company, "Company")
    company_url_valid = await _validate_company_url(company_url)
    keyword_valid = _validate_search_param(keyword, "Keyword")
    location_valid = _validate_search_param(location, "Location")
    employment_type_valid = _validate_search_param(employment_type, "EmploymentType")
    experience_valid = _validate_search_param(experience, "Experience")

    cache_key = build_cache_key(
        route="company_jobs",
        company=company_key,
        company_url=company_url_valid,
        keyword=keyword_valid,
        location=location_valid,
        employment_type=employment_type_valid,
        experience=experience_valid,
        page=page,
        limit=limit,
    )

    cached = await crawl_cache.get(cache_key)
    if cached is not None:
        logger.info("GET /jobs/%s cache hit for key=%s", company_key, cache_key)
        return {**cached, "cache": "memory"}

    # Existing clients can keep sending company_url; Go owns the crawl.
    if company_url_valid:
        await crawl_with_go(url=company_url_valid, company=company_key, save=True)

    try:
        jobs, total = await find_jobs(
            company=company_key,
            keyword=keyword_valid,
            location=location_valid,
            employment_type=employment_type_valid,
            experience=experience_valid,
            page=page,
            limit=limit,
            fresh_only=False,
        )
    except RuntimeError:
        logger.warning("GET /jobs/%s DB unavailable", company_key)
        raise HTTPException(status_code=503, detail="Job database is not available")

    logger.info("GET /jobs/%s resolved: total=%d returned=%d", company_key, total, len(jobs))
    return await _cache_response(cache_key, {
        "company": jobs[0].get("company", company.title()) if jobs else company.title(),
        "total": total,
        "jobs": jobs,
        "page": page,
        "limit": limit,
        "cache": "mongo",
    })


@router.post("/scrape")
async def legacy_scrape_disabled() -> dict:
    raise HTTPException(
        status_code=410,
        detail="Python scraper removed. Submit a public careers/job URL to POST /crawler/scan.",
    )


@router.post("/push-to-db")
async def push_to_db(request: Request) -> dict:
    body = await request.json()
    jobs = body.get("jobs", [])
    if not jobs:
        logger.warning("POST /push-to-db called with no jobs")
        raise HTTPException(status_code=400, detail="No jobs provided")

    logger.info("POST /push-to-db received %d jobs", len(jobs))
    try:
        from app.db.mongo import connect_mongo
        await connect_mongo()
    except Exception as exc:
        logger.error("POST /push-to-db MongoDB connection failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"MongoDB connection failed: {exc}")

    saved = 0
    try:
        from app.services.job_store import upsert_jobs
        canonicalized = []
        for j in jobs:
            from app.schemas.job import canonicalize_job
            canonicalized.append(canonicalize_job(j))
        await upsert_jobs(canonicalized)
        saved = len(canonicalized)
        logger.info("Pushed %d jobs to database (upsert)", saved)
    except Exception as exc:
        logger.exception("Failed to save %d jobs: %s", len(jobs), exc)
        raise HTTPException(status_code=500, detail=f"Failed to save jobs: {exc}")
    finally:
        from app.db.mongo import close_mongo
        await close_mongo()

    return {"saved": saved}


@router.post("/logs")
async def ingest_client_logs(request: Request) -> dict:
    body = await request.json()
    entries = body.get("logs", []) if isinstance(body, dict) else body
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="Invalid logs payload")

    accepted = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        level = str(entry.get("level", "info")).upper()
        message = str(entry.get("message", "")).strip()
        if not message:
            continue
        _CLIENT_LOGS.append({
            "level": level,
            "message": message,
            "source": str(entry.get("source", "client"))[:200],
            "timestamp": entry.get("timestamp", datetime.utcnow().isoformat()),
            "url": str(entry.get("url", ""))[:500],
        })
        getattr(logger, level.lower(), logger.info)("[CLIENT] %s", message)
        accepted += 1

    if len(_CLIENT_LOGS) > 2000:
        del _CLIENT_LOGS[: len(_CLIENT_LOGS) - 2000]

    logger.info("POST /logs accepted %d/%d client log entries", accepted, len(entries))
    return {"accepted": accepted}


@router.get("/logs")
async def list_client_logs(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    return {"logs": _CLIENT_LOGS[-limit:], "count": len(_CLIENT_LOGS)}


@router.post("/webhooks")
async def register_webhook(request: Request) -> dict:
    body = await request.json()
    url = body.get("url", "").strip()
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Valid webhook URL required")
    _WEBHOOKS.append({"url": url, "created_at": datetime.utcnow().isoformat()})
    logger.info("Webhook registered: %s", url)
    return {"status": "registered", "webhooks_count": len(_WEBHOOKS)}


@router.get("/webhooks")
async def list_webhooks() -> dict:
    return {"webhooks": [{"url": w["url"], "created_at": w["created_at"]} for w in _WEBHOOKS], "count": len(_WEBHOOKS)}


@router.get("/job/{job_id}", response_model=JobDetailResponse)
async def get_job_detail(job_id: str):
    cache_key = build_cache_key(route="job_detail", job_id=job_id)
    cached = await crawl_cache.get(cache_key)
    if cached is not None:
        logger.info("GET /job/%s cache hit", job_id)
        return {**cached, "cache": "memory"}

    try:
        job = await find_job_by_id(job_id)
    except RuntimeError:
        logger.warning("GET /job/%s DB unavailable", job_id)
        raise HTTPException(status_code=503, detail="Job detail storage is not available")

    if not job:
        logger.info("GET /job/%s not found", job_id)
        raise HTTPException(status_code=404, detail="Job not found")

    return await _cache_response(cache_key, {"job": job, "cache": "mongo"})
