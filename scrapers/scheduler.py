from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEDULE_PATH = Path(__file__).resolve().parent / "schedule.json"

_DEFAULT_INTERVALS: dict[str, int] = {
    "amazon": 86400,
    "google": 43200,
    "microsoft": 86400,
    "meta": 43200,
    "apple": 86400,
}


class ScrapeScheduler:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        if _SCHEDULE_PATH.exists():
            try:
                return json.loads(_SCHEDULE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_config(self) -> None:
        _SCHEDULE_PATH.write_text(json.dumps(self._config, indent=2), encoding="utf-8")

    def _should_run(self, company: str, entry: dict[str, Any]) -> bool:
        last_run = entry.get("last_run")
        if last_run is None:
            return True
        interval = entry.get("interval", _DEFAULT_INTERVALS.get(company, 86400))
        return time.time() - last_run >= interval

    async def _scrape_company(self, company: str) -> None:
        from scrapers.scrape_jobs import _scrape_company as scrape

        jobs = await scrape(company, keyword=None, location=None, pages=1, page_size=20, delay_seconds=0.5)
        logger.info("Scheduler scraped %s: %d jobs", company, len(jobs))
        if company in self._config:
            self._config[company]["last_run"] = time.time()
            self._config[company]["last_count"] = len(jobs)
            self._save_config()

    async def run_loop(self) -> None:
        logger.info("Scheduler started")
        while self._running:
            for company, entry in list(self._config.items()):
                if not self._running:
                    break
                if self._should_run(company, entry):
                    try:
                        await self._scrape_company(company)
                    except Exception as exc:
                        logger.error("Scheduler failed for %s: %s", company, exc)
            await asyncio.sleep(60)

    def start(self) -> None:
        if self._running:
            return
        if not self._config:
            self._config = {c: {"interval": _DEFAULT_INTERVALS.get(c, 86400), "last_run": None}
                           for c in _DEFAULT_INTERVALS}
            self._save_config()
        self._running = True
        self._task = asyncio.create_task(self.run_loop())
        logger.info("Scheduler started with %d companies", len(self._config))

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Scheduler stopped")


scheduler = ScrapeScheduler()