from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import BulkWriteError

from app.config import get_settings
from app.db.mongo import get_db
from app.schemas.job import canonicalize_job
from app.services.normalizer import html_to_text


_MAX_INPUT_LENGTH = 200


def _validate_search_input(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if len(stripped) > _MAX_INPUT_LENGTH:
        raise ValueError(f"{label} exceeds maximum length of {_MAX_INPUT_LENGTH}")
    return stripped


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    serialized = dict(job)
    serialized.pop("_id", None)
    crawled_at = serialized.get("crawled_at")
    if isinstance(crawled_at, datetime):
        serialized["crawled_at"] = crawled_at.isoformat()
    if serialized.get("description"):
        serialized["description"] = html_to_text(serialized["description"])
    return serialized


def _build_filter(
    *,
    company: str | None = None,
    keyword: str | None = None,
    location: str | None = None,
    employment_type: str | None = None,
    experience: str | None = None,
    fresh_only: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    # Legacy documents without the field remain active; explicitly removed
    # jobs are hidden from the product search surface.
    query["active"] = {"$ne": False}
    company = _validate_search_input(company, "Company")
    keyword = _validate_search_input(keyword, "Keyword")
    location = _validate_search_input(location, "Location")
    employment_type = _validate_search_input(employment_type, "EmploymentType")
    experience = _validate_search_input(experience, "Experience")
    if company:
        query["company"] = {"$regex": f"^{re.escape(company)}$", "$options": "i"}
    if keyword:
        escaped = re.escape(keyword)
        query["$or"] = [
            {"title": {"$regex": escaped, "$options": "i"}},
            {"skills": {"$regex": escaped, "$options": "i"}},
        ]
    if location:
        query["location"] = {"$regex": re.escape(location), "$options": "i"}
    if employment_type:
        query["employment_type"] = {"$regex": f"^{re.escape(employment_type)}$", "$options": "i"}
    if experience:
        query["experience"] = {"$regex": f"^{re.escape(experience)}$", "$options": "i"}
    if fresh_only:
        ttl = get_settings().cache_ttl_seconds
        query["crawled_at"] = {"$gte": _now() - timedelta(seconds=ttl)}
    return query


async def upsert_jobs(jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        return
    db = get_db()
    crawled_at = _now()
    operations: list[Any] = []
    for raw_job in jobs:
        job = canonicalize_job(raw_job)
        if not job.get("id"):
            continue
        job["crawled_at"] = crawled_at
        from pymongo import UpdateOne

        operations.append(
            UpdateOne(
                {"id": job["id"]},
                {"$set": job, "$setOnInsert": {"first_seen_at": crawled_at}},
                upsert=True,
            )
        )
    if operations:
        try:
            await db.jobs.bulk_write(operations, ordered=False)
        except BulkWriteError as e:
            if any(err.get("code") != 11000 for err in e.details.get("writeErrors", [])):
                raise


async def find_jobs(
    *,
    company: str | None = None,
    keyword: str | None = None,
    location: str | None = None,
    employment_type: str | None = None,
    experience: str | None = None,
    page: int = 1,
    limit: int = 20,
    fresh_only: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    db = get_db()
    query = _build_filter(company=company, keyword=keyword, location=location, employment_type=employment_type, experience=experience, fresh_only=fresh_only)
    skip = max(page - 1, 0) * limit
    total = await db.jobs.count_documents(query)
    cursor = (
        db.jobs.find(query)
        .sort([("posted_date", DESCENDING), ("crawled_at", DESCENDING), ("title", ASCENDING)])
        .skip(skip)
        .limit(limit)
    )
    jobs = [_serialize_job(job) async for job in cursor]
    return jobs, total


async def find_companies() -> list[dict[str, Any]]:
    db = get_db()
    pipeline = [
        {"$group": {"_id": "$company", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    cursor = db.jobs.aggregate(pipeline)
    return [
        {"name": doc["_id"], "count": doc.get("count", 0)}
        async for doc in cursor
        if doc.get("_id")
    ]


async def find_job_by_id(job_id: str) -> dict[str, Any] | None:
    db = get_db()
    job = await db.jobs.find_one({"$or": [{"id": job_id}, {"job_id": job_id}]})
    return _serialize_job(job) if job else None


async def mark_removed_jobs(*, company: str, seen_ids: set[str], portal: str = "") -> int:
    """Mark jobs absent from a successful crawl as inactive.

    Callers should only invoke this after a non-degraded crawl. Keeping this
    operation explicit prevents a temporary 403/empty response from expiring
    an entire company's inventory.
    """
    db = get_db()
    query: dict[str, Any] = {"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}, "active": {"$ne": False}}
    if portal:
        query["portal"] = portal
    if seen_ids:
        query["id"] = {"$nin": list(seen_ids)}
    result = await db.jobs.update_many(query, {"$set": {"active": False, "removed_at": _now()}})
    return int(result.modified_count)
