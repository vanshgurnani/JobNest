"""Mongo persistence for crawl runs, company profiles, raw payloads, and state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.mongo import get_db


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def save_crawl_result(result: dict[str, Any]) -> None:
    db = get_db()
    crawl_id = str(result.get("crawl_id") or "")
    if not crawl_id:
        return
    metrics = result.get("metrics") or {}
    await db.crawl_runs.update_one(
        {"crawl_id": crawl_id},
        {"$set": {**metrics, "crawl_id": crawl_id, "company": result.get("company", ""),
                  "status": result.get("status", "unknown"), "updated_at": _now()},
         "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )
    errors = metrics.get("errors") or []
    if errors:
        await db.crawl_errors.insert_many([
            {"crawl_id": crawl_id, "company": result.get("company", ""), **error, "created_at": _now()}
            for error in errors
        ])


async def save_company_profile(profile: dict[str, Any]) -> None:
    company_id = str(profile.get("company_id") or profile.get("name") or "").strip().lower()
    if not company_id:
        return
    await get_db().companies.update_one(
        {"company_id": company_id},
        {"$set": {**profile, "company_id": company_id, "updated_at": _now()}, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )


async def save_raw_payload(*, crawl_id: str, company: str, portal: str, payload: dict[str, Any], reference: str = "") -> None:
    await get_db().raw_job_payloads.update_one(
        {"crawl_id": crawl_id, "reference": reference},
        {"$set": {"crawl_id": crawl_id, "company": company, "portal": portal,
                  "reference": reference, "payload": payload, "updated_at": _now()},
         "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )


async def get_crawl_state(company_id: str) -> dict[str, Any] | None:
    return await get_db().crawl_state.find_one({"company_id": company_id}, {"_id": 0})


async def save_crawl_state(state: dict[str, Any]) -> None:
    company_id = str(state.get("company_id") or "").strip().lower()
    if not company_id:
        return
    await get_db().crawl_state.update_one(
        {"company_id": company_id},
        {"$set": {**state, "company_id": company_id, "updated_at": _now()}},
        upsert=True,
    )
