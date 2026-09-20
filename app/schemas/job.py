from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field
from typing import Any, Optional, TypedDict


class Job(BaseModel):
    id: str
    job_id: str = ""
    company: str
    title: str
    location: str = ""
    description: str = ""
    employment_type: str = ""
    experience: str = ""
    skills: list[str] = Field(default_factory=list)
    apply_url: str = ""
    url: str = ""
    source: str = ""
    posted_date: str = ""
    valid_through: str = ""
    # Canonical ingestion fields. Legacy flat fields above remain for the
    # frontend/API compatibility surface.
    source_job_id: str = ""
    canonical_url: str = ""
    department: str = ""
    team: str = ""
    seniority: str = ""
    workplace_type: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    remote: bool = False
    locations: list[dict[str, Any]] = Field(default_factory=list)
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: str = ""
    raw_salary: str = ""
    posted_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    portal: str = ""
    adapter: str = ""
    extraction_method: str = ""
    raw_payload_reference: str = ""
    content_hash: str = ""
    active: bool = True


def _stable_job_id(job: dict[str, Any]) -> str:
    existing = str(job.get("id") or job.get("job_id") or "").strip()
    if existing:
        return existing
    apply_url = str(job.get("apply_url") or job.get("url") or "").strip()
    company = str(job.get("company") or "").strip().lower()
    title = str(job.get("title") or "").strip().lower()
    seed = f"{apply_url}:::{company}:::{title}" if apply_url else f"{company}:{title}"
    if not seed:
        return ""
    return hashlib.sha256(seed.encode()).hexdigest()[:20]


def canonicalize_job(job: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy and canonical adapter payloads to one flat document."""
    from scrapers.crawlers.normalization import canonical_job

    normalized = canonical_job(
        job,
        company=str(job.get("company") or "").strip(),
        portal=str(job.get("portal") or job.get("source") or "unknown"),
        adapter=str(job.get("adapter") or "universal"),
    )
    # Explicit ids from an existing integration are still honored; new jobs
    # use provider/source-aware identity from canonical_job.
    if str(job.get("id") or "").strip():
        normalized["id"] = str(job["id"]).strip()
    normalized["job_id"] = str(job.get("job_id") or normalized.get("source_job_id") or normalized["id"])
    normalized["title"] = normalized.get("title") or "Untitled"
    return normalized


class JobListResponse(BaseModel):
    total: int = 0
    jobs: list[Job] = []
    latest_jobs: list[Job] = []
    page: int = 1
    limit: int = 20
    cache: str = ""


class JobDetailResponse(BaseModel):
    job: Job
    cache: str = ""


class RawJobDict(TypedDict, total=False):
    id: str
    job_id: str
    company: str
    title: str
    location: str
    description: str
    employment_type: str
    experience: str
    skills: list[str]
    apply_url: str
    url: str
    source: str
    posted_date: str
    valid_through: str
    date_posted: str
    crawled_at: str
