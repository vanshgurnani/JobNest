from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

# Ensure workspace root is on sys.path (must be before local package imports)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.crawlers.base import request_with_retries, shared_httpx_client

from app.schemas.job import canonicalize_job
from scrapers.crawlers.orchestrator import crawl_jobs
from scrapers.utils import company_name_from_url, detect_ats, sanitize_url, supported_companies

LOGGER = logging.getLogger("scrapers.scrape_jobs")


def _parse_company_list(value: str | None) -> list[str]:
    if not value or value.strip().lower() == "all":
        return supported_companies()
    companies = [part.strip().lower() for part in value.split(",") if part.strip()]
    known = set(supported_companies())
    for c in companies:
        if c not in known:
            LOGGER.warning(
                "Company '%s' is not a seeded company. The scraper will auto-discover its "
                "careers page and detect its ATS at runtime.",
                c,
            )
    return companies


def _parse_url_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _format_jobs_preview(jobs: list[dict[str, Any]]) -> str:
    preview = []
    for idx, job in enumerate(jobs[:4], start=1):
        preview.append({
            "index": idx,
            "id": job.get("id") or job.get("job_id"),
            "company": job.get("company"),
            "title": job.get("title"),
            "location": job.get("location"),
            "apply_url": job.get("apply_url") or job.get("url"),
            "source": job.get("source"),
        })
    return json.dumps(preview, indent=2, ensure_ascii=False)


async def _push_to_db(jobs: list[dict[str, Any]]) -> int:
    """Persist scraped jobs to MongoDB (mirrors POST /push-to-db)."""
    if not jobs:
        return 0
    try:
        from app.db.mongo import connect_mongo, close_mongo
        from app.services.job_store import upsert_jobs

        await connect_mongo()
        await upsert_jobs(jobs)
        await close_mongo()
        return len(jobs)
    except Exception as exc:
        LOGGER.exception("Failed to push %d jobs to the database: %s", len(jobs), exc)
        return 0


