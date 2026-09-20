"""Deterministic, multi-signal career portal detection."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scrapers.crawlers.contracts import DetectionResult

_PROVIDER_PATTERNS: dict[str, tuple[str, ...]] = {
    "greenhouse": (r"boards\.greenhouse\.io", r"greenhouse\.io/embed", r"greenhouse-job-board"),
    "lever": (r"jobs\.lever\.co", r"lever\.co", r"lever-jobs"),
    "ashby": (r"ashbyhq\.com", r"ashby\.co", r"posting-api/job-board"),
    "workday": (r"myworkdayjobs\.com", r"/wday/cxs/", r"portalpacks", r"wd-browser-id"),
    "smartrecruiters": (r"smartrecruiters\.com", r"jobs\.smartrecruiters"),
    "icims": (r"icims\.com", r"iCIMS", r"icims-site"),
    "workable": (r"workable\.com", r"apply\.workable", r"workable-jobs"),
    "jobvite": (r"jobvite\.com", r"jobvite"),
    "bamboohr": (r"bamboohr\.com", r"bamboohr"),
    "recruitee": (r"recruitee\.com", r"recruitee"),
    "teamtailor": (r"teamtailor\.com", r"teamtailor"),
    "pinpoint": (r"pinpointhq\.com", r"pinpoint"),
    "successfactors": (r"successfactors\.com", r"successfactors", r"jobs\.sap\.com"),
    "taleo": (r"taleo\.net", r"oracle\.com/taleo", r"taleo"),
    "custom_api": (r"/api/(?:jobs|positions|requisitions)", r"/graphql", r"posting-api"),
}

_CAPABILITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "graphql": (r"/graphql", r"graphqlquery", r"apollo", r"urql"),
    "api": (r"/api/", r"/rest/", r"/json", r"/posting-api/", r"/wday/cxs/"),
    "embedded_json": (r"__next_data__", r"application/json", r"window\.__", r"jobpostings"),
    "json_ld": (r"application/ld\+json", r"jobposting"),
    "pagination": (r"pagination", r"page=", r"offset", r"load more", r"next"),
    "infinite_scroll": (r"infinite.?scroll", r"load.?more", r"fetchmore", r"intersectionobserver"),
}


def _searchable_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = [html]
    for tag in soup.find_all(["script", "link", "iframe", "form", "meta"]):
        parts.extend(str(tag.get(attr, "")) for attr in ("src", "href", "action", "content", "data-provider"))
    return "\n".join(parts)


def detect_capabilities(url: str, html: str = "") -> list[str]:
    searchable = f"{url}\n{_searchable_html(html)}".lower()
    capabilities = [name for name, patterns in _CAPABILITY_PATTERNS.items()
                    if any(re.search(pattern, searchable, re.IGNORECASE) for pattern in patterns)]
    if re.search(r"<form|<a\b|job-title|job-card|job-listing", searchable, re.IGNORECASE):
        capabilities.append("html")
    if re.search(r"application/javascript|type=\"module\"|webpack|react|next/", searchable, re.IGNORECASE):
        capabilities.append("browser_possible")
    return list(dict.fromkeys(capabilities))


def detect_portal(url: str, html: str = "") -> dict[str, Any]:
    """Return provider, confidence, explainable signals, and capabilities.

    Scores are deliberately additive: an iframe plus a matching script and a
    known hostname is stronger than any individual signal.  The output is a
    plain dictionary for easy persistence and API use.
    """
    searchable = f"{url}\n{_searchable_html(html)}"
    scores: dict[str, float] = defaultdict(float)
    signals: dict[str, list[str]] = defaultdict(list)
    for provider, patterns in _PROVIDER_PATTERNS.items():
        for pattern in patterns:
            matches = list(re.finditer(pattern, searchable, re.IGNORECASE))
            for match in matches[:3]:
                source = "url" if match.start() < len(url) else "html"
                weight = 0.55 if source == "url" else 0.35
                scores[provider] += weight
                signals[provider].append(f"{source}:{pattern}")

    # Strong semantic markers from structured DOM attributes.
    soup = BeautifulSoup(html, "html.parser") if html else None
    if soup:
        for element in soup.find_all(attrs={"data-ats": True}):
            provider = str(element.get("data-ats", "")).lower()
            if provider in _PROVIDER_PATTERNS:
                scores[provider] += 0.8
                signals[provider].append("html:data-ats")

    provider = max(scores, key=scores.get) if scores else "unknown"
    raw_score = scores.get(provider, 0.0)
    confidence = min(0.99, round(0.35 + raw_score * 0.22, 3)) if provider != "unknown" else 0.0
    # A single weak custom-api match is not enough to claim a known ATS.
    if provider == "custom_api" and raw_score < 0.7:
        provider = "unknown"
        confidence = 0.0
    result = DetectionResult(
        provider=provider,
        confidence=confidence,
        signals=list(dict.fromkeys(signals.get(provider, []))),
        capabilities=detect_capabilities(url, html),
        metadata={"host": urlparse(url).netloc.lower(), "scores": dict(scores)},
    )
    return result.to_dict()


def detection_result(url: str, html: str = "") -> DetectionResult:
    value = detect_portal(url, html)
    return DetectionResult(**value)


# Short alias for adapter code and integrations that treat detection as a
# service operation.
detect = detect_portal
