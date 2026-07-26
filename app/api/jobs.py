from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.services.cache import build_cache_key, crawl_cache
from app.services.job_store import find_companies, find_job_by_id, find_jobs

router = APIRouter(prefix="", tags=["jobs"])

SUPPORTED_COMPANIES = [
    "amazon", "meta", "microsoft", "tca", "kpmg", "jpmorgan", "wipro",
]


@router.get("/companies")
async def get_companies() -> dict:
    try:
        companies = await find_companies()
        if not companies:
            companies = [c.title() for c in SUPPORTED_COMPANIES]
    except RuntimeError:
        companies = [c.title() for c in SUPPORTED_COMPANIES]
    return {"companies": companies}


async def _cache_response(key: str, payload: dict) -> dict:
    await crawl_cache.set(key, payload)
    return payload


@router.get("/jobs")
async def get_jobs(
    company: Optional[str] = Query(default=None, description="Optional company filter"),
    company_url: Optional[str] = Query(default=None, description="Optional official company careers/base URL"),
    keyword: Optional[str] = Query(default=None, description="Optional keyword filter"),
    location: Optional[str] = Query(default=None, description="Optional location filter"),
    page: int = Query(default=1, ge=1, description="Pagination page (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
) -> dict:
    cache_key = build_cache_key(
        route="jobs",
        company=company,
        company_url=company_url,
        keyword=keyword,
        location=location,
        page=page,
        limit=limit,
    )

    cached = await crawl_cache.get(cache_key)
    if cached is not None:
        return {**cached, "cache": "memory"}

    try:
        jobs, total = await find_jobs(
            company=company,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
            fresh_only=False,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Job database is not available. Run the scraper in db mode before serving the portal.",
        ) from exc

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
    company_url: Optional[str] = Query(default=None, description="Optional official company careers/base URL"),
    keyword: Optional[str] = Query(default=None, description="Optional keyword filter"),
    location: Optional[str] = Query(default=None, description="Optional location filter"),
    page: int = Query(default=1, ge=1, description="Pagination page (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
) -> dict:
    company_key = company.lower()
    cache_key = build_cache_key(
        route="company_jobs",
        company=company_key,
        company_url=company_url,
        keyword=keyword,
        location=location,
        page=page,
        limit=limit,
    )

    cached = await crawl_cache.get(cache_key)
    if cached is not None:
        return {**cached, "cache": "memory"}

    try:
        jobs, total = await find_jobs(
            company=company_key,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
            fresh_only=False,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Job database is not available. Run the scraper in db mode before serving the portal.",
        ) from exc

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
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Job detail storage is not available") from exc

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return await _cache_response(cache_key, {"job": job, "cache": "mongo"})
