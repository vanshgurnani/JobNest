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


@router.post("/crawl")
async def crawl_company(request: Request) -> dict:
    """Run one discovery/detection/adapter crawl through the service boundary."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    company = str(body.get("company") or body.get("company_name") or "").strip() or None
    target_url = str(body.get("company_url") or body.get("domain") or "").strip() or None
    if not company and not target_url:
        raise HTTPException(status_code=400, detail="company, domain, or company_url is required")
    target_url = await _validate_company_url(target_url)
    from scrapers.crawlers.base import shared_httpx_client
    from scrapers.crawlers.orchestrator import CrawlOrchestrator

    try:
        async with shared_httpx_client(max_connections=12) as client:
            result = await CrawlOrchestrator().crawl(
                company=company,
                company_url=target_url,
                keyword=str(body.get("keyword") or "").strip() or None,
                location=str(body.get("location") or "").strip() or None,
                page=max(1, int(body.get("page", 1))),
                limit=min(100, max(1, int(body.get("limit", 20)))),
                use_playwright=bool(body.get("use_playwright", False)),
                client=client,
            )
    except Exception as exc:
        logger.exception("Crawl service failed: %s", exc)
        raise HTTPException(status_code=502, detail="Crawl service failed") from exc
    if result.get("status") == "failed":
        raise HTTPException(status_code=502, detail=result.get("error", "Crawl failed"))
    return result


@router.post("/scraper/discover")
async def discover_scraper_portal(request: Request) -> dict:
    """Discover and inspect a portal without starting job ingestion."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    company = str(body.get("company") or body.get("company_name") or "").strip() or None
    target_url = str(body.get("company_url") or body.get("domain") or "").strip() or None
    if not company and not target_url:
        raise HTTPException(status_code=400, detail="company, domain, or company_url is required")
    target_url = await _validate_company_url(target_url)

    from scrapers.crawlers.base import request_with_retries, shared_httpx_client
    from scrapers.crawlers.detector import detect_portal
    from scrapers.crawlers.discovery import CareerPageDiscovery

    try:
        async with shared_httpx_client(max_connections=8) as client:
            discovery = await CareerPageDiscovery(client=client).discover(target_url or company or "")
            html = ""
            if discovery.careers_url:
                try:
                    html = await request_with_retries(discovery.careers_url, client=client, max_retries=2)
                except Exception as exc:
                    logger.warning("Portal inspection fetch failed for %s: %s", discovery.careers_url, exc)
            detection = detect_portal(discovery.careers_url, html)
            try:
                from app.services.crawl_repository import save_company_profile
                await save_company_profile({
                    "company_id": discovery.company,
                    "name": discovery.company,
                    "domain": discovery.official_domain,
                    "careers_url": discovery.careers_url,
                    "career_url": discovery.careers_url,
                    "career_page_url": discovery.careers_url,
                    "portal_provider": detection.get("provider", "unknown"),
                    "detection_confidence": detection.get("confidence", 0.0),
                    "capabilities": detection.get("capabilities", []),
                    "detection_signals": detection.get("signals", []),
                    "crawl_status": "discovered",
                })
            except RuntimeError:
                # Discovery is useful without MongoDB; persistence is best effort.
                pass
        return {"discovery": discovery.to_dict(), "detection": detection}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Portal discovery failed: %s", exc)
        raise HTTPException(status_code=502, detail="Portal discovery failed") from exc


