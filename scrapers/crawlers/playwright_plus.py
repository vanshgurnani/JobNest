from __future__ import annotations

import asyncio
import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SESSION_DIR = Path(__file__).resolve().parent.parent / ".sessions"

_SPA_SITES: set[str] = set()


def is_spa_site(domain: str) -> bool:
    return domain in _SPA_SITES


def mark_spa_site(domain: str) -> None:
    _SPA_SITES.add(domain)
    logger.info("Marked %s as SPA site", domain)


async def capture_network_requests(url: str, company: str) -> list[dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed")
        return []

    api_responses: list[dict[str, Any]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                storage_state=_load_session(company) if _session_exists(company) else None,
            )

            page = await context.new_page()

            async def handle_response(response):
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    try:
                        body = await response.json()
                        if body:
                            api_responses.append({
                                "url": response.url,
                                "status": response.status,
                                "body": body,
                            })
                    except Exception:
                        pass

            page.on("response", handle_response)
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            _save_session(context, company)
            await browser.close()
    except Exception as exc:
        logger.warning("Network capture failed for %s: %s", url, exc)
        return []

    return api_responses


def _session_path(company: str) -> Path:
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return _SESSION_DIR / f"{company.lower().replace(' ', '_')}.pkl"


def _session_exists(company: str) -> bool:
    return _session_path(company).exists()


def _save_session(context: Any, company: str) -> None:
    try:
        path = _session_path(company)
        asyncio.create_task(_async_save(context, path))
    except Exception:
        pass


async def _async_save(context: Any, path: Path) -> None:
    try:
        state = await context.storage_state()
        path.write_bytes(pickle.dumps(state))
    except Exception:
        pass


def _load_session(company: str) -> Any:
    path = _session_path(company)
    if path.exists():
        try:
            return pickle.loads(path.read_bytes())
        except Exception:
            pass
    return None