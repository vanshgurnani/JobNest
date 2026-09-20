"""Adapters around the existing provider crawlers.

Keeping these calls here lets new providers be introduced without changing
the orchestrator. The underlying implementations remain the compatibility
source of truth until each provider is migrated to a dedicated module.
"""

from __future__ import annotations

from typing import AsyncIterator

from scrapers.crawlers.adapters.base import CareerPortalAdapter
from scrapers.crawlers.base import crawl_ats_jobs, detect_ats as detect_legacy_ats
from scrapers.crawlers.contracts import DetectionResult, JobReference, PortalContext, RawJob
from scrapers.crawlers.detector import detection_result
from scrapers.crawlers.normalization import canonical_job


class ProviderAdapter(CareerPortalAdapter):
    def __init__(self, provider: str) -> None:
        self.name = provider
        self.provider = provider
        self._jobs: dict[str, dict] = {}

    async def detect(self, context: PortalContext) -> DetectionResult:
        detected = detection_result(context.careers_url, context.html)
        if detected.provider == "unknown":
            legacy = detect_legacy_ats(context.careers_url, context.html)
            if legacy:
                detected = DetectionResult(provider=self.provider, confidence=0.8, signals=["legacy_detector"],
                                           capabilities=["api"], metadata=legacy)
        return detected

    async def discover_jobs(self, context: PortalContext) -> AsyncIterator[JobReference]:
        # The legacy detector knows provider-specific tokens (board names,
        # tenants, and slugs) that the generic signal detector intentionally
        # does not expose.
        info = detect_legacy_ats(context.careers_url, context.html)
        if not info and context.detection and context.detection.metadata.get("platform"):
            info = context.detection.metadata
        if not info:
            info = {"platform": self.provider}
        jobs = await crawl_ats_jobs(info, company=context.company_name, keyword=context.keyword,
                                    location=context.location, page=context.page, limit=context.limit,
                                    client=context.client)
        for index, job in enumerate(jobs):
            url = str(job.get("apply_url") or job.get("url") or context.careers_url)
            reference = JobReference(url=url, source_job_id=str(job.get("job_id") or job.get("id") or ""),
                                     title=str(job.get("title") or ""), metadata={"job": job, "index": index})
            self._jobs[url] = job
            yield reference

    async def fetch_job(self, reference: JobReference, context: PortalContext) -> RawJob:
        return RawJob(payload=self._jobs.get(reference.url, reference.metadata.get("job", {})),
                       reference=reference, source=self.provider, extraction_method="provider_adapter")

    async def normalize(self, raw_job: RawJob, context: PortalContext) -> dict:
        payload = dict(raw_job.payload)
        payload.setdefault("raw_payload_reference", raw_job.reference.url if raw_job.reference else "")
        return canonical_job(payload, company=context.company_name, portal=self.provider,
                             adapter=self.name, careers_url=context.careers_url)


class UniversalAdapter(CareerPortalAdapter):
    name = "universal"

    async def detect(self, context: PortalContext) -> DetectionResult:
        return detection_result(context.careers_url, context.html)

    async def discover_jobs(self, context: PortalContext) -> AsyncIterator[JobReference]:
        # Import lazily so importing the registry never initializes browser
        # dependencies or changes the legacy module's startup behavior.
        from scrapers.crawlers.universal import universal_crawl_jobs

        jobs = await universal_crawl_jobs(company_name=context.company_name, company_url=context.careers_url,
                                          keyword=context.keyword, location=context.location, page=context.page,
                                          limit=context.limit, use_playwright=context.use_playwright, client=context.client)
        for index, job in enumerate(jobs):
            url = str(job.get("apply_url") or job.get("url") or context.careers_url)
            yield JobReference(url=url, source_job_id=str(job.get("job_id") or job.get("id") or ""),
                               title=str(job.get("title") or ""), metadata={"job": job, "index": index})

    async def fetch_job(self, reference: JobReference, context: PortalContext) -> RawJob:
        return RawJob(payload=reference.metadata.get("job", {}), reference=reference,
                       source="universal", extraction_method="universal")

    async def normalize(self, raw_job: RawJob, context: PortalContext) -> dict:
        payload = dict(raw_job.payload)
        payload.setdefault("raw_payload_reference", raw_job.reference.url if raw_job.reference else "")
        return canonical_job(payload, company=context.company_name, portal="unknown",
                             adapter=self.name, careers_url=context.careers_url)
