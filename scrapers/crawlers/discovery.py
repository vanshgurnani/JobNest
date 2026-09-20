"""Career-page discovery for names, domains, and supplied portal URLs."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from scrapers.crawlers.base import request_with_retries
from scrapers.crawlers.contracts import DiscoveryResult
from scrapers.crawlers.detector import detect_portal

logger = logging.getLogger(__name__)

CAREER_PATHS = ("/careers", "/career", "/jobs", "/join-us", "/work-with-us", "/opportunities", "/vacancies")
CAREER_TEXT = ("career", "jobs", "join us", "work with us", "we're hiring", "open positions", "opportunities", "vacancies", "talent")
UNOFFICIAL_HOSTS = ("indeed.com", "linkedin.com", "glassdoor.com", "monster.com", "naukri.com", "ziprecruiter.com")


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _root(url: str) -> str:
    host = _host(url)
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _as_url(value: str) -> str:
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value


def _is_unofficial(url: str) -> bool:
    host = _host(url)
    return any(host == item or host.endswith("." + item) for item in UNOFFICIAL_HOSTS)


def _is_career_url(url: str) -> bool:
    lowered = url.lower()
    return any(path in lowered for path in CAREER_PATHS) or bool(detect_portal(url).get("provider") != "unknown")


def _candidate_score(url: str, text: str = "", *, base_host: str = "") -> float:
    if not url or _is_unofficial(url):
        return -1.0
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return -1.0
    score = 0.0
    lowered = url.lower()
    text_lower = text.lower()
    if _is_career_url(url):
        score += 0.45
    if any(term in text_lower for term in CAREER_TEXT):
        score += 0.3
    if base_host and (_host(url) == base_host or _root(url) == _root("https://" + base_host)):
        score += 0.2
    if detect_portal(url).get("provider") not in ("unknown", "custom_api"):
        score += 0.25
    return score


def _homepage_candidates(domain: str) -> list[str]:
    root = _root(_as_url(domain))
    return list(dict.fromkeys([
        f"https://{root}", f"https://www.{root}",
        *(f"https://{prefix}.{root}" for prefix in ("careers", "jobs", "career")),
        *(f"https://{root}{path}" for path in CAREER_PATHS),
    ]))


def _extract_links(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    links: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, str(anchor.get("href")))
        text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        if href.startswith(("http://", "https://")):
            links.append((href, text))
    return links


def _extract_sitemaps(robots: str) -> list[str]:
    return [line.split(":", 1)[1].strip() for line in (robots or "").splitlines()
            if line.lower().startswith("sitemap:") and line.split(":", 1)[1].strip()]


async def _fetch(url: str, client: httpx.AsyncClient | None = None) -> str:
    return await request_with_retries(url, timeout=15, max_retries=2, client=client,
                                      headers={"Accept": "text/html,application/xml,text/plain"})


class CareerPageDiscovery:
    def __init__(self, *, client: httpx.AsyncClient | None = None, max_candidates: int = 12) -> None:
        self.client = client
        self.max_candidates = max(1, max_candidates)

    async def discover(self, target: str, *, company_name: str | None = None) -> DiscoveryResult:
        target = (target or "").strip()
        if not target:
            raise ValueError("A company name, domain, or careers URL is required")

        if target.startswith(("http://", "https://")):
            company = company_name or _root(target).split(".")[0].replace("-", " ").title()
            if _is_unofficial(target):
                raise ValueError(f"Refusing unofficial job board URL: {target}")
            if _is_career_url(target):
                return DiscoveryResult(company=company, official_domain=_root(target), careers_url=target,
                                       confidence=0.98, discovery_method="supplied_url")
            return await self._discover_from_domain(target, company)

        from scrapers.directory import careers_url as seeded_careers_url, resolve_company
        normalized = resolve_company(target) or target.strip().lower()
        seeded = seeded_careers_url(normalized)
        if seeded:
            return DiscoveryResult(company=normalized.title(), official_domain=_root(seeded), careers_url=seeded,
                                   confidence=0.99, discovery_method="known_company_metadata")
        if "." in target and " " not in target:
            return await self._discover_from_domain(_as_url(target), target.split(".")[0].title())
        return await self._discover_from_domain(_as_url(re.sub(r"[^a-zA-Z0-9-]", "", target).lower() + ".com"), target.title())

    async def _discover_from_domain(self, domain_url: str, company: str) -> DiscoveryResult:
        candidates: list[tuple[float, str, str]] = []
        base_url = _as_url(domain_url)
        base_host = _host(base_url)
        robots_urls: list[str] = []
        sitemap_urls: list[str] = []
        fetched_pages: dict[str, str] = {}

        for candidate in _homepage_candidates(base_url)[:self.max_candidates]:
            try:
                html = await _fetch(candidate, self.client)
            except Exception as exc:
                logger.debug("Career discovery candidate failed: %s (%s)", candidate, exc)
                continue
            fetched_pages[candidate] = html
            score = _candidate_score(candidate, base_host=base_host)
            candidates.append((score, candidate, "url_heuristic"))
            for link, text in _extract_links(html, candidate):
                link_score = _candidate_score(link, text, base_host=base_host)
                if link_score > 0:
                    candidates.append((link_score, link, "internal_link" if _host(link) == base_host else "external_career_link"))
            robots_url = urljoin(candidate, "/robots.txt")
            if not robots_urls:
                try:
                    robots = await _fetch(robots_url, self.client)
                    robots_urls.append(robots_url)
                    sitemap_urls.extend(_extract_sitemaps(robots))
                except Exception:
                    pass
            if candidates and max(item[0] for item in candidates) >= 0.9:
                break

        # A sitemap can be the only discoverable surface on a JS-heavy site.
        for sitemap in list(dict.fromkeys(sitemap_urls + [urljoin(base_url, "/sitemap.xml")]))[:4]:
            try:
                sitemap_body = await _fetch(sitemap, self.client)
            except Exception:
                continue
            sitemap_urls.append(sitemap)
            for match in re.findall(r"<loc>\s*(.*?)\s*</loc>", sitemap_body, re.IGNORECASE | re.DOTALL):
                url = match.strip()
                score = _candidate_score(url, base_host=base_host)
                if score > 0:
                    candidates.append((score + 0.1, url, "sitemap"))

        if not candidates:
            return DiscoveryResult(company=company, official_domain=_root(base_url), careers_url=urljoin(base_url, "/careers"),
                                   confidence=0.15, discovery_method="heuristic_fallback", robots_urls=robots_urls, sitemap_urls=list(dict.fromkeys(sitemap_urls)))
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = candidates[0]
        alternatives = list(dict.fromkeys(item[1] for item in candidates[1:] if item[1] != selected[1]))[:10]
        return DiscoveryResult(company=company, official_domain=_root(selected[1]), careers_url=selected[1],
                               confidence=min(0.97, round(selected[0], 3)), discovery_method=selected[2],
                               alternatives=alternatives, robots_urls=robots_urls, sitemap_urls=list(dict.fromkeys(sitemap_urls)))


async def discover_career_page(target: str, *, company_name: str | None = None, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    return (await CareerPageDiscovery(client=client).discover(target, company_name=company_name)).to_dict()
