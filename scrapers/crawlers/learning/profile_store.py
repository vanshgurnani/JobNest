from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROFILES_PATH = Path(__file__).resolve().parent.parent.parent / "api_profiles.json"


def load_profiles() -> dict[str, Any]:
    if _PROFILES_PATH.exists():
        try:
            return json.loads(_PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_profile(domain: str, profile: dict[str, Any]) -> None:
    profiles = load_profiles()
    profiles[domain] = profile
    _PROFILES_PATH.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    logger.info("Saved API profile for %s", domain)


def get_profile(domain: str) -> dict[str, Any] | None:
    return load_profiles().get(domain)


def learn_from_response(domain: str, url: str, response: Any) -> dict[str, Any] | None:
    if existing := get_profile(domain):
        return existing

    pagination = _detect_pagination_pattern(response)
    profile = {
        "domain": domain,
        "url": url,
        "pagination": pagination,
    }
    save_profile(domain, profile)
    return profile


def _detect_pagination_pattern(data: Any) -> str | None:
    if isinstance(data, dict):
        if "nextPageToken" in data or "cursor" in data:
            return "cursor"
        if "page" in data or "pageNumber" in data:
            return "page"
        if "offset" in data:
            return "offset"
    return None