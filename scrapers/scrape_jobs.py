from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure workspace root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.mongo import close_mongo, connect_mongo
from app.schemas.job import canonicalize_job
from app.services.job_store import upsert_jobs
from scrapers.crawlers.orchestrator import crawl_jobs, supported_companies

LOGGER = logging.getLogger("scrapers.scrape_jobs")


def _parse_company_list(value: str | None) -> list[str]:
    if not value or value.strip().lower() == "all":
        return supported_companies()
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def _parse_url_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _format_jobs_preview(jobs: list[dict[str, Any]]) -> str:
    preview = []
    for idx, job in enumerate(jobs[:4], start=1):
        preview.append({
            "index": idx,
            "id": job.get("id") or job.get("job_id"),
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "apply_url": job.get("apply_url") or job.get("url"),
            "source": job.get("source"),
        })
    return json.dumps(preview, indent=2, ensure_ascii=False)


async def _scrape_company(
    company: str | None,
    *,
    company_url: str | None = None,
    keyword: str | None,
    location: str | None,
    pages: int,
    page_size: int,
    delay_seconds: float,
) -> list[dict[str, Any]]:
    all_jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    label = company_url or company or "unknown"

    for page in range(1, pages + 1):
        LOGGER.info("[SCRAPE] Fetching target='%s' page=%d limit=%d", label, page, page_size)
        results = await crawl_jobs(
            company=company,
            company_url=company_url,
            keyword=keyword,
            location=location,
            page=page,
            limit=page_size,
        )

        page_jobs: list[dict[str, Any]] = []
        for result in results:
            status = result.get("status", "unknown")
            if status != "ok":
                LOGGER.warning(
                    "[SCRAPE] Crawler reported failure for company='%s' page=%d: %s",
                    company,
                    page,
                    result.get("error", "unknown"),
                )
            for raw_job in result.get("jobs", []):
                job = canonicalize_job(raw_job)
                job_id = job.get("id") or f"{label}-{len(seen_ids)+1}"
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                page_jobs.append(job)

        LOGGER.info("[SCRAPE] Page complete target='%s' page=%d jobs_found=%d", label, page, len(page_jobs))
        if not page_jobs:
            LOGGER.info("[SCRAPE] No further jobs found for target='%s' on page=%d. Ending pagination.", label, page)
            break

        all_jobs.extend(page_jobs)
        if page < pages and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    LOGGER.info("[SCRAPE] Finished scraping target='%s'. Total jobs collected: %d", label, len(all_jobs))
    return all_jobs


async def _run(args: argparse.Namespace) -> None:
    companies = _parse_company_list(args.companies)
    urls = _parse_url_list(args.company_url)

    if not companies and not urls:
        raise SystemExit("No companies or company URLs selected for scraping.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    LOGGER.info("=" * 60)
    LOGGER.info("STARTING JOB SCRAPER | Mode: %s", args.mode.upper())
    if companies:
        LOGGER.info("Target Companies: %s", ", ".join(companies))
    if urls:
        LOGGER.info("Target URLs: %s", ", ".join(urls))
    LOGGER.info("Pages per Target: %d | Limit per Page: %d", args.pages, args.page_size)
    LOGGER.info("=" * 60)

    if args.mode == "db":
        LOGGER.info("[DB MODE] Connecting to MongoDB...")
        await connect_mongo()

    total_scraped = 0
    all_collected_jobs: list[dict[str, Any]] = []

    try:
        for company in companies:
            LOGGER.info("[SEQUENTIAL] Processing company: %s", company)
            jobs = await _scrape_company(
                company,
                keyword=args.keyword,
                location=args.location,
                pages=args.pages,
                page_size=args.page_size,
                delay_seconds=args.delay_seconds,
            )
            total_scraped += len(jobs)
            all_collected_jobs.extend(jobs)

            if args.mode == "db" and jobs:
                await upsert_jobs(jobs)
                LOGGER.info("[DB MODE] Successfully upserted %d jobs for '%s' into MongoDB.", len(jobs), company)

            if args.delay_seconds > 0:
                await asyncio.sleep(args.delay_seconds)

        for url in urls:
            LOGGER.info("[SEQUENTIAL] Processing company URL: %s", url)
            jobs = await _scrape_company(
                company=None,
                company_url=url,
                keyword=args.keyword,
                location=args.location,
                pages=args.pages,
                page_size=args.page_size,
                delay_seconds=args.delay_seconds,
            )
            total_scraped += len(jobs)
            all_collected_jobs.extend(jobs)

            if args.mode == "db" and jobs:
                await upsert_jobs(jobs)
                LOGGER.info("[DB MODE] Successfully upserted %d jobs for URL '%s' into MongoDB.", len(jobs), url)

            if args.delay_seconds > 0:
                await asyncio.sleep(args.delay_seconds)

        LOGGER.info("=" * 60)
        LOGGER.info("SCRAPE SUMMARY | Mode: %s", args.mode.upper())
        LOGGER.info("Total Jobs Scraped Across All Targets: %d", total_scraped)

        if all_collected_jobs:
            LOGGER.info("\n--- FIRST 4 DATA POINTS PREVIEW ---\n%s\n---------------------------------", _format_jobs_preview(all_collected_jobs))
        else:
            LOGGER.info("No job data points were retrieved.")

        LOGGER.info("=" * 60)

    finally:
        if args.mode == "db":
            LOGGER.info("[DB MODE] Closing MongoDB connection...")
            await close_mongo()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequential Playwright-free job scraper for Job Nest.")
    parser.add_argument("--mode", choices=["local", "db"], default="local", help="Operation mode: local (dry run / preview) or db (upsert to MongoDB).")
    parser.add_argument("--companies", default="all", help="Comma-separated company slugs or 'all'.")
    parser.add_argument("--company-url", default=None, help="Comma-separated company career page URLs to scrape (bypasses company name lookup).")
    parser.add_argument("--keyword", default=None, help="Filter jobs by keyword.")
    parser.add_argument("--location", default=None, help="Filter jobs by location.")
    parser.add_argument("--pages", type=int, default=2, help="Number of pages to scrape per company.")
    parser.add_argument("--page-size", type=int, default=20, help="Number of items per page.")
    parser.add_argument("--delay-seconds", type=float, default=0.5, help="Delay between page/company requests in seconds (CPU protection).")

    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
