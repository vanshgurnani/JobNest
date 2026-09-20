"""Provider-independent job identity and canonical normalization helpers."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services.normalizer import html_to_text

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref",
}


def canonicalize_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(str(value).strip())
    if not parsed.scheme or not parsed.netloc:
        return str(value).strip()
    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
             if key.lower() not in _TRACKING_PARAMS]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(query), ""))


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_location(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        city = normalize_text(value.get("city") or value.get("addressLocality"))
        state = normalize_text(value.get("state") or value.get("addressRegion"))
        country = normalize_text(value.get("country") or value.get("addressCountry"))
        text = ", ".join(part for part in (city, state, country) if part)
    elif isinstance(value, list):
        locations = [normalize_location(item) for item in value]
        text = "; ".join(item["text"] for item in locations if item["text"])
        return {"text": text, "city": "", "state": "", "country": "", "remote": "remote" in text.lower(), "locations": locations}
    else:
        text = normalize_text(value)
        parts = [part.strip() for part in text.split(",")]
        city = parts[0] if parts else ""
        state = parts[1] if len(parts) > 2 else ""
        country = parts[-1] if len(parts) > 1 else ""
    return {
        "text": text,
        "city": city,
        "state": state,
        "country": country,
        "remote": any(term in text.lower() for term in ("remote", "work from anywhere", "distributed")),
        "locations": [],
    }


def parse_salary(value: Any) -> dict[str, Any]:
    raw = normalize_text(value)
    if not raw:
        return {"salary_min": None, "salary_max": None, "currency": "", "raw_salary": ""}
    currency_match = re.search(r"(USD|EUR|GBP|INR|CAD|AUD|[$€£₹])", raw, re.IGNORECASE)
    currency_map = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
    currency = currency_map.get(currency_match.group(1), currency_match.group(1).upper()) if currency_match else ""
    numbers = [float(item.replace(",", "")) for item in re.findall(r"\d[\d,]*(?:\.\d+)?", raw)]
    if not numbers:
        return {"salary_min": None, "salary_max": None, "currency": currency, "raw_salary": raw}
    if len(numbers) == 1:
        numbers.append(numbers[0])
    return {"salary_min": numbers[0], "salary_max": numbers[1], "currency": currency, "raw_salary": raw}


def job_identity(job: dict[str, Any]) -> str:
    provider = normalize_text(job.get("portal") or job.get("source") or "unknown").lower()
    source_id = normalize_text(job.get("source_job_id") or job.get("job_id"))
    if source_id:
        seed = f"{provider}|{source_id}"
    else:
        url = canonicalize_url(job.get("canonical_url") or job.get("url") or job.get("apply_url"))
        if url:
            seed = url
        else:
            company = normalize_text(job.get("company") or job.get("company_name")).lower()
            title = normalize_text(job.get("title")).lower()
            location = normalize_location(job.get("location")).get("text", "").lower()
            seed = f"{company}|{title}|{location}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def canonical_job(raw: dict[str, Any], *, company: str = "", portal: str = "unknown", adapter: str = "universal", careers_url: str = "") -> dict[str, Any]:
    title = normalize_text(raw.get("title") or raw.get("job_title") or raw.get("jobTitle") or raw.get("name"))
    location = normalize_location(raw.get("location") or raw.get("job_location") or raw.get("jobLocation") or raw.get("city"))
    canonical_url = canonicalize_url(raw.get("canonical_url") or raw.get("url") or raw.get("apply_url") or careers_url)
    apply_url = canonicalize_url(raw.get("apply_url") or raw.get("url") or canonical_url)
    description = html_to_text(normalize_text(raw.get("description") or raw.get("content") or raw.get("summary")))
    source_job_id = normalize_text(raw.get("source_job_id") or raw.get("job_id") or raw.get("jobId") or raw.get("id"))
    salary = parse_salary(raw.get("raw_salary") or raw.get("salary") or raw.get("compensation"))
    raw_skills = raw.get("skills") or []
    if isinstance(raw_skills, str):
        raw_skills = re.split(r"[,;|/]", raw_skills)
    result: dict[str, Any] = {
        "id": job_identity({**raw, "source_job_id": source_job_id, "canonical_url": canonical_url, "company": company, "portal": portal, "title": title, "location": location["text"]}),
        "job_id": source_job_id,
        "source_job_id": source_job_id,
        "canonical_url": canonical_url,
        "apply_url": apply_url,
        "url": apply_url,
        "company": normalize_text(raw.get("company") or company),
        "company_name": normalize_text(raw.get("company") or company),
        "title": title,
        "department": normalize_text(raw.get("department")),
        "team": normalize_text(raw.get("team")),
        "employment_type": normalize_text(raw.get("employment_type") or raw.get("employmentType") or raw.get("type")),
        "seniority": normalize_text(raw.get("seniority") or raw.get("experience") or raw.get("experience_level")),
        "workplace_type": normalize_text(raw.get("workplace_type") or ("remote" if location["remote"] else "")),
        "location": location["text"],
        "city": location["city"],
        "state": location["state"],
        "country": location["country"],
        "remote": location["remote"],
        "locations": location["locations"],
        **salary,
        "description": description,
        "responsibilities": normalize_text(raw.get("responsibilities")),
        "qualifications": normalize_text(raw.get("qualifications") or raw.get("requirements")),
        "preferred_qualifications": normalize_text(raw.get("preferred_qualifications")),
        "benefits": normalize_text(raw.get("benefits")),
        "skills": [normalize_text(item) for item in raw_skills if normalize_text(item)],
        "posted_at": raw.get("posted_at") or raw.get("posted_date") or raw.get("date_posted") or "",
        "updated_at": raw.get("updated_at") or "",
        "expires_at": raw.get("expires_at") or raw.get("valid_through") or "",
        "posted_date": raw.get("posted_date") or raw.get("posted_at") or "",
        "valid_through": raw.get("valid_through") or raw.get("expires_at") or "",
        "source": normalize_text(raw.get("source") or portal),
        "portal": portal,
        "adapter": adapter,
        "extraction_method": normalize_text(raw.get("extraction_method") or "unknown"),
        "raw_payload_reference": raw.get("raw_payload_reference", ""),
        "scraped_at": raw.get("scraped_at") or datetime.now(timezone.utc).isoformat(),
        "content_hash": hashlib.sha256(f"{title}|{location['text']}|{description}".encode("utf-8")).hexdigest(),
        "active": bool(raw.get("active", True)),
    }
    return result
