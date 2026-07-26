from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from scrapers.crawlers.base import (
    collect_job_candidates,
    crawl_ats_jobs,
    detect_ats,
    extract_jobs_from_html,
    normalize_job_payload,
    request_json_with_retries,
    request_with_retries,
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

_KNOWN_COMPANY_CAREERS_URLS = {
    "accenture": "https://www.accenture.com/in-en/careers/jobsearch",
    "amazon": "https://www.amazon.jobs/en/search.json",
    "cognizant": "https://careers.cognizant.com/global-en/jobs/",
    "google": "https://www.google.com/about/careers/applications/jobs/results/",
    "infosys": "https://career.infosys.com/joblist",

    "jp morgan": "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions",
    "jpmorgan": "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions",
    "j.p. morgan": "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions",
    "jpm": "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions",

    "mastercard": "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers",

    "tcs": "https://www.tcs.com/careers",
    "tca": "https://www.tcs.com/careers",

    "wipro": "https://careers.wipro.com/viewalljobs/?locale=en_US",

    "kpmg": "https://kpmg.wd5.myworkdayjobs.com/KPMG_External_Careers",
    "kpmg jp": "https://kpmg.wd5.myworkdayjobs.com/KPMG_External_Careers",

    "zoho": "https://www.zoho.com/careers/",
}


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
    api_terms = ("/api/", "/graphql", "/services/", "/rest/", "/wday/cxs/", "/posting-api/", "/requisitions")
    return any(term in path for term in api_terms) or any(term.strip("/") in query for term in api_terms)


async def _fetch_html(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0) -> str:
    return await request_with_retries(url, headers=headers, timeout=timeout)


async def _get_homepage_html(company_url: str) -> tuple[str, str]:
    headers = _default_headers()
    html = await _fetch_html(company_url, headers=headers)
    return company_url, html


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
    if not apply_url:
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
    out: list[dict[str, Any]] = []
    for j in jobs:
        job_id = (j.get("job_id") or "").strip()
        url = (j.get("url") or j.get("apply_url") or "").strip()
        title = (j.get("title") or "").strip().lower()
        location = (j.get("location") or "").strip().lower()
        key = f"{j.get('company','').strip().lower()}|{job_id or url or title + '|' + location}"
        if not key or key in seen:
            continue
        seen.add(key)
        if not j.get("url") and j.get("apply_url"):
            j["url"] = j.get("apply_url")
        out.append(j)
    return out


def _common_careers_candidates(company_name: str) -> list[str]:
    slug = _slugify_company_name(company_name)
    if not slug:
        return []
    normalized_name = _clean_text(company_name).lower()
    known_url = _KNOWN_COMPANY_CAREERS_URLS.get(normalized_name) or _KNOWN_COMPANY_CAREERS_URLS.get(slug)
    if not known_url:
        normalized_no_dots = normalized_name.replace(".", "")
        known_url = _KNOWN_COMPANY_CAREERS_URLS.get(normalized_no_dots)

    candidates = [
        f"https://careers.{slug}.com",
        f"https://jobs.{slug}.com",
        f"https://{slug}.com/careers",
        f"https://{slug}.com/jobs",
        f"https://{slug}.com",
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
    for href in _extract_anchor_urls(html):
        abs_url = urljoin(base_url, href)
        if abs_url.startswith("http") and _looks_like_careers_url(abs_url):
            candidates.append(abs_url)

    official = [c for c in candidates if _is_allowed_source_url(c, company_base_url)]
    official.sort(key=lambda u: ("/careers" not in u.lower(), "/jobs" not in u.lower(), len(u)))
    return official


async def _first_fetchable_careers_candidate(
    candidates: list[str],
    *,
    company_base_url: str,
    headers: dict[str, str],
) -> tuple[str, str | None]:
    for candidate in candidates:
        if _is_unofficial_job_board(candidate) or not _is_allowed_source_url(candidate, company_base_url):
            continue
        if any(_host(candidate) == domain or _host(candidate).endswith("." + domain) for domain in _ALLOWED_ATS_DOMAINS):
            return candidate, None
        try:
            html = await _fetch_html(candidate, headers=headers, timeout=12.0)
        except Exception as exc:
            logger.info("Careers candidate failed for %s: %s", candidate, exc)
            continue
        official = _extract_official_career_links(html, base_url=candidate, company_base_url=company_base_url)
        return (official[0], None) if official else (candidate, html)
    return "", None


async def _resolve_careers_page(*, company_name: str, company_url: str | None) -> tuple[str, str]:
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
            html = await _fetch_html(company_base, headers=headers)
        except Exception as exc:
            logger.warning("Failed fetching company base for %s (%s): %s", company_name, company_base, exc)
            careers_url, _ = await _first_fetchable_careers_candidate(
                _careers_candidates_from_base(company_base),
                company_base_url=company_base,
                headers=headers,
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
        )
        return company_base, careers_url or urljoin(company_base + "/", "careers")

    normalized_name = _clean_text(company_name).lower()
    slug = _slugify_company_name(company_name)
    known_url = _KNOWN_COMPANY_CAREERS_URLS.get(normalized_name) or _KNOWN_COMPANY_CAREERS_URLS.get(slug)
    if known_url:
        known_base = known_url[:known_url.index("/", 8)] if known_url.startswith("http") and "/" in known_url[8:] else known_url
        return known_base, known_url

    name = company_name.strip()
    if name.startswith("http"):
        return await _resolve_careers_page(company_name=company_name, company_url=name)

    if "." in name and " " not in name:
        return await _resolve_careers_page(company_name=company_name, company_url=name)

    if not slug:
        raise ValueError("Unable to resolve company URL")

    company_base = f"https://{slug}.com"
    careers_url, _ = await _first_fetchable_careers_candidate(
        _common_careers_candidates(name),
        company_base_url=company_base,
        headers=headers,
    )
    return company_base, careers_url or urljoin(company_base + "/", "careers")


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
                payload = await request_json_with_retries(detail_url, headers=headers, timeout=12.0)
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
    candidate_apis = _extract_candidate_api_urls(html, careers_url, company_base_url)[:5]

    for api_url in candidate_apis:
        await asyncio.sleep(0.1 + random.random() * 0.15)
        if any(term in api_url.lower() for term in ("captcha", "cloudflare", "turnstile")):
            logger.info("Restricted due to likely block for %s: %s", company, api_url)
            break

        try:
            payload = await request_json_with_retries(api_url, headers=headers, timeout=15.0)
        except Exception:
            continue

        extracted = await _extract_jobs_from_json_payload(payload, company, "json-api") if payload is not None else []

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


async def _extract_jobs_by_fallback(company: str, careers_url: str, company_base_url: str, html: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []

    for href in _extract_anchor_urls(html):
        candidate = _job_from_search_result_url(href, company=company, base_url=careers_url)
        if candidate and _is_allowed_source_url(candidate["url"], company_base_url):
            jobs.append(candidate)

    for payload in _extract_embedded_json(html):
        for job in await _extract_jobs_from_json_payload(payload, company, "embedded-json"):
            apply_url = job.get("apply_url") or ""
            if apply_url and not apply_url.startswith("http"):
                job["apply_url"] = urljoin(careers_url, apply_url)
                apply_url = job["apply_url"]
            if apply_url and not _is_allowed_source_url(apply_url, company_base_url):
                continue
            jobs.append(job)

    if not jobs:
        jobs_from_html = extract_jobs_from_html(html, company=company, base_url=careers_url)
        for j in jobs_from_html:
            if not j.get("apply_url"):
                j["apply_url"] = j.get("url", "")
            if j.get("url") and not _is_allowed_source_url(j["url"], company_base_url):
                continue
            jobs.append(
                {
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
                }
            )

    if not jobs:
        jsonld = _extract_jsonld_jobpostings(html)
        for j in jsonld:
            parsed = _parse_jsonld_jobposting(j)
            if not parsed.get("title"):
                continue
            apply_url = parsed.get("apply_url") or ""
            if apply_url and not _is_allowed_source_url(urljoin(careers_url, apply_url), company_base_url):
                continue
            job_id = parsed.get("job_id") or ""
            normalized = normalize_job_payload(
                {
                    "job_id": job_id,
                    "title": parsed.get("title"),
                    "location": parsed.get("location"),
                    "description": parsed.get("description"),
                    "apply_url": urljoin(careers_url, apply_url) if apply_url else careers_url,
                    "employment_type": "",
                    "experience": "",
                    "skills": [],
                },
                company,
                "jsonld",
            )
            normalized["posted_date"] = parsed.get("posted_date", "")
            normalized["valid_through"] = parsed.get("valid_through", "")
            jobs.append(normalized)

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
    rendered_html: str | None = None

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
                            api_responses.append(body)
                    except Exception:
                        pass

            page_obj.on("response", handle_response)

            await page_obj.goto(url, wait_until="networkidle", timeout=30000)
            await page_obj.wait_for_timeout(2000)

            rendered_html = await page_obj.content()
            await browser.close()
    except Exception as exc:
        logger.warning("Playwright extraction failed for %s: %s", url, exc)
        return []

    all_jobs: list[dict[str, Any]] = []

    for payload in api_responses:
        extracted = await _extract_jobs_from_json_payload(payload, company, "playwright-api")
        for job in extracted:
            if job.get("title"):
                all_jobs.append(job)

    if not all_jobs and rendered_html:
        ats = detect_ats(url, rendered_html)
        if ats:
            try:
                jobs = await crawl_ats_jobs(ats, company, keyword=keyword, location=location, page=page, limit=limit)
                all_jobs.extend(jobs)
            except Exception:
                pass
        if not all_jobs:
            from scrapers.crawlers.base import extract_jobs_from_html as extract_html

            html_jobs = extract_html(rendered_html, company=company, base_url=url)
            for j in html_jobs:
                if j.get("title"):
                    all_jobs.append(normalize_job_payload(j, company, "playwright-html"))

        if not all_jobs:
            jsonld = _extract_jsonld_jobpostings(rendered_html)
            for j in jsonld:
                parsed = _parse_jsonld_jobposting(j)
                if parsed.get("title"):
                    all_jobs.append(
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

    html = await _fetch_html(build_url(), headers=headers)
    payload = _try_parse(html)
    if payload is None:
        logger.warning("Amazon jobs API returned non-JSON (rate-limited or busy)")
        return []

    total_hits = int(payload.get("hits", 0))
    all_jobs_data = list(payload.get("jobs") or [])

    offsets = list(range(AMAZON_MAX_PER_PAGE, total_hits, AMAZON_MAX_PER_PAGE))
    for o in offsets:
        await asyncio.sleep(0.25 + random.random() * 0.15)
        page_html = await _fetch_html(build_url(offset=o), headers=headers)
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
) -> list[dict[str, Any]]:
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )

    all_jobs: list[dict[str, Any]] = []

    async with httpx.AsyncClient(headers={"User-Agent": ua}, follow_redirects=True, timeout=15) as c:
        # Get session cookie
        await c.get("https://careers.wipro.com/viewalljobs/?locale=en_US")

        api_headers = {
            "User-Agent": ua,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cookie": "; ".join(f"{k}={v}" for k, v in c.cookies.items()),
        }

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
                r = await c.post(WIPRO_JOBS_API, json=payload, headers=api_headers)
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
) -> list[dict[str, Any]]:
    company_base_url, careers_url = await _resolve_careers_page(company_name=company_name, company_url=company_url)

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
        )
        return _dedupe_jobs(_normalize_universal_output(jobs, company=company_name, careers_url=careers_url))

    is_wipro = "wipro" in _host(careers_url) or company_name.strip().lower() == "wipro"
    if is_wipro:
        jobs = await _crawl_wipro_jobs(
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
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
        html = await _fetch_html(fetch_url, headers=headers)
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
            )
            filtered = _normalize_universal_output(jobs, company=company_name, careers_url=careers_url)
            return _dedupe_jobs(filtered)[:limit]
        except Exception as exc:
            logger.warning("ATS crawl failed for %s (%s). Falling back. Err=%s", company_name, careers_url, exc)

    jobs = await _fetch_jobs_from_candidate_apis(
        company=company_name,
        careers_url=careers_url,
        company_base_url=company_base_url,
        html=html,
        keyword=keyword,
        location=location,
    )
    if not jobs:
        jobs = await _extract_jobs_by_fallback(
            company=company_name,
            careers_url=careers_url,
            company_base_url=company_base_url,
            html=html,
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
            jobs = pw_jobs

    if page > 1:
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
                page_html = await _fetch_html(try_url, headers=headers)
            except Exception:
                continue
            more = await _fetch_jobs_from_candidate_apis(
                company=company_name,
                careers_url=try_url,
                company_base_url=company_base_url,
                html=page_html,
                keyword=keyword,
                location=location,
            )
            if not more:
                more = await _extract_jobs_by_fallback(company=company_name, careers_url=try_url, company_base_url=company_base_url, html=page_html)
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
