from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from app.crawler.base import normalize_job_payload

logger = logging.getLogger(__name__)

# Discovered via Playwright network inspection of https://www.metacareers.com/jobsearch/
# Meta uses a persisted GraphQL endpoint with doc_id values embedded in page JS.
_GRAPHQL_URL = "https://www.metacareers.com/graphql"
_SEARCH_PAGE_URL = "https://www.metacareers.com/jobsearch/"

# doc_id for CareersJobSearchResultsV2DataQuery (confirmed via Playwright capture)
_SEARCH_DOC_ID = "27129360303422352"

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _extract_lsd_token(html: str) -> str | None:
    """Extract the LSD CSRF token embedded in Meta's page HTML."""
    match = re.search(r'"LSD",\[\],\{"token":"([^"]+)"\}', html)
    return match.group(1) if match else None


def _parse_ldplus_json(html: str) -> dict[str, Any] | None:
    """
    Parse Schema.org JobPosting JSON-LD block embedded in a Meta job detail page.
    This is embedded in a <script type="application/ld+json"> tag.
    """
    match = re.search(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _build_graphql_payload(lsd: str, keyword: str, location: str = "") -> dict[str, str]:

    """Build the form-encoded payload for Meta's GraphQL endpoint."""
    # Exact variable structure confirmed by Playwright network capture.
    # IMPORTANT: results_per_page MUST be null (not an integer) — any int causes
    # a 'noncoercible_variable_value' error from the server.
    variables = json.dumps({
        "search_input": {
            "q": keyword,
            "divisions": [],
            "offices": [location] if location else [],

            "roles": [],
            "leadership_levels": [],
            "saved_jobs": [],
            "saved_searches": [],
            "sub_teams": [],
            "teams": [],
            "is_leadership": False,
            "is_remote_only": False,
            "sort_by_new": False,
            "results_per_page": None,   # must be null, not an integer
        },
        "viewasUserID": None,
        "isLoggedIn": False,
    })
    return {
        "av": "0",
        "__user": "0",
        "__a": "1",
        "fb_api_req_friendly_name": "CareersJobSearchResultsV2DataQuery",
        "variables": variables,
        "doc_id": _SEARCH_DOC_ID,
        "lsd": lsd,
    }



async def _fetch_job_detail(client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    """
    Fetch job detail from Meta's public job page.
    The detail URL redirects to /profile/job_details/{id}/ which contains
    a Schema.org JobPosting JSON-LD block with full description.
    Strategy: HTTP GET with follow_redirects, parse ld+json block.
    """
    url = f"https://www.metacareers.com/v2/jobs/{job_id}/"
    try:
        r = await client.get(url)
        r.raise_for_status()
        return _parse_ldplus_json(r.text) or {}
    except Exception as exc:
        logger.debug("Failed to fetch Meta job detail for %s: %s", job_id, exc)
        return {}


async def fetch_meta_jobs(
    keyword: str = "Software",
    location: str = "",
    max_pages: int = 2,
    page: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:

    """
    Fetch Meta Careers job listings using the GraphQL API endpoint.

    Strategy:
    1. GET /jobsearch/ to extract the per-session LSD CSRF token from embedded JS.
    2. POST to /graphql with doc_id=27129360303422352 and search variables.
       Response: {"data": {"job_search_with_featured_jobs_v2": {"all_jobs": [...]}}}
       Each job has: id, title, locations, teams, sub_teams.
       NOTE: results_per_page must be null — passing an int causes a server error.
    3. For each job, fetch the detail page and parse Schema.org JSON-LD:
       title, description, responsibilities, qualifications, employmentType.
    4. Normalize to the common job schema.
    """
    jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(headers=_HEADERS, timeout=25.0, follow_redirects=True) as client:
        # Step 1: Extract LSD CSRF token from the job search page
        try:
            page_resp = await client.get(_SEARCH_PAGE_URL)
            page_resp.raise_for_status()
            lsd = _extract_lsd_token(page_resp.text)
            if not lsd:
                logger.error("Meta crawler: could not extract LSD token from search page")
                return []
        except Exception as exc:
            logger.error("Meta crawler: failed to fetch search page: %s", exc)
            return []

        graphql_headers = {
            "x-fb-friendly-name": "CareersJobSearchResultsV2DataQuery",
            "x-fb-lsd": lsd,
            "x-asbd-id": "359341",
            "referer": "https://www.metacareers.com/jobsearch/",
            "content-type": "application/x-www-form-urlencoded",
        }

        # Step 2: Fetch job list via GraphQL (single call returns all matches)
        try:
            payload = _build_graphql_payload(lsd, keyword, location)

            r = await client.post(_GRAPHQL_URL, headers=graphql_headers, data=payload)
            r.raise_for_status()
            resp_json = r.json()
            if "errors" in resp_json:
                logger.error("Meta GraphQL returned errors: %s", resp_json["errors"])
                return []
            search_data = resp_json.get("data", {}).get("job_search_with_featured_jobs_v2") or {}
            raw_jobs: list[dict[str, Any]] = search_data.get("all_jobs") or []
        except Exception as exc:
            logger.warning("Meta GraphQL request failed: %s", exc)
            return []

        if not raw_jobs:
            return []

        # GraphQL response returns many jobs; apply pagination by slicing.
        page_start = max(0, (page - 1) * limit)
        page_end = page_start + limit

        # Limit how many detail pages we fetch to avoid overloading.
        # First slice to the requested window, then cap detail fetches.
        sliced_jobs = raw_jobs[page_start:page_end]
        max_detail_fetches = min(len(sliced_jobs), max_pages * 10)
        raw_jobs = sliced_jobs[:max_detail_fetches]


        # Step 3: Fetch job details concurrently in small batches
        async def _enrich(raw_job: dict[str, Any]) -> dict[str, Any] | None:
            job_id = str(raw_job.get("id") or "")
            if not job_id or job_id in seen_ids:
                return None
            seen_ids.add(job_id)

            title = raw_job.get("title") or ""
            locations = raw_job.get("locations") or []
            location_val = ", ".join(locations) if locations else location
            teams = raw_job.get("teams") or []
            team_val = teams[0] if teams else ""

            # Fetch Schema.org JSON-LD from the detail page
            detail = await _fetch_job_detail(client, job_id)

            description = detail.get("description") or ""
            responsibilities = detail.get("responsibilities") or ""
            qualifications = detail.get("qualifications") or ""

            if responsibilities:
                description += f"\n\nResponsibilities:\n{responsibilities}"
            if qualifications:
                description += f"\n\nQualifications:\n{qualifications}"

            employment_type = detail.get("employmentType") or "Full-time"
            apply_url = f"https://www.metacareers.com/v2/jobs/{job_id}/"

            return normalize_job_payload(
                {
                    "job_id": job_id,
                    "title": title,
                    "location": location_val,
                    "description": description,
                    "apply_url": apply_url,
                    "employment_type": employment_type,
                    "experience": "",
                    "skills": [],
                    "team": team_val,
                },
                "Meta",
                "meta",
            )

        for i in range(0, len(raw_jobs), 5):
            chunk = raw_jobs[i : i + 5]
            results = await asyncio.gather(*[_enrich(j) for j in chunk])
            for result in results:
                if result and result.get("title"):
                    jobs.append(result)
            if i + 5 < len(raw_jobs):
                await asyncio.sleep(0.3)

    # Apply final limit for API-level pagination
    return jobs[:limit]


