from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from app.crawler.amazon import fetch_amazon_jobs
from app.crawler.meta import fetch_meta_jobs
from app.crawler.microsoft import fetch_microsoft_jobs
from app.services.ai_parser import parse_job_details

logger = logging.getLogger(__name__)


# Registry maps company slug → (fetch_fn, default_keyword, default_location)
_REGISTRY: dict[str, tuple[Callable[..., Coroutine[Any, Any, list[dict[str, Any]]]], str, str]] = {
    "amazon": (fetch_amazon_jobs, "Software", ""),
    "microsoft": (fetch_microsoft_jobs, "software", ""),
    "meta": (fetch_meta_jobs, "Software", ""),
}


def _enrich_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backfill skills and experience from title when not already populated."""
    for job in jobs:
        title = job.get("title", "")
        parsed = parse_job_details(title)
        job.setdefault("employment_type", "Full Time")
        if not job.get("skills"):
            job["skills"] = parsed["skills"]
        if not job.get("experience"):
            job["experience"] = parsed["experience"]
    return jobs


async def _safe_crawl(
    name: str,
    fetch_fn: Callable[..., Coroutine[Any, Any, list[dict[str, Any]]]],
    keyword: str,
    location: str,
    page: int,
    limit: int,
) -> dict[str, Any]:
    """

    Wraps a single company crawler with independent error handling.
    If this company fails, it returns a failure dict instead of propagating.
    All other companies are unaffected.
    """
    try:
        jobs = await fetch_fn(keyword=keyword, location=location, page=page, limit=limit)
        return {"company": name.title(), "status": "ok", "jobs": _enrich_jobs(jobs)}
    except Exception as exc:

        logger.error("Crawler for %s failed: %s", name, exc, exc_info=True)
        return {"company": name.title(), "status": "failed", "error": str(exc), "jobs": []}


async def crawl_jobs(
    company: Optional[str] = None,
    keyword: Optional[str] = None,
    location: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """

    Orchestrates all company crawlers concurrently. Each crawler is isolated —
    a failure in one does NOT affect results from others.

    Args:
        company: If provided, crawl only this company (e.g. "amazon").
        keyword:  Search keyword override.
        location: Location filter override.

    Returns:
        List of dicts, one per company, each containing:
          - company: company display name
          - status: "ok" | "failed"
          - jobs: list of normalized job dicts
          - error: only present when status == "failed"
    """
    if company:
        company_key = company.lower()
        if company_key not in _REGISTRY:
            raise ValueError(
                f"Unsupported company: '{company}'. "
                f"Supported: {', '.join(_REGISTRY.keys())}"
            )
        fetch_fn, default_kw, default_loc = _REGISTRY[company_key]
        result = await _safe_crawl(
            company_key,
            fetch_fn,
            keyword or default_kw,
            location or default_loc,
            page,
            limit,
        )

        return [result]

    # Crawl all companies concurrently, failures are isolated per company

    tasks = [
        _safe_crawl(
            name,
            fetch_fn,
            keyword or default_kw,
            location or default_loc,
            page,
            limit,
        )
        for name, (fetch_fn, default_kw, default_loc) in _REGISTRY.items()
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: list[dict[str, Any]] = []
    for name, result in zip(_REGISTRY.keys(), results):
        if isinstance(result, Exception):
            # Should not normally happen since _safe_crawl already catches,
            # but guard defensively.
            output.append({
                "company": name.title(),
                "status": "failed",
                "error": str(result),
                "jobs": [],
            })
        else:
            output.append(result)

    return output