class GenericScraper:
    def __init__(self, company: str = "") -> None:
        self.company = company
        self.logger = logging.getLogger("scrapers.scrape_jobs.GenericScraper")

    async def fetch_jobs(
        self,
        url: str,
        keyword: str | None = None,
        location: str | None = None,
        page: int = 1,
        limit: int = 20,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, Any]]:
        fetch_url = _build_page_url(url, page) if page > 1 else url
        html: str | None = None
        try:
            html = await request_with_retries(fetch_url, client=client)
        except Exception as exc:
            self.logger.warning("GenericScraper failed to fetch %s: %s", fetch_url, exc)
            return []

        # Lazy imports to avoid circular deps and keep universal.py untouched
        from scrapers.crawlers.universal import (
            _dedupe_jobs,
            _extract_embedded_json,
            _extract_jsonld_jobpostings,
            _parse_jsonld_jobposting,
        )
        from scrapers.crawlers.base import extract_jobs_from_html, _crawl_phenom

        company_name = self.company or _company_name_from_url(url)
        all_jobs: list[dict[str, Any]] = []
        seen_titles: set[str] = set()

        # 0 — If page is a Phenom SPA (data-ph-id or phenompeople CDN), use sitemap-based approach
        if "data-ph-id" in html or "phenompeople.com" in html:
            phenom_jobs = await _crawl_phenom(url, company_name, keyword=keyword, location=location, page=page, limit=limit, client=client)
            if phenom_jobs:
                return _slice_and_filter(phenom_jobs, keyword, location, page, limit)

        # 1 — JSON-LD (structured data, e.g. Apple, Google, etc.)
        jsonld_items = _extract_jsonld_jobpostings(html)
        for item in jsonld_items:
            parsed = _parse_jsonld_jobposting(item)
            title = (parsed.get("title") or "").strip()
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())
            all_jobs.append({
                "title": title,
                "company": parsed.get("company") or company_name.title(),
                "location": parsed.get("location", ""),
                "description": parsed.get("description", ""),
                "apply_url": parsed.get("apply_url", url),
                "url": parsed.get("apply_url", url),
                "job_id": parsed.get("job_id", ""),
                "posted_date": parsed.get("posted_date", ""),
                "skills": [],
                "employment_type": "",
                "experience": "",
                "source": "generic-jsonld",
            })

        # 2 — Embedded JSON (e.g. Next.js __NEXT_DATA__, Gatsby)
        embedded_payloads = _extract_embedded_json(html)
        for payload in embedded_payloads:
            for candidate in _collect_job_candidates(payload):
                title = (_pick(candidate, "title", "name", "jobTitle", "role") or "").strip()
                if not title or not _looks_like_job_title(title):
                    continue
                if title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                all_jobs.append({
                    "title": title,
                    "company": company_name.title(),
                    "location": (_pick(candidate, "location", "city", "workLocation") or ""),
                    "description": (_pick(candidate, "description", "summary", "snippet") or ""),
                    "apply_url": (_pick(candidate, "url", "applyUrl", "apply_url", "link") or url),
                    "url": (_pick(candidate, "url", "applyUrl", "apply_url", "link") or url),
                    "job_id": (_pick(candidate, "id", "jobId", "job_id", "uuid") or ""),
                    "skills": (_pick(candidate, "skills", "technologies") or []),
                    "employment_type": (_pick(candidate, "employmentType", "type", "workType") or ""),
                    "experience": (_pick(candidate, "experience", "experienceLevel", "level") or ""),
                    "source": "generic-embedded",
                })

        # 3 — Anchor links (catches <a> tags with job-like hrefs/text)
        html_jobs = extract_jobs_from_html(html, company=company_name, base_url=url)
        # 3a — Extract location & description from search page HTML layout (Apple etc.)
        sp_map = _extract_search_page_metadata(html)
        for j in html_jobs:
            title = (j.get("title") or "").strip()
            if not title or not _looks_like_job_title(title):
                continue
            if title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())
            loc = j.get("location", "")
            if not loc:
                title_norm = title.lower().replace("&amp;", "&")
                for sp_title, sp_loc in sp_map:
                    st_lower = sp_title.lower().replace("&amp;", "&")
                    if st_lower and (title_norm in st_lower or st_lower in title_norm):
                        loc = sp_loc
                        break
            job_url = j.get("url", "") or ""
            all_jobs.append({
                "title": title,
                "company": company_name.title(),
                "location": loc,
                "description": j.get("description", ""),
                "apply_url": job_url,
                "url": job_url,
                "job_id": j.get("job_id", ""),
                "skills": j.get("skills", []),
                "employment_type": "",
                "experience": "",
                "source": "generic-anchor",
            })

        # 4 — BS4 heuristic (only if nothing found above)
        if not all_jobs:
            soup = BeautifulSoup(html, "lxml")
            heuristic_seen: set[str] = set()

            _JOB_TITLE_KEYWORDS = {
                "engineer", "developer", "analyst", "manager", "designer",
                "intern", "scientist", "specialist", "coordinator", "director",
                "architect", "consultant", "associate", "lead", "head",
                "vp", "vice president", "chief", "officer",
            }
            _SKIP_KEYWORDS = {"join", "search", "filter", "team", "culture", "life@", "sign in", "register", "submit"}

            _JOB_PATH_PATTERN = re.compile(
                r"/(?:job|career|position|requisition|opening|opportunity)s?\b",
                re.IGNORECASE,
            )

            for tag in soup.find_all(["h1", "h2", "h3", "h4", "a"]):
                text = tag.get_text(strip=True)
                if not text or len(text) < 3 or len(text) > 200:
                    continue

                text_lower = text.lower()
                if any(sk in text_lower for sk in _SKIP_KEYWORDS):
                    continue
                if text_lower in heuristic_seen:
                    continue

                href = (tag.get("href") or "") if tag.name == "a" else ""
                if not href:
                    parent = tag.find_parent("a")
                    if parent:
                        href = parent.get("href", "") or ""

                is_job_link = bool(_JOB_PATH_PATTERN.search(href))
                has_job_keyword = any(kw in text_lower for kw in _JOB_TITLE_KEYWORDS)

                if not is_job_link and not has_job_keyword:
                    continue

                heuristic_seen.add(text_lower)
                full_url = urljoin(url, href) if href else url

                location_text = ""
                for sibling in tag.find_next_siblings():
                    sibling_text = sibling.get_text(strip=True)
                    if not sibling_text or len(sibling_text) > 150:
                        break
                    if re.search(r"[A-Z][a-z]+(?:[\s,]+[A-Z][a-z]+)*(?:,\s*[A-Z]{2,})?", sibling_text) or "remote" in sibling_text.lower():
                        location_text = sibling_text[:100]
                        break
                if not location_text:
                    el = tag
                    for _ in range(10):
                        el = el.parent
                        if not el:
                            break
                        ptext = el.get_text(strip=True)
                        loc_match = re.search(
                            r"(?:Bengaluru|Hyderabad|Mumbai|Pune|Gurgaon|Gurugram|Delhi|Chennai|Kolkata|New Delhi)"
                            r"(?:,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)?(?:\s*,\s*India)?",
                            ptext,
                        )
                        if loc_match:
                            location_text = loc_match.group(0)
                            break

                all_jobs.append({
                    "title": text[:200],
                    "company": company_name.title(),
                    "location": location_text,
                    "description": "",
                    "skills": [],
                    "employment_type": "",
                    "experience": "",
                    "apply_url": full_url,
                    "url": full_url,
                    "job_id": "",
                    "source": "generic-heuristic",
                })

            all_jobs = [j for j in all_jobs if _looks_like_job_title(j.get("title", ""))]

        # 5 — Fix apply_url from embedded detail-page URLs (e.g. Google)
        _patch_detail_urls(all_jobs, html, url)

        if all_jobs:
            all_jobs = await _enrich_jobs(all_jobs, page, limit, client=client)

        return _slice_and_filter(all_jobs, keyword, location, page, limit)


