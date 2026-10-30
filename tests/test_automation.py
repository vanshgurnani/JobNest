import pytest
from scrapers.crawlers.anti_bot import (
    browser_headers,
    random_user_agent,
    json_api_headers,
    needs_playwright,
    is_rate_limited,
    is_bot_blocked,
    is_retryable,
)
from scrapers.resolver import resolve_company_input


def test_anti_bot_headers_are_browser_like() -> None:
    headers = browser_headers()
    assert "User-Agent" in headers
    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "Accept-Language" in headers
    assert "Accept-Encoding" not in headers  # Let httpx auto-decompress
    assert "sec-ch-ua" in headers


def test_anti_bot_user_agent_rotates() -> None:
    agents = {random_user_agent() for _ in range(50)}
    assert len(agents) > 1


def test_needs_playwright_detects_spa_shells() -> None:
    assert needs_playwright("<div>short</div>") is True
    # Long HTML with SPA marker and no jobs
    long_spa = '<div id="root">' + " " * 3000 + "</div>"
    assert needs_playwright(long_spa) is True
    # Long HTML with jobs
    long_with_jobs = '<div id="root">' + " " * 3000 + "Software Engineer job position opening</div>"
    assert needs_playwright(long_with_jobs) is False


def test_http_status_helpers() -> None:
    assert is_rate_limited(429) is True
    assert is_rate_limited(200) is False
    assert is_bot_blocked(403) is True
    assert is_retryable(502) is True
    assert is_retryable(404) is False


def test_resolver_resolves_seeded_company() -> None:
    import asyncio
    res = asyncio.run(resolve_company_input("stripe"))
    assert res["company_name"] == "stripe"
    assert res.get("ats", {}).get("platform") == "greenhouse"
    assert res.get("ats", {}).get("token") == "stripe"


def test_resolver_resolves_direct_ats_url() -> None:
    import asyncio
    res = asyncio.run(resolve_company_input("https://boards.greenhouse.io/airbnb"))
    assert res.get("ats", {}).get("platform") == "greenhouse"
    assert res.get("ats", {}).get("token") == "airbnb"
