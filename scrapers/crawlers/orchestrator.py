from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from app.services.ai_parser import parse_job_details

logger = logging.getLogger(__name__)


def _company_name_from_url(company_url: str) -> str:
    parsed = urlparse(company_url if company_url.startswith("http") else f"https://{company_url}")
    host = parsed.netloc.lower().removeprefix("www.")
    labels = [label for label in host.split(".") if label and label not in {"careers", "jobs", "apply"}]
    if not labels:
        return "company"
    return labels[0].replace("-", " ")


def supported_companies() -> list[str]:
    _path = Path(__file__).resolve().parent.parent / "company_urls.json"
    companies: list[str] = []
    if _path.exists():
        try:
            raw = json.loads(_path.read_text(encoding="utf-8"))
            for key in raw:
                if not key.startswith("_"):
                    companies.append(key)
        except Exception:
            pass
    if not companies:
        companies = [
            "accenture", "amazon", "apple", "cisco", "cognizant", "deloitte",
            "google", "hcl", "ibm", "infosys", "jpmorgan", "kpmg",
            "mastercard", "meta", "microsoft", "oracle", "tcs", "wipro", "zoho",
        ]
    return companies


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
) -> list[dict[str, Any]]:
    name = company or (_company_name_from_url(company_url) if company_url else "unknown")

    return [
        await _crawl_universal(
            company_name=name,
            company_url=company_url,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
        )
    ]
