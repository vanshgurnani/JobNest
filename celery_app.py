"""
celery_app.py — Celery application instance for JobNest.

Broker:  Redis (redis://localhost:6379/0)
Backend: Redis (redis://localhost:6379/1)

Schedules (celery beat):
  - scrape-all-companies: every 6 hours
  - retry-failing-scrapers: every 3 hours (only degraded/failing targets)
  - health-check-cleanup: once daily

Run worker:
  celery -A celery_app worker --loglevel=info --concurrency=4 -Q scrape,retry,default

Run beat scheduler:
  celery -A celery_app beat --loglevel=info
"""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
BACKEND_URL = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

app = Celery(
    "jobnest",
    broker=BROKER_URL,
    backend=BACKEND_URL,
    include=["app.tasks.scrape"],
)

app.conf.update(
    # Serialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Task behaviour
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,       # One task at a time per worker process
    task_track_started=True,
    task_soft_time_limit=300,           # 5 min soft limit
    task_time_limit=600,                # 10 min hard limit per company task
    # Result expiry
    result_expires=3600 * 24,           # Keep results for 24 hours
    # Retry policy
    task_max_retries=3,
    task_default_retry_delay=120,       # 2 minutes between retries
    # Routes — separate queues for priority control
    task_routes={
        "app.tasks.scrape.scrape_company_task": {"queue": "scrape"},
        "app.tasks.scrape.scrape_all_companies": {"queue": "scrape"},
        "app.tasks.scrape.retry_failing_scrapers": {"queue": "retry"},
    },
    # Beat schedule
    beat_schedule={
        # Full sweep every 6 hours
        "scrape-all-companies-6h": {
            "task": "app.tasks.scrape.scrape_all_companies",
            "schedule": crontab(minute=0, hour="*/6"),
            "options": {"queue": "scrape"},
        },
        # Retry degraded/failing scrapers every 3 hours
        "retry-failing-scrapers-3h": {
            "task": "app.tasks.scrape.retry_failing_scrapers",
            "schedule": crontab(minute=30, hour="*/3"),
            "options": {"queue": "retry"},
        },
    },
)