def _build_page_url(url: str, page: int) -> str:
    if page <= 1:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}page={page}"


_DETAIL_URL_RE = re.compile(
    r'(?:href|data-url|data-href)=["\']([^"\']*(?:job|career|careers|position|requisition|opening)s?/'
    r'(?:\d+[-\w]*|results/\d+[-\w]*)[^"\']*)["\']'
)


def _patch_detail_urls(
    jobs: list[dict[str, Any]],
    html: str,
    search_url: str,
) -> None:
    base = "https://www.google.com/about/careers/applications"
    detail_urls: list[tuple[str, str]] = []
    seen_slugs: set[str] = set()
    for m in _DETAIL_URL_RE.finditer(html):
        raw = m.group(1).replace("&amp;", "&")
        slug_match = re.search(r'results/(\d+)-([^&?\s]+)', raw)
        if slug_match:
            slug = slug_match.group(2)
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                furl = f"{base}/jobs/results/{slug_match.group(1)}-{slug}?location=India"
                detail_urls.append((slug, furl))

    for job in jobs:
        title = (job.get("title") or "").lower()
        title_slug = re.sub(r"[^a-z0-9]+", "-", title).strip("-")
        for slug, furl in detail_urls:
            if title_slug in slug or slug in title_slug:
                job["apply_url"] = furl
                job["url"] = furl
                break


