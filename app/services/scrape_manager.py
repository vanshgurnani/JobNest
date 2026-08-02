from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class ScrapeTask:
    def __init__(self, task_id: str, config: dict[str, Any]) -> None:
        self.task_id = task_id
        self.config = config
        self.status = "pending"
        self.progress = 0.0
        self.message = ""
        self.results: list[dict[str, Any]] = []
        self.total = 0
        self.error: str | None = None
        self._cancel_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "total": self.total,
            "results": self.results,
            "error": self.error,
        }

    async def emit(self) -> None:
        await self._event_queue.put(self.to_dict())

    async def events(self):
        while True:
            try:
                data = await asyncio.wait_for(self._event_queue.get(), timeout=30)
                yield data
                if data["status"] in ("completed", "cancelled", "failed"):
                    return
            except asyncio.TimeoutError:
                yield {"type": "heartbeat"}
                continue


class ScrapeManager:
    def __init__(self) -> None:
        self._tasks: dict[str, ScrapeTask] = {}

    def get(self, task_id: str) -> ScrapeTask | None:
        return self._tasks.get(task_id)

    async def start(self, config: dict[str, Any]) -> str:
        self.cleanup_old()
        task_id = str(uuid.uuid4())[:8]
        task = ScrapeTask(task_id, config)
        self._tasks[task_id] = task
        task._task = asyncio.create_task(self._run(task))
        return task_id

    def stop(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == "running":
            task._cancel_event.set()
            return True
        return False

    def cleanup(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def cleanup_old(self, max_age: float = 300) -> None:
        now = time.monotonic()
        stale = [tid for tid, t in self._tasks.items()
                 if t.status in ("completed", "cancelled", "failed") and (t._task and t._task.done())]
        for tid in stale:
            self._tasks.pop(tid, None)

    async def _run(self, task: ScrapeTask) -> None:
        task.status = "running"
        await task.emit()

        try:
            from scrapers.scrape_jobs import _scrape_company

            cfg = task.config
            companies_str = (cfg.get("companies") or "").strip()
            urls_str = (cfg.get("company_url") or "").strip()

            from scrapers.utils import supported_companies
            explicit_companies = [c.strip().lower() for c in companies_str.split(",") if c.strip()] if companies_str else []
            urls = [u.strip() for u in urls_str.split(",") if u.strip()] if urls_str else []
            if not explicit_companies and not urls:
                companies = supported_companies()
            else:
                companies = explicit_companies

            keyword = (cfg.get("keyword") or "").strip() or None
            location = (cfg.get("location") or "").strip() or None
            pages = int(cfg.get("pages", 2))
            page_size = int(cfg.get("page_size", 20))
            delay = float(cfg.get("delay_seconds", 0.5))
            batch = companies + urls

            for idx, target in enumerate(batch, 1):
                if task._cancel_event.is_set():
                    task.status = "cancelled"
                    task.message = "Cancelled by user"
                    await task.emit()
                    return

                is_url = target in urls
                label = target
                task.message = f"[{idx}/{len(batch)}] Scraping {label}..."
                task.progress = (idx - 1) / len(batch)
                await task.emit()

                try:
                    result_jobs = await asyncio.wait_for(
                        _scrape_company(
                            None if is_url else target,
                            company_url=target if is_url else None,
                            keyword=keyword,
                            location=location,
                            pages=pages,
                            page_size=page_size,
                            delay_seconds=delay,
                        ),
                        timeout=300,
                    )
                    task.results.append({"target": target, "jobs": result_jobs, "count": len(result_jobs)})
                    task.total += len(result_jobs)
                    task.message = f"[{idx}/{len(batch)}] Done: {label} ({len(result_jobs)} jobs)"
                except asyncio.TimeoutError:
                    task.results.append({"target": target, "jobs": [], "count": 0, "error": "Timeout"})
                    task.message = f"[{idx}/{len(batch)}] Timeout: {label}"
                except Exception as e:
                    task.results.append({"target": target, "jobs": [], "count": 0, "error": str(e)})
                    task.message = f"[{idx}/{len(batch)}] Failed: {label} — {e}"

                task.progress = idx / len(batch)
                await task.emit()

            task.status = "completed"
            task.message = f"Done — {task.total} jobs from {len(batch)} targets"
            await task.emit()

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"Failed: {e}"
            await task.emit()
            logger.exception("Scrape task %s failed", task.task_id)


manager = ScrapeManager()
