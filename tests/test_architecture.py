import asyncio

from scrapers.crawlers.adapters.registry import AdapterRegistry
from scrapers.crawlers.contracts import DetectionResult
from scrapers.crawlers.detector import detect_portal
from scrapers.crawlers.discovery import CareerPageDiscovery
from scrapers.crawlers.normalization import canonical_job, canonicalize_url, job_identity


def test_detector_aggregates_url_and_html_signals() -> None:
    result = detect_portal(
        "https://acme.wd5.myworkdayjobs.com/External",
        '<script src="/wday/cxs/acme/External/jobs"></script>',
    )

    assert result["provider"] == "workday"
    assert result["confidence"] > 0
    assert result["signals"]
    assert "api" in result["capabilities"]


def test_registry_selects_provider_without_company_router() -> None:
    registry = AdapterRegistry.default()
    adapter = registry.select(DetectionResult(provider="greenhouse", confidence=0.9))

    assert adapter.name == "greenhouse"
    assert "universal" in registry.providers()


def test_canonical_identity_prefers_provider_source_id() -> None:
    first = {"company": "Acme", "portal": "greenhouse", "source_job_id": "42", "title": "Engineer"}
    second = {"company": "Acme", "portal": "greenhouse", "source_job_id": "42", "title": "Changed title"}
    assert job_identity(first) == job_identity(second)
    assert canonicalize_url("https://ACME.com/jobs/42/?utm_source=test") == "https://acme.com/jobs/42"


def test_canonical_job_exposes_searchable_fields() -> None:
    job = canonical_job(
        {"title": "Backend Engineer", "location": "Remote, US", "salary": "$100,000 - $120,000", "description": "<p>Build APIs</p>"},
        company="Acme",
        portal="custom_api",
    )

    assert job["remote"] is True
    assert job["salary_min"] == 100000
    assert job["salary_max"] == 120000
    assert job["description"] == "Build APIs"


def test_supplied_careers_url_is_validated_without_network() -> None:
    result = asyncio.run(CareerPageDiscovery().discover("https://acme.com/careers", company_name="Acme"))
    assert result.careers_url == "https://acme.com/careers"
    assert result.discovery_method == "supplied_url"
