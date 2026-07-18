from __future__ import annotations
import asyncio
import logging
import re
from typing import Any

import httpx

from app.crawler.base import normalize_job_payload, request_json_with_retries

logger = logging.getLogger(__name__)

# Discovered via Playwright network inspection:
# https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=...&start=0
# https://apply.careers.microsoft.com/api/pcsx/position_details?position_id=...&domain=microsoft.com&hl=en
# https://apply.careers.microsoft.com/api/pcsx/position_insights?position_id=...&domain=microsoft.com

_SEARCH_URL = "https://apply.careers.microsoft.com/api/pcsx/search"
_DETAILS_URL = "https://apply.careers.microsoft.com/api/pcsx/position_details"
_INSIGHTS_URL = "https://apply.careers.microsoft.com/api/pcsx/position_insights"
_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def _strip_html(text: str) -> str:
    """Strip HTML tags from a string and normalize whitespace."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _fetch_position_details(client: httpx.AsyncClient, position_id: int) -> dict[str, Any]:
    """Fetch full job description for a single position."""
    try:
        r = await client.get(
            _DETAILS_URL,
            params={"position_id": str(position_id), "domain": "microsoft.com", "hl": "en"},
        )
        r.raise_for_status()
        return r.json().get("data") or {}
    except Exception as exc:
        logger.debug("Failed to fetch MS position details for %s: %s", position_id, exc)
        return {}


async def _fetch_position_insights(client: httpx.AsyncClient, position_id: int) -> list[str]:
    """Fetch skills list from position insights endpoint."""
    try:
        r = await client.get(
            _INSIGHTS_URL,
            params={"position_id": str(position_id), "domain": "microsoft.com"},
        )
        r.raise_for_status()
        insights = r.json().get("data", {}).get("insights", {})
        return list(insights.get("skills", {}).keys())
    except Exception as exc:
        logger.debug("Failed to fetch MS position insights for %s: %s", position_id, exc)
        return []


async def fetch_microsoft_jobs(
    keyword: str = "software",
    location: str = "",
    max_pages: int = 2,
    page: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:


    """
    Fetch Microsoft job listings using the internal PCSX JSON API discovered via
    Playwright network inspection. Each page returns up to 20 results; we paginate
    by incrementing the `start` offset.

    Strategy:
    1. Search API returns position list (id, name, locations, department).
    2. For each position, fetch full description via position_details endpoint.
    3. Optionally fetch skill tags via position_insights endpoint.
    4. Normalize into the common job schema.
    """
    jobs: list[dict[str, Any]] = []
    page_size = 20
    seen_ids: set[int] = set()

    # Microsoft paging is offset-based: start = page_idx * 20
    start_page_idx = max(0, page - 1)

    async with httpx.AsyncClient(headers=_BASE_HEADERS, timeout=25.0, follow_redirects=True) as client:
        for page_idx in range(start_page_idx, start_page_idx + max_pages):
            offset = page_idx * page_size

            try:
                r = await client.get(
                    _SEARCH_URL,
                    params={
                        "domain": "microsoft.com",
                        "query": keyword,
                        "location": location,
                        "start": str(offset),
                    },
                )
                r.raise_for_status()
                positions = r.json().get("data", {}).get("positions") or []
            except Exception as exc:
                logger.warning("Microsoft search page %s failed: %s", page_idx + 1, exc)
                break

            if not positions:
                break

            # Fetch details for each position concurrently (batch of 5 to avoid throttling)
            batch_tasks = []
            for pos in positions:
                pid = pos.get("id")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                batch_tasks.append((pos, pid))

            async def _enrich(pos: dict[str, Any], pid: int) -> dict[str, Any] | None:
                details, skills = await asyncio.gather(
                    _fetch_position_details(client, pid),
                    _fetch_position_insights(client, pid),
                )
                title = details.get("name") or pos.get("name") or ""
                if not title:
                    return None

                location_val = (
                    details.get("location")
                    or (pos.get("locations") or [""])[0]
                    or ""
                )

                description_html = details.get("jobDescription") or ""
                description = _strip_html(description_html) if description_html else ""

                # Business group / department from API
                department = (
                    details.get("department")
                    or pos.get("department")
                    or ""
                )
                if department and description:
                    description = f"{description}\n\nBusiness Group: {department}"

                employment_type = ""
                custom_employment = details.get("efcustomTextEmploymentType")
                if isinstance(custom_employment, list) and custom_employment:
                    employment_type = custom_employment[0]

                apply_url = details.get("publicUrl") or (
                    "https://apply.careers.microsoft.com" + (details.get("positionUrl") or "")
                )

                return normalize_job_payload(
                    {
                        "job_id": details.get("displayJobId") or details.get("atsJobId") or str(pid),
                        "title": title,
                        "location": location_val,
                        "description": description,
                        "apply_url": apply_url,
                        "employment_type": employment_type,
                        "experience": "",
                        "skills": skills,
                        "team": department,
                    },
                    "Microsoft",
                    "microsoft",
                )

            # Run in small concurrent batches
            for i in range(0, len(batch_tasks), 5):
                chunk = batch_tasks[i : i + 5]
                results = await asyncio.gather(*[_enrich(pos, pid) for pos, pid in chunk])
                for result in results:
                    if result and result.get("title"):
                        jobs.append(result)
                if i + 5 < len(batch_tasks):
                    await asyncio.sleep(0.2)

            if len(positions) < page_size:
                break
            await asyncio.sleep(0.3)

    # Apply final limit for API-level pagination
    return jobs[:limit]

