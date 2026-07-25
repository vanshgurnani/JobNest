import asyncio
from typing import Any

from scripts.scraping.crawlers.base import normalize_job_payload


async def fetch_meta_jobs(
    keyword: str = "Software",
    location: str = "",
    page: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Meta scraping requires Playwright. Install requirements-scraping.txt "
            "and run the scraper with --include-browser."
        ) from exc

    jobs_data = []
    seen_ids = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page_obj = await context.new_page()

        # 🔥 Collect ALL GraphQL responses (not just first)
        async def handle_response(response):
            nonlocal jobs_data, seen_ids

            if "graphql" in response.url:
                try:
                    data = await response.json()

                    possible_paths = [
                        ("data", "job_search", "edges"),
                        ("data", "job_search_with_featured_jobs_v2", "all_jobs"),
                    ]

                    for path in possible_paths:
                        ref = data
                        for key in path:
                            ref = ref.get(key, {})

                        if isinstance(ref, list):
                            for item in ref:
                                job = item.get("node") if "node" in item else item
                                job_id = str(job.get("id"))

                                if job_id and job_id not in seen_ids:
                                    seen_ids.add(job_id)
                                    jobs_data.append(job)

                except:
                    pass

        page_obj.on("response", handle_response)

        # 🔥 Open page
        await page_obj.goto("https://www.metacareers.com/jobsearch/", timeout=60000)

        # 🔥 SCROLL LOOP (this is the real fix)
        max_scrolls = 15
        scroll_count = 0

        while len(jobs_data) < (page * limit) and scroll_count < max_scrolls:
            await page_obj.mouse.wheel(0, 5000)
            await page_obj.wait_for_timeout(1500)
            scroll_count += 1

        await browser.close()

    if not jobs_data:
        return []

    # 🔥 Pagination (now safe)
    start = (page - 1) * limit
    raw_jobs = jobs_data[start:start + limit]

    results = []
    for job in raw_jobs:
        job_id = str(job.get("id") or "")

        results.append(
            normalize_job_payload(
                {
                    "job_id": job_id,
                    "title": job.get("title", ""),
                    "location": ", ".join(job.get("locations", []))
                    if isinstance(job.get("locations"), list)
                    else "",
                    "description": "",
                    "apply_url": f"https://www.metacareers.com/v2/jobs/{job_id}/",
                    "employment_type": "Full-time",
                    "skills": [],
                },
                "Meta",
                "meta",
            )
        )

    return results
