"""Small per-domain politeness limiter shared by HTTP-first adapters."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from urllib.parse import urlparse


class DomainRateLimiter:
    def __init__(self, *, min_delay: float = 0.15, max_concurrency: int = 4) -> None:
        self.min_delay = max(0.0, min_delay)
        self.max_concurrency = max(1, max_concurrency)
        self._last_request: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._semaphores: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(self.max_concurrency))

    async def acquire(self, url: str) -> None:
        domain = urlparse(url).netloc.lower() or "unknown"
        semaphore = self._semaphores[domain]
        await semaphore.acquire()
        lock = self._locks[domain]
        try:
            async with lock:
                elapsed = time.monotonic() - self._last_request[domain]
                if elapsed < self.min_delay:
                    await asyncio.sleep(self.min_delay - elapsed)
                self._last_request[domain] = time.monotonic()
        except BaseException:
            semaphore.release()
            raise

    def release(self, url: str) -> None:
        domain = urlparse(url).netloc.lower() or "unknown"
        self._semaphores[domain].release()

    @asynccontextmanager
    async def slot(self, url: str):
        await self.acquire(url)
        try:
            yield
        finally:
            self.release(url)


domain_rate_limiter = DomainRateLimiter()
