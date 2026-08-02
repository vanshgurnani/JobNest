from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_SCHEDULE_PATH = Path(__file__).resolve().parent / "schedule.json"

_DEFAULT_INTERVALS: dict[str, int] = {
    "amazon": 86400,
    "google": 43200,
    "microsoft": 86400,
    "meta": 43200,
    "apple": 86400,
}


async def notify_webhooks(company: str, jobs: list[dict[str, Any]]) -> None:
    webhook_path = Path(__file__).resolve().parent / "webhooks.json"
    if not webhook_path.exists():
        return
    try:
        webhooks = json.loads(webhook_path.read_text(encoding="utf-8"))
    except Exception:
        return

    company_wh = [w for w in webhooks if w.get("company", "").lower() == company.lower() or w.get("company") == "*"]
    if not company_wh:
        return

    payload = {
        "company": company,
        "job_count": len(jobs),
        "jobs": [
            {
                "title": j.get("title"),
                "location": j.get("location"),
                "apply_url": j.get("apply_url"),
                "job_id": j.get("job_id"),
            }
            for j in jobs[:10]
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    async with httpx.AsyncClient(timeout=10) as client:
        for wh in company_wh:
            url = wh.get("url")
            if not url:
                continue
            try:
                resp = await client.post(url, json=payload)
                logger.info("Webhook %s responded %s for %s", url, resp.status_code, company)
            except Exception as exc:
                logger.warning("Webhook %s failed for %s: %s", url, company, exc)


async def check_page_changed(url: str) -> bool:
    from scrapers.crawlers.learning.etag_store import has_page_changed, save_response_headers
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as c:
            resp = await c.head(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return True
            changed = has_page_changed(url, resp)
            save_response_headers(url, resp)
            return changed
    except Exception:
        return True


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

    def _schedule_priority(self, entry: dict[str, Any]) -> float:
        last_run = entry.get("last_run") or 0
        interval = entry.get("interval", 86400)
        last_count = entry.get("last_count", 0)
        overdue = (time.time() - last_run) / interval
        return overdue + (0.1 if last_count > 0 else 0.5)

    async def _scrape_company(self, company: str) -> None:
        from scrapers.scrape_jobs import _scrape_company as scrape

        company_config = self._config.get(company, {})
        company_url = company_config.get("url")

        if company_url:
            changed = await check_page_changed(company_url)
            if not changed:
                logger.info("Skipping %s — page unchanged (ETag/Last-Modified)", company)
                self._config[company]["last_run"] = time.time()
                self._save_config()
                return

        jobs = await scrape(
            company,
            keyword=None,
            location=None,
            pages=1,
            page_size=20,
            delay_seconds=0.5,
            company_url=company_url,
        )
        logger.info("Scheduler scraped %s: %d jobs", company, len(jobs))

        if company in self._config:
            self._config[company]["last_run"] = time.time()
            self._config[company]["last_count"] = len(jobs)
            self._save_config()

        if jobs:
            await notify_webhooks(company, jobs)

    def add_company(self, company: str, url: str | None = None, interval: int = 86400) -> None:
        self._config[company] = {
            "url": url,
            "interval": interval,
            "last_run": None,
            "last_count": 0,
        }
        self._save_config()
        logger.info("Added %s to scheduler (interval=%ds)", company, interval)

    def remove_company(self, company: str) -> None:
        self._config.pop(company, None)
        self._save_config()

    async def run_loop(self) -> None:
        logger.info("Scheduler started")
        while self._running:
            pending = [(c, e) for c, e in self._config.items() if self._should_run(c, e)]
            pending.sort(key=lambda x: self._schedule_priority(x[1]), reverse=True)

            for company, entry in pending[:5]:
                if not self._running:
                    break
                try:
                    await self._scrape_company(company)
                except Exception as exc:
                    logger.error("Scheduler failed for %s: %s", company, exc)
                await asyncio.sleep(2)

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
