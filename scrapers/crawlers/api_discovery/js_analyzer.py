from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

_HTTP_CALL_PATTERNS = [
    re.compile(r"""(?:fetch|axios|got|ky)\s*\(\s*["']([^"']+)["']"""),
    re.compile(r"""\$\.(?:get|post|ajax|json)\s*\(\s*["']([^"']+)["']"""),
    re.compile(r"""new\s+XMLHttpRequest\(\)[^;]*open\s*\(\s*["'](?:GET|POST)["']\s*,\s*["']([^"']+)["']"""),
    re.compile(r"""axios\s*\.\s*(?:get|post|put|delete)\s*\(\s*["']([^"']+)["']"""),
    re.compile(r"""(["'])(/api/[^"']*)\1"""),
    re.compile(r"""url\s*:\s*["']([^"']+)["']"""),
    re.compile(r"""`([^`]*(?:/api/|/graphql|/jobs|/careers)[^`]*)`"""),
]

_API_ENDPOINT_PATTERNS = [
    re.compile(r"/api/[\w/.-]+"),
    re.compile(r"/graphql"),
    re.compile(r"/v\d+/[\w/.-]+"),
    re.compile(r"/[\w-]+/(?:jobs|positions|requisitions|openings|careers)"),
]


def analyze_inline_scripts(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    script_matches = re.finditer(
        r'<script\b[^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    for m in script_matches:
        content = m.group(1)
        for pattern in _HTTP_CALL_PATTERNS:
            for pm in pattern.finditer(content):
                raw = pm.group(1)
                resolved = urljoin(base_url, raw)
                if resolved not in seen and resolved.startswith(("http://", "https://")):
                    seen.add(resolved)
                    urls.append(resolved)

    return urls


async def analyze_external_scripts(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    src_matches = re.finditer(
        r'<script\b[^>]*src=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/javascript,*/*"}

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        for m in src_matches:
            src = m.group(1)
            js_url = urljoin(base_url, src)
            if not js_url.startswith(("http://", "https://")):
                continue
            try:
                r = await c.get(js_url, headers=headers)
                if r.status_code == 200:
                    found = analyze_inline_scripts(f"<script>{r.text}</script>", base_url)
                    for u in found:
                        if u not in seen:
                            seen.add(u)
                            urls.append(u)
            except Exception:
                continue

    return urls


def extract_api_endpoints(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for pattern in _API_ENDPOINT_PATTERNS:
        for m in pattern.finditer(html):
            raw = m.group(0)
            resolved = urljoin(base_url, raw)
            if resolved not in seen and resolved.startswith(("http://", "https://")):
                seen.add(resolved)
                urls.append(resolved)

    return urls


async def discover_apis(html: str, base_url: str) -> dict[str, list[str]]:
    inline = analyze_inline_scripts(html, base_url)
    external = await analyze_external_scripts(html, base_url)
    endpoints = extract_api_endpoints(html, base_url)

    all_urls: list[str] = []
    seen: set[str] = set()
    for u in inline + external + endpoints:
        if u not in seen:
            seen.add(u)
            all_urls.append(u)

    logger.info("JS analysis found %d API-like URLs from %s", len(all_urls), base_url)
    return {"urls": all_urls, "inline_count": len(inline), "external_count": len(external), "endpoint_count": len(endpoints)}