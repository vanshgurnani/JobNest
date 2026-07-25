from __future__ import annotations
import asyncio
import importlib
import logging
from typing import Any, Callable, Coroutine, Optional
from urllib.parse import urlparse

from app.services.ai_parser import parse_job_details

logger = logging.getLogger(__name__)


_CrawlerSpec = tuple[str, str, str]

# Registry maps company slug -> (module.function, default_keyword, default_location).
# Crawler modules are imported lazily so production API boot does not require
# optional scraper-only dependencies such as Playwright.
_REGISTRY: dict[str, _CrawlerSpec] = {
    "amazon": ("scripts.scraping.crawlers.amazon.fetch_amazon_jobs", "Software", ""),
    "microsoft": ("scripts.scraping.crawlers.microsoft.fetch_microsoft_jobs", "software", ""),
    "meta": ("scripts.scraping.crawlers.meta.fetch_meta_jobs", "Software", ""),
}


def _company_name_from_url(company_url: str) -> str:
    parsed = urlparse(company_url if company_url.startswith("http") else f"https://{company_url}")
    host = parsed.netloc.lower().removeprefix("www.")
    labels = [label for label in host.split(".") if label and label not in {"careers", "jobs", "apply"}]
    if not labels:
        return "company"
    return labels[0].replace("-", " ")


def supported_companies() -> list[str]:
    return sorted(_REGISTRY.keys())


def _load_fetch_fn(path: str) -> Callable[..., Coroutine[Any, Any, list[dict[str, Any]]]]:
    module_name, function_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


async def _crawl_universal(
    *,
    company_name: str,
    company_url: Optional[str],
    keyword: Optional[str],
    location: Optional[str],
    page: int,
    limit: int,
) -> dict[str, Any]:
    from scripts.scraping.crawlers.universal import universal_crawl_jobs

    try:
        jobs = await universal_crawl_jobs(
            company_name=company_name,
            company_url=company_url,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
        )
        return {"company": company_name.title(), "status": "ok", "jobs": _enrich_jobs(jobs)}
    except Exception as exc:
        logger.error("Universal crawler for %s failed: %s", company_name, exc, exc_info=True)
        return {"company": company_name.title(), "status": "failed", "error": str(exc), "jobs": []}


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
    company_url: Optional[str] = None,
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
    if company_url and not company:
        inferred_company = _company_name_from_url(company_url)
        return [
            await _crawl_universal(
                company_name=inferred_company,
                company_url=company_url,
                keyword=keyword,
                location=location,
                page=page,
                limit=limit,
            )
        ]

    if company:
        company_key = company.lower()
        if company_key not in _REGISTRY:
            return [
                await _crawl_universal(
                    company_name=company,
                    company_url=company_url,
                    keyword=keyword,
                    location=location,
                    page=page,
                    limit=limit,
                )
            ]

        fetch_path, default_kw, default_loc = _REGISTRY[company_key]
        fetch_fn = _load_fetch_fn(fetch_path)
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
            _load_fetch_fn(fetch_path),
            keyword or default_kw,
            location or default_loc,
            page,
            limit,
        )
        for name, (fetch_path, default_kw, default_loc) in _REGISTRY.items()
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
