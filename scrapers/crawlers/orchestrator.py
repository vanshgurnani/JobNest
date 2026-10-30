from __future__ import annotations
import logging
from typing import Any, Optional

import httpx

from app.services.ai_parser import parse_job_details
from scrapers.utils import company_name_from_url, supported_companies

logger = logging.getLogger(__name__)


def _company_name_from_url(company_url: str) -> str:
    return company_name_from_url(company_url)


def _enrich_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for job in jobs:
        title = job.get("title", "")
        parsed = parse_job_details(title)
        job.setdefault("employment_type", "Full Time")
        if not job.get("skills"):
            job["skills"] = parsed["skills"]
        if not job.get("experience"):
            job["experience"] = parsed["experience"]
    return jobs


async def _crawl_universal(
    *,
    company_name: str,
    company_url: Optional[str],
    keyword: Optional[str],
    location: Optional[str],
    page: int,
    limit: int,
    use_playwright: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    from scrapers.crawlers.universal import universal_crawl_jobs

    try:
        jobs = await universal_crawl_jobs(
            company_name=company_name,
            company_url=company_url,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
            use_playwright=use_playwright,
            client=client,
        )
        return {"company": company_name.title(), "status": "ok", "jobs": _enrich_jobs(jobs)}
    except Exception as exc:
        logger.error("Universal crawler for %s failed: %s", company_name, exc, exc_info=True)
        return {"company": company_name.title(), "status": "failed", "error": str(exc), "jobs": []}


async def crawl_jobs(
    company: Optional[str] = None,
    company_url: Optional[str] = None,
    keyword: Optional[str] = None,
    location: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    use_playwright: bool = False,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    name = (company or (_company_name_from_url(company_url) if company_url else "unknown")).lower()

    return [
        await _crawl_universal(
            company_name=name,
            company_url=company_url,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
            use_playwright=use_playwright,
            client=client,
        )
    ]
