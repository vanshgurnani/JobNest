from typing import Any


def normalize_job(raw_job: dict[str, Any], company: str, source: str) -> dict[str, Any]:
    title = (
        raw_job.get("title")
        or raw_job.get("job_title")
        or raw_job.get("jobTitle")
        or raw_job.get("name")
        or ""
    )
    location = (
        raw_job.get("location")
        or raw_job.get("job_location")
        or raw_job.get("city")
        or ""
    )
    description = (
        raw_job.get("description")
        or raw_job.get("summary")
        or raw_job.get("snippet")
        or ""
    )
    url = (
        raw_job.get("url")
        or raw_job.get("apply_link")
        or raw_job.get("link")
        or ""
    )

    return {
        "id": raw_job.get("id") or f"{company.lower()}-{abs(hash(title + location + source))}",
        "company": company.title(),
        "title": title,
        "location": location,
        "description": description,
        "employment_type": raw_job.get("employment_type") or raw_job.get("type") or "",
        "experience": raw_job.get("experience") or "",
        "skills": raw_job.get("skills") or [],
        "url": url,
        "source": source,
    }
