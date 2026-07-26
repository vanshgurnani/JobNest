from __future__ import annotations

import os
from functools import lru_cache


@lru_cache
def get_settings() -> "Settings":
    return Settings()


class Settings:
    """Application settings loaded from environment variables."""

    mongodb_uri: str = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017"
    mongodb_db: str = os.getenv("MONGODB_DB") or os.getenv("MONGO_DB_NAME") or "job_portal"

    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days

    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "900"))  # 15 min
    cache_max_entries: int = int(os.getenv("CACHE_MAX_ENTRIES", "512"))

    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5174,http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    ]

    rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
