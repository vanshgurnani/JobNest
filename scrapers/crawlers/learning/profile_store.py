from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PROFILES_PATH = Path(__file__).resolve().parent.parent.parent / "api_profiles.json"


def load_profiles() -> dict[str, Any]:
    if _PROFILES_PATH.exists():
        try:
            return json.loads(_PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_profile(domain: str, profile: dict[str, Any]) -> None:
    profiles = load_profiles()
    profiles[domain] = profile
    _PROFILES_PATH.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    logger.info("Saved API profile for %s", domain)


def get_profile(domain: str) -> dict[str, Any] | None:
    return load_profiles().get(domain)


def get_profile_by_url(url: str) -> dict[str, Any] | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    profile = get_profile(host)
    if profile:
        return profile
    root = ".".join(host.split(".")[-2:]) if len(host.split(".")) > 2 else host
    return get_profile(root)


def learn_from_successful_fetch(
    domain: str,
    request_url: str,
    response: Any,
    extracted_jobs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    existing = get_profile(domain)
    if existing and existing.get("verified", False):
        return existing

    if not extracted_jobs:
        return existing

    url_pattern = _generalize_url(request_url)
    response_paths = _discover_response_paths(response, extracted_jobs)
    pagination = _detect_pagination_params(request_url, response)
    field_map = _build_field_map(extracted_jobs)

    profile = {
        "domain": domain,
        "url_pattern": url_pattern,
        "response_paths": response_paths,
        "pagination": pagination,
        "field_map": field_map,
        "sample_jobs": extracted_jobs[:2],
        "verified": True,
    }
    save_profile(domain, profile)
    return profile


async def learn_from_api_response(
    domain: str,
    api_url: str,
    response: Any,
    company: str,
) -> list[dict[str, Any]] | None:
    from scrapers.crawlers.base import collect_job_candidates, normalize_job_payload
    from scrapers.crawlers.universal import _extract_jobs_from_json_payload

    profile = get_profile(domain)
    if not profile:
        return None

    payload = response
    if profile.get("response_paths"):
        for path_key in profile["response_paths"]:
            parts = path_key.split(".")
            current = payload
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                elif isinstance(current, list):
                    try:
                        idx = int(part)
                        current = current[idx] if idx < len(current) else None
                    except ValueError:
                        current = None
                else:
                    current = None
                if current is None:
                    break
            if current is not None:
                payload = current
                break

    candidates = collect_job_candidates(payload)
    if profile.get("field_map"):
        mapped = []
        for c in candidates:
            job = normalize_job_payload(c, company, "profile-api")
            if job.get("title"):
                mapped.append(job)
        if mapped:
            return mapped

    return await _extract_jobs_from_json_payload(payload, company, "profile-api")


def _generalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/\d+", "/{id}", parsed.path)
    path = re.sub(r"/[\w-]+-\d+", "/{slug}-{id}", path)
    return f"{parsed.netloc}{path}"


def _discover_response_paths(data: Any, sample_jobs: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    if not isinstance(data, dict) or not sample_jobs:
        return paths

    sample_keys = set(sample_jobs[0].keys()) if sample_jobs else set()

    def walk(obj: Any, prefix: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                current = f"{prefix}.{k}" if prefix else k
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    if any(key in v[0] for key in ("title", "name", "jobTitle", "description")):
                        paths.append(current)
                walk(v, current)
        elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
            if any(key in obj[0] for key in ("title", "name", "jobTitle")):
                paths.append(prefix)
            for item in obj:
                walk(item, prefix)

    walk(data)
    return paths[:5]


def _detect_pagination_params(url: str, data: Any) -> dict[str, Any]:
    pagination: dict[str, Any] = {}
    from urllib.parse import parse_qs
    params = parse_qs(urlparse(url).query)
    for key in ("page", "p", "offset", "start", "cursor", "pageNumber"):
        if key in params:
            pagination["param"] = key
            pagination["offset"] = 0
            break

    if isinstance(data, dict):
        for key in ("nextPageToken", "cursor", "nextCursor", "continuationToken", "hasMore"):
            if key in data:
                pagination["type"] = "cursor"
                pagination["cursor_field"] = key
                break
        for key in ("totalPages", "totalCount", "total", "hits", "count"):
            if key in data:
                pagination["total_field"] = key
                break

    return pagination


def _build_field_map(jobs: list[dict[str, Any]]) -> dict[str, str]:
    if not jobs:
        return {}
    field_map: dict[str, str] = {}
    job = jobs[0]
    known = {
        "title": ("title", "name", "jobTitle", "role", "position"),
        "location": ("location", "city", "workLocation", "locationsText", "jobLocation"),
        "description": ("description", "summary", "content", "details", "snippet"),
        "job_id": ("id", "jobId", "job_id", "requisitionId", "uuid", "externalPath"),
        "apply_url": ("applyUrl", "apply_url", "url", "absolute_url", "hostedUrl", "ref"),
        "employment_type": ("employmentType", "employment_type", "type", "workType", "timeType"),
        "experience": ("experience", "experienceLevel", "experience_level", "level", "seniority"),
        "skills": ("skills", "technologies", "requirements", "qualifications"),
    }
    for target, candidates in known.items():
        for key in job:
            if key.lower() in candidates:
                field_map[target] = key
                break
    return field_map
