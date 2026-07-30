from __future__ import annotations

import gzip
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

_SOURCEMAP_PATTERN = re.compile(
    r'//#\s*sourceMappingURL=([^\s]+)',
    re.IGNORECASE,
)


async def extract_sourcemaps(html: str, base_url: str) -> list[str]:
    sourcemaps: list[str] = []
    seen: set[str] = set()

    script_matches = re.finditer(
        r'<script\b[^>]*src=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        for m in script_matches:
            js_url = urljoin(base_url, m.group(1))
            if not js_url.startswith(("http://", "https://")):
                continue
            try:
                r = await c.get(js_url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    continue
                sm_match = _SOURCEMAP_PATTERN.search(r.text)
                if sm_match:
                    sm_url = urljoin(js_url, sm_match.group(1))
                    if sm_url not in seen:
                        seen.add(sm_url)
                        sourcemaps.append(sm_url)
            except Exception:
                continue

    return sourcemaps


async def analyze_sourcemap_content(sourcemap_url: str) -> list[str]:
    apis: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(sourcemap_url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return apis

            raw = r.text
            if sourcemap_url.endswith(".gz"):
                raw = gzip.decompress(r.content).decode()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return apis

            sources_content = data.get("sourcesContent", []) or []
            for content in sources_content:
                if not content:
                    continue
                found = re.findall(
                    r"""(?:fetch|axios|got)\s*\(\s*["']([^"']*(?:api|graphql|jobs|positions)[^"']*)["']""",
                    content,
                    re.IGNORECASE,
                )
                apis.extend(found)

                found = re.findall(
                    r"""["'](/[\w/-]*(?:api|jobs|positions|requisitions)[\w/-]*)["']""",
                    content,
                    re.IGNORECASE,
                )
                apis.extend(found)

    except Exception:
        pass

    return list(set(apis))