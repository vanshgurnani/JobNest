from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SELECTOR_STORE_PATH = Path(__file__).resolve().parent.parent.parent / "selector_profiles.json"

_JOB_TITLE_KEYWORDS = {
    "engineer", "developer", "analyst", "manager", "designer",
    "intern", "scientist", "specialist", "coordinator", "director",
    "architect", "consultant", "associate", "lead", "head",
}


def load_selectors() -> dict[str, Any]:
    if _SELECTOR_STORE_PATH.exists():
        try:
            return json.loads(_SELECTOR_STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_selector(domain: str, selector: dict[str, Any]) -> None:
    selectors = load_selectors()
    selectors[domain] = selector
    _SELECTOR_STORE_PATH.write_text(json.dumps(selectors, indent=2), encoding="utf-8")


def mark_stale(domain: str, strategy: str) -> None:
    selectors = load_selectors()
    if domain in selectors:
        selectors[domain]["stale_strategies"] = selectors[domain].get("stale_strategies", [])
        if strategy not in selectors[domain]["stale_strategies"]:
            selectors[domain]["stale_strategies"].append(strategy)
        _SELECTOR_STORE_PATH.write_text(json.dumps(selectors, indent=2), encoding="utf-8")


def guess_alternative_selectors(html: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for tag in ["h1", "h2", "h3", "h4", "a", "div", "span"]:
        for m in re.finditer(f"<{tag}[^>]*>(.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL):
            text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if not text or len(text) < 5 or len(text) > 200:
                continue
            text_lower = text.lower()
            if text_lower in seen:
                continue
            if any(kw in text_lower for kw in _JOB_TITLE_KEYWORDS):
                seen.add(text_lower)
                candidates.append({"tag": tag, "text": text, "score": 1})
                if len(candidates) >= 50:
                    return candidates

    return candidates