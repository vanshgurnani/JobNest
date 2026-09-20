from __future__ import annotations
import logging
from typing import Any, Optional

import httpx

from app.services.ai_parser import parse_job_details
from scrapers.utils import company_name_from_url, supported_companies

logger = logging.getLogger(__name__)


class CrawlOrchestrator:
    """Resolve a portal, select an adapter, and run one crawl.

    The old ``crawl_jobs`` function remains the public compatibility wrapper;
    this class is the new service boundary used by it and by future workers.
    """

    def __init__(self, *, registry=None, discovery=None) -> None:
        from scrapers.crawlers.adapters.registry import default_registry
        from scrapers.crawlers.discovery import CareerPageDiscovery

        self.registry = registry or default_registry
        self.discovery = discovery or CareerPageDiscovery

    async def crawl(
        self,
        *,
        company: str | None = None,
        company_url: str | None = None,
        keyword: str | None = None,
        location: str | None = None,
        page: int = 1,
        limit: int = 20,
        use_playwright: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        from scrapers.crawlers.contracts import CrawlMetrics, PortalContext
        from scrapers.crawlers.detector import detection_result
        from scrapers.crawlers.monitoring.audit import audit
        from scrapers.crawlers.monitoring.metrics import metrics as legacy_metrics

        company_name = company or ((_company_name_from_url(company_url).lower()) if company_url else "unknown")
        metrics = CrawlMetrics(crawl_id=__import__("uuid").uuid4().hex, company=company_name)
        try:
            if company_url:
                # A supplied URL is already the user's strongest discovery
                # signal. Avoid an unnecessary homepage crawl and preserve the
                # existing URL validation/routing behavior.
                discovery = {
                    "careers_url": company_url,
                    "official_domain": company_url,
                    "confidence": 0.98,
                    "discovery_method": "supplied_url",
                }
            else:
                result = await self.discovery(client=client).discover(company_name)
                discovery = result.to_dict()
            careers_url = discovery["careers_url"]
            detected = detection_result(careers_url, "")
            adapter = self.registry.select(detected)
            metrics.portal = detected.provider
            metrics.adapter = adapter.name
            context = PortalContext(company_name=company_name, careers_url=careers_url,
                                    official_domain=discovery.get("official_domain", ""), detection=detected,
                                    keyword=keyword, location=location, page=page, limit=limit,
                                    use_playwright=use_playwright, client=client)
            try:
                references = [reference async for reference in adapter.discover_jobs(context)]
            except Exception as exc:
                # Provider adapters are preferred, but a changed provider API
                # must degrade to the existing universal path.
                metrics.fallback_count += 1
                metrics.record_error(exc, stage="provider_adapter", retryable=True)
                adapter = self.registry.get("universal")
                metrics.adapter = adapter.name
                references = [reference async for reference in adapter.discover_jobs(context)]
            metrics.jobs_discovered = len(references)
            jobs: list[dict[str, Any]] = []
            for reference in references:
                raw = await adapter.fetch_job(reference, context)
                normalized = await adapter.normalize(raw, context)
                # Keep the API's historical flat fields while adding the
                # canonical contract fields for persistence and search.
                jobs.append(normalized)
            metrics.jobs_parsed = len(jobs)
            metrics.finish()
            legacy_metrics.record_success(company_name, len(jobs), adapter.name, metrics.duration_seconds)
            audit.record(company_name, metrics.duration_seconds, len(jobs), adapter.name)
            return {"crawl_id": metrics.crawl_id, "company": company_name.title(), "status": "ok",
                    "discovery": discovery, "detection": detected.to_dict(), "adapter": adapter.name,
                    "jobs": jobs, "metrics": metrics.to_dict()}
        except Exception as exc:
            metrics.record_error(exc)
            metrics.finish()
            legacy_metrics.record_failure(company_name, metrics.adapter)
            audit.record(company_name, metrics.duration_seconds, 0, metrics.adapter or "crawl", str(exc))
            logger.error("Crawl failed for %s: %s", company_name, exc, exc_info=True)
            return {"crawl_id": metrics.crawl_id, "company": company_name.title(), "status": "failed",
                    "error": str(exc), "jobs": [], "metrics": metrics.to_dict()}


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
    orchestrator = CrawlOrchestrator()
    return [await orchestrator.crawl(company=company, company_url=company_url, keyword=keyword,
                                     location=location, page=page, limit=limit,
                                     use_playwright=use_playwright, client=client)]
