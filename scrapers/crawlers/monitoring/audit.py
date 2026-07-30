from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class ScrapeAudit:
    def __init__(self) -> None:
        self._log: list[dict[str, Any]] = []

    def record(
        self,
        company: str,
        duration: float,
        jobs_found: int,
        strategy: str,
        error: str | None = None,
    ) -> None:
        entry = {
            "company": company,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(duration, 2),
            "jobs_found": jobs_found,
            "strategy": strategy,
            "error": error,
        }
        self._log.append(entry)
        if error:
            logger.warning("AUDIT: %s failed after %.2fs: %s", company, duration, error)
        else:
            logger.info("AUDIT: %s found %d jobs via %s in %.2fs", company, jobs_found, strategy, duration)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._log[-limit:]

    def failures(self, limit: int = 10) -> list[dict[str, Any]]:
        return [e for e in self._log if e["error"]][-limit:]

    def clear(self) -> None:
        self._log.clear()


audit = ScrapeAudit()