def _extract_search_page_metadata(html: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    soup = BeautifulSoup(html, "lxml")
    for title_div in soup.find_all("div", class_=lambda c: c and "job-title-location" in c):
        text = title_div.get_text(strip=True)
        loc = text.removeprefix("Location").strip() if text.startswith("Location") else text
        sibling = title_div.find_previous_sibling("div")
        if not sibling:
            sibling = title_div.parent.find_previous_sibling("div") if title_div.parent else None
        parent_row = title_div.find_parent(class_=lambda c: c and "job-list-item" in c)
        if parent_row:
            title_el = parent_row.find(class_=lambda c: c and "job-title" in c)
            if title_el:
                title_text = title_el.get_text(strip=True)
                title_clean = title_text.split("Apple Retail")[0].split("Software and Services")[0].split("Operations")[0].split("Corporate")[0].strip()
                results.append((title_clean, loc))
    if not results:
        for item in soup.find_all("div", class_=lambda c: c and "job-title" in c):
            parent = item.find_parent(class_=lambda c: c and "job-list-item" in c)
            if not parent:
                continue
            title_text = item.get_text(strip=True)
            title_clean = re.sub(r"\s+(Software and Services|Operations|Corporate|Apple Retail).*", "", title_text).strip()
            loc_div = parent.find(class_=lambda c: c and "job-title-location" in c)
            if loc_div:
                loc_text = loc_div.get_text(strip=True).removeprefix("Location").strip()
                dist = abs(title_clean.count(" ") - loc_text.count(" ")) if title_clean and loc_text else 999
                if dist < 8 and not any(title_clean == t for t, _ in results):
                    results.append((title_clean, loc_text))
    return results


async def _enrich_jobs(
    jobs: list[dict[str, Any]],
    page: int,
    limit: int,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    _DEFAULT_DESC = "Job listing scraped from"

    async def _enrich_one(job: dict[str, Any]) -> dict[str, Any]:
        detail_url = job.get("apply_url") or job.get("url", "")
        if not detail_url:
            return job
        try:
            detail_html = await request_with_retries(detail_url, timeout=10.0, client=client)
            from scrapers.crawlers.universal import _extract_jsonld_jobpostings, _parse_jsonld_jobposting

            soup = BeautifulSoup(detail_html, "lxml")
            jsonld_items = _extract_jsonld_jobpostings(detail_html)
            for item in jsonld_items:
                parsed = _parse_jsonld_jobposting(item)
                if parsed.get("description"):
                    job["description"] = parsed["description"]
                if parsed.get("location"):
                    job["location"] = parsed["location"]
                if parsed.get("apply_url") and "?" not in parsed["apply_url"].split("/")[-1]:
                    job["apply_url"] = parsed["apply_url"]
                    job["url"] = parsed["apply_url"]

            cur_desc = job.get("description") or ""
            if _DEFAULT_DESC in cur_desc or not cur_desc:
                meta = soup.find("meta", attrs={"name": "description"})
                if meta and meta.get("content"):
                    job["description"] = meta["content"]
                og = soup.find("meta", property="og:description")
                if og and og.get("content") and (not job.get("description") or _DEFAULT_DESC in str(job.get("description",""))):
                    job["description"] = og["content"]

            if not job.get("location"):
                loc_meta = soup.find("meta", attrs={"name": "joblocation"})
                if loc_meta and loc_meta.get("content"):
                    job["location"] = loc_meta["content"]
        except Exception:
            pass
        return job

    max_enrich = min(len(jobs), 15)
    BATCH = 5
    enriched = []
    for i in range(0, max_enrich, BATCH):
        batch = jobs[i : i + BATCH]
        results = await asyncio.gather(*[_enrich_one(j) for j in batch])
        enriched.extend(results)
    enriched.extend(jobs[max_enrich:])
    return enriched


def _looks_like_job_title(text: str) -> bool:
    if len(text) < 5:
        return False
    if " " not in text.strip():
        return False
    if re.match(r"^[a-z]+(?:[-_][a-z]+)+$", text):
        return False
    if re.match(r"^[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$", text):
        return False
    _NAV_PATTERNS = [
        r"^(jobs|careers|work|life|explore)\s+(at|with|@)\s",
        r"^explore\s+(work|life)\s+at\s",
        r"^(quick|suggested)\s+(links|searches|pages)",
        r"career\s+opportunities?$",
        r"recycling\s+program(me)?$",
        r"apple\s+retail$",
        r"see\s+full\s+role\s+description",
        r"^shared\s+values$",
        r"^sign\s+in$",
        r"(policy|rights|discrimination|illegal)",
        r"^how\s+we\s+(hire|work|build)",
    ]
    lower = text.lower().strip()
    for pat in _NAV_PATTERNS:
        if re.search(pat, lower):
            return False
    _JOB_KEYWORDS_IN_TITLE = {
        "engineer", "developer", "manager", "designer", "analyst",
        "scientist", "intern", "architect", "consultant", "specialist",
        "coordinator", "director", "lead", "head", "vp", "chief",
        "officer", "associate", "operations", "product", "software",
    }
    if not any(kw in lower for kw in _JOB_KEYWORDS_IN_TITLE):
        return False
    return True


def _collect_job_candidates(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if any(key in payload for key in ("title", "name", "jobTitle", "role", "description", "location", "url")):
            candidates.append(payload)
        for value in payload.values():
            candidates.extend(_collect_job_candidates(value))
    elif isinstance(payload, list):
        for item in payload:
            candidates.extend(_collect_job_candidates(item))
    return candidates


def _pick(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        val = obj.get(key)
        if val is not None:
            return val
    return ""


def _slice_and_filter(
    jobs: list[dict[str, Any]],
    keyword: str | None,
    location: str | None,
    page: int,
    limit: int,
) -> list[dict[str, Any]]:
    if keyword:
        kw = keyword.lower()
        jobs = [j for j in jobs if kw in j.get("title", "").lower() or kw in j.get("description", "").lower()]
    if location:
        loc = location.lower()
        jobs = [j for j in jobs if not j.get("location") or loc in j["location"].lower()]
    return jobs[:limit]


_company_name_from_url = company_name_from_url


class _ATSScraper:
    def __init__(self, ats: str, company: str, ats_info: dict[str, Any] | None = None) -> None:
        self.ats = ats
        self.company = company
        self.ats_info = ats_info
        self.logger = LOGGER

    async def fetch_jobs(
        self,
        url: str | None = None,
        keyword: str | None = None,
        location: str | None = None,
        page: int = 1,
        limit: int = 20,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, Any]]:
        from scrapers.crawlers.base import crawl_ats_jobs, detect_ats as detect_ats_impl

        ats_info = self.ats_info or detect_ats_impl(url or "", "")
        if not ats_info:
            self.logger.warning("ATS scraper could not detect ATS info for %s", url)
            return []

        jobs = await crawl_ats_jobs(
            ats_info,
            company=self.company,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
            client=client,
        )
        return jobs


def route_scraper(url: str, html: str = "") -> GenericScraper | None:
    company_name = _company_name_from_url(url)

    ats = detect_ats(url, html)
    if ats:
        LOGGER.info("[INFO] Using scraper: %s (ATS)", ats)
        return _ATSScraper(ats, company_name)

    LOGGER.info("[INFO] Using scraper: generic")
    return GenericScraper(company=company_name)


async def _enrich_job_descriptions(
    jobs: list[dict[str, Any]],
    label: str,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    BATCH = 5
    enriched = 0
    for i in range(0, len(jobs), BATCH):
        batch = jobs[i : i + BATCH]
        results = await asyncio.gather(
            *[_fetch_description(j, client=client) for j in batch],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                continue
            enriched += 1
    LOGGER.info("[ENRICH] Enriched descriptions for %d/%d jobs from '%s'", enriched, len(jobs), label)
    return jobs


async def _fetch_description(job: dict[str, Any], client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    url = job.get("apply_url") or job.get("url", "")
    if not url or job.get("description", "").strip():
        return job
    try:
        html = await request_with_retries(url, timeout=10.0, client=client)
        from scrapers.crawlers.universal import _extract_jsonld_jobpostings, _parse_jsonld_jobposting

        jsonld_items = _extract_jsonld_jobpostings(html)
        for item in jsonld_items:
            parsed = _parse_jsonld_jobposting(item)
            if parsed.get("description"):
                job["description"] = parsed["description"]
                break
        else:
            soup = BeautifulSoup(html, "lxml")
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                job["description"] = meta["content"]
            else:
                og = soup.find("meta", property="og:description")
                if og and og.get("content"):
                    job["description"] = og["content"]
    except Exception:
        pass
    return job


async def _scrape_company(
    company: str | None,
    *,
    company_url: str | None = None,
    keyword: str | None,
    location: str | None,
    pages: int,
    page_size: int,
    delay_seconds: float,
    generic_only: bool = False,
    use_playwright: bool = False,
) -> list[dict[str, Any]]:
    # ── Smart Resolution ────────────────────────────────────────────────────
    # If we have neither a seeded URL nor a known company, try the resolver
    # to auto-discover the careers URL and detect ATS.
    if not company_url and company:
        try:
            from scrapers.resolver import resolve_company_input
            resolved = await resolve_company_input(company)
            if resolved.get("careers_url") and not company_url:
                company_url = resolved["careers_url"]
                LOGGER.info(
                    "[RESOLVER] '%s' → careers_url=%s (method=%s, ats=%s)",
                    company,
                    company_url,
                    resolved.get("discovery_method"),
                    (resolved.get("ats") or {}).get("platform"),
                )
        except Exception as resolve_err:
            LOGGER.debug("[RESOLVER] Resolution failed for '%s': %s", company, resolve_err)

    elif company_url and not company:
        # URL given without name — extract company name and try ATS detection
        try:
            from scrapers.resolver import resolve_company_input
            resolved = await resolve_company_input(company_url)
            if not company:
                company = resolved.get("company_name") or company_name_from_url(company_url)
            LOGGER.info(
                "[RESOLVER] URL '%s' → company=%s ats=%s",
                company_url,
                company,
                (resolved.get("ats") or {}).get("platform"),
            )
        except Exception as resolve_err:
            LOGGER.debug("[RESOLVER] URL resolution failed for '%s': %s", company_url, resolve_err)

    target = company or company_url or "unknown"
    ats_platform = None

    # Check circuit breaker before attempting scrape
    try:
        from app.services.scraper_health import is_circuit_open
        if await is_circuit_open(target):
            LOGGER.warning("[CIRCUIT BREAKER] Circuit is OPEN for '%s' (too many consecutive failures). Skipping.", target)
            return []
    except Exception as cb_err:
        LOGGER.debug("[CIRCUIT BREAKER] Check failed: %s", cb_err)

    try:
        async with shared_httpx_client() as client:
            jobs = await _scrape_company_with_client(
                company,
                company_url=company_url,
                keyword=keyword,
                location=location,
                pages=pages,
                page_size=page_size,
                delay_seconds=delay_seconds,
                generic_only=generic_only,
                use_playwright=use_playwright,
                client=client,
            )
            # Record success / zero-jobs
            try:
                from app.services.scraper_health import record_scrape_result
                await record_scrape_result(target, success=True, job_count=len(jobs), ats=ats_platform)
            except Exception:
                pass
            return jobs
    except Exception as exc:
        # Record failure
        try:
            from app.services.scraper_health import record_scrape_result
            await record_scrape_result(target, success=False, error=str(exc), ats=ats_platform)
        except Exception:
            pass
        raise


async def _scrape_company_with_client(
    company: str | None,
    *,
    company_url: str | None,
    keyword: str | None,
    location: str | None,
    pages: int,
    page_size: int,
    delay_seconds: float,
    generic_only: bool,
    use_playwright: bool,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    all_jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    if company_url:
        company_url = sanitize_url(company_url)
    label = company_url or company or "unknown"

    _scraper: GenericScraper | None = None
    if use_playwright:
        LOGGER.info("[PLAYWRIGHT] Playwright mode enabled for '%s' — skipping routed scrapers", label)
    else:
        # 1. Prefer known ATS adapter for company name
        if company and not generic_only:
            from scrapers.directory import ats_info as dir_atts_info
            info = dir_atts_info(company)
            if info:
                LOGGER.info("[DIRECTORY] Using ATS adapter '%s' for '%s'", info.get("platform"), company)
                _scraper = _ATSScraper(info.get("platform"), company, ats_info=info)

        # 2. If no company ATS adapter, route via careers URL
        if _scraper is None and company_url:
            if generic_only:
                company_name = company or _company_name_from_url(company_url)
                LOGGER.info("[INFO] Using scraper: generic (forced)")
                _scraper = GenericScraper(company=company_name)
            else:
                _scraper = route_scraper(company_url)

    for page in range(1, pages + 1):
        LOGGER.info("[SCRAPE] Fetching target='%s' page=%d limit=%d", label, page, page_size)

        if _scraper is not None:
            try:
                raw_jobs = await _scraper.fetch_jobs(
                    url=company_url,
                    keyword=keyword,
                    location=location,
                    page=page,
                    limit=page_size,
                    client=client,
                )
                results = [{"status": "ok", "jobs": raw_jobs, "company": label}]
            except Exception as exc:
                LOGGER.warning(
                    "[SCRAPE] Router scraper failed for '%s' page=%d: %s. Falling back to default.",
                    label,
                    page,
                    exc,
                )
                _scraper = None
                results = await crawl_jobs(
                    company=company,
                    company_url=company_url,
                    keyword=keyword,
                    location=location,
                    page=page,
                    limit=page_size,
                    use_playwright=use_playwright,
                    client=client,
                )
        else:
            results = await crawl_jobs(
                company=company,
                company_url=company_url,
                keyword=keyword,
                location=location,
                page=page,
                limit=page_size,
                use_playwright=use_playwright,
                client=client,
            )

        page_jobs: list[dict[str, Any]] = []
        for result in results:
            status = result.get("status", "unknown")
            if status != "ok":
                LOGGER.warning(
                    "[SCRAPE] Crawler reported failure for company='%s' page=%d: %s",
                    company,
                    page,
                    result.get("error", "unknown"),
                )
            for raw_job in result.get("jobs", []):
                job = canonicalize_job(raw_job)
                job_id = job.get("id") or f"{label}-{len(seen_ids)+1}"
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                page_jobs.append(job)

        if not page_jobs and generic_only and _scraper is not None and page == 1:
            LOGGER.info("[SCRAPE] Generic scraper returned 0 jobs — retrying via ATS/universal crawler for '%s'", label)
            _scraper = None
            results = await crawl_jobs(
                company=company,
                company_url=company_url,
                keyword=keyword,
                location=location,
                page=page,
                limit=page_size,
                use_playwright=use_playwright,
                client=client,
            )
            for result in results:
                for raw_job in result.get("jobs", []):
                    job = canonicalize_job(raw_job)
                    job_id = job.get("id") or f"{label}-{len(seen_ids)+1}"
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    page_jobs.append(job)

        LOGGER.info("[SCRAPE] Page complete target='%s' page=%d jobs_found=%d", label, page, len(page_jobs))
        if not page_jobs:
            LOGGER.info("[SCRAPE] No further jobs found for target='%s' on page=%d. Ending pagination.", label, page)
            break

        all_jobs.extend(page_jobs)
        if page < pages and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    if all_jobs:
        all_jobs = await _enrich_job_descriptions(all_jobs, label, client=client)

    LOGGER.info("[SCRAPE] Finished scraping target='%s'. Total jobs collected: %d", label, len(all_jobs))
    return all_jobs


async def _run(args: argparse.Namespace) -> None:
    generic_only = getattr(args, "generic_only", False)
    companies = [] if generic_only else _parse_company_list(args.companies)
    urls = _parse_url_list(args.company_url)

    if generic_only and not urls:
        raise SystemExit("--generic-only requires --company-url.")

    if not companies and not urls:
        raise SystemExit("No companies or company URLs selected for scraping.")

    from app.services.logging_setup import setup_logging
    setup_logging()

    LOGGER.info("=" * 60)
    LOGGER.info("STARTING JOB SCRAPER | Generic-only: %s", generic_only)
    mode = getattr(args, "mode", "local")
    LOGGER.info("Mode: %s | %s", mode.upper(), "JOB results will be persisted to the database" if mode == "db" else "JOB results are terminal-only")
    if companies:
        LOGGER.info("Target Companies: %s", ", ".join(companies))
    if urls:
        LOGGER.info("Target URLs: %s", ", ".join(urls))
    LOGGER.info("Pages per Target: %d | Limit per Page: %d | Concurrency: %d", args.pages, args.page_size, getattr(args, "concurrency", 1))
    LOGGER.info("=" * 60)

    total_scraped = 0
    all_collected_jobs: list[dict[str, Any]] = []
    # Order matters for consistent log ordering, so keep insertion order in the list.
    targets = [(c, None) for c in companies] + [(None, u) for u in urls]

    concurrency = getattr(args, "concurrency", 1)
    sem = asyncio.Semaphore(concurrency)

    async def _scrape_target(company: str | None, url: str | None) -> list[dict[str, Any]]:
        async with sem:
            label = url or company
            LOGGER.info("[CONC] (%d-way) Processing target: %s", concurrency, label)
            return await _scrape_company(
                company,
                company_url=url,
                keyword=args.keyword,
                location=args.location,
                pages=args.pages,
                page_size=args.page_size,
                delay_seconds=args.delay_seconds,
                generic_only=generic_only,
                use_playwright=args.browser_first,
            )

    results = await asyncio.gather(
        *[_scrape_target(c, u) for c, u in targets],
        return_exceptions=True,
    )

    for label, result in zip([x or y for x, y in targets], results):
        if isinstance(result, Exception):
            LOGGER.error("[CONCURRENCY] Target '%s' raised an unhandled exception: %s", label, result)
            continue
        total_scraped += len(result)
        all_collected_jobs.extend(result)

    pushed = 0
    if mode == "db" and all_collected_jobs:
        pushed = await _push_to_db(all_collected_jobs)
        LOGGER.info("Pushed %d/%d scraped jobs to the database.", pushed, len(all_collected_jobs))

    LOGGER.info("=" * 60)
    LOGGER.info("SCRAPE SUMMARY | Mode: %s", mode.upper())
    LOGGER.info("Total Jobs Scraped Across All Targets: %d", total_scraped)
    if mode == "db":
        LOGGER.info("Jobs Persisted to Database: %d", pushed)

    if all_collected_jobs:
        LOGGER.info("\n--- FIRST 4 DATA POINTS PREVIEW ---\n%s\n---------------------------------", _format_jobs_preview(all_collected_jobs))
    else:
        LOGGER.info("No job data points were retrieved.")

    LOGGER.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequential job scraper for Job Nest.")
    parser.add_argument("--companies", default="all", help="Comma-separated company slugs or 'all'.")
    parser.add_argument("--company-url", default=None, help="Comma-separated company career page URLs to scrape (bypasses company name lookup).")
    parser.add_argument("--keyword", default=None, help="Filter jobs by keyword.")
    parser.add_argument("--location", default=None, help="Filter jobs by location.")
    parser.add_argument("--pages", type=int, default=2, help="Number of pages to scrape per company.")
    parser.add_argument("--page-size", type=int, default=20, help="Number of items per page.")
    parser.add_argument("--delay-seconds", type=float, default=0.5, help="Delay between page/company requests in seconds (CPU protection).")
    parser.add_argument("--concurrency", type=int, default=1, help="Max companies/URLs to scrape in parallel (default 1 = sequential).")
    parser.add_argument("--generic-only", action="store_true", help="Skip registered companies; scrape provided URLs with the generic fallback scraper only.")
    parser.add_argument("--browser-first", action="store_true", help="Use Playwright immediately for known SPA-heavy sites instead of as last resort.")
    parser.add_argument(
        "--mode",
        choices=["local", "db"],
        default="local",
        help="local = print results to terminal only; db = persist scraped jobs to MongoDB (like POST /push-to-db).",
    )

    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
