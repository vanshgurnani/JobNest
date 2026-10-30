"""
scraper_health.py — Scraper health tracking service.

Tracks per-company/URL scraper runs in MongoDB (collection: scraper_health).
Provides:
  - Record success/failure per run
  - Circuit-breaker logic (skip consistently-failing scrapers)
  - Query health status for all companies
  - Auto-reset circuit breaker after cool-down period
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Circuit breaker thresholds
_MAX_CONSECUTIVE_FAILURES = 5        # Open circuit after this many consecutive failures
_CIRCUIT_RESET_HOURS = 6             # Try again after this many hours (cool-down)
_ZERO_JOBS_THRESHOLD = 3             # Treat zero-job runs as soft failures after this many

_COLLECTION = "scraper_health"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# DB helpers (lazy motor import to avoid hard dep at import time)
# ---------------------------------------------------------------------------
async def _get_collection():
    try:
        from app.db.mongo import get_db
        db = get_db()
        return db[_COLLECTION]
    except Exception as exc:
        logger.warning("scraper_health: DB not available: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def record_success(target: str, *, job_count: int, ats: str | None = None) -> None:
    """Record a successful scrape run."""
    col = await _get_collection()
    if col is None:
        return
    now = _now()
    await col.update_one(
        {"target": target},
        {
            "$set": {
                "target": target,
                "last_run": now,
                "last_success": now,
                "last_job_count": job_count,
                "consecutive_failures": 0,
                "zero_job_runs": 0,
                "last_error": None,
                "status": "healthy",
                "ats_detected": ats,
            },
            "$inc": {"total_runs": 1, "total_jobs_scraped": job_count},
        },
        upsert=True,
    )
    logger.debug("Health: recorded success for '%s' (%d jobs)", target, job_count)


async def record_failure(target: str, *, error: str = "", ats: str | None = None) -> None:
    """Record a failed scrape run (exception or 0 jobs returned)."""
    col = await _get_collection()
    if col is None:
        return
    now = _now()
    # Fetch current consecutive_failures count
    doc = await col.find_one({"target": target}, {"consecutive_failures": 1})
    prev_failures = (doc or {}).get("consecutive_failures", 0)
    new_failures = prev_failures + 1
    status = "failing" if new_failures >= _MAX_CONSECUTIVE_FAILURES else "degraded"

    await col.update_one(
        {"target": target},
        {
            "$set": {
                "target": target,
                "last_run": now,
                "last_error": error[:500] if error else "unknown",
                "consecutive_failures": new_failures,
                "status": status,
                "ats_detected": ats,
            },
            "$inc": {"total_runs": 1},
        },
        upsert=True,
    )
    logger.warning("Health: recorded failure for '%s' (consecutive=%d): %s", target, new_failures, error[:120])


async def record_zero_jobs(target: str, *, ats: str | None = None) -> None:
    """Record a run that completed but returned 0 jobs (soft failure)."""
    col = await _get_collection()
    if col is None:
        return
    now = _now()
    doc = await col.find_one({"target": target}, {"zero_job_runs": 1, "consecutive_failures": 1})
    zero_runs = (doc or {}).get("zero_job_runs", 0) + 1
    consec = (doc or {}).get("consecutive_failures", 0)
    # After threshold zero-job runs, treat as degraded
    status = "degraded" if zero_runs >= _ZERO_JOBS_THRESHOLD else "healthy"

    await col.update_one(
        {"target": target},
        {
            "$set": {
                "target": target,
                "last_run": now,
                "zero_job_runs": zero_runs,
                "last_job_count": 0,
                "status": status,
                "ats_detected": ats,
            },
            "$inc": {"total_runs": 1},
        },
        upsert=True,
    )
    logger.info("Health: zero-jobs run for '%s' (zero_runs=%d)", target, zero_runs)


async def record_scrape_result(
    target: str,
    *,
    success: bool = True,
    job_count: int = 0,
    error: str = "",
    ats: str | None = None,
) -> None:
    """Convenience dispatcher to record success, zero jobs, or failure."""
    if not success:
        await record_failure(target, error=error, ats=ats)
    elif job_count == 0:
        await record_zero_jobs(target, ats=ats)
    else:
        await record_success(target, job_count=job_count, ats=ats)


async def is_circuit_open(target: str) -> bool:
    """
    Return True if the circuit is open for this target (too many failures).

    The circuit auto-resets after _CIRCUIT_RESET_HOURS of cool-down.
    """
    col = await _get_collection()
    if col is None:
        return False

    doc = await col.find_one({"target": target}, {"consecutive_failures": 1, "last_run": 1, "status": 1})
    if doc is None:
        return False

    failures = doc.get("consecutive_failures", 0)
    if failures < _MAX_CONSECUTIVE_FAILURES:
        return False

    # Auto-reset: if enough time has passed since last run, reset the circuit
    last_run = doc.get("last_run")
    if last_run:
        cool_down = timedelta(hours=_CIRCUIT_RESET_HOURS)
        if _now() - last_run.replace(tzinfo=timezone.utc) > cool_down:
            logger.info("Circuit auto-reset for '%s' after cool-down", target)
            await _reset_circuit(target)
            return False

    return True


async def _reset_circuit(target: str) -> None:
    col = await _get_collection()
    if col is None:
        return
    await col.update_one(
        {"target": target},
        {"$set": {"consecutive_failures": 0, "status": "healthy", "last_error": None}},
    )


async def get_all_health() -> list[dict[str, Any]]:
    """Return health records for all tracked targets."""
    col = await _get_collection()
    if col is None:
        return []
    cursor = col.find({}, {"_id": 0}).sort("target", 1)
    return await cursor.to_list(length=1000)


async def get_health(target: str) -> dict[str, Any] | None:
    """Return health record for a specific target."""
    col = await _get_collection()
    if col is None:
        return None
    return await col.find_one({"target": target}, {"_id": 0})


async def ensure_indexes() -> None:
    """Create MongoDB indexes for the scraper_health collection."""
    col = await _get_collection()
    if col is None:
        return
    await col.create_index("target", unique=True)
    await col.create_index("status")
    await col.create_index("last_run")
    logger.info("scraper_health: indexes ensured")
