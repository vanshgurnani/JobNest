from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from scrapers.crawlers.api_discovery.sitemap import discover_job_urls
from scrapers.crawlers.api_discovery.graphql import introspect_graphql
from scrapers.crawlers.api_discovery.swagger import detect_openapi
from scrapers.crawlers.api_discovery.js_analyzer import discover_apis
from scrapers.crawlers.api_discovery.sourcemap import extract_sourcemaps
from scrapers.crawlers.learning.profile_store import get_profile_by_url, learn_from_successful_fetch, learn_from_api_response
from scrapers.crawlers.learning.pagination import detect_pagination, PaginationPattern
from scrapers.crawlers.base import (
    collect_job_candidates,
    crawl_ats_jobs,
    detect_ats,
    extract_jobs_from_html,
    _looks_like_job_title,
    normalize_job_payload,
    request_json_with_retries,
    request_with_retries,
    shared_httpx_client,
)

logger = logging.getLogger(__name__)

AMAZON_MAX_PER_PAGE = 100
AMAZON_JOBS_DOMAIN = "https://www.amazon.jobs"

_UNOFFICIAL_JOB_DOMAINS = (
    "indeed.com",
    "linkedin.com",
    "glassdoor.com",
    "monster.com",
    "naukri.com",
    "ziprecruiter.com",
)

_ALLOWED_ATS_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "ashbyhq.com",
    "oraclecloud.com",
    "successfactors.com",
    "phenompeople.com",
)

_CAREERS_URL_HINTS = (
    "/careers",
    "/jobs",
    "careers.",
    "jobs.",
    "myworkdayjobs.com",
    "greenhouse.io",
    "lever.co",
    "smartrecruiters.com",
    "ashbyhq.com",
)

_CAREERS_LINK_TEXT_HINTS = (
    "career", "careers", "job", "jobs", "join us", "join our team",
    "we're hiring", "we are hiring", "work with us", "openings",
    "open positions", "vacancies", "opportunities", "work at",
    "life at", "work here", "talent", "recruit", "hiring",
    "position", "requisition", "employment",
)

_STATIC_EXTENSIONS = (
    ".css",
    ".js",
    ".mjs",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
)

_COMPANY_ALIASES: dict[str, str] = {}
_KNOWN_COMPANY_CAREERS_URLS: dict[str, str] = {}
_LOADED = False


def _ensure_company_urls_loaded() -> None:
    """Bootstrap known company -> careers URL hints from the in-code seed directory.

    Only used as a fast path; any company not listed here is still resolved
    dynamically at runtime (slug-based candidate probing + homepage discovery).
    """
    global _KNOWN_COMPANY_CAREERS_URLS, _COMPANY_ALIASES, _LOADED
    if _LOADED:
        return
    _LOADED = True

    from scrapers.directory import _SEED_ALIASES, _SEED_URLS

    _KNOWN_COMPANY_CAREERS_URLS = {k: v for k, v in _SEED_URLS.items() if v.startswith("http")}
    _COMPANY_ALIASES = {k.strip().lower(): v.strip().lower() for k, v in _SEED_ALIASES.items()}


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _default_headers(accept: str = "text/html,application/xhtml+xml,application/json") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _registrable_root(host: str) -> str:
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    return ".".join(parts[-2:])


def _is_unofficial_job_board(url: str) -> bool:
    host = _host(url)
    return any(host == domain or host.endswith("." + domain) for domain in _UNOFFICIAL_JOB_DOMAINS)


