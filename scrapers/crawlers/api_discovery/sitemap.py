from __future__ import annotations

import logging
import re
from typing import Any
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)


async def fetch_sitemap_urls(base_url: str) -> list[str]:
    candidates = [
        f"{base_url.rstrip('/')}/sitemap.xml",
        f"{base_url.rstrip('/')}/sitemap_index.xml",
        f"{base_url.rstrip('/')}/sitemap/",
        f"{base_url.rstrip('/')}/job-sitemap.xml",
        f"{base_url.rstrip('/')}/careers-sitemap.xml",
    ]
    urls: list[str] = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        for url in candidates:
            try:
                r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    continue
                urls.extend(_parse_sitemap(r.text, url))
            except Exception:
                continue
    return urls


def _parse_sitemap(content: str, source_url: str) -> list[str]:
    urls: list[str] = []
    try:
        root = ElementTree.fromstring(content)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.iterfind(".//s:loc", ns):
            text = loc.text
            if text:
                urls.append(text.strip())
        if not urls:
            for loc in root.iterfind(".//loc"):
                text = loc.text
                if text:
                    urls.append(text.strip())
    except ElementTree.ParseError:
        job_urls = re.findall(r"https?://[^\s<>\"']+/(?:job|career|position|requisition|opening)\S*", content, re.IGNORECASE)
        urls.extend(job_urls)
    return urls


async def fetch_robots_txt(base_url: str) -> list[str]:
    robots_url = f"{base_url.rstrip('/')}/robots.txt"
    sitemaps: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(robots_url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                for line in r.text.splitlines():
                    m = re.match(r"^\s*Sitemap:\s*(\S+)", line, re.IGNORECASE)
                    if m:
                        sitemaps.append(m.group(1))
    except Exception:
        pass
    return sitemaps


async def discover_job_urls(base_url: str) -> list[str]:
    sitemap_urls = await fetch_sitemap_urls(base_url)
    if sitemap_urls:
        logger.info("Found %d URLs via sitemap for %s", len(sitemap_urls), base_url)
        return sitemap_urls
    robots = await fetch_robots_txt(base_url)
    all_urls: list[str] = []
    for sm in robots:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
                r = await c.get(sm, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200:
                    all_urls.extend(_parse_sitemap(r.text, sm))
        except Exception:
            continue
    if all_urls:
        logger.info("Found %d URLs via robots.txt sitemaps for %s", len(all_urls), base_url)
    return all_urls