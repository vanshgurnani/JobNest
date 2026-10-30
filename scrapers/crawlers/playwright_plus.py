"""
playwright_plus.py — Full Playwright-based browser engine for JS-heavy career pages.

Features:
  - Headless Chromium with realistic browser fingerprint
  - Network request interception (captures XHR/fetch job API calls)
  - Smart wait strategies (networkidle + job-selector polling)
  - Session persistence (cookies / storage) per company
  - Asset blocking (images, fonts, media) for speed
  - Automatic retry on navigation failure
"""
from __future__ import annotations

import asyncio
import json
import logging
import pickle
import random
from pathlib import Path
from typing import Any

from scrapers.crawlers.anti_bot import _USER_AGENTS

logger = logging.getLogger(__name__)

_SESSION_DIR = Path(__file__).resolve().parent.parent / ".sessions"

# Domains known to always be SPAs (always use Playwright)
_SPA_SITES: set[str] = {
    "eightfold.ai",
    "phenompeople.com",
    "metacareers.com",
}

# CSS selectors that typically indicate job listings are rendered
_JOB_READY_SELECTORS = [
    '[class*="job-card"]',
    '[class*="job-listing"]',
    '[class*="job-tile"]',
    '[class*="job-result"]',
    '[class*="position-card"]',
    '[data-job-id]',
    '[data-jobid]',
    '[class*="jobCard"]',
    '[class*="JobCard"]',
    'li[class*="job"]',
    'article[class*="job"]',
    'div[class*="job"][class*="item"]',
    'a[href*="/job/"]',
    'a[href*="/jobs/"]',
    'a[href*="/position/"]',
]

# Resource types to block for performance
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


def is_spa_site(domain: str) -> bool:
    return any(spa in domain for spa in _SPA_SITES)


def mark_spa_site(domain: str) -> None:
    _SPA_SITES.add(domain)
    logger.info("Marked %s as SPA site", domain)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def _session_path(company: str) -> Path:
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    safe = company.lower().replace(" ", "_").replace("/", "_")
    return _SESSION_DIR / f"{safe}.pkl"


def _session_exists(company: str) -> bool:
    return _session_path(company).exists()


def _load_session(company: str) -> Any | None:
    path = _session_path(company)
    if path.exists():
        try:
            return pickle.loads(path.read_bytes())
        except Exception:
            path.unlink(missing_ok=True)
    return None


async def _save_session(context: Any, company: str) -> None:
    try:
        state = await context.storage_state()
        _session_path(company).write_bytes(pickle.dumps(state))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Core page fetcher
# ---------------------------------------------------------------------------
async def fetch_page_html(
    url: str,
    *,
    wait_for: str = "networkidle",
    timeout_ms: int = 30_000,
    extra_wait_ms: int = 2_000,
    company: str = "",
) -> str:
    """
    Render a URL with a headless Chromium browser and return the full HTML.

    Args:
        url:           Target URL.
        wait_for:      Playwright wait strategy: 'networkidle', 'domcontentloaded', 'load'.
        timeout_ms:    Navigation timeout in milliseconds.
        extra_wait_ms: Additional wait after navigation (for lazy-loaded content).
        company:       Company name used for session caching.

    Returns:
        The rendered HTML string, or "" on failure.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )
        return ""

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--disable-extensions",
                ],
            )

            ua = random.choice(_USER_AGENTS)
            context_opts: dict[str, Any] = {
                "user_agent": ua,
                "locale": "en-US",
                "timezone_id": "America/New_York",
                "viewport": {"width": 1280, "height": 800},
                "extra_http_headers": {
                    "Accept-Language": "en-US,en;q=0.9",
                    "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"macOS"',
                },
            }

            session = _load_session(company) if company and _session_exists(company) else None
            if session:
                context_opts["storage_state"] = session

            context = await browser.new_context(**context_opts)

            # Block unnecessary assets for speed
            async def _route_handler(route: Any) -> None:
                if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", _route_handler)

            page = await context.new_page()

            # Spoof automation detection
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            try:
                await page.goto(url, wait_until=wait_for, timeout=timeout_ms)
            except Exception as nav_err:
                logger.warning("Playwright navigation failed (trying 'load'): %s — %s", url, nav_err)
                try:
                    await page.goto(url, wait_until="load", timeout=timeout_ms)
                except Exception:
                    await browser.close()
                    return ""

            # Wait for job-like content to appear
            for selector in _JOB_READY_SELECTORS:
                try:
                    await page.wait_for_selector(selector, timeout=5_000)
                    break
                except Exception:
                    continue

            if extra_wait_ms > 0:
                await page.wait_for_timeout(extra_wait_ms)

            html = await page.content()

            if company:
                await _save_session(context, company)

            await browser.close()
            return html

    except Exception as exc:
        logger.warning("Playwright fetch_page_html failed for %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# Network interceptor — captures XHR/fetch job API calls
# ---------------------------------------------------------------------------
async def capture_network_requests(
    url: str,
    company: str,
    *,
    timeout_ms: int = 30_000,
    extra_wait_ms: int = 3_000,
) -> list[dict[str, Any]]:
    """
    Navigate to a URL with Playwright and collect all JSON API responses.

    Useful for sites where jobs are loaded via background XHR/fetch calls
    (e.g. Meta Careers, custom React apps).

    Returns:
        List of dicts: [{"url": str, "status": int, "body": Any}, ...]
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed — run: pip install playwright && playwright install chromium")
        return []

    api_responses: list[dict[str, Any]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ua = random.choice(_USER_AGENTS)
            context = await browser.new_context(
                user_agent=ua,
                locale="en-US",
                viewport={"width": 1280, "height": 800},
                storage_state=_load_session(company) if _session_exists(company) else None,
            )

            page = await context.new_page()

            async def _handle_response(response: Any) -> None:
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    return
                # Only capture responses that look like job/career API calls
                resp_url = response.url.lower()
                if not any(kw in resp_url for kw in ("job", "career", "position", "posting", "search", "listing")):
                    return
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

            page.on("response", _handle_response)

            try:
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                try:
                    await page.goto(url, wait_until="load", timeout=timeout_ms)
                except Exception:
                    await browser.close()
                    return []

            await page.wait_for_timeout(extra_wait_ms)

            await _save_session(context, company)
            await browser.close()

    except Exception as exc:
        logger.warning("Network capture failed for %s: %s", url, exc)
        return []

    logger.info("Playwright captured %d API responses from %s", len(api_responses), url)
    return api_responses


# ---------------------------------------------------------------------------
# Scroll and paginate helper (for infinite-scroll pages)
# ---------------------------------------------------------------------------
async def scroll_and_collect_html(
    url: str,
    *,
    max_scrolls: int = 8,
    scroll_pause_ms: int = 1_500,
    company: str = "",
) -> str:
    """
    Render a page and auto-scroll to load lazy/infinite-scroll job listings.

    Returns the final HTML after all scrolls.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return ""

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=random.choice(_USER_AGENTS),
                locale="en-US",
                viewport={"width": 1280, "height": 800},
            )

            # Block assets for speed
            async def _route(route: Any) -> None:
                if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", _route)
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
            except Exception:
                await browser.close()
                return ""

            prev_height = 0
            for _ in range(max_scrolls):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(scroll_pause_ms)
                curr_height = await page.evaluate("document.body.scrollHeight")
                if curr_height == prev_height:
                    break
                prev_height = curr_height

            html = await page.content()
            await browser.close()
            return html

    except Exception as exc:
        logger.warning("scroll_and_collect_html failed for %s: %s", url, exc)
        return ""