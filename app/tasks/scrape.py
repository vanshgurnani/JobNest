"""
app/tasks/scrape.py — Celery tasks for automated job scraping.

Tasks:
  - scrape_company_task:     Scrape a single company or URL (with circuit-breaker check)
  - scrape_all_companies:    Kick off scrape_company_task for all seeded companies
  - retry_failing_scrapers:  Re-queue only degraded/failing targets
  - scrape_url_task:         Scrape an arbitrary URL (user-triggered)
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure workspace root is on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from celery_app import app  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: run async code from a sync Celery task
# ---------------------------------------------------------------------------
def _run(coro):
    """Execute an async coroutine synchronously inside a Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Single-company scrape task
# ---------------------------------------------------------------------------
@app.task(
    bind=True,
    name="app.tasks.scrape.scrape_company_task",
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
)
def scrape_company_task(
    self,
    *,
    company: str | None = None,
    url: str | None = None,
    keyword: str | None = None,
    location: str | None = None,
    pages: int = 2,
    page_size: int = 20,
    save_to_db: bool = True,
) -> dict[str, Any]:
    """
    Scrape a single company or URL and persist results to MongoDB.

    Uses the circuit breaker: if the target has >= 5 consecutive failures
    and hasn't cooled down, the task exits early without retrying.
    """
    target = url or company or "unknown"
    logger.info("[TASK] scrape_company_task started for '%s'", target)

    try:
        from app.services.scraper_health import is_circuit_open

        # Circuit-breaker check
        circuit_open = _run(is_circuit_open(target))
        if circuit_open:
            logger.warning("[TASK] Circuit open for '%s' — skipping this run", target)
            return {"target": target, "skipped": True, "reason": "circuit_open", "jobs": 0}

        # Resolve input (company name or URL)
        from scrapers.resolver import resolve_company_input
        resolved = _run(resolve_company_input(url or company or ""))
        effective_url = url or resolved.get("careers_url")
        effective_company = company or resolved.get("company_name")

        # Run the scraper
        from scrapers.scrape_jobs import _scrape_company
        jobs = _run(
            _scrape_company(
                effective_company,
                company_url=effective_url,
                keyword=keyword,
                location=location,
                pages=pages,
                page_size=page_size,
                delay_seconds=0.5,
            )
        )

        ats = (resolved.get("ats") or {}).get("platform")
        job_count = len(jobs)

        # Record health
        from app.services.scraper_health import record_success, record_zero_jobs
        if job_count > 0:
            _run(record_success(target, job_count=job_count, ats=ats))
        else:
            _run(record_zero_jobs(target, ats=ats))

        # Persist to MongoDB
        saved = 0
        if save_to_db and jobs:
            from app.db.mongo import connect_mongo, close_mongo
            from app.services.job_store import upsert_jobs

            async def _save():
                await connect_mongo()
                await upsert_jobs(jobs)
                await close_mongo()
                return len(jobs)

            saved = _run(_save())
            logger.info("[TASK] Saved %d jobs for '%s'", saved, target)

        return {
            "target": target,
            "jobs_found": job_count,
            "jobs_saved": saved,
            "ats": ats,
            "status": "ok",
        }

    except Exception as exc:
        logger.exception("[TASK] scrape_company_task failed for '%s': %s", target, exc)
        try:
            from app.services.scraper_health import record_failure
            _run(record_failure(target, error=str(exc)))
        except Exception:
            pass
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Scrape a user-supplied arbitrary URL
# ---------------------------------------------------------------------------
@app.task(
    bind=True,
    name="app.tasks.scrape.scrape_url_task",
    max_retries=2,
    default_retry_delay=60,
)
def scrape_url_task(
    self,
    url: str,
    *,
    keyword: str | None = None,
    location: str | None = None,
    pages: int = 2,
    page_size: int = 20,
    save_to_db: bool = True,
) -> dict[str, Any]:
    """Scrape an arbitrary URL (user-triggered via POST /scrape/async)."""
    return scrape_company_task(
        self=self,
        url=url,
        keyword=keyword,
        location=location,
        pages=pages,
        page_size=page_size,
        save_to_db=save_to_db,
    )


# ---------------------------------------------------------------------------
# Batch: scrape all seeded companies
# ---------------------------------------------------------------------------
@app.task(name="app.tasks.scrape.scrape_all_companies")
def scrape_all_companies(
    *,
    keyword: str | None = None,
    location: str | None = None,
    pages: int = 2,
    page_size: int = 20,
) -> dict[str, Any]:
    """
    Fan out scrape_company_task for every company in the seed directory.

    Uses Celery group for parallel execution.
    """
    from scrapers.utils import supported_companies
    from celery import group

    companies = supported_companies()
    logger.info("[TASK] scrape_all_companies: queueing %d companies", len(companies))

    job_group = group(
        scrape_company_task.s(
            company=c,
            keyword=keyword,
            location=location,
            pages=pages,
            page_size=page_size,
            save_to_db=True,
        )
        for c in companies
    )
    result = job_group.apply_async()
    return {"queued": len(companies), "group_id": result.id}


# ---------------------------------------------------------------------------
# Retry only degraded / failing targets
# ---------------------------------------------------------------------------
@app.task(name="app.tasks.scrape.retry_failing_scrapers")
def retry_failing_scrapers() -> dict[str, Any]:
    """
    Re-queue scrape tasks only for targets in 'degraded' or 'failing' state.

    Does NOT re-queue targets with open circuits (still in cool-down).
    """
    health_docs = _run(_fetch_unhealthy_targets())
    to_retry = [
        doc["target"]
        for doc in health_docs
        if doc.get("status") in ("degraded", "failing")
    ]
    logger.info("[TASK] retry_failing_scrapers: retrying %d targets", len(to_retry))

    queued = 0
    for target in to_retry:
        circuit_open = _run(_check_circuit(target))
        if circuit_open:
            logger.info("[TASK] Skipping circuit-open target: %s", target)
            continue
        # Determine if target is a URL or company name
        is_url = target.startswith("http")
        scrape_company_task.apply_async(
            kwargs={
                "url": target if is_url else None,
                "company": None if is_url else target,
                "save_to_db": True,
            },
            queue="retry",
        )
        queued += 1

    return {"retried": queued, "candidates": len(to_retry)}


async def _fetch_unhealthy_targets() -> list[dict]:
    from app.services.scraper_health import get_all_health
    all_health = await get_all_health()
    return [h for h in all_health if h.get("status") in ("degraded", "failing")]


async def _check_circuit(target: str) -> bool:
    from app.services.scraper_health import is_circuit_open
    return await is_circuit_open(target)