def _is_allowed_source_url(url: str, company_base_url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")) or _is_unofficial_job_board(url):
        return False
    host = _host(url)
    base_host = _host(company_base_url)
    if host == base_host or host.endswith("." + base_host):
        return True
    if _registrable_root(host) == _registrable_root(base_host):
        return True
    return any(host == domain or host.endswith("." + domain) for domain in _ALLOWED_ATS_DOMAINS)


def _slugify_company_name(company_name: str) -> str:
    name = company_name.strip().lower()
    name = re.sub(r"\b(private|limited|ltd|inc|corp|corporation|company|co|plc|llc)\b\.?", "", name)
    return re.sub(r"[^a-z0-9]+", "", name)


def _looks_like_careers_url(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in _CAREERS_URL_HINTS)


def _has_static_asset_extension(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(_STATIC_EXTENSIONS)


def _looks_like_json_api_url(url: str) -> bool:
    if _has_static_asset_extension(url):
        return False
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    host = parsed.netloc.lower()
    if any(domain in host for domain in _ALLOWED_ATS_DOMAINS):
        return True
    if path.endswith((".json", "/json")):
        return True
    api_terms = ("/api/", "/graphql", "/rest/", "/wday/cxs/", "/posting-api/", "/requisitions")
    return any(term in path for term in api_terms) or any(term.strip("/") in query for term in api_terms)


async def _fetch_html(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0, client: httpx.AsyncClient | None = None) -> str:
    return await request_with_retries(url, headers=headers, timeout=timeout, client=client)


async def _get_homepage_html(company_url: str, *, client: httpx.AsyncClient | None = None) -> tuple[str, str]:
    headers = _default_headers()
    html = await _fetch_html(company_url, headers=headers, client=client)
    return company_url, html


def _extract_page_title(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if m:
        title = _clean_text(_strip_tags(m.group(1)))
        if title:
            return title
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        title = _clean_text(_strip_tags(m.group(1)))
        if title:
            for sep in (" - ", " | ", " — ", " – "):
                if sep in title:
                    return title.split(sep)[0]
            return title
    return ""


def _extract_jsonld_jobpostings(html: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = m.group(1)
        try:
            data = json.loads(raw)
        except Exception:
            continue

        items: list[Any]
        if isinstance(data, list):
            items = data
        else:
            items = [data]

        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            if item_type == "JobPosting" or (isinstance(item_type, list) and "JobPosting" in item_type):
                jobs.append(item)
            else:
                graph = item.get("@graph")
                if isinstance(graph, list):
                    for gi in graph:
                        gi_type = gi.get("@type") if isinstance(gi, dict) else None
                        if isinstance(gi, dict) and (gi_type == "JobPosting" or (isinstance(gi_type, list) and "JobPosting" in gi_type)):
                            jobs.append(gi)
    return jobs


def _parse_jsonld_jobposting(job: dict[str, Any]) -> dict[str, Any]:
    title = _clean_text(job.get("title"))
    hiring_org = job.get("hiringOrganization") if isinstance(job.get("hiringOrganization"), dict) else {}
    location = hiring_org.get("address", {}).get("addressLocality") if isinstance(hiring_org.get("address"), dict) else ""
    if not location:
        loc = job.get("jobLocation")
        if isinstance(loc, dict):
            address = loc.get("address")
            if isinstance(address, dict):
                location = ", ".join(
                    part for part in (
                        address.get("addressLocality"),
                        address.get("addressRegion"),
                        address.get("addressCountry"),
                    )
                    if part
                )
            else:
                location = loc.get("addressLocality") or address
        elif isinstance(loc, list):
            locations = []
            for item in loc:
                if isinstance(item, dict):
                    address = item.get("address")
                    if isinstance(address, dict):
                        locations.append(
                            ", ".join(
                                part for part in (
                                    address.get("addressLocality"),
                                    address.get("addressRegion"),
                                    address.get("addressCountry"),
                                )
                                if part
                            )
                        )
            location = "; ".join(locations)
        elif isinstance(loc, str):
            location = loc

    posted = job.get("datePosted") or ""
    apply_url = job.get("directApply")
    if isinstance(apply_url, dict):
        apply_url = apply_url.get("url")
    if isinstance(apply_url, str):
        # Some boards (e.g. Barclays) emit the literal string "False" instead of
        # omitting the field. Treat it as absent.
        if apply_url.strip().lower() in ("false", "none", "null", "true"):
            apply_url = ""
    if not apply_url or not isinstance(apply_url, str):
        apply_url = job.get("url") or job.get("applicationUrl") or ""

    job_id = _clean_text(job.get("identifier", {}).get("value")) if isinstance(job.get("identifier"), dict) else ""

    description = ""
    desc = job.get("description")
    if isinstance(desc, str):
        description = _strip_tags(desc)

    return {
        "title": title,
        "company": _clean_text(hiring_org.get("name")) or "",
        "location": _clean_text(location),
        "description": description,
        "apply_url": apply_url or "",
        "posted_date": posted,
        "job_id": job_id,
        "valid_through": job.get("validThrough") or "",
    }


def _dedupe_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    seen_normalized: set[str] = set()
    out: list[dict[str, Any]] = []
    for j in jobs:
        job_id = (j.get("job_id") or "").strip()
        url = (j.get("url") or j.get("apply_url") or "").strip()
        title = (j.get("title") or "").strip().lower()
        title_norm = re.sub(r"[\s\-–—/\\,;&#x2013;]+", " ", title).strip()
        location = (j.get("location") or "").strip().lower()
        key = f"{j.get('company','').strip().lower()}|{job_id or url or title + '|' + location}"
        norm_key = f"{j.get('company','').strip().lower()}|{title_norm}"
        if not key or key in seen or norm_key in seen_normalized:
            continue
        seen.add(key)
        seen_normalized.add(norm_key)
        if not j.get("url") and j.get("apply_url"):
            j["url"] = j.get("apply_url")
        out.append(j)
    return out


def _common_careers_candidates(company_name: str) -> list[str]:
    slug = _slugify_company_name(company_name)
    if not slug:
        return []
    normalized_name = _clean_text(company_name).lower()

    _ensure_company_urls_loaded()
    alias_target = _COMPANY_ALIASES.get(normalized_name)
    known_url = (
        _KNOWN_COMPANY_CAREERS_URLS.get(normalized_name)
        or _KNOWN_COMPANY_CAREERS_URLS.get(alias_target)
        or _KNOWN_COMPANY_CAREERS_URLS.get(slug)
    )
    if not known_url:
        normalized_no_dots = normalized_name.replace(".", "")
        known_url = _KNOWN_COMPANY_CAREERS_URLS.get(normalized_no_dots)

    candidates = [
        f"https://www.{slug}.com/careers",
        f"https://www.{slug}.com/jobs",
        f"https://careers.{slug}.com",
        f"https://career.{slug}.com",
        f"https://jobs.{slug}.com",
        f"https://{slug}.com/careers",
        f"https://{slug}.com/jobs",
        f"https://{slug}.com/career",
        f"https://{slug}.com/en/careers",
        f"https://{slug}.com/en/jobs",
        f"https://www.{slug}.com",
        f"https://{slug}.com",
        f"https://{slug}.co/careers",
        f"https://{slug}.co/jobs",
        f"https://{slug}.co",
        f"https://{slug}.io/careers",
        f"https://{slug}.io/jobs",
        f"https://{slug}.io",
    ]
    if known_url:
        candidates.insert(0, known_url)
    out: list[str] = []
    for candidate in candidates:
        if candidate not in out:
            out.append(candidate)
    return out


def _extract_anchor_urls(html: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
        href = match.group(1)
        if href:
            urls.append(href)
    return urls


def _job_from_search_result_url(url: str, *, company: str, base_url: str) -> dict[str, Any] | None:
    full_url = urljoin(base_url, url)
    parsed = urlparse(full_url)
    query = parse_qs(parsed.query)
    title = ""
    for key in ("jk", "job", "jobtitle", "title", "keyword", "keywords"):
        values = query.get(key)
        if values and values[0] and "{" not in values[0]:
            title = _clean_text(unquote(values[0]))
            break

    job_id = ""
    for key in ("job_id", "jobId", "jobid", "job", "id", "reqid", "requisitionId"):
        values = query.get(key)
        if values and values[0] and "{" not in values[0]:
            job_id = _clean_text(unquote(values[0]))
            break
    if not job_id:
        id_match = re.search(r"(?:jobs?|requisitions?|jobdetails?)[/-](\d{4,}|\w+-\w+)", parsed.path, re.IGNORECASE)
        if id_match:
            job_id = id_match.group(1)

    if not title and not job_id:
        return None
    if not title:
        # Only fabricate a title from the slug when the path actually looks like
        # a job posting; otherwise this turns nav links ("/board-and-leadership/")
        # into fake jobs.
        if not re.search(r"(?:/jobs?|/jobdetail|/requisition|/position|/opening|/candidate-experience)/", parsed.path, re.IGNORECASE):
            return None
        slug = parsed.path.rstrip("/").split("/")[-1]
        title = _clean_text(unquote(slug.replace("-", " ")))
    if not title or title.lower() in {"jobsearch", "search-results", "results"}:
        return None

    return {
        "company": company.title(),
        "job_id": job_id,
        "title": title[:160],
        "location": "",
        "description": f"Job listing discovered from {company} careers search results.",
        "apply_url": full_url,
        "url": full_url,
        "source": "search-url",
    }


def _discover_company_domain_from_url(company_url: str) -> str:
    return urlparse(company_url).netloc.lower()


def _careers_candidates_from_base(company_base: str) -> list[str]:
    parsed = urlparse(company_base if company_base.startswith("http") else f"https://{company_base}")
    host = parsed.netloc.lower().removeprefix("www.")
    if not host:
        return []
    root = _registrable_root(host)
    scheme = parsed.scheme or "https"
    candidates = [
        company_base if company_base.startswith("http") else f"{scheme}://{host}",
        f"{scheme}://careers.{root}",
        f"{scheme}://jobs.{root}",
        f"{scheme}://{root}/careers",
        f"{scheme}://{root}/jobs",
    ]
    out: list[str] = []
    for candidate in candidates:
        if candidate not in out:
            out.append(candidate)
    return out


def _extract_official_career_links(html: str, *, base_url: str, company_base_url: str) -> list[str]:
    candidates: list[str] = []
    seen_urls: set[str] = set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\']\s*[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href = m.group(1)
        link_text = _clean_text(_strip_tags(m.group(2)))
        abs_url = urljoin(base_url, href)
        if not abs_url.startswith("http"):
            continue
        is_careers_url = _looks_like_careers_url(abs_url)
        has_careers_text = link_text and any(hint in link_text.lower() for hint in _CAREERS_LINK_TEXT_HINTS)
        if is_careers_url or has_careers_text:
            if abs_url not in seen_urls:
                seen_urls.add(abs_url)
                candidates.append((abs_url, link_text))

    official_raw = [c for c, _ in candidates if _is_allowed_source_url(c, company_base_url)]
    official_raw = list(dict.fromkeys(official_raw))
    official_raw.sort(key=lambda u: (
        0 if any(p in u.lower() for p in ("/careers", "/jobs", "careers.", "jobs.")) else 1,
        len(u),
    ))
    return official_raw


async def _first_fetchable_careers_candidate(
    candidates: list[str],
    *,
    company_base_url: str,
    headers: dict[str, str],
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str | None]:
    for candidate in candidates:
        if _is_unofficial_job_board(candidate) or not _is_allowed_source_url(candidate, company_base_url):
            continue
        if any(_host(candidate) == domain or _host(candidate).endswith("." + domain) for domain in _ALLOWED_ATS_DOMAINS):
            return candidate, None
        try:
            html = await _fetch_html(candidate, headers=headers, timeout=12.0, client=client)
        except Exception as exc:
            logger.info("Careers candidate failed for %s: %s", candidate, exc)
            continue
        official = _extract_official_career_links(html, base_url=candidate, company_base_url=company_base_url)
        return (official[0], None) if official else (candidate, html)
    return "", None


async def _resolve_careers_page(*, company_name: str, company_url: str | None, client: httpx.AsyncClient | None = None) -> tuple[str, str]:
    headers = _default_headers()

    if company_url:
        company_base = company_url
        if not company_base.startswith("http"):
            company_base = "https://" + company_base
        if _is_unofficial_job_board(company_base):
            raise ValueError(f"Refusing unofficial job board URL for {company_name}: {company_base}")

        company_host = _host(company_base)
        if any(company_host == domain or company_host.endswith("." + domain) for domain in _ALLOWED_ATS_DOMAINS):
            return company_base, company_base

        try:
            html = await _fetch_html(company_base, headers=headers, client=client)
        except Exception as exc:
            logger.warning("Failed fetching company base for %s (%s): %s", company_name, company_base, exc)
            careers_url, _ = await _first_fetchable_careers_candidate(
                _careers_candidates_from_base(company_base),
                company_base_url=company_base,
                headers=headers,
                client=client,
            )
            if careers_url:
                return company_base, careers_url
            return company_base, urljoin(company_base + "/", "careers")

        official = _extract_official_career_links(html, base_url=company_base, company_base_url=company_base)
        if official:
            return company_base, official[0]

        careers_url, _ = await _first_fetchable_careers_candidate(
            _careers_candidates_from_base(company_base),
            company_base_url=company_base,
            headers=headers,
            client=client,
        )
        return company_base, careers_url or urljoin(company_base + "/", "careers")

    _ensure_company_urls_loaded()

    normalized_name = _clean_text(company_name).lower()
    slug = _slugify_company_name(company_name)

    # Resolve aliases
    alias_target = _COMPANY_ALIASES.get(normalized_name) or _COMPANY_ALIASES.get(slug)
    if alias_target:
        logger.info("Company '%s' resolved via alias to '%s'", company_name, alias_target)
        return await _resolve_careers_page(company_name=alias_target, company_url=None, client=client)

    known_url = _KNOWN_COMPANY_CAREERS_URLS.get(normalized_name) or _KNOWN_COMPANY_CAREERS_URLS.get(slug)
    if known_url:
        known_base = known_url[:known_url.index("/", 8)] if known_url.startswith("http") and "/" in known_url[8:] else known_url
        return known_base, known_url

    name = company_name.strip()
    if name.startswith("http"):
        return await _resolve_careers_page(company_name=company_name, company_url=name, client=client)

    if "." in name and " " not in name:
        return await _resolve_careers_page(company_name=company_name, company_url=name, client=client)

    if not slug:
        raise ValueError("Unable to resolve company URL")

    company_base = f"https://{slug}.com"
    careers_url, careers_html = await _first_fetchable_careers_candidate(
        _common_careers_candidates(name),
        company_base_url=company_base,
        headers=headers,
        client=client,
    )
    if careers_url:
        return company_base, careers_url

    # Last resort: try the homepage and extract career links from it
    try:
        html = await _fetch_html(company_base, headers=headers, timeout=12.0, client=client)
        official = _extract_official_career_links(html, base_url=company_base, company_base_url=company_base)
        if official:
            return company_base, official[0]
    except Exception:
        pass

    return company_base, urljoin(company_base + "/", "careers")


def _extract_embedded_json(html: str) -> list[Any]:
    candidates: list[Any] = []
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script"):
        script_id = (script.get("id") or "").lower()
        script_type = (script.get("type") or "").lower()
        text = script.string or script.get_text() or ""
        if not text:
            continue
        if script_type == "application/json" or script_id in {"__next_data__", "gatsby-focus-wrapper"}:
            try:
                candidates.append(json.loads(text))
            except Exception:
                continue

    patterns = [
        r"jobs\s*:\s*(\[\s*\{.*?\}\s*\]|\[.*?\])",
        r"jobPostings\s*:\s*(\[.*?\])",
        r"postings\s*:\s*(\[.*?\])",
        r"requisitions\s*:\s*(\[.*?\])",
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, flags=re.IGNORECASE | re.DOTALL):
            raw = m.group(1)
            try:
                candidates.append(json.loads(raw))
            except Exception:
                continue
    return candidates


def _extract_dynamic_tokens(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    tokens: dict[str, str] = {}
    meta_names = ("csrf-token", "csrf", "x-csrf-token", "x-xsrf-token")
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        if name in meta_names and meta.get("content"):
            tokens["x-csrf-token"] = meta["content"]
    for hidden in soup.find_all("input", {"type": "hidden"}):
        name = (hidden.get("name") or "").lower()
        value = hidden.get("value")
        if value and any(token_name in name for token_name in ("csrf", "xsrf", "token", "lsd")):
            tokens[name] = value
    return tokens


def _extract_candidate_api_urls(html: str, careers_url: str, company_base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    for tag in soup.find_all(["a", "script", "link"]):
        for attr in ("href", "src"):
            value = tag.get(attr)
            if value:
                urls.append(urljoin(careers_url, value))

    for match in re.finditer(r'["\']([^"\']*(?:api|jobs|careers|positions|requisitions)[^"\']*)["\']', html, re.IGNORECASE):
        value = match.group(1)
        if value.startswith(("http://", "https://", "/")):
            urls.append(urljoin(careers_url, value))

    out: list[str] = []
    seen: set[str] = set()
    for candidate in urls:
        if candidate in seen or not _is_allowed_source_url(candidate, company_base_url):
            continue
        if not _looks_like_json_api_url(candidate):
            continue
        seen.add(candidate)
        out.append(candidate)
    return out[:20]


async def _extract_jobs_from_json_payload(payload: Any, company: str, source: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for candidate in collect_job_candidates(payload):
        normalized = normalize_job_payload(candidate, company, source)
        if normalized.get("title") and (normalized.get("apply_url") or normalized.get("job_id") or normalized.get("description")):
            jobs.append(normalized)
    return jobs


def _has_working_apply(job: dict[str, Any]) -> bool:
    return bool((job.get("apply_url") or job.get("url") or "").strip() or (job.get("job_id") or "").strip())


def _job_missing_fields(job: dict[str, Any]) -> set[str]:
    missing: set[str] = set()
    if not (job.get("description") or "").strip():
        missing.add("description")
    if not (job.get("job_id") or "").strip():
        missing.add("job_id")
    if not (job.get("location") or "").strip():
        missing.add("location")
    if not _has_working_apply(job):
        missing.add("apply")
    return missing


def _merge_job_enrichment(base: dict[str, Any], enriched: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for field in ("description", "job_id", "location", "apply_url", "url"):
        cur = (merged.get(field) or "").strip()
        nxt = (enriched.get(field) or "").strip()
        if nxt and not cur:
            merged[field] = enriched[field]

    if merged.get("apply_url") and not merged.get("url"):
        merged["url"] = merged.get("apply_url")
    if merged.get("url") and not merged.get("apply_url"):
        merged["apply_url"] = merged.get("url")

    return merged


async def _chain_enrich_jobs_from_possible_details(
    *,
    jobs: list[dict[str, Any]],
    company: str,
    careers_url: str,
    company_base_url: str,
    html: str,
    keyword: str | None,
    location: str | None,
    max_secondary_per_page: int = 5,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    detail_urls: list[str] = []
    for match in re.finditer(r'["\']([^"\']*(?:job|posting|requisition|requisitions|positions)[^"\']*)["\']', html, re.IGNORECASE):
        value = match.group(1)
        if not value:
            continue
        if value.startswith(("http://", "https://")):
            full = value
        else:
            full = urljoin(careers_url, value)
        if _is_allowed_source_url(full, company_base_url) and _looks_like_json_api_url(full):
            detail_urls.append(full)

    templates: list[str] = []
    for du in detail_urls[:10]:
        if du.endswith(("/jobs", "/job", "/postings", "/posting", "/requisitions", "/positions", "/requisition")):
            templates.append(du.rstrip("/"))
        else:
            templates.append(du)

    budget = max_secondary_per_page
    enriched_jobs: list[dict[str, Any]] = []

    tokens = _extract_dynamic_tokens(html)
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Referer": careers_url,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    }
    if "x-csrf-token" in tokens:
        headers["x-csrf-token"] = tokens["x-csrf-token"]

    for job in jobs:
        if budget <= 0:
            enriched_jobs.append(job)
            continue

        missing = _job_missing_fields(job)
        if not missing.intersection({"description", "job_id", "location"}):
            enriched_jobs.append(job)
            continue

        identifier = (job.get("job_id") or "").strip()
        apply_url = (job.get("apply_url") or job.get("url") or "").strip()

        candidates: list[str] = []
        for tpl in templates[:5]:
            if identifier:
                candidates.append(tpl.rstrip("/") + "/" + identifier)
                sep = "&" if "?" in tpl else "?"
                candidates.append(f"{tpl}{sep}id={identifier}")
            if not candidates and apply_url:
                id_match = re.search(r"(?:jobs?|job|requisitions?|posting|position)[/-](\d{4,}|\w+-\w+)", apply_url, re.IGNORECASE)
                if id_match:
                    candidates.append(tpl.rstrip("/") + "/" + id_match.group(1))

        uniq: list[str] = []
        seen: set[str] = set()
        for c in candidates:
            if c in seen:
                continue
            seen.add(c)
            if _is_allowed_source_url(c, company_base_url):
                uniq.append(c)
        uniq = uniq[:3]

        if not uniq:
            enriched_jobs.append(job)
            continue

        fetched: dict[str, Any] | None = None
        for detail_url in uniq[:1]:
            try:
                payload = await request_json_with_retries(detail_url, headers=headers, timeout=12.0, client=client)
            except Exception as exc:
                logger.debug("Secondary enrich failed for %s (%s): %s", company, detail_url, exc)
                continue

            try:
                extracted = await _extract_jobs_from_json_payload(payload, company, "secondary")
            except Exception:
                extracted = []

            if extracted:
                if identifier:
                    for ej in extracted:
                        if (ej.get("job_id") or "").strip() == identifier:
                            fetched = ej
                            break
                if not fetched:
                    fetched = extracted[0]

        if fetched:
            merged = _merge_job_enrichment(job, fetched)
            enriched_jobs.append(merged)
            budget -= 1
        else:
            enriched_jobs.append(job)

    return enriched_jobs


async def _fetch_jobs_from_candidate_apis(
    *,
    company: str,
    careers_url: str,
    company_base_url: str,
    html: str,
    keyword: str | None,
    location: str | None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    tokens = _extract_dynamic_tokens(html)
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Referer": careers_url,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    }
    if "x-csrf-token" in tokens:
        headers["x-csrf-token"] = tokens["x-csrf-token"]

    jobs: list[dict[str, Any]] = []
    company_domain = _host(company_base_url)

    profile = get_profile_by_url(company_base_url)
    if profile and profile.get("url_pattern"):
        known_api_url = f"https://{profile['url_pattern']}"
        try:
            profile_payload = await request_json_with_retries(known_api_url, headers=headers, timeout=15.0, client=client)
            if profile_payload:
                profile_jobs = await learn_from_api_response(company_domain, known_api_url, profile_payload, company)
                if profile_jobs:
                    logger.info("Using cached API profile for %s — %d jobs", company_domain, len(profile_jobs))
                    return profile_jobs
        except Exception:
            logger.debug("Profile URL failed for %s, falling back to discovery", company_domain)

    candidate_apis = _extract_candidate_api_urls(html, careers_url, company_base_url)[:5]

    js_api_result = await discover_apis(html, careers_url)
    for js_url in js_api_result.get("urls", []):
        if js_url not in candidate_apis and _is_allowed_source_url(js_url, company_base_url) and _looks_like_json_api_url(js_url):
            candidate_apis.append(js_url)

    sourcemap_urls = await extract_sourcemaps(html, careers_url)
    for sm_url in sourcemap_urls[:3]:
        try:
            from scrapers.crawlers.api_discovery.sourcemap import analyze_sourcemap_content
            found_apis = await analyze_sourcemap_content(sm_url)
            for api_url in found_apis:
                resolved = urljoin(careers_url, api_url)
                if resolved not in candidate_apis and _is_allowed_source_url(resolved, company_base_url) and _looks_like_json_api_url(resolved):
                    candidate_apis.append(resolved)
        except Exception:
            continue

    candidate_apis = candidate_apis[:8]

    for api_url in candidate_apis:
        await asyncio.sleep(0.1 + random.random() * 0.15)
        if any(term in api_url.lower() for term in ("captcha", "cloudflare", "turnstile")):
            logger.info("Restricted due to likely block for %s: %s", company, api_url)
            break

        try:
            payload = await request_json_with_retries(api_url, headers=headers, timeout=15.0, client=client)
        except Exception:
            continue

        extracted = await _extract_jobs_from_json_payload(payload, company, "json-api") if payload is not None else []

        if extracted and len(extracted) >= 2:
            learn_from_successful_fetch(company_domain, api_url, payload, extracted)

        for job in extracted:
            if not (job.get("title") or "").strip():
                continue
            if not ((job.get("apply_url") or job.get("url") or "").strip() or (job.get("job_id") or "").strip()):
                continue

            if keyword:
                blob = f"{job.get('title', '')} {job.get('description', '')}".lower()
                if keyword.lower() not in blob:
                    continue

            if location and job.get("location") and location.lower() not in job["location"].lower():
                continue

            apply_url = job.get("apply_url") or ""
            if apply_url and not apply_url.startswith("http"):
                job["apply_url"] = urljoin(careers_url, apply_url)
                apply_url = job["apply_url"]
            if apply_url and not _is_allowed_source_url(apply_url, company_base_url):
                continue

            jobs.append(job)

    return jobs


async def _try_graphql_and_openapi_discovery(
    company: str,
    careers_url: str,
    company_base_url: str,
    *,
    keyword: str | None = None,
    location: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []

    graphql_info = await introspect_graphql(careers_url)
    if graphql_info:
        logger.info("GraphQL introspection succeeded for %s — trying job queries", company)
        gql_url = graphql_info["url"]
        queries = graphql_info.get("queries", [])
        gql_headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        for q in queries[:5]:
            try:
                payload = {"query": q["query"]}
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                    resp = await c.post(gql_url, json=payload, headers=gql_headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        extracted = await _extract_jobs_from_json_payload(data, company, "graphql")
                        for job in extracted:
                            if job.get("title"):
                                jobs.append(job)
            except Exception:
                continue
        if jobs:
            logger.info("GraphQL discovery found %d jobs for %s", len(jobs), company)
            domain = _host(company_base_url)
            learn_from_successful_fetch(domain, gql_url, data, jobs)
            return jobs

    openapi_info = await detect_openapi(company_base_url)
    if not openapi_info:
        openapi_info = await detect_openapi(careers_url)
    if openapi_info:
        logger.info("OpenAPI discovery succeeded for %s — %d endpoints", company, len(openapi_info["endpoints"]))
        for ep in openapi_info["endpoints"][:3]:
            ep_url = f"{company_base_url.rstrip('/')}{ep['path']}"
            try:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                    resp = await c.get(ep_url, headers=_default_headers("application/json"))
                    if resp.status_code == 200:
                        data = resp.json()
                        extracted = await _extract_jobs_from_json_payload(data, company, "openapi")
                        for job in extracted:
                            if job.get("title"):
                                jobs.append(job)
            except Exception:
                continue
        if jobs:
            try:
                domain = _host(company_base_url)
                learn_from_successful_fetch(domain, ep_url, data, jobs)
            except Exception:
                pass

    if jobs:
        logger.info("OpenAPI discovery found %d jobs for %s", len(jobs), company)
    return jobs


async def _fetch_job_from_url(
    url: str,
    *,
    company: str,
    company_base_url: str,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Fetch a candidate job URL and extract a real listing (JSON-LD / embedded JSON / meta).

    Returns None when the page isn't actually a job posting, so nav links never
    masquerade as jobs.
    """
    try:
        page_html = await _fetch_html(url, headers=_default_headers(), timeout=12.0, client=client)
    except Exception:
        return None
    if not page_html:
        return None

    for item in _extract_jsonld_jobpostings(page_html):
        parsed = _parse_jsonld_jobposting(item)
        if parsed.get("title"):
            apply_url = parsed.get("apply_url") or url
            if not apply_url.startswith("http"):
                apply_url = urljoin(url, apply_url)
            if not _is_allowed_source_url(apply_url, company_base_url):
                continue
            return {
                "company": company.title(),
                "job_id": parsed.get("job_id", ""),
                "title": parsed["title"],
                "location": parsed.get("location", ""),
                "description": parsed.get("description", ""),
                "apply_url": apply_url,
                "url": apply_url,
                "source": "fetched-jsonld",
                "posted_date": parsed.get("posted_date", ""),
                "valid_through": parsed.get("valid_through", ""),
            }

    for payload in _extract_embedded_json(page_html):
        for job in await _extract_jobs_from_json_payload(payload, company, "fetched-json"):
            apply_url = job.get("apply_url") or ""
            if apply_url and not apply_url.startswith("http"):
                apply_url = urljoin(url, apply_url)
            if apply_url and not _is_allowed_source_url(apply_url, company_base_url):
                continue
            job["apply_url"] = apply_url or url
            job["url"] = apply_url or url
            job["source"] = "fetched-json"
            return job

    title = _extract_page_title(page_html)
    if not title or not _looks_like_job_title(title, url):
        return None
    if not re.search(r"(?:/job(?:s|detail)?/|/requisition/|/position/|/opening/|jobId=|requisitionId=)", url, re.IGNORECASE):
        return None
    return {
        "company": company.title(),
        "job_id": "",
        "title": title[:160],
        "location": "",
        "description": f"Job listing scraped from {company}.",
        "apply_url": url,
        "url": url,
        "source": "fetched-html",
    }


async def _extract_jobs_by_fallback(company: str, careers_url: str, company_base_url: str, html: str, *, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    async def _from_anchors() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        candidates: list[str] = []
        for href in _extract_anchor_urls(html):
            full = urljoin(careers_url, href)
            if full not in candidates and _is_allowed_source_url(full, company_base_url):
                candidates.append(full)
        for url in candidates[:20]:
            fast = _job_from_search_result_url(url, company=company, base_url=careers_url)
            if fast:
                result.append(fast)
                continue
            job = await _fetch_job_from_url(url, company=company, company_base_url=company_base_url, client=client)
            if job:
                result.append(job)
        return result

    async def _from_embedded() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for payload in _extract_embedded_json(html):
            for job in await _extract_jobs_from_json_payload(payload, company, "embedded-json"):
                apply_url = job.get("apply_url") or ""
                if apply_url and not apply_url.startswith("http"):
                    job["apply_url"] = urljoin(careers_url, apply_url)
                    apply_url = job["apply_url"]
                if apply_url and not _is_allowed_source_url(apply_url, company_base_url):
                    continue
                result.append(job)
        return result

    async def _from_html() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        jobs_from_html = extract_jobs_from_html(html, company=company, base_url=careers_url)
        for j in jobs_from_html:
            if not j.get("apply_url"):
                j["apply_url"] = j.get("url", "")
            if j.get("url") and not _is_allowed_source_url(j["url"], company_base_url):
                continue
            if not re.search(r"(?:/job(?:s|detail)?/|/requisition/|/position/|/opening/|jobId=|requisitionId=)", j.get("url", ""), re.IGNORECASE):
                continue
            result.append({
                "company": j.get("company", company).title(),
                "job_id": j.get("job_id", ""),
                "title": j.get("title", ""),
                "location": j.get("location", ""),
                "description": j.get("description", ""),
                "skills": j.get("skills", []),
                "employment_type": "",
                "experience": "",
                "apply_url": j.get("url", ""),
                "source": "html",
                "url": j.get("url", ""),
            })
        return result

    async def _from_jsonld() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        jsonld = _extract_jsonld_jobpostings(html)
        for j in jsonld:
            parsed = _parse_jsonld_jobposting(j)
            if not parsed.get("title"):
                continue
            apply_url = parsed.get("apply_url") or ""
            if apply_url and not _is_allowed_source_url(urljoin(careers_url, apply_url), company_base_url):
                continue
            job_id = parsed.get("job_id") or ""
            normalized = normalize_job_payload({
                "job_id": job_id,
                "title": parsed.get("title"),
                "location": parsed.get("location"),
                "description": parsed.get("description"),
                "apply_url": urljoin(careers_url, apply_url) if apply_url else careers_url,
                "employment_type": "",
                "experience": "",
                "skills": [],
            }, company, "jsonld")
            normalized["posted_date"] = parsed.get("posted_date", "")
            normalized["valid_through"] = parsed.get("valid_through", "")
            result.append(normalized)
        return result

    async def _from_sitemap() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        try:
            sitemap_urls = await discover_job_urls(careers_url)
            if not sitemap_urls:
                sitemap_urls = await discover_job_urls(company_base_url)
            seen_sitemap: set[str] = set()
            for su in sitemap_urls[:30]:
                if su in seen_sitemap:
                    continue
                seen_sitemap.add(su)
                if not _is_allowed_source_url(su, company_base_url):
                    continue
                candidate = _job_from_search_result_url(su, company=company, base_url=careers_url)
                if candidate and candidate.get("title"):
                    result.append(candidate)
                    continue
                try:
                    detail_html = await _fetch_html(su, headers=_default_headers(), timeout=10.0, client=client)
                    jsonld_items = _extract_jsonld_jobpostings(detail_html)
                    for item in jsonld_items:
                        parsed = _parse_jsonld_jobposting(item)
                        if parsed.get("title"):
                            normalized = normalize_job_payload({
                                "job_id": parsed.get("job_id"),
                                "title": parsed.get("title"),
                                "location": parsed.get("location"),
                                "description": parsed.get("description"),
                                "apply_url": parsed.get("apply_url") or su,
                                "employment_type": "",
                                "experience": "",
                                "skills": [],
                            }, company, "sitemap")
                            result.append(normalized)
                            break
                    if not jsonld_items:
                        detail_jobs = extract_jobs_from_html(detail_html, company=company, base_url=su)
                        for dj in detail_jobs:
                            if dj.get("title"):
                                result.append({
                                    "company": company.title(),
                                    "job_id": "",
                                    "title": dj["title"],
                                    "location": dj.get("location", ""),
                                    "description": dj.get("description", f"Job listing from {company} careers."),
                                    "apply_url": dj.get("url", su),
                                    "url": dj.get("url", su),
                                    "source": "sitemap-html",
                                })
                                break
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Sitemap extraction failed for %s: %s", company, exc)
        logger.info("Sitemap extraction: %d jobs from %s", len(result), company)
        return result

    results = await asyncio.gather(
        _from_anchors(),
        _from_embedded(),
        _from_html(),
        _from_jsonld(),
        _from_sitemap(),
        return_exceptions=True,
    )

    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in results:
        if isinstance(r, Exception):
            logger.warning("Parallel extraction strategy failed: %s", r)
            continue
        for job in r:
            key = (job.get("title", "") + job.get("company", "") + job.get("location", "")).lower()
            if key and key not in seen:
                seen.add(key)
                jobs.append(job)

    logger.info("Parallel extraction: %d total jobs from %s", len(jobs), company)
    return jobs


async def _extract_jobs_with_playwright(
    url: str,
    company: str,
    *,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("Playwright not installed - skipping browser render for %s", url)
        return []

    api_responses: list[dict[str, Any]] = []
    api_requests: list[dict[str, Any]] = []
    rendered_html: str | None = None
    logger.info("Playwright launching browser for %s", url)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                )
            )
            page_obj = await context.new_page()

            async def handle_response(response):
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    try:
                        body = await response.json()
                        if body:
                            api_responses.append({"url": response.url, "body": body})
                    except Exception:
                        pass

            async def handle_request(request):
                if request.url and ("typesense" in request.url or "multi_search" in request.url):
                    try:
                        api_requests.append({
                            "url": request.url,
                            "method": request.method,
                            "headers": dict(request.headers),
                            "post_data": request.post_data,
                        })
                    except Exception:
                        pass

            page_obj.on("response", handle_response)
            page_obj.on("request", handle_request)

            await page_obj.goto(url, wait_until="load", timeout=15000)
            await page_obj.wait_for_timeout(1500)

            job_api_urls = [r["url"] for r in api_responses
                           if any(kw in r["url"] for kw in ("search", "job", "career", "requisition", "position", "posting"))]
            if not job_api_urls:
                await page_obj.wait_for_timeout(4000)

            if page > 1:
                replayed = False
                if api_requests and api_responses:
                    for resp_entry in api_responses:
                        resp_body = resp_entry["body"] if isinstance(resp_entry, dict) and "body" in resp_entry else resp_entry
                        if not isinstance(resp_body, dict):
                            continue
                        searches = resp_body.get("searches") or resp_body.get("results")
                        if not searches or not isinstance(searches, list):
                            continue
                        for sr in searches:
                            found = sr.get("found", 0)
                            per_page_val = sr.get("per_page", 10)
                            if found > (page - 1) * per_page_val:
                                req = api_requests[0]
                                if req and req.get("post_data"):
                                    try:
                                        body_data = json.loads(req["post_data"])
                                        for s in body_data.get("searches", []):
                                            s["page"] = page
                                        clean_url = req["url"].split("&_token")[0] if "_token" in req["url"] else req["url"]
                                        async with httpx.AsyncClient() as cl:
                                            http_resp = await cl.post(
                                                clean_url,
                                                content=json.dumps(body_data),
                                                headers={"content-type": "text/plain"},
                                                timeout=15,
                                            )
                                            if http_resp.status_code == 200:
                                                api_responses.clear()
                                                api_responses.append({"url": clean_url, "body": http_resp.json()})
                                                logger.info("Playwright fetched page %d from TypeSense API for %s", page, url)
                                                replayed = True
                                    except Exception as e:
                                        logger.warning("Failed to fetch TypeSense page %d: %s", page, e)
                                break
                        if replayed:
                            break
                if not replayed:
                    api_responses.clear()

            rendered_html = await page_obj.content()
            await browser.close()
    except Exception as exc:
        logger.warning("Playwright extraction failed for %s: %s", url, exc)
        return []

    all_jobs: list[dict[str, Any]] = []
    logger.info("Playwright captured %d API responses for %s", len(api_responses), url)

    for resp_entry in api_responses:
        resp_url = resp_entry.get("url", "") if isinstance(resp_entry, dict) else ""
        payload = resp_entry["body"] if isinstance(resp_entry, dict) and "body" in resp_entry else resp_entry
        extracted = await _extract_jobs_from_json_payload(payload, company, "playwright-api")
        if extracted:
            logger.info("Playwright extracted %d items from %s", len(extracted), resp_url[:80])
        for job in extracted:
            if job.get("title"):
                job["_api_url"] = resp_url
                all_jobs.append(job)

    if all_jobs:
        is_job_api = lambda u: any(kw in u for kw in ("search", "job", "career", "requisition", "position", "posting"))
        job_api_jobs = [j for j in all_jobs if is_job_api(j.get("_api_url", ""))]
        if job_api_jobs:
            all_jobs = job_api_jobs

        _job_url_pat = re.compile(r"/job(?:s|detail)?/\d+|jobId=|requisition|position/\d+", re.IGNORECASE)
        real_jobs = [j for j in all_jobs if j.get("job_id") or _job_url_pat.search(j.get("apply_url", "") or "")]
        if real_jobs:
            all_jobs = real_jobs

        for j in all_jobs:
            j.pop("_api_url", None)

    api_had_location = sum(1 for j in all_jobs if j.get("location"))
    api_quality_ok = len(all_jobs) >= 3 and api_had_location >= len(all_jobs) * 0.3

    if rendered_html:
        fallback_jobs: list[dict[str, Any]] = []

        if not api_quality_ok:
            jsonld = _extract_jsonld_jobpostings(rendered_html)
            for j in jsonld:
                parsed = _parse_jsonld_jobposting(j)
                if parsed.get("title"):
                    fallback_jobs.append(
                        normalize_job_payload(
                            {
                                "job_id": parsed.get("job_id"),
                                "title": parsed.get("title"),
                                "location": parsed.get("location"),
                                "description": parsed.get("description"),
                                "apply_url": parsed.get("apply_url"),
                            },
                            company,
                            "playwright-jsonld",
                        )
                    )

        if not fallback_jobs and (not all_jobs or not api_had_location):
            ats = detect_ats(url, rendered_html)
            if ats:
                try:
                    ats_jobs = await crawl_ats_jobs(ats, company, keyword=keyword, location=location, page=page, limit=limit)
                    fallback_jobs.extend(ats_jobs)
                except Exception:
                    pass

        if not fallback_jobs and (not all_jobs or not api_had_location):
            from scrapers.crawlers.base import extract_jobs_from_html as extract_html
            html_jobs = extract_html(rendered_html, company=company, base_url=url)
            for j in html_jobs:
                if j.get("title") and re.search(
                    r"(?:/job(?:s|detail)?/|/requisition/|/position/|/opening/|jobId=|requisitionId=)",
                    j.get("url", ""),
                    re.IGNORECASE,
                ):
                    fallback_jobs.append(normalize_job_payload(j, company, "playwright-html"))

        if fallback_jobs:
            seen_titles = set((j.get("title") or "").strip().lower() for j in all_jobs)
            for j in fallback_jobs:
                t = (j.get("title") or "").strip().lower()
                if t and t not in seen_titles:
                    seen_titles.add(t)
                    all_jobs.append(j)

    _ui_label_re = re.compile(
        r"^(?:saved\s*)?jobs?(?:\s+\d+)?$|^\d+\s*locations?$|^location$|^company$|"
        r"^department$|^category$|^workplace$|^type$|^all$|^clear$|"
        r"^filter|^sort\s+by|^results?$|^showing\b|^page\b|^prev|^next|^load\s+more|"
        r"^sign\s+in|^log\s+in|^register|^create\s+account|^latest\s+vacancies?|"
        r"^[a-z]+@[a-z]+\.[a-z]+$",
        re.IGNORECASE,
    )
    _pure_number_re = re.compile(r"^\d+$")
    all_jobs = [
        j for j in all_jobs
        if not _ui_label_re.match((j.get("title") or "").strip())
           and not _pure_number_re.match((j.get("title") or "").strip())
    ]

    return all_jobs[:limit]


def _is_expired(job: dict[str, Any]) -> bool:
    blob = (job.get("title", "") + " " + job.get("description", "")).lower()
    if any(k in blob for k in ("expired", "closed", "no longer accepting", "position filled", "removed")):
        return True
    valid_through = (job.get("valid_through") or "").strip()
    if valid_through:
        from datetime import date, datetime
        try:
            expires = datetime.fromisoformat(valid_through.replace("Z", "+00:00")).date()
            if expires < date.today():
                return True
        except ValueError:
            return False
    return False


def _normalize_universal_output(jobs: list[dict[str, Any]], *, company: str, careers_url: str) -> list[dict[str, Any]]:
    normalized_jobs: list[dict[str, Any]] = []
    for job in jobs:
        apply_url = job.get("url") or job.get("apply_url") or careers_url
        if apply_url and not apply_url.startswith("http"):
            apply_url = urljoin(careers_url, apply_url)
        normalized = {
            "title": job.get("title", ""),
            "company": job.get("company") or company.title(),
            "location": job.get("location", ""),
            "description": job.get("description", ""),
            "url": apply_url,
            "posted_date": job.get("posted_date", ""),
            "job_id": job.get("job_id", ""),
            "apply_url": apply_url,
            "skills": job.get("skills", []),
            "employment_type": job.get("employment_type", ""),
            "experience": job.get("experience", ""),
            "source": job.get("source", "universal"),
        }
        if job.get("valid_through"):
            normalized["valid_through"] = job["valid_through"]
        if normalized["title"] and not _is_expired(normalized):
            normalized_jobs.append(normalized)
    return normalized_jobs


async def _crawl_amazon_jobs(
    careers_url: str,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int = 20,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    qp: dict[str, Any] = {"result_limit": AMAZON_MAX_PER_PAGE}
    if keyword:
        qp["base_query"] = keyword
    if location:
        qp["location[]"] = location

    sep = "&" if "?" in careers_url else "?"
    build_url = lambda **extra: careers_url + sep + "&".join(f"{k}={v}" for k, v in {**qp, **extra}.items())

    headers = _default_headers()

    def _try_parse(resp: str) -> dict | None:
        try:
            return json.loads(resp)
        except (ValueError, TypeError):
            return None

    html = await _fetch_html(build_url(), headers=headers, client=client)
    payload = _try_parse(html)
    if payload is None:
        logger.warning("Amazon jobs API returned non-JSON (rate-limited or busy)")
        return []

    total_hits = int(payload.get("hits", 0))
    all_jobs_data = list(payload.get("jobs") or [])

    offsets = list(range(AMAZON_MAX_PER_PAGE, total_hits, AMAZON_MAX_PER_PAGE))
    for o in offsets:
        await asyncio.sleep(0.25 + random.random() * 0.15)
        page_html = await _fetch_html(build_url(offset=o), headers=headers, client=client)
        page_payload = _try_parse(page_html)
        if page_payload is not None:
            all_jobs_data.extend(page_payload.get("jobs") or [])

    jobs = []
    for j in all_jobs_data:
        job_path = j.get("job_path", "")
        jobs.append({
            "title": j.get("title"),
            "location": j.get("location") or "",
            "city": j.get("city") or "",
            "country": j.get("country_code") or "",
            "job_id": str(j.get("id", "")),
            "url": urljoin(AMAZON_JOBS_DOMAIN, job_path) if job_path else "",
            "apply_url": urljoin(AMAZON_JOBS_DOMAIN, job_path) if job_path else "",
            "description": (j.get("description_short") or "").strip(),
            "posted_date": j.get("posted_date"),
            "source": "amazon",
        })

    start = (page - 1) * limit
    return jobs[start:start + limit]


WIPRO_JOBS_API = "https://careers.wipro.com/services/recruiting/v1/jobs"


async def _crawl_wipro_jobs(
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int = 20,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )

    all_jobs: list[dict[str, Any]] = []

    if client is None:
        client = httpx.AsyncClient(headers={"User-Agent": ua}, follow_redirects=True, timeout=15)

    # Get session cookie (shared client persists cookies for subsequent POST requests)
    await client.get("https://careers.wipro.com/viewalljobs/?locale=en_US")

    target_page_count = max(page + 2, (limit // 10) + 2)

    for page_num in range(target_page_count):
        payload = {
            "locale": "en_US",
            "pageNumber": page_num,
            "keywords": keyword or "",
            "location": location or "",
            "facetFilters": {},
        }

        try:
            r = await client.post(WIPRO_JOBS_API, json=payload)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.warning("Wipro API page %d failed: %s", page_num, exc)
            break

        results = data.get("jobSearchResult", [])
        for item in results:
            j = item.get("response", {})
            job_id = (j.get("id") or "").strip()
            title = (j.get("unifiedStandardTitle") or j.get("urlTitle") or "").strip()
            if not title or not job_id:
                continue

            url_title = j.get("unifiedUrlTitle") or j.get("urlTitle") or title.lower().replace(" ", "-")
            city = (j.get("sfstd_jobLocation_obj") or [""])[0]
            state = (j.get("jobLocationState") or [""])[0]
            country = (j.get("jobLocationCountry") or [""])[0]
            location_parts = [p for p in (city, state, country) if p]
            location_str = ", ".join(location_parts) if location_parts else ""

            posted = (j.get("unifiedStandardStart") or "").strip()
            valid_through = (j.get("unifiedStandardEnd") or "").strip()
            apply_url = f"https://careers.wipro.com/{job_id}/{url_title}/job"

            all_jobs.append({
                "title": title,
                "company": "Wipro",
                "location": location_str,
                "description": "",
                "url": apply_url,
                "apply_url": apply_url,
                "job_id": job_id,
                "posted_date": posted,
                "valid_through": valid_through,
                "skills": [],
                "source": "wipro-api",
            })

        if len(results) < 10:
            break

    start = max(page - 1, 0) * limit
    return all_jobs[start:start + limit]


async def universal_crawl_jobs(
    *,
    company_name: str,
    company_url: str | None = None,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int = 20,
    use_playwright: bool = False,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )

    if use_playwright:
        if not company_url:
            from scrapers.directory import careers_url
            company_url = careers_url(company_name.lower())
        target_url = company_url or f"https://{company_name.replace(' ', '')}.com/careers"
        pw_jobs = await _extract_jobs_with_playwright(
            target_url,
            company_name,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
        )
        pw_jobs = _normalize_universal_output(pw_jobs, company=company_name, careers_url=target_url)
        pw_jobs = _dedupe_jobs(pw_jobs)

        def _is_category_item(j):
            u = (j.get("url") or j.get("apply_url") or "").strip()
            if j.get("location") or j.get("job_id"):
                return False
            if not u or u == target_url:
                return True
            path = urlparse(u).path.lower()
            if any(p in path for p in ("/job/", "/jobs/", "/detail/", "/position/", "/requisition/", "/opening/", "/apply/")):
                return False
            return True

        real_jobs = [j for j in pw_jobs if not _is_category_item(j)]
        logger.info("Playwright extracted %d raw items, %d real jobs for %s", len(pw_jobs), len(real_jobs), company_name)

        if real_jobs:
            missing_fields = [j for j in real_jobs if not j.get("location") or not j.get("description")]
            for j in missing_fields[:5]:
                detail_url = j.get("url") or j.get("apply_url") or ""
                if not detail_url or not detail_url.startswith("http"):
                    continue
                try:
                    async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": ua}, timeout=10) as cl:
                        resp = await cl.get(detail_url)
                        if resp.status_code == 200:
                            html_body = resp.text
                            jsonld = _extract_jsonld_jobpostings(html_body)
                            for ld in jsonld:
                                parsed = _parse_jsonld_jobposting(ld)
                                if parsed.get("title", "").strip().lower() == j.get("title", "").strip().lower()[:30]:
                                    if not j.get("location") and parsed.get("location"):
                                        j["location"] = parsed["location"]
                                    if not j.get("description") and parsed.get("description"):
                                        j["description"] = parsed["description"]
                                    if not j.get("job_id") and parsed.get("job_id"):
                                        j["job_id"] = parsed["job_id"]
                                    break
                            if not j.get("description") or not j.get("location"):
                                html_jobs = extract_jobs_from_html(html_body, company=company_name, base_url=detail_url)
                                for hj in html_jobs:
                                    if hj.get("title", "").strip().lower()[:20] == j.get("title", "").strip().lower()[:20]:
                                        if not j.get("location") and hj.get("location"):
                                            j["location"] = hj["location"]
                                        if not j.get("description") and hj.get("description"):
                                            j["description"] = hj["description"]
                                        break
                except Exception:
                    pass

        cat_link_candidates = []
        for j in pw_jobs:
            u = (j.get("url") or j.get("apply_url") or "").strip()
            if not u or u == target_url or u.startswith("mailto:"):
                continue
            if urlparse(u).netloc.lower() != urlparse(target_url).netloc.lower():
                continue
            if u not in cat_link_candidates:
                cat_link_candidates.append(u)
        if not real_jobs and cat_link_candidates:
            if keyword:
                kw = keyword.lower()
                cat_link_candidates.sort(key=lambda u: 0 if kw in u.lower() else 1)
            for cl in cat_link_candidates[:2]:
                logger.info("Playwright following category link: %s", cl)
                await asyncio.sleep(0.3)
                sub = await _extract_jobs_with_playwright(cl, company_name, keyword=keyword, location=location, page=page, limit=limit)
                if sub:
                    sub = _normalize_universal_output(sub, company=company_name, careers_url=cl)
                    sub = _dedupe_jobs(sub)
                    real_sub = [j for j in sub if not _is_category_item(j)]
                    if real_sub:
                        real_jobs.extend(real_sub)
                        break

        def _location_matches(flt: str, job_loc: str) -> bool:
            flt_lower, job_lower = flt.lower().strip(), job_loc.lower().strip()
            if flt_lower in job_lower:
                return True
            flt_words = set(flt_lower.replace(",", "").split())
            job_words = set(job_lower.replace(",", "").split())
            if flt_words & job_words:
                return True
            _abbrevs: dict[str, str] = {}
            for country, code in (
                ("india", "in"), ("germany", "de"), ("france", "fr"), ("spain", "es"),
                ("italy", "it"), ("netherlands", "nl"), ("belgium", "be"), ("switzerland", "ch"),
                ("sweden", "se"), ("norway", "no"), ("denmark", "dk"), ("finland", "fi"),
                ("austria", "at"), ("poland", "pl"), ("portugal", "pt"), ("ireland", "ie"),
                ("japan", "jp"), ("china", "cn"), ("australia", "au"), ("canada", "ca"),
                ("brazil", "br"), ("mexico", "mx"), ("singapore", "sg"), ("malaysia", "my"),
                ("united states", "us"), ("usa", "us"), ("united kingdom", "uk"), ("uk", "gb"),
            ):
                _abbrevs[country] = code
            code = _abbrevs.get(flt_lower)
            if code and code in job_words:
                return True
            return False

        filtered: list[dict[str, Any]] = []
        candidate_pool = real_jobs if real_jobs else [j for j in pw_jobs if not _is_category_item(j)]
        for j in candidate_pool:
            if _is_expired(j):
                continue
            if location and not _location_matches(location, j.get("location", "")):
                if j.get("location"):
                    continue
            if keyword:
                k = keyword.lower()
                if k not in (j.get("title", "") or "").lower() and k not in (j.get("description", "") or "").lower():
                    continue
            filtered.append(j)
        return filtered[:limit]

    jobs: list[dict[str, Any]] = []

    async with shared_httpx_client(
        headers={"User-Agent": ua},
        timeout=30,
    ) as _own_client:
        client = client or _own_client

        company_base_url, careers_url = await _resolve_careers_page(
            company_name=company_name, company_url=company_url, client=client,
        )

        direct_ats = detect_ats(careers_url, "")
        if direct_ats:
            try:
                jobs = await crawl_ats_jobs(
                    direct_ats,
                    company=company_name,
                    keyword=keyword,
                    location=location,
                    page=page,
                    limit=limit,
                    client=client,
                )
                return _dedupe_jobs(_normalize_universal_output(jobs, company=company_name, careers_url=careers_url))[:limit]
            except Exception as exc:
                logger.warning("Direct ATS crawl failed for %s (%s): %s", company_name, careers_url, exc)

        headers = _default_headers()
        await asyncio.sleep(0.15 + random.random() * 0.15)

        is_amazon = "amazon" in _host(careers_url)
        if is_amazon and _looks_like_json_api_url(careers_url):
            jobs = await _crawl_amazon_jobs(
                careers_url,
                keyword=keyword,
                location=location,
                page=page,
                limit=limit,
                client=client,
            )
            return _dedupe_jobs(_normalize_universal_output(jobs, company=company_name, careers_url=careers_url))

        is_wipro = "wipro" in _host(careers_url) or company_name.strip().lower() == "wipro"
        if is_wipro:
            jobs = await _crawl_wipro_jobs(
                keyword=keyword,
                location=location,
                page=page,
                limit=limit,
                client=client,
            )
            return _dedupe_jobs(_normalize_universal_output(jobs, company=company_name, careers_url=careers_url))

        fetch_url = careers_url
        if _looks_like_json_api_url(careers_url):
            qp: dict[str, Any] = {}
            if keyword:
                qp["query"] = keyword
            if location:
                qp["location"] = location
            if page > 1:
                qp["page"] = page
            if limit:
                qp["limit"] = limit
            if qp:
                sep = "&" if "?" in fetch_url else "?"
                fetch_url = fetch_url + sep + "&".join(f"{k}={v}" for k, v in qp.items())

        try:
            html = await _fetch_html(fetch_url, headers=headers, client=client)
        except Exception as exc:
            logger.warning("Universal crawler could not fetch careers page for %s (%s): %s", company_name, careers_url, exc)
            ats = detect_ats(careers_url, "")
            if not ats:
                return []
            try:
                jobs = await crawl_ats_jobs(
                    ats,
                    company=company_name,
                    keyword=keyword,
                    location=location,
                    page=page,
                    limit=limit,
                    client=client,
                )
                return _dedupe_jobs(_normalize_universal_output(jobs, company=company_name, careers_url=careers_url))[:limit]
            except Exception as ats_exc:
                logger.warning("ATS direct fallback failed for %s (%s): %s", company_name, careers_url, ats_exc)
                return []

        try:
            payload = json.loads(html)
            logger.info("Careers URL returned JSON for %s — extracting directly", company_name)
            jobs = await _extract_jobs_from_json_payload(payload, company_name, "json-api")
            return _dedupe_jobs(_normalize_universal_output(jobs, company=company_name, careers_url=careers_url))[:limit]
        except (ValueError, TypeError):
            pass

        ats = detect_ats(careers_url, html)
        if ats:
            try:
                jobs = await crawl_ats_jobs(
                    ats,
                    company=company_name,
                    keyword=keyword,
                    location=location,
                    page=page,
                    limit=limit,
                    client=client,
                )
                if jobs:
                    filtered = _normalize_universal_output(jobs, company=company_name, careers_url=careers_url)
                    return _dedupe_jobs(filtered)[:limit]
            except Exception as exc:
                logger.warning("ATS crawl failed for %s (%s). Falling back. Err=%s", company_name, careers_url, exc)

        if not jobs:
            jobs = await _try_graphql_and_openapi_discovery(
                company=company_name,
                careers_url=careers_url,
                company_base_url=company_base_url,
                keyword=keyword,
                location=location,
                client=client,
            )

        if not jobs:
            jobs = await _fetch_jobs_from_candidate_apis(
                company=company_name,
                careers_url=careers_url,
                company_base_url=company_base_url,
                html=html,
                keyword=keyword,
                location=location,
                client=client,
            )
        if not jobs:
            jobs = await _extract_jobs_by_fallback(
                company=company_name,
                careers_url=careers_url,
                company_base_url=company_base_url,
                html=html,
                client=client,
            )

        if jobs:
            jobs = await _chain_enrich_jobs_from_possible_details(
                jobs=jobs,
                company=company_name,
                careers_url=careers_url,
                company_base_url=company_base_url,
                html=html,
                keyword=keyword,
                location=location,
                max_secondary_per_page=5,
                client=client,
            )

        if not jobs:
            logger.info("HTML extraction yielded no jobs for %s — trying Playwright render", company_name)
            pw_jobs = await _extract_jobs_with_playwright(
                careers_url,
                company_name,
                keyword=keyword,
                location=location,
                page=page,
                limit=limit,
            )
            if pw_jobs:
                logger.info("Playwright found %d jobs for %s", len(pw_jobs), company_name)

                def _is_category_item(j):
                    u = (j.get("url") or j.get("apply_url") or "").strip()
                    if j.get("location") or j.get("job_id"):
                        return False
                    if not u or u == careers_url:
                        return True
                    path = urlparse(u).path.lower()
                    if any(p in path for p in ("/job/", "/jobs/", "/detail/", "/position/", "/requisition/", "/opening/", "/apply/")):
                        return False
                    return True

                jobs = [j for j in pw_jobs if not _is_category_item(j)]
                logger.info("Playwright yielded %d real jobs for %s after filtering", len(jobs), company_name)

        if page > 1:
            pagination_pattern = detect_pagination(careers_url, html, None)
            if pagination_pattern:
                paginated_url = pagination_pattern.next_url(careers_url, page)
                await asyncio.sleep(0.1 + random.random() * 0.1)
                try:
                    page_html = await _fetch_html(paginated_url, headers=headers, client=client)
                except Exception:
                    pagination_pattern = None
                if pagination_pattern:
                    more = await _fetch_jobs_from_candidate_apis(
                        company=company_name,
                        careers_url=paginated_url,
                        company_base_url=company_base_url,
                        html=page_html,
                        keyword=keyword,
                        location=location,
                        client=client,
                    )
                    if not more:
                        more = await _extract_jobs_by_fallback(company=company_name, careers_url=paginated_url, company_base_url=company_base_url, html=page_html, client=client)
                    if more:
                        jobs.extend(more)
            if not pagination_pattern:
                params_to_try = [
                    {"page": page},
                    {"p": page},
                    {"offset": (page - 1) * 20},
                    {"start": (page - 1) * 20},
                    {"cursor": page},
                ]
                for qp in params_to_try:
                    try_url = careers_url
                    sep = "?" if "?" not in try_url else "&"
                    try_url = try_url + sep + "&".join([f"{k}={v}" for k, v in qp.items()])
                    await asyncio.sleep(0.1 + random.random() * 0.1)
                    try:
                        page_html = await _fetch_html(try_url, headers=headers, client=client)
                    except Exception:
                        continue
                    more = await _fetch_jobs_from_candidate_apis(
                        company=company_name,
                        careers_url=try_url,
                        company_base_url=company_base_url,
                        html=page_html,
                        keyword=keyword,
                        location=location,
                        client=client,
                    )
                    if not more:
                        more = await _extract_jobs_by_fallback(company=company_name, careers_url=try_url, company_base_url=company_base_url, html=page_html, client=client)
                    jobs.extend(more)
                    if len(_dedupe_jobs(jobs)) >= limit:
                        break

        jobs = _dedupe_jobs(_normalize_universal_output(jobs, company=company_name, careers_url=careers_url))

        out: list[dict[str, Any]] = []
        for j in jobs:
            if _is_expired(j):
                continue
            if location and location.lower() not in (j.get("location", "") or "").lower():
                if j.get("location"):
                    continue

            if keyword:
                k = keyword.lower()
                if k not in (j.get("title", "") or "").lower() and k not in (j.get("description", "") or "").lower():
                    continue
            out.append(j)

        start = max(page - 1, 0) * limit
        return out[start : start + limit]
