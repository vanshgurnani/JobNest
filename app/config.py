from __future__ import annotations
from dotenv import load_dotenv 
load_dotenv()
import os
from functools import lru_cache


@lru_cache
def get_settings() -> "Settings":
    return Settings()


class Settings:
    """Application settings loaded from environment variables."""

    mongodb_uri: str = os.getenv("MONGO_URI")
    mongodb_db: str = os.getenv("MONGO_DB_NAME")

    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "900"))
    cache_max_entries: int = int(os.getenv("CACHE_MAX_ENTRIES", "512"))

    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5174,http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    ]

    rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