@router.get("/companies")
async def get_companies() -> dict:
    """Return the global company directory with career-page metadata."""
    company_map: dict[str, dict[str, Any]] = {}
    try:
        job_companies = await find_companies()
        for item in job_companies:
            name = str(item.get("name") or item.get("_id") or "").strip()
            if name:
                company_map[name.lower()] = {"name": name, "count": item.get("count", 0)}
    except RuntimeError:
        logger.warning("find_companies failed; using directory/profile fallback")

    # Profiles discovered through the scraper are the most authoritative
    # source for custom domains and manually confirmed career URLs.
    try:
        from app.db.mongo import get_db
        profile_cursor = get_db().companies.find({}, {"_id": 0})
        async for profile in profile_cursor:
            name = str(profile.get("name") or profile.get("company") or "").strip()
            if name:
                key = name.lower()
                company_map[key] = {**company_map.get(key, {}), **profile, "name": name}
    except RuntimeError:
        pass

    # Seed metadata keeps the global directory useful before the first crawl
    # and supplies official career URLs for known companies.
    from scrapers.directory import ats_info, careers_url, companies as seeded_companies
    for seed in seeded_companies():
        key = seed.lower()
        url = careers_url(seed) or ""
        ats = ats_info(seed) or {}
        current = company_map.get(key, {})
        company_map[key] = {
            **current,
            "name": current.get("name") or seed.title(),
            "count": current.get("count", 0),
            "domain": current.get("domain") or (url.split("//", 1)[-1].split("/", 1)[0] if url else ""),
            "career_url": current.get("career_url") or current.get("careers_url") or url,
            "careers_url": current.get("careers_url") or current.get("career_url") or url,
            "career_page_url": current.get("career_page_url") or current.get("careers_url") or current.get("career_url") or url,
            "portal_provider": current.get("portal_provider") or ats.get("platform", "unknown"),
            "detection_confidence": current.get("detection_confidence", 0.0),
            "crawl_status": current.get("crawl_status", "not_crawled"),
        }

    companies = sorted(company_map.values(), key=lambda item: str(item.get("name", "")).lower())
    logger.info("GET /companies returned %d companies with career metadata", len(companies))
    return {"companies": companies, "total": len(companies)}


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
async def run_scrape(request: Request) -> dict:
    body = await request.json()
    companies_str = (body.get("companies") or "").strip()
    urls_str = (body.get("company_url") or "").strip()
    keyword = (body.get("keyword") or "").strip() or None
    location = (body.get("location") or "").strip() or None
    pages = int(body.get("pages", 2))
    page_size = int(body.get("page_size", 20))
    delay = float(body.get("delay_seconds", 0.5))
    save_to_db = bool(body.get("save_to_db", False))

    logger.info(
        "POST /scrape requested companies='%s' urls='%s' keyword=%s location=%s pages=%d page_size=%d save_to_db=%s",
        companies_str, urls_str, keyword, location, pages, page_size, save_to_db,
    )

    mod = await _get_scraper()
    explicit_companies = [c.strip().lower() for c in companies_str.split(",") if c.strip()] if companies_str else []
    urls = [u.strip() for u in urls_str.split(",") if u.strip()] if urls_str else []
    if not explicit_companies and not urls:
        companies = mod.supported_companies()
    else:
        companies = explicit_companies

    all_results: list[dict[str, Any]] = []

    COMPANY_TIMEOUT = 240  # seconds per company

    async def _scrape_one(target: str, *, is_url: bool = False) -> dict[str, Any]:
        start = time.monotonic()
        metrics.record_attempt(target)
        try:
            jobs = await asyncio.wait_for(
                mod._scrape_company(
                    None if is_url else target,
                    company_url=target if is_url else None,
                    keyword=keyword,
                    location=location,
                    pages=pages,
                    page_size=page_size,
                    delay_seconds=delay,
                ),
                timeout=COMPANY_TIMEOUT,
            )
            job_count = len(jobs)
            duration = time.monotonic() - start
            metrics.record_success(target, job_count, "scrape", duration)
            audit.record(target, duration, job_count, "scrape")
            logger.info("Scraped %s: %d jobs", target, job_count)
            if save_to_db:
                pushed = await _save_results(jobs, target)
                logger.info("Pushed %d jobs from '%s' to database", pushed, target)
                return {"target": target, "jobs": jobs, "count": job_count, "saved_to_db": pushed}
            return {"target": target, "jobs": jobs, "count": job_count}
        except asyncio.TimeoutError:
            duration = time.monotonic() - start
            logger.warning("Scrape timed out for '%s' after %ds", target, duration)
            metrics.record_failure(target)
            audit.record(target, duration, 0, "scrape", "timeout")
            return {"target": target, "jobs": [], "count": 0, "error": f"Timed out after {COMPANY_TIMEOUT}s"}
        except Exception as e:
            duration = time.monotonic() - start
            metrics.record_failure(target)
            audit.record(target, duration, 0, "scrape", str(e))
            return {"target": target, "jobs": [], "count": 0, "error": str(e)}

    batch = companies + urls
    concurrency = max(1, int(body.get("concurrency", min(len(batch), 5) if len(batch) > 1 else 1)))
    logger.info("POST /scrape concurrency=%d targets=%d", concurrency, len(batch))
    sem = asyncio.Semaphore(concurrency)

    async def _scrape_bounded(target: str, *, is_url: bool = False) -> dict[str, Any]:
        async with sem:
            return await _scrape_one(target, is_url=is_url)

    if len(batch) > 1:
        results = await asyncio.gather(
            *[_scrape_bounded(c) for c in companies] + [_scrape_bounded(u, is_url=True) for u in urls],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error("Parallel scrape failed: %s", r)
                all_results.append({"target": "unknown", "jobs": [], "count": 0, "error": str(r)})
            else:
                all_results.append(r)
    else:
        for company in companies:
            all_results.append(await _scrape_one(company))
        for url in urls:
            all_results.append(await _scrape_one(url, is_url=True))

    total = sum(r["count"] for r in all_results)
    for r in all_results:
        await _notify_webhooks(r["target"], r["count"])
    logger.info("POST /scrape completed: total=%d targets=%d save_to_db=%s", total, len(all_results), save_to_db)
    return {"results": all_results, "total": total, "mode": "local" if not save_to_db else "db"}


async def _save_results(jobs: list[dict[str, Any]], label: str) -> int:
    """Persist scraped jobs to MongoDB (mirrors POST /push-to-db)."""
    if not jobs:
        return 0
    try:
        from app.db.mongo import connect_mongo, close_mongo
        from app.services.job_store import upsert_jobs

        await connect_mongo()
        canonicalized = [canonicalize_job(j) for j in jobs]
        await upsert_jobs(canonicalized)
        await close_mongo()
        return len(canonicalized)
    except Exception as exc:
        logger.exception("Failed to push %d jobs from '%s' to database: %s", len(jobs), label, exc)
        return 0


@router.post("/scrape/start")
async def start_scrape(request: Request) -> dict:
    body = await request.json()
    from app.services.scrape_manager import manager
    task_id = await manager.start(body)
    logger.info("POST /scrape/start created task %s", task_id)
    return {"task_id": task_id}


@router.post("/scrape/stop/{task_id}")
async def stop_scrape(task_id: str) -> dict:
    from app.services.scrape_manager import manager
    ok = manager.stop(task_id)
    return {"stopped": ok}


@router.get("/scrape/status/{task_id}")
async def scrape_status(task_id: str) -> dict:
    from app.services.scrape_manager import manager
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.get("/scrape/status")
async def scrape_history() -> dict:
    from app.services.scrape_manager import manager
    runs = manager.list()
    return {"runs": runs, "count": len(runs)}


@router.get("/scrape/events/{task_id}")
async def scrape_events(request: Request, task_id: str):
    from app.services.scrape_manager import manager
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_stream():
        async for event in task.events():
            if event.get("type") == "heartbeat":
                yield ": heartbeat\n\n"
            else:
                yield f"data: {json.dumps(event)}\n\n"
            if event.get("status") in ("completed", "cancelled", "failed"):
                break

    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
