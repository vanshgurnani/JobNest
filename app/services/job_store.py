from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from app.config import get_settings
from app.db.mongo import get_db
from app.schemas.job import canonicalize_job


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
    return serialized


def _build_filter(
    *,
    company: str | None = None,
    keyword: str | None = None,
    location: str | None = None,
    fresh_only: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    company = _validate_search_input(company, "Company")
    keyword = _validate_search_input(keyword, "Keyword")
    location = _validate_search_input(location, "Location")
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
    if fresh_only:
        ttl = get_settings().cache_ttl_seconds
        query["crawled_at"] = {"$gte": _now() - timedelta(seconds=ttl)}
    return query


def _upsert_jobs_sync(jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        return
    db = get_db()
    crawled_at = _now()
    for raw_job in jobs:
        job = canonicalize_job(raw_job)
        if not job.get("id"):
            continue
        job["crawled_at"] = crawled_at
        db.jobs.update_one(
            {"id": job["id"]},
            {"$set": job, "$setOnInsert": {"first_seen_at": crawled_at}},
            upsert=True,
        )


async def upsert_jobs(jobs: list[dict[str, Any]]) -> None:
    await asyncio.to_thread(_upsert_jobs_sync, jobs)


def _find_jobs_sync(
    *,
    company: str | None = None,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int = 20,
    fresh_only: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    db = get_db()
    query = _build_filter(company=company, keyword=keyword, location=location, fresh_only=fresh_only)
    skip = max(page - 1, 0) * limit
    total = db.jobs.count_documents(query)
    cursor = (
        db.jobs.find(query)
        .sort([("posted_date", DESCENDING), ("crawled_at", DESCENDING), ("title", ASCENDING)])
        .skip(skip)
        .limit(limit)
    )
    jobs = [_serialize_job(job) for job in cursor]
    return jobs, total


async def find_jobs(
    *,
    company: str | None = None,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int = 20,
    fresh_only: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    return await asyncio.to_thread(
        _find_jobs_sync,
        company=company,
        keyword=keyword,
        location=location,
        page=page,
        limit=limit,
        fresh_only=fresh_only,
    )


def _find_companies_sync() -> list[str]:
    db = get_db()
    pipeline = [
        {"$group": {"_id": "$company"}},
        {"$sort": {"_id": 1}},
    ]
    cursor = db.jobs.aggregate(pipeline)
    return [doc["_id"] for doc in cursor if doc["_id"]]


async def find_companies() -> list[str]:
    return await asyncio.to_thread(_find_companies_sync)


def _find_job_by_id_sync(job_id: str) -> dict[str, Any] | None:
    db = get_db()
    job = db.jobs.find_one({"$or": [{"id": job_id}, {"job_id": job_id}]})
    return _serialize_job(job) if job else None


async def find_job_by_id(job_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_find_job_by_id_sync, job_id)
