from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

logger = logging.getLogger(__name__)


class PaginationPattern:
    def __init__(self, param: str = "page", offset: int = 1, increment: int = 1):
        self.param = param
        self.offset = offset
        self.increment = increment

    def next_url(self, base_url: str, page: int) -> str:
        params = parse_qs(urlparse(base_url).query)
        params[self.param] = [str(self.offset + (page - 1) * self.increment)]
        query = urlencode(params, doseq=True)
        base = base_url.split("?")[0]
        return f"{base}?{query}"

    def to_dict(self) -> dict[str, Any]:
        return {"param": self.param, "offset": self.offset, "increment": self.increment}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PaginationPattern:
        return cls(param=d.get("param", "page"), offset=d.get("offset", 1), increment=d.get("increment", 1))


def detect_pagination(url: str, response_text: str, response_json: Any = None) -> PaginationPattern | None:
    pattern = _detect_url_pagination(url)
    if pattern:
        return pattern

    if response_json and isinstance(response_json, dict):
        pattern = _detect_json_pagination(response_json)
        if pattern:
            return pattern

    return None


def _detect_json_pagination(data: dict[str, Any]) -> PaginationPattern | None:
    total = _find_key(data, {"total", "totalCount", "total_count", "totalResults", "total_results", "count", "size", "numResults", "hits"})
    if total is not None:
        try:
            total = int(total)
        except (ValueError, TypeError):
            pass

    page_keys = {"page", "pageNumber", "page_number", "currentPage", "current_page", "p"}
    page = _find_key(data, page_keys)
    if page is not None:
        try:
            return PaginationPattern(param="page", offset=int(page))
        except (ValueError, TypeError):
            pass

    limit_keys = {"limit", "pageSize", "page_size", "size", "perPage", "per_page", "maxResults"}
    limit = _find_key(data, limit_keys)
    if limit is not None:
        try:
            return PaginationPattern(param="page", offset=1)
        except (ValueError, TypeError):
            pass

    cursor_keys = {"nextPageToken", "nextCursor", "cursor", "nextToken", "continuationToken"}
    cursor = _find_key(data, cursor_keys)
    if cursor:
        return PaginationPattern(param="cursor", offset=1)

    return None


def _detect_url_pagination(url: str) -> PaginationPattern | None:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    page_params = {"page", "p", "pageNumber", "page_number", "currentPage", "offset", "start", "startIndex", "from"}
    for key in params:
        if key.lower() in page_params:
            try:
                val = int(params[key][0])
                return PaginationPattern(param=key, offset=val if val == 0 else 1)
            except (ValueError, TypeError):
                continue

    if re.search(r"/page[/=](\d+)", parsed.path, re.IGNORECASE):
        return PaginationPattern(param="page", offset=1)

    return None


def _find_key(data: dict[str, Any], keys: set[str]) -> Any:
    for k, v in data.items():
        if k in keys:
            return v
        if isinstance(v, dict):
            result = _find_key(v, keys)
            if result is not None:
                return result
    return None
