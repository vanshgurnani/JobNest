from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_COOKIE_STORE_PATH = Path(__file__).resolve().parent.parent.parent / "cookies.json"


def _domain_key(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def load_cookies(domain: str) -> list[dict[str, Any]]:
    if not _COOKIE_STORE_PATH.exists():
        return []
    try:
        store = json.loads(_COOKIE_STORE_PATH.read_text(encoding="utf-8"))
        return store.get(domain, [])
    except Exception:
        return []


def save_cookies(domain: str, cookies: list[dict[str, Any]]) -> None:
    store: dict[str, Any] = {}
    if _COOKIE_STORE_PATH.exists():
        try:
            store = json.loads(_COOKIE_STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    store[domain] = cookies[-20:]
    _COOKIE_STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")


def extract_cookies_from_response(response: httpx.Response, url: str) -> list[dict[str, Any]]:
    domain = _domain_key(url)
    cookies = []
    for cookie in response.cookies.jar:
        cookies.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or domain,
            "path": cookie.path or "/",
        })
    if cookies:
        save_cookies(domain, cookies)
    return cookies


def apply_cookies_to_client(client: httpx.AsyncClient, url: str) -> None:
    domain = _domain_key(url)
    cookies = load_cookies(domain)
    for c in cookies:
        client.cookies.set(c["name"], c["value"], domain=c.get("domain", domain), path=c.get("path", "/"))
    if cookies:
        logger.info("Applied %d stored cookies for %s", len(cookies), domain)
