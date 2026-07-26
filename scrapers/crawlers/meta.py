from __future__ import annotations

import logging
import re
from typing import Any

from scrapers.crawlers.base import normalize_job_payload, request_json_with_retries, request_with_retries

logger = logging.getLogger(__name__)

META_SEARCH_URL = "https://www.metacareers.com/jobs/"
META_GRAPHQL_URL = "https://www.metacareers.com/graphql"


async def fetch_meta_jobs(
    keyword: str = "Software",
    location: str = "",
    page: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch Meta jobs using HTTP requests. Playwright-free for low CPU footprint."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }

    # Strategy 1: Attempt GraphQL query POST request
    try:
        gql_headers = dict(headers)
        gql_headers["Accept"] = "application/json, text/plain, */*"
        gql_headers["Content-Type"] = "application/x-www-form-urlencoded"
        gql_headers["Referer"] = META_SEARCH_URL

        payload = {
            "av": "0",
            "__user": "0",
            "__a": "1",
            "__req": "1",
            "doc_id": "6817290138356952",
            "variables": f'{{"q":"{keyword}","page":{page},"limit":{limit}}}',
        }
        res_json = await request_json_with_retries(
            META_GRAPHQL_URL,
            method="POST",
            headers=gql_headers,
            data=payload,
            timeout=10.0,
            max_retries=1,
        )
        if isinstance(res_json, dict):
            edges = (
                res_json.get("data", {})
                .get("job_search", {})
                .get("edges", [])
            )
            jobs_list = []
            for edge in edges:
                node = edge.get("node", {}) if isinstance(edge, dict) else {}
                job_id = str(node.get("id") or "")
                if job_id:
                    jobs_list.append(
                        normalize_job_payload(
                            {
                                "job_id": job_id,
                                "title": node.get("title", ""),
                                "location": ", ".join(node.get("locations", []))
                                if isinstance(node.get("locations"), list)
                                else str(node.get("location") or ""),
                                "description": node.get("description", ""),
                                "apply_url": f"https://www.metacareers.com/v2/jobs/{job_id}/",
                                "employment_type": "Full-time",
                            },
                            "Meta",
                            "meta",
                        )
                    )
            if jobs_list:
                return jobs_list[:limit]
    except Exception as exc:
        logger.debug("Meta GraphQL HTTP fetch fallback: %s", exc)

    # Strategy 2: Fetch HTML and extract embedded job links
    try:
        html = await request_with_retries(META_SEARCH_URL, headers=headers, timeout=10.0, max_retries=1)
        jobs = []
        seen_ids = set()

        for m in re.finditer(r'/v2/jobs/(\d+)/', html):
            job_id = m.group(1)
            if job_id not in seen_ids:
                seen_ids.add(job_id)
                jobs.append(
                    normalize_job_payload(
                        {
                            "job_id": job_id,
                            "title": f"Meta Role ({keyword}) #{job_id}",
                            "location": location or "Remote / Various",
                            "apply_url": f"https://www.metacareers.com/v2/jobs/{job_id}/",
                            "employment_type": "Full-time",
                        },
                        "Meta",
                        "meta",
                    )
                )

        if jobs:
            start = (page - 1) * limit
            return jobs[start : start + limit]
    except Exception as exc:
        logger.debug("Meta HTML scrape error: %s", exc)

    return []
