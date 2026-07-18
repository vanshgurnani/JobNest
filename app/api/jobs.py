from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.crawler.orchestrator import crawl_jobs

router = APIRouter(prefix="", tags=["jobs"])


@router.get("/jobs")
async def get_jobs(
    company: Optional[str] = Query(default=None, description="Optional company filter"),
    keyword: Optional[str] = Query(default=None, description="Optional keyword filter"),
    location: Optional[str] = Query(default=None, description="Optional location filter"),
) -> dict:
    try:
        results = await crawl_jobs(company=company, keyword=keyword, location=location)
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    jobs = []
    for company_result in results:
        if isinstance(company_result, dict) and "jobs" in company_result:
            jobs.extend(company_result.get("jobs", []))

    return {
        "total": len(jobs),
        "latest_jobs": jobs,
        "jobs": jobs,
    }


@router.get("/jobs/{company}")
async def get_company_jobs(
    company: str,
    keyword: Optional[str] = Query(default=None, description="Optional keyword filter"),
    location: Optional[str] = Query(default=None, description="Optional location filter"),
) -> dict:
    company_key = company.lower()
    try:
        results = await crawl_jobs(company=company_key, keyword=keyword, location=location)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not results:
        raise HTTPException(status_code=404, detail=f"No jobs found for {company}")

    first_result = results[0]
    return {
        "company": first_result.get("company", company.title()),
        "jobs": first_result.get("jobs", []),
    }
