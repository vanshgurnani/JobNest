import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.cache import build_cache_key, crawl_cache
from app.services.job_store import find_companies, find_job_by_id, find_jobs
from app.services.security import is_safe_url

router = APIRouter(prefix="", tags=["jobs"])

_MAX_SEARCH_LENGTH = 200


def _load_supported_companies() -> list[str]:
    _path = Path(__file__).resolve().parents[2] / "scrapers" / "company_urls.json"
    companies: list[str] = []
    if _path.exists():
        try:
            raw = json.loads(_path.read_text(encoding="utf-8"))
            for key in raw:
                if not key.startswith("_"):
                    companies.append(key)
        except Exception:
            pass
    return companies or [
        "accenture", "amazon", "apple", "cisco", "cognizant", "deloitte",
        "google", "ibm", "infosys", "jpmorgan", "kpmg",
        "mastercard", "meta", "microsoft", "oracle", "tcs", "wipro",
    ]


SUPPORTED_COMPANIES = _load_supported_companies()


def _validate_search_param(value: Optional[str], name: str) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) > _MAX_SEARCH_LENGTH:
        raise HTTPException(status_code=400, detail=f"{name} exceeds maximum length")
    return stripped


def _validate_company_url(url: Optional[str]) -> Optional[str]:
    if url is None:
        return None
    safe, reason = is_safe_url(url)
    if not safe:
        raise HTTPException(status_code=400, detail=f"Invalid company_url: {reason}")
    return url


@router.get("/companies")
async def get_companies() -> dict:
    try:
        companies = await find_companies()
        if not companies:
            companies = [{"name": c.title(), "count": 0} for c in SUPPORTED_COMPANIES]
    except RuntimeError:
        companies = [{"name": c.title(), "count": 0} for c in SUPPORTED_COMPANIES]
    return {
        "companies": companies,
        "companies_list": [c["name"] for c in companies],
    }


async def _cache_response(key: str, payload: dict) -> dict:
    await crawl_cache.set(key, payload)
    return payload


@router.get("/jobs")
async def get_jobs(
    company: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    company_url: Optional[str] = Query(default=None, max_length=2048),
    keyword: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    location: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    company_valid = _validate_search_param(company, "Company")
    company_url_valid = _validate_company_url(company_url)
    keyword_valid = _validate_search_param(keyword, "Keyword")
    location_valid = _validate_search_param(location, "Location")

    cache_key = build_cache_key(
        route="jobs",
        company=company_valid,
        company_url=company_url_valid,
        keyword=keyword_valid,
        location=location_valid,
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


@router.get("/jobs/{company}")
async def get_company_jobs(
    company: str,
    company_url: Optional[str] = Query(default=None, max_length=2048),
    keyword: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    location: Optional[str] = Query(default=None, max_length=_MAX_SEARCH_LENGTH),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    company_key = _validate_search_param(company, "Company")
    company_url_valid = _validate_company_url(company_url)
    keyword_valid = _validate_search_param(keyword, "Keyword")
    location_valid = _validate_search_param(location, "Location")

    cache_key = build_cache_key(
        route="company_jobs",
        company=company_key,
        company_url=company_url_valid,
        keyword=keyword_valid,
        location=location_valid,
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


@router.get("/job/{job_id}")
async def get_job_detail(job_id: str) -> dict:
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
