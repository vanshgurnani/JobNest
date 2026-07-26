from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Generic, TypeVar

from app.config import get_settings

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Thread-safe in-memory TTL cache with LRU eviction."""

    def __init__(self, max_entries: int, ttl_seconds: int) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, tuple[T, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> T | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() >= expires_at:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: T) -> None:
        async with self._lock:
            expires_at = time.monotonic() + self._ttl_seconds
            self._store[key] = (value, expires_at)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


_settings = get_settings()
crawl_cache: TTLCache[Any] = TTLCache(_settings.cache_max_entries, _settings.cache_ttl_seconds)


def build_cache_key(**params: Any) -> str:
    parts = [f"{key}={params[key]}" for key in sorted(params) if params.get(key) is not None]
    return "|".join(parts) if parts else "all"
