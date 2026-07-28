from __future__ import annotations

import logging
from typing import Any

from pymongo import MongoClient

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: MongoClient | None = None
_db: Any = None


def connect_mongo() -> None:
    global _client, _db
    settings = get_settings()
    _client = MongoClient(settings.mongodb_uri)
    _db = _client[settings.mongodb_db]
    _ensure_indexes()
    logger.info("Connected to MongoDB database: %s", settings.mongodb_db)


def close_mongo() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def get_db() -> Any:
    if _db is None:
        raise RuntimeError("MongoDB is not connected")
    return _db


def _ensure_indexes() -> None:
    db = get_db()
    db.jobs.create_index("id", unique=True)
    db.jobs.create_index([("company", 1), ("crawled_at", -1)])
    db.jobs.create_index("title")


def ping_mongo() -> dict[str, Any]:
    db = get_db()
    db.command("ping")
    return {"mongodb": "connected", "database": db.name}
