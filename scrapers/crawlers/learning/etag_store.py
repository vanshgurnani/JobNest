from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_ETAG_PATH = Path(__file__).resolve().parent.parent.parent / "etags.json"


def _domain_key(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def get_etag(url: str) -> str | None:
    domain = _domain_key(url)
    if not _ETAG_PATH.exists():
        return None
    try:
        store = json.loads(_ETAG_PATH.read_text(encoding="utf-8"))
        entry = store.get(domain, {})
        return entry.get("etag")
    except Exception:
        return None


def get_last_modified(url: str) -> str | None:
    domain = _domain_key(url)
    if not _ETAG_PATH.exists():
        return None
    try:
        store = json.loads(_ETAG_PATH.read_text(encoding="utf-8"))
        entry = store.get(domain, {})
        return entry.get("last_modified")
    except Exception:
        return None


def save_response_headers(url: str, response: httpx.Response) -> None:
    domain = _domain_key(url)
    etag = response.headers.get("etag")
    last_modified = response.headers.get("last-modified")
    if not etag and not last_modified:
        return

    store: dict[str, Any] = {}
    if _ETAG_PATH.exists():
        try:
            store = json.loads(_ETAG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    if domain not in store:
        store[domain] = {}
    if etag:
        store[domain]["etag"] = etag
    if last_modified:
        store[domain]["last_modified"] = last_modified

    _ETAG_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")
    logger.debug("Saved ETag/last-modified for %s", domain)


def has_page_changed(url: str, response: httpx.Response) -> bool:
    new_etag = response.headers.get("etag")
    new_lm = response.headers.get("last-modified")
    if not new_etag and not new_lm:
        return True

    old_etag = get_etag(url)
    old_lm = get_last_modified(url)

    if new_etag and old_etag and new_etag == old_etag:
        logger.info("ETag unchanged for %s — page has not changed", url)
        return False
    if new_lm and old_lm and new_lm == old_lm:
        logger.info("Last-Modified unchanged for %s — page has not changed", url)
        return False

    return True
