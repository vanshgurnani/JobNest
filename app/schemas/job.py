from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field


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
    """Normalize runtime job dicts to a single API schema."""
    apply_url = str(job.get("apply_url") or job.get("url") or "").strip()
    job_id = str(job.get("job_id") or job.get("id") or "").strip()
    stable_id = _stable_job_id(job)

    desc = str(job.get("description") or "").strip()
    desc = re.sub(r"<[^>]+>", " ", desc)
    desc = re.sub(r"\s+", " ", desc).strip()

    return {
        "id": stable_id,
        "job_id": job_id or stable_id,
        "company": str(job.get("company") or "").strip(),
        "title": str(job.get("title") or "Untitled").strip(),
        "location": str(job.get("location") or "").strip(),
        "description": desc,
        "employment_type": str(job.get("employment_type") or "").strip(),
        "experience": str(job.get("experience") or "").strip(),
        "skills": list(job.get("skills") or []),
        "apply_url": apply_url,
        "url": apply_url,
        "source": str(job.get("source") or "").strip(),
        "posted_date": str(job.get("posted_date") or job.get("date_posted") or "").strip(),
        "valid_through": str(job.get("valid_through") or "").strip(),
    }
