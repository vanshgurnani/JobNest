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
        logger.info("[TASK] Started scrape task %s config=%s", task_id, json.dumps(config, default=str))
        return task_id

    def stop(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == "running":
            task._cancel_event.set()
            logger.info("[TASK] Cancel requested for task %s", task_id)
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
            logger.info("[TASK] Cleaned up finished task %s", tid)

    async def _push_to_db(self, jobs: list[dict[str, Any]], label: str) -> int:
        if not jobs:
            logger.info("[DB] No jobs to push for '%s'", label)
            return 0
        try:
            from app.db.mongo import connect_mongo, close_mongo
            from app.services.job_store import upsert_jobs

            await connect_mongo()
            await upsert_jobs(jobs)
            await close_mongo()
            logger.info("[DB] Pushed %d jobs to database for '%s'", len(jobs), label)
            return len(jobs)
        except Exception as exc:
            logger.exception("[DB] Failed to push jobs for '%s': %s", label, exc)
            return 0

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
            save_to_db = bool(cfg.get("save_to_db", False))
            batch = companies + urls

            if save_to_db:
                logger.info("[TASK] %s: DB persistence enabled — results will be pushed after scraping", task.task_id)

            if not batch:
                task.message = "No targets to scrape"
                task.status = "completed"
                await task.emit()
                return

            concurrency = max(1, int(cfg.get("concurrency", min(len(batch), 5))))
            sem = asyncio.Semaphore(concurrency)
            logger.info("[TASK] %s: %d targets with concurrency=%d", task.task_id, len(batch), concurrency)

            async def _scrape_target(target: str, is_url: bool) -> dict[str, Any]:
                async with sem:
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
                        entry: dict[str, Any] = {"target": target, "jobs": result_jobs, "count": len(result_jobs)}
                        logger.info("[TASK] %s scraped '%s': %d jobs", task.task_id, target, len(result_jobs))
                    except asyncio.TimeoutError:
                        entry = {"target": target, "jobs": [], "count": 0, "error": "Timeout"}
                        logger.warning("[TASK] %s timed out scraping '%s'", task.task_id, target)
                    except Exception as e:
                        entry = {"target": target, "jobs": [], "count": 0, "error": str(e)}
                        logger.error("[TASK] %s failed scraping '%s': %s", task.task_id, target, e)

                    if save_to_db and not task._cancel_event.is_set():
                        pushed = await self._push_to_db(entry.get("jobs", []), target)
                        entry["saved_to_db"] = pushed
                    return entry

            targets = [(c, False) for c in companies] + [(u, True) for u in urls]
            results = await asyncio.gather(
                *[_scrape_target(t, iu) for t, iu in targets],
                return_exceptions=True,
            )

            for idx, r in enumerate(results, 1):
                label = targets[idx - 1][0]
                if task._cancel_event.is_set():
                    task.status = "cancelled"
                    task.message = f"Cancelled by user after {idx - 1}/{len(batch)} targets"
                    await task.emit()
                    logger.warning("[TASK] %s cancelled by user after %d/%d targets", task.task_id, idx - 1, len(batch))
                    return

                entry = r if isinstance(r, dict) else {"target": label, "jobs": [], "count": 0, "error": str(r)}
                task.results.append(entry)
                task.total += entry.get("count", 0)
                if entry.get("error"):
                    task.message = f"[{idx}/{len(batch)}] Failed: {label} — {entry['error']}"
                else:
                    task.message = f"[{idx}/{len(batch)}] Done: {label} ({entry.get('count', 0)} jobs)"
                    if entry.get("saved_to_db") is not None:
                        task.message += f" [db:{entry['saved_to_db']}]"
                task.progress = idx / len(batch)
                await task.emit()

            task.status = "completed"
            task.message = f"Done — {task.total} jobs from {len(batch)} targets"
            await task.emit()
            logger.info("[TASK] %s completed: %d jobs from %d targets", task.task_id, task.total, len(batch))

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"Failed: {e}"
            await task.emit()
            logger.exception("Scrape task %s failed", task.task_id)


manager = ScrapeManager()
