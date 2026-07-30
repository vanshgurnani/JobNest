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
from app.schemas.job import Job, JobDetailResponse, JobListResponse, canonicalize_job
from scrapers.crawlers.monitoring.metrics import metrics
from scrapers.crawlers.monitoring.audit import audit
from scrapers.utils import supported_companies

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["jobs"])

_WEBHOOKS: list[dict[str, Any]] = []


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

# Lazily imported scraper
_scraper_module = None

async def _get_scraper():
    global _scraper_module
    if _scraper_module is None:
        import importlib
        _scraper_module = importlib.import_module("scrapers.scrape_jobs")
    return _scraper_module


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
        if not companies:
            companies = [c.title() for c in supported_companies()]
    except RuntimeError:
        companies = [c.title() for c in supported_companies()]
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
        return {**cached, "cache": "memory"}

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
        raise HTTPException(status_code=503, detail="Job database is not available")

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
        return {**cached, "cache": "memory"}

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
        raise HTTPException(status_code=503, detail="Job database is not available")

    return await _cache_response(cache_key, {
        "company": jobs[0].get("company", company.title()) if jobs else company.title(),
        "total": total,
        "jobs": jobs,
        "page": page,
        "limit": limit,
        "cache": "mongo",
    })


@router.post("/scrape")
async def run_scrape(request: Request) -> dict:
    body = await request.json()
    companies_str = (body.get("companies") or "").strip()
    urls_str = (body.get("company_url") or "").strip()
    keyword = (body.get("keyword") or "").strip() or None
    location = (body.get("location") or "").strip() or None
    pages = int(body.get("pages", 2))
    page_size = int(body.get("page_size", 20))
    delay = float(body.get("delay_seconds", 0.5))
    mode = (body.get("mode") or "local").strip().lower()
    use_playwright = bool(body.get("playwright", False))

    mod = await _get_scraper()
    companies = [c.strip().lower() for c in companies_str.split(",") if c.strip()] if companies_str else mod.supported_companies()
    urls = [u.strip() for u in urls_str.split(",") if u.strip()] if urls_str else []
    if not companies and not urls:
        companies = mod.supported_companies()

    all_results: list[dict[str, Any]] = []

    if mode == "db":
        try:
            from app.db.mongo import connect_mongo
            await connect_mongo()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"MongoDB connection failed: {exc}")

    async def _scrape_one(target: str, *, is_url: bool = False) -> dict[str, Any]:
        start = time.monotonic()
        metrics.record_attempt(target)
        try:
            jobs = await mod._scrape_company(
                None if is_url else target,
                company_url=target if is_url else None,
                keyword=keyword,
                location=location,
                pages=pages,
                page_size=page_size,
                delay_seconds=delay,
                use_playwright=use_playwright,
            )
            job_count = len(jobs)
            duration = time.monotonic() - start
            metrics.record_success(target, job_count, "scrape", duration)
            audit.record(target, duration, job_count, "scrape")
            logger.info("Scraped %s: %d jobs", target, job_count)
            if mode == "db" and jobs:
                from app.services.job_store import upsert_jobs
                await upsert_jobs(jobs)
            return {"target": target, "jobs": jobs, "count": job_count}
        except Exception as e:
            duration = time.monotonic() - start
            metrics.record_failure(target)
            audit.record(target, duration, 0, "scrape", str(e))
            raise

    batch = companies + urls
    if len(batch) > 1:
        results = await asyncio.gather(*[_scrape_one(c) for c in companies] + [_scrape_one(u, is_url=True) for u in urls], return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error("Parallel scrape failed: %s", r)
            else:
                all_results.append(r)
    else:
        for company in companies:
            all_results.append(await _scrape_one(company))
        for url in urls:
            all_results.append(await _scrape_one(url, is_url=True))

    if mode == "db":
        try:
            from app.db.mongo import close_mongo
            await close_mongo()
        except Exception:
            pass

    total = sum(r["count"] for r in all_results)
    for r in all_results:
        await _notify_webhooks(r["target"], r["count"])
    return {"results": all_results, "total": total, "mode": mode}


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


@router.get("/metrics")
async def get_metrics() -> dict:
    return {"scrape_summary": metrics.summary(), "audit_recent": audit.recent(), "audit_failures": audit.failures()}


@router.get("/metrics/prometheus")
async def prometheus_metrics() -> str:
    return metrics.prometheus()


@router.get("/job/{job_id}", response_model=JobDetailResponse)
async def get_job_detail(job_id: str):
    cache_key = build_cache_key(route="job_detail", job_id=job_id)
    cached = await crawl_cache.get(cache_key)
    if cached is not None:
        return {**cached, "cache": "memory"}

    try:
        job = await find_job_by_id(job_id)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Job detail storage is not available")

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return await _cache_response(cache_key, {"job": job, "cache": "mongo"})
