from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: Any = None


async def connect_mongo() -> None:
    global _client, _db
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongodb_uri)
    _db = _client[settings.mongodb_db]
    await _ensure_indexes()
    logger.info("Connected to MongoDB database: %s", settings.mongodb_db)


async def close_mongo() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def get_db() -> Any:
    if _db is None:
        raise RuntimeError("MongoDB is not connected")
    return _db


async def _ensure_indexes() -> None:
    db = get_db()
    await db.jobs.create_index("id", unique=True)
    await db.jobs.create_index([("company", 1), ("crawled_at", -1)])
    await db.jobs.create_index("title")
    await db.jobs.create_index([("title", "text"), ("skills", "text"), ("location", "text")])
    await db.jobs.create_index("location")
    await db.jobs.create_index([("source_job_id", 1), ("portal", 1)], sparse=True)
    await db.jobs.create_index("canonical_url", sparse=True)
    await db.jobs.create_index([("portal", 1), ("posted_at", -1)], sparse=True)
    await db.jobs.create_index([("company", 1), ("active", 1)], sparse=True)
    await db.companies.create_index("company_id", unique=True)
    await db.companies.create_index("domain", sparse=True)
    await db.crawl_runs.create_index("crawl_id", unique=True)
    await db.crawl_runs.create_index([("company", 1), ("started_at", -1)])
    await db.crawl_errors.create_index([("crawl_id", 1), ("created_at", -1)])
    await db.raw_job_payloads.create_index([("crawl_id", 1), ("reference", 1)], unique=True)
    await db.crawl_state.create_index("company_id", unique=True)


async def ping_mongo() -> dict[str, Any]:
    db = get_db()
    await db.command("ping")
    return {"mongodb": "connected", "database": db.name}
