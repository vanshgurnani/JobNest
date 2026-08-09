import hashlib
import html
import re
from typing import Any


def _stable_job_id(title: str, location: str, source: str, company: str) -> str:
    seed = f"{company.lower()}:{title}:{location}:{source}"
    return hashlib.sha256(seed.encode()).hexdigest()[:20]


def _clean_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def html_to_text(raw: str | None) -> str:
    """Convert HTML job descriptions into readable plain text."""
    if not raw:
        return ""
    text = str(raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|ul|ol|tr|blockquote|section|article|header|footer)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n• ", text)
    text = re.sub(r"(?i)<(p|div|h[1-6]|tr|section|article|header|footer)[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
        "id": raw_job.get("id") or _stable_job_id(title, location, source, company),
        "company": company.title(),
        "title": title,
        "location": location,
        "description": _clean_html(description),
        "employment_type": raw_job.get("employment_type") or raw_job.get("type") or "",
        "experience": raw_job.get("experience") or "",
        "skills": raw_job.get("skills") or [],
        "url": url,
        "source": source,
    }
