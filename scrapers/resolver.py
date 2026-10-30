"""
resolver.py — Smart company/URL input resolver for JobNest.

Given any input (company name, URL, partial name, alias), resolves it to:
  - A canonical company name
  - The best known careers URL
  - ATS platform info (if detectable)
  - Discovery method used

Resolution chain:
  1. URL given → detect ATS from URL → done
  2. Exact match in seed directory
  3. Alias match (_SEED_ALIASES)
  4. Fuzzy name match (substring, partial)
  5. Dynamic discovery:
       a. Try common /careers /jobs path patterns
       b. Fetch homepage, parse careers links
       c. Detect ATS from discovered URL / page HTML
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from scrapers.crawlers.anti_bot import browser_headers, random_user_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Common careers path candidates to probe
# ---------------------------------------------------------------------------
_CAREERS_PATH_CANDIDATES: list[str] = [
    "/careers",
    "/jobs",
    "/about/careers",
    "/company/careers",
    "/en/careers",
    "/us/en/careers",
    "/en-us/careers",
    "/work-with-us",
    "/join-us",
    "/join",
    "/opportunities",
    "/open-roles",
    "/hiring",
    "/talent",
    "/recruitment",
    "/career",
    "/job",
    "/job-openings",
    "/working-with-us",
    "/life-at",
]

# Link text patterns that hint at a careers page
_CAREERS_LINK_TEXT_RE = re.compile(
    r"\b(career|careers|job|jobs|join\s+us|join\s+our\s+team|we(?:'re|\s+are)\s+hiring"
    r"|work\s+with\s+us|openings|open\s+positions|vacancies|opportunities|work\s+at"
    r"|talent|recruit|hiring|positions?|requisition|employment)\b",
    re.IGNORECASE,
)

# URL patterns that strongly indicate a careers page
_CAREERS_URL_RE = re.compile(
    r"(?:/careers|/jobs|careers\.|jobs\.|myworkdayjobs\.com|greenhouse\.io"
    r"|lever\.co|smartrecruiters\.com|ashbyhq\.com|taleo\.net|icims\.com"
    r"|jobvite\.com|bamboohr\.com|eightfold\.ai|phenompeople\.com)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------
async def resolve_company_input(
    input_str: str,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """
    Resolve a company name OR URL to a structured dict.

    Returns:
        {
            "company_name": str,
            "careers_url": str | None,
            "ats": dict | None,        # Same format as detect_ats() return
            "discovery_method": str,   # "seed" | "alias" | "direct_url" | "discovered" | "unknown"
            "raw_input": str,
        }
    """
    raw = input_str.strip()
    result: dict[str, Any] = {
        "raw_input": raw,
        "company_name": "",
        "careers_url": None,
        "ats": None,
        "discovery_method": "unknown",
    }

    if not raw:
        return result

    # ── 1. Is this a URL? ──────────────────────────────────────────────────
    if raw.startswith(("http://", "https://", "www.")):
        url = raw if raw.startswith("http") else f"https://{raw}"
        return await _resolve_from_url(url, result, timeout=timeout)

    # ── 2 & 3. Name-based lookup ───────────────────────────────────────────
    return await _resolve_from_name(raw, result, timeout=timeout)


# ---------------------------------------------------------------------------
# URL-based resolution
# ---------------------------------------------------------------------------
async def _resolve_from_url(
    url: str,
    base: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    from scrapers.crawlers.base import detect_ats
    from scrapers.utils import company_name_from_url

    base["careers_url"] = url
    base["company_name"] = company_name_from_url(url)
    base["discovery_method"] = "direct_url"

    # Try ATS detection from URL alone first (fast path)
    ats = detect_ats(url, "")
    if ats:
        base["ats"] = ats
        return base

    # Fetch page HTML and try ATS detection from content
    try:
        html = await _fetch_html(url, timeout=timeout)
        ats = detect_ats(url, html)
        if ats:
            base["ats"] = ats
    except Exception as exc:
        logger.debug("URL-based ATS detection fetch failed for %s: %s", url, exc)

    return base


# ---------------------------------------------------------------------------
# Name-based resolution
# ---------------------------------------------------------------------------
async def _resolve_from_name(
    name: str,
    base: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    from scrapers import directory
    from scrapers.crawlers.base import detect_ats

    normalized = _normalize_name(name)
    base["company_name"] = normalized

    # ── 2. Exact seed match ────────────────────────────────────────────────
    seed_url = directory.careers_url(normalized)
    if seed_url:
        base["careers_url"] = seed_url
        base["discovery_method"] = "seed"
        seed_ats = directory.ats_info(normalized)
        if seed_ats:
            base["ats"] = seed_ats
        else:
            # Try ATS detection from the seed URL
            try:
                html = await _fetch_html(seed_url, timeout=timeout)
                ats = detect_ats(seed_url, html)
                if ats:
                    base["ats"] = ats
            except Exception:
                pass
        return base

    # ── 3. Alias match ─────────────────────────────────────────────────────
    from scrapers.directory import _SEED_ALIASES
    alias_target = _SEED_ALIASES.get(normalized)
    if alias_target:
        base["company_name"] = alias_target
        return await _resolve_from_name(alias_target, base, timeout=timeout)

    # ── 4. Fuzzy / partial match in seed directory ─────────────────────────
    all_companies = directory.companies()
    fuzzy = _fuzzy_match(normalized, all_companies)
    if fuzzy:
        logger.info("Fuzzy match: '%s' → '%s'", normalized, fuzzy)
        base["company_name"] = fuzzy
        return await _resolve_from_name(fuzzy, base, timeout=timeout)

    # ── 5. Dynamic discovery from homepage ────────────────────────────────
    homepage = _guess_homepage(name)
    if homepage:
        discovered = await _discover_careers_url(homepage, timeout=timeout)
        if discovered:
            base["careers_url"] = discovered
            base["discovery_method"] = "discovered"
            try:
                html = await _fetch_html(discovered, timeout=timeout)
                ats = detect_ats(discovered, html)
                if ats:
                    base["ats"] = ats
            except Exception:
                pass
            return base

    logger.warning("Could not resolve company: '%s'", name)
    return base


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------
async def _discover_careers_url(homepage: str, *, timeout: float) -> str | None:
    """
    Try to find the careers/jobs page for a given homepage URL.

    Steps:
      1. Try common path patterns directly
      2. Fetch homepage and look for careers links in anchor tags
    """
    # Step 1 — Probe common paths
    parsed = urlparse(homepage)
    base = f"{parsed.scheme}://{parsed.netloc}"

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for path in _CAREERS_PATH_CANDIDATES:
            candidate = base + path
            try:
                resp = await client.head(candidate, headers=browser_headers())
                if resp.status_code < 400:
                    logger.info("Discovered careers URL via path probe: %s", candidate)
                    return candidate
            except Exception:
                continue

        # Step 2 — Parse homepage
        try:
            html = await _fetch_html(homepage, timeout=timeout)
        except Exception:
            return None

        careers_links = _extract_careers_links(html, homepage)
        if careers_links:
            best = careers_links[0]
            logger.info("Discovered careers URL from homepage links: %s", best)
            return best

    return None


def _extract_careers_links(html: str, base_url: str) -> list[str]:
    """Extract potential careers page URLs from HTML anchor tags."""
    candidates: list[str] = []
    seen: set[str] = set()

    # Find all <a href="...">text</a>
    for m in re.finditer(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        href = m.group(1).strip()
        text = re.sub(r"<[^>]+>", " ", m.group(2)).strip()

        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        full_url = urljoin(base_url, href)
        if full_url in seen:
            continue

        # URL must look like a careers page
        if not _CAREERS_URL_RE.search(full_url):
            # Link text must contain careers keywords as fallback
            if not _CAREERS_LINK_TEXT_RE.search(text):
                continue

        seen.add(full_url)
        candidates.append(full_url)

    # Prefer URLs with "careers" / "jobs" in the path
    candidates.sort(
        key=lambda u: (
            0 if re.search(r"/careers|/jobs|careers\.|jobs\.", u, re.IGNORECASE) else 1
        )
    )
    return candidates


def _guess_homepage(company_name: str) -> str | None:
    """
    Make an educated guess at a company's homepage URL from their name.

    e.g. "Stripe" → "https://stripe.com"
         "JP Morgan" → "https://jpmorgan.com"
    """
    slug = re.sub(r"[^a-z0-9]", "", company_name.lower())
    if not slug:
        return None
    return f"https://www.{slug}.com"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------
def _normalize_name(name: str) -> str:
    """Normalize a company name for lookup."""
    cleaned = re.sub(r"\b(inc|ltd|llc|corp|co|plc|group|technologies|tech|solutions)\b", "", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _fuzzy_match(name: str, candidates: list[str]) -> str | None:
    """Return the first candidate that contains `name` as a substring (or vice versa)."""
    for candidate in candidates:
        if name in candidate or candidate in name:
            return candidate
    return None


async def _fetch_html(url: str, *, timeout: float = 15.0) -> str:
    headers = browser_headers()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text
