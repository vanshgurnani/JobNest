import asyncio

import pytest

from scrapers.crawlers.base import detect_ats, extract_jobs_from_html
from scrapers.crawlers.orchestrator import crawl_jobs
from scrapers.crawlers.universal import (
    _common_careers_candidates,
    _dedupe_jobs,
    _extract_candidate_api_urls,
    _extract_jsonld_jobpostings,
    _extract_jobs_by_fallback,
    _is_unofficial_job_board,
    _job_from_search_result_url,
    _normalize_universal_output,
    _parse_jsonld_jobposting,
    universal_crawl_jobs,
)


def test_extract_jobs_from_html_prioritizes_job_links() -> None:
    html = """
    <html><body>
        <a href="/jobs/100">Software Engineer</a>
        <a href="/jobs/101">Data Scientist</a>
        <a href="/jobs/102">Marketing</a>
    </body></html>
    """

    jobs = extract_jobs_from_html(
        html,
        company="TestCo",
        base_url="https://example.com",
        location_hint="Seattle",
    )

    assert any(job["title"] == "Software Engineer" for job in jobs)
    assert jobs[0]["location"] == "Seattle"


def test_detect_ats_supports_smartrecruiters_from_html() -> None:
    html = '<a href="https://jobs.smartrecruiters.com/AcmeInc">Careers</a>'

    assert detect_ats("https://acme.com/careers", html) == {
        "platform": "smartrecruiters",
        "token": "AcmeInc",
    }


def test_detect_ats_supports_multilevel_workday_host() -> None:
    ats = detect_ats("https://mastercard.wd1.myworkdayjobs.com/CorporateCareers", "")

    assert ats == {
        "platform": "workday",
        "subdomain": "mastercard.wd1",
        "tenant": "mastercard",
        "board": "CorporateCareers",
    }


def test_detect_ats_supports_eightfold_vanity_host() -> None:
    ats = detect_ats(
        "https://jobs.twilio.com/careers?start=0&pid=1099555572151&sort_by=timestamp",
        "<html>Powered by eightfold.ai</html>",
    )

    assert ats == {
        "platform": "eightfold",
        "host": "jobs.twilio.com",
        "domain": "twilio.com",
    }


def test_detect_ats_detects_eightfold_from_html_marker() -> None:
    ats = detect_ats("https://careers.acme.com/careers", '<link href="https://static.vscdn.net/fonts/a.css">')

    assert ats is not None
    assert ats["platform"] == "eightfold"


def test_universal_rejects_unofficial_job_boards() -> None:
    assert _is_unofficial_job_board("https://www.indeed.com/cmp/acme/jobs")
    assert not _is_unofficial_job_board("https://careers.acme.com/jobs")


