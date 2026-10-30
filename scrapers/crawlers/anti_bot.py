"""
anti_bot.py — Anti-detection layer for all HTTP requests.

Provides:
  - Rotating, realistic User-Agent pool
  - Full browser-like header sets
  - Exponential backoff with jitter
  - SPA / JS-rendering detection heuristics
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Any

# ---------------------------------------------------------------------------
# User-Agent pool (rotate to avoid fingerprinting)
# ---------------------------------------------------------------------------
_USER_AGENTS: list[str] = [
    # Chrome on macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    # Chrome on Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    # Chrome on Linux
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    # Firefox on macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.0; rv:127.0) "
        "Gecko/20100101 Firefox/127.0"
    ),
    # Firefox on Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    ),
    # Edge on Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
    ),
    # Safari on macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4 Safari/605.1.15"
    ),
]


def random_user_agent() -> str:
    """Return a random User-Agent string from the pool."""
    return random.choice(_USER_AGENTS)


# Alias
rotate_user_agent = random_user_agent


# ---------------------------------------------------------------------------
# Realistic browser-like headers
# ---------------------------------------------------------------------------
_REFERERS = [
    "https://www.google.com/",
    "https://www.linkedin.com/",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
]


def browser_headers(
    *,
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    extra: dict[str, str] | None = None,
    ua: str | None = None,
) -> dict[str, str]:
    """
    Return a realistic set of browser request headers.

    Args:
        accept:  The Accept header value.
        extra:   Additional headers to merge in (override defaults).
        ua:      Specific User-Agent; if None, a random one is chosen.
    """
    headers: dict[str, str] = {
        "User-Agent": ua or random_user_agent(),
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": random.choice(_REFERERS),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "cross-site",
        "Upgrade-Insecure-Requests": "1",
    }
    if extra:
        headers.update(extra)
    return headers


# Alias
realistic_headers = browser_headers


def json_api_headers(*, ua: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Headers suitable for JSON API requests (XHR/fetch-like)."""
    headers: dict[str, str] = {
        "User-Agent": ua or random_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "X-Requested-With": "XMLHttpRequest",
    }
    if extra:
        headers.update(extra)
    return headers


# ---------------------------------------------------------------------------
# Exponential backoff with jitter
# ---------------------------------------------------------------------------
async def backoff_sleep(attempt: int, *, base: float = 1.5, cap: float = 30.0) -> None:
    """
    Sleep for an exponentially growing duration with random jitter.

    Formula: min(base^attempt, cap) + uniform(0, 1)
    """
    delay = min(base ** attempt, cap) + random.uniform(0.0, 1.0)
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# SPA / JS-rendering detection
# ---------------------------------------------------------------------------
_SPA_SIGNALS: list[str] = [
    # React
    "<div id=\"root\"",
    "<div id=\"app\"",
    "data-reactroot",
    "__REACT_FIBER",
    # Next.js
    "__NEXT_DATA__",
    "__next/static",
    "_next/static",
    # Nuxt.js
    "window.__NUXT__",
    "__NUXT_",
    # Angular
    "ng-version",
    "ng-app",
    "[ng-version]",
    # Vue
    "data-v-app",
    "__VUE_HMR",
    # Gatsby
    "___gatsby",
    # Generic SPA markers
    "window.__INITIAL_STATE__",
    "window.__REDUX_STATE__",
    "window.__APP_STATE__",
    # Eightfold / Phenom (always SPA)
    "static.vscdn.net",
    "eightfold.ai",
    "data-ph-id",
    "phenompeople.com",
]

_JOB_CONTENT_SIGNALS: list[str] = [
    "job", "career", "position", "requisition", "opening", "role",
]


def needs_playwright(html: str, *, url: str = "") -> bool:
    """
    Return True if the page likely requires a JS-rendering engine.

    Heuristics:
      1. The HTML is very short (SPA shell, actual content not rendered)
      2. The page contains SPA framework markers AND no job-like content
    """
    # Very short response = SPA shell with no rendered content
    if len(html) < 2_500:
        return True

    has_spa = any(signal in html for signal in _SPA_SIGNALS)
    has_jobs = any(signal in html.lower() for signal in _JOB_CONTENT_SIGNALS)

    # SPA without visible job content
    if has_spa and not has_jobs:
        return True

    # URL-based signals (always need Playwright)
    url_lower = url.lower()
    if any(d in url_lower for d in ("eightfold.ai", "phenompeople.com")):
        return True

    return False


# ---------------------------------------------------------------------------
# HTTP status helpers
# ---------------------------------------------------------------------------
def is_rate_limited(status_code: int) -> bool:
    return status_code == 429


def is_bot_blocked(status_code: int) -> bool:
    return status_code in (403, 406, 407, 503)


def is_retryable(status_code: int) -> bool:
    """Return True if the status code warrants a retry."""
    return status_code in (429, 500, 502, 503, 504)


def parse_retry_after(headers: dict[str, Any]) -> float | None:
    """Extract the Retry-After value from response headers, if present."""
    val = headers.get("retry-after") or headers.get("Retry-After")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
