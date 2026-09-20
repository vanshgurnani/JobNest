"""Typed contracts shared by discovery, detection, adapters, and persistence.

The legacy crawler returns dictionaries for backwards compatibility.  These
small dataclasses provide a stable boundary for new code without forcing a
flag-day migration of the API or existing provider crawlers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Mapping


@dataclass
class DetectionResult:
    provider: str = "unknown"
    confidence: float = 0.0
    signals: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiscoveryResult:
    company: str
    official_domain: str = ""
    careers_url: str = ""
    confidence: float = 0.0
    discovery_method: str = "unknown"
    alternatives: list[str] = field(default_factory=list)
    robots_urls: list[str] = field(default_factory=list)
    sitemap_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortalContext:
    company_name: str
    careers_url: str
    official_domain: str = ""
    html: str = ""
    detection: DetectionResult | None = None
    keyword: str | None = None
    location: str | None = None
    page: int = 1
    limit: int = 20
    use_playwright: bool = False
    client: Any = None


@dataclass
class JobReference:
    url: str
    source_job_id: str = ""
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawJob:
    payload: dict[str, Any]
    reference: JobReference | None = None
    source: str = ""
    extraction_method: str = ""


@dataclass
class CrawlMetrics:
    crawl_id: str
    company: str
    portal: str = "unknown"
    adapter: str = "unknown"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    jobs_discovered: int = 0
    jobs_parsed: int = 0
    jobs_inserted: int = 0
    jobs_updated: int = 0
    jobs_removed: int = 0
    duplicates: int = 0
    fallback_count: int = 0
    browser_used: bool = False
    errors: list[dict[str, Any]] = field(default_factory=list)

    def finish(self) -> None:
        self.finished_at = datetime.now(timezone.utc)

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())

    def record_error(self, error: Exception | str, *, stage: str = "crawl", retryable: bool = False) -> None:
        self.errors.append({
            "stage": stage,
            "error": str(error),
            "type": type(error).__name__ if isinstance(error, Exception) else "Error",
            "retryable": retryable,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["started_at"] = self.started_at.isoformat()
        value["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        value["duration_seconds"] = round(self.duration_seconds, 3)
        return value


@dataclass
class CrawlState:
    company_id: str
    portal: str = "unknown"
    last_crawl_at: datetime | None = None
    last_success_at: datetime | None = None
    etag: str = ""
    last_modified: str = ""
    job_count: int = 0
    known_job_ids: set[str] = field(default_factory=set)
    crawl_hash: str = ""
    status: str = "never_run"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("last_crawl_at", "last_success_at"):
            if value[key]:
                value[key] = value[key].isoformat()
        value["known_job_ids"] = sorted(self.known_job_ids)
        return value


@dataclass
class CompanyProfile:
    company_id: str
    name: str
    legal_name: str = ""
    domain: str = ""
    aliases: list[str] = field(default_factory=list)
    careers_url: str = ""
    portal_provider: str = "unknown"
    portal_type: str = "unknown"
    detection_confidence: float = 0.0
    adapter: str = "universal"
    crawl_strategy: str = "http"
    capabilities: list[str] = field(default_factory=list)
    last_verified_at: datetime | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.last_verified_at:
            value["last_verified_at"] = self.last_verified_at.isoformat()
        return value


AdapterFactory = Callable[[], Any]


async def iter_list(values: list[Any]) -> AsyncIterator[Any]:
    """Turn a list into an async iterator for adapter implementations."""
    for value in values:
        yield value