def test_jsonld_jobposting_parses_graph_and_locations() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@graph": [{
        "@type": ["Thing", "JobPosting"],
        "title": "Backend Engineer",
        "datePosted": "2026-07-01",
        "validThrough": "2099-01-01",
        "identifier": {"value": "BE-1"},
        "hiringOrganization": {"name": "Acme"},
        "jobLocation": [{
          "address": {
            "addressLocality": "Bengaluru",
            "addressRegion": "KA",
            "addressCountry": "IN"
          }
        }],
        "description": "<p>Build APIs.</p>",
        "url": "https://acme.com/jobs/be-1"
      }]
    }
    </script>
    """

    postings = _extract_jsonld_jobpostings(html)
    parsed = _parse_jsonld_jobposting(postings[0])

    assert parsed["title"] == "Backend Engineer"
    assert parsed["location"] == "Bengaluru, KA, IN"
    assert parsed["job_id"] == "BE-1"
    assert parsed["posted_date"] == "2026-07-01"


def test_dedupe_uses_company_job_id_or_url() -> None:
    jobs = [
        {"company": "Acme", "job_id": "1", "url": "https://acme.com/jobs/1", "title": "A"},
        {"company": "Acme", "job_id": "1", "url": "https://acme.com/jobs/1-copy", "title": "A"},
        {"company": "Acme", "job_id": "", "url": "https://acme.com/jobs/2", "title": "B"},
    ]

    assert len(_dedupe_jobs(jobs)) == 2


def test_normalize_universal_output_adds_requested_url_shape() -> None:
    jobs = _normalize_universal_output(
        [{"title": "Engineer", "apply_url": "/jobs/1", "posted_date": "2026-07-01"}],
        company="Acme",
        careers_url="https://acme.com/careers",
    )

    assert jobs[0]["url"] == "https://acme.com/jobs/1"
    assert jobs[0]["posted_date"] == "2026-07-01"


def test_orchestrator_passes_company_url_to_universal(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_universal_crawl_jobs(**kwargs):
        captured.update(kwargs)
        return []

    import scrapers.crawlers.universal as universal

    monkeypatch.setattr(universal, "universal_crawl_jobs", fake_universal_crawl_jobs)

    asyncio.run(crawl_jobs(company="acme", company_url="https://acme.com/careers"))

    assert captured["company_name"] == "acme"
    assert captured["company_url"] == "https://acme.com/careers"


def test_company_url_without_company_uses_universal_not_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_universal_crawl_jobs(**kwargs):
        captured.update(kwargs)
        return [{"title": "Consultant", "company": "Accenture", "url": kwargs["company_url"]}]

    import scrapers.crawlers.universal as universal

    monkeypatch.setattr(universal, "universal_crawl_jobs", fake_universal_crawl_jobs)

    results = asyncio.run(
        crawl_jobs(company_url="https://www.accenture.com/in-en/careers/jobsearch")
    )

    assert len(results) == 1
    assert results[0]["company"] == "Accenture"
    assert results[0]["jobs"][0]["title"] == "Consultant"
    assert captured["company_name"] == "accenture"


def test_common_careers_candidates_try_subdomains_first() -> None:
    candidates = _common_careers_candidates("Mastercard")

    assert "https://careers.mastercard.com" in candidates
    assert "https://jobs.mastercard.com" in candidates
    assert "https://mastercard.com/careers" in candidates


def test_common_careers_candidates_uses_known_official_alias() -> None:
    assert _common_careers_candidates("accenture")[0] == "https://www.accenture.com/in-en/careers/jobsearch"
    assert _common_careers_candidates("mastercard")[0] == "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers"


def test_candidate_api_urls_skip_static_assets() -> None:
    html = """
    <link href="/platform/css/jobs.css">
    <script src="/platform/js/careers.js"></script>
    <script>
      window.api = "/api/jobs/search";
      window.asset = "/careers/banner.png";
    </script>
    """

    urls = _extract_candidate_api_urls(html, "https://careers.acme.com", "https://acme.com")

    assert urls == ["https://careers.acme.com/api/jobs/search"]


def test_candidate_api_urls_do_not_treat_html_jobsearch_as_json_api() -> None:
    html = """
    <a href="/in-en/careers/jobsearch?jk=Custom%20Software%20Engineer%20Python%20-%206365277&sb=0">Apply</a>
    """

    urls = _extract_candidate_api_urls(html, "https://www.accenture.com/in-en/careers/jobsearch", "https://www.accenture.com")

    assert urls == []


def test_job_from_search_result_url_extracts_title_and_id() -> None:
    job = _job_from_search_result_url(
        "/in-en/careers/jobsearch?jk=Custom%20Software%20Engineer%20Python%20-%206365277&job_id=6365277",
        company="accenture",
        base_url="https://www.accenture.com/in-en/careers/jobsearch",
    )

    assert job is not None
    assert job["title"] == "Custom Software Engineer Python - 6365277"
    assert job["job_id"] == "6365277"


def test_fallback_extracts_jobs_from_search_result_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_discover(*args, **kwargs):
        return []

    import scrapers.crawlers.universal as universal
    monkeypatch.setattr(universal, "discover_job_urls", fake_discover)

    html = """
    <a href="/in-en/careers/jobsearch?jk=Custom%20Software%20Engineer%20Python%20-%206365277&job_id=6365277">
      Expand job details
    </a>
    """

    jobs = asyncio.run(
        _extract_jobs_by_fallback(
            "accenture",
            "https://www.accenture.com/in-en/careers/jobsearch",
            "https://www.accenture.com",
            html,
        )
    )

    assert jobs[0]["title"] == "Custom Software Engineer Python - 6365277"


def test_universal_crawl_fetch_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(**kwargs):
        return "https://mastercard.com", "https://mastercard.com/careers"

    async def fake_fetch_html(*args, **kwargs):
        raise RuntimeError("403 Forbidden")

    import scrapers.crawlers.universal as universal

    monkeypatch.setattr(universal, "_resolve_careers_page", fake_resolve)
    monkeypatch.setattr(universal, "_fetch_html", fake_fetch_html)

    jobs = asyncio.run(universal_crawl_jobs(company_name="mastercard", limit=5))

    assert jobs == []
