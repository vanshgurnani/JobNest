from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


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


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("MongoDB is not connected")
    return _db


async def _ensure_indexes() -> None:
    db = get_db()
    await db.jobs.create_index("id", unique=True)
    await db.jobs.create_index([("company", 1), ("crawled_at", -1)])
    await db.jobs.create_index("title")


async def ping_mongo() -> dict[str, Any]:
    db = get_db()
    await db.command("ping")
    return {"mongodb": "connected", "database": db.name}
