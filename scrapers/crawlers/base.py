from __future__ import annotations
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
import httpx

from scrapers.crawlers.rate_limit import domain_rate_limiter

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONNECTIONS = 50


def build_client(
    *,
    timeout: float = 25.0,
    max_connections: int = _DEFAULT_MAX_CONNECTIONS,
    http2: bool = False,
    headers: dict[str, str] | None = None,
    max_retries: int = 2,
) -> httpx.AsyncClient:
    """Create a connection-pooled httpx client for reuse across many requests."""
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max(4, int(max_connections * 0.3)),
    )
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        limits=limits,
        http2=http2,
        headers=headers,
        transport=httpx.AsyncHTTPTransport(retries=max_retries),
    )


@asynccontextmanager
async def shared_httpx_client(
    *,
    timeout: float = 25.0,
    max_connections: int = _DEFAULT_MAX_CONNECTIONS,
    http2: bool = False,
    headers: dict[str, str] | None = None,
):
    """Context manager yielding one pooled client for a whole scrape task."""
    async with build_client(
        timeout=timeout,
        max_connections=max_connections,
        http2=http2,
        headers=headers,
    ) as client:
        yield client


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _looks_like_job_title(text: str, href: str) -> bool:
    text_lower = text.lower()
    href_lower = href.lower()

    _SKIP_TEXTS = {
        "sign in", "sign up", "register", "log in", "login",
        "english", "deutsch", "español", "français", "português",
        "talent community", "search results", "previous", "next",
    }
    if any(skip in text_lower for skip in _SKIP_TEXTS):
        return False
    if re.search(r'locale\s*=', href_lower) or re.search(r'language\s*=', href_lower):
        return False

    job_path_patterns = [
        "/job/", "/jobs/", "/position/", "/requisition/",
        "/opening/", "/careers/job", "/careers/position",
        "/detail/",
    ]
    if any(pattern in href_lower for pattern in job_path_patterns):
        return True

    keywords = [
        "engineer", "developer", "program", "analyst", "scientist",
        "intern", "manager", "designer", "product", "support",
        "operations", "specialist", "coordinator", "consultant",
        "associate", "director", "architect", "vp", "lead",
    ]
    if any(keyword in text_lower for keyword in keywords):
        word_count = len(text.split())
        if word_count >= 3:
            return True
        if word_count < 3 and not any(p in href_lower for p in job_path_patterns):
            return False
        return True

    return False


def _matches_filter(job: dict[str, Any], *, keyword: str | None = None, location: str | None = None) -> bool:
    if keyword:
        needle = keyword.lower()
        searchable = " ".join(
            str(job.get(key) or "") for key in ("title", "description", "summary", "content")
        ).lower()
        if needle not in searchable:
            return False
    if location:
        job_location = str(job.get("location") or "").lower()
        if job_location and location.lower() not in job_location:
            return False
    return True


def _slice_page(jobs: list[dict[str, Any]], *, page: int = 1, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is None:
        return jobs
    start = max(page - 1, 0) * limit
    return jobs[start : start + limit]


def _extract_anchor_links(html: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href = match.group(1)
        text = _clean_text(_strip_tags(match.group(2)))
        if href and text:
            links.append({"href": href, "text": text})
    return links


def _is_client_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        # 408 and 429 are transient and should consume the bounded retry
        # budget; authentication and other client errors should fail fast.
        return 400 <= exc.response.status_code < 500 and exc.response.status_code not in (408, 429)
    return False


async def _limited_request(client: httpx.AsyncClient, url: str, *, method: str = "GET",
                           params: dict[str, Any] | None = None,
                           headers: dict[str, str] | None = None,
                           json_data: Any | None = None,
                           data: Any | None = None) -> httpx.Response:
    await domain_rate_limiter.acquire(url)
    try:
        if method.upper() == "POST":
            return await client.post(url, params=params, headers=headers, json=json_data, data=data)
        return await client.get(url, params=params, headers=headers)
    finally:
        domain_rate_limiter.release(url)


async def request_with_retries(
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_data: Any | None = None,
    data: Any | None = None,
    timeout: float = 20.0,
    max_retries: int = 3,
    client: httpx.AsyncClient | None = None,
) -> str:
    if client is not None:
        return await _request_with_client(client, url, method=method, params=params, headers=headers, json_data=json_data, data=data, timeout=timeout, max_retries=max_retries)

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                if method.upper() == "POST":
                    response = await _limited_request(c, url, method=method, params=params, headers=headers, json_data=json_data, data=data)
                else:
                    response = await _limited_request(c, url, method=method, params=params, headers=headers, json_data=json_data, data=data)
                response.raise_for_status()
                return response.text
        except Exception as exc:
            last_error = exc
            exc_msg = str(exc) or f"[{type(exc).__name__}]"
            logger.warning("Request attempt %s failed for %s: %s", attempt + 1, url, exc_msg)
            if _is_client_error(exc) or attempt >= max_retries - 1:
                raise RuntimeError(str(last_error)) from last_error
            await asyncio.sleep(min(2**attempt, 4))
    raise RuntimeError(str(last_error)) from last_error


async def request_json_with_retries(
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_data: Any | None = None,
    data: Any | None = None,
    timeout: float = 20.0,
    max_retries: int = 3,
    client: httpx.AsyncClient | None = None,
) -> Any:
    if client is not None:
        return await _request_json_with_client(client, url, method=method, params=params, headers=headers, json_data=json_data, data=data, timeout=timeout, max_retries=max_retries)

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                if method.upper() == "POST":
                    response = await _limited_request(c, url, method=method, params=params, headers=headers, json_data=json_data, data=data)
                else:
                    response = await _limited_request(c, url, method=method, params=params, headers=headers, json_data=json_data, data=data)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            last_error = exc
            exc_msg = str(exc) or f"[{type(exc).__name__}]"
            logger.warning("JSON request attempt %s failed for %s: %s", attempt + 1, url, exc_msg)
            if _is_client_error(exc) or attempt >= max_retries - 1:
                raise RuntimeError(str(last_error)) from last_error
            await asyncio.sleep(min(2**attempt, 4))
    raise RuntimeError(str(last_error)) from last_error


async def _request_with_client(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_data: Any | None = None,
    data: Any | None = None,
    timeout: float = 20.0,
    max_retries: int = 3,
) -> str:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            if method.upper() == "POST":
                response = await _limited_request(client, url, method=method, params=params, headers=headers, json_data=json_data, data=data)
            else:
                response = await _limited_request(client, url, method=method, params=params, headers=headers, json_data=json_data, data=data)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_error = exc
            exc_msg = str(exc) or f"[{type(exc).__name__}]"
            logger.warning("Client request attempt %s failed for %s: %s", attempt + 1, url, exc_msg)
            if _is_client_error(exc) or attempt >= max_retries - 1:
                raise RuntimeError(str(last_error)) from last_error
            await asyncio.sleep(min(2**attempt, 4))
    raise RuntimeError(str(last_error)) from last_error


async def _request_json_with_client(
    client: httpx.AsyncClient,
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_data: Any | None = None,
    data: Any | None = None,
    timeout: float = 20.0,
    max_retries: int = 3,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            if method.upper() == "POST":
                response = await _limited_request(client, url, method=method, params=params, headers=headers, json_data=json_data, data=data)
            else:
                response = await _limited_request(client, url, method=method, params=params, headers=headers, json_data=json_data, data=data)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            exc_msg = str(exc) or f"[{type(exc).__name__}]"
            logger.warning("Client JSON request attempt %s failed for %s: %s", attempt + 1, url, exc_msg)
            if _is_client_error(exc) or attempt >= max_retries - 1:
                raise RuntimeError(str(last_error)) from last_error
            await asyncio.sleep(min(2**attempt, 4))
    raise RuntimeError(str(last_error)) from last_error


def _eightfold_domain(url: str, html_content: str = "") -> str | None:
    """Resolve the Eightfold tenant domain used as the `domain` API param.

    Vanity hosts (e.g. jobs.twilio.com) are registered against a brand domain
    (twilio.com). Derive it from the host when possible, else from embedded
    page JSON, else fall back to the registrable domain via tldextract.
    """
    if not url:
        return None

    host = urlparse(url).netloc.lower()
    cands = re.findall(r'"domain"\s*:\s*"?([a-z0-9][a-z0-9.-]+\.[a-z]{2,})"?', html_content or "")
    for cand in cands:
        if "." in cand and not cand.startswith("."):
            return cand

    subdomain_match = re.search(r'^([^.]+)\.([a-z0-9-]+)\.[a-z]{2,}$', host)
    if subdomain_match and subdomain_match.group(1) in ("jobs", "careers", "career", "talent", "apply"):
        return f"{subdomain_match.group(2)}.{host.rsplit('.', 1)[-1]}"

    try:
        import tldextract
        ext = tldextract.extract(host)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
    except Exception:
        pass

    return None


def _workday_board_path(url: str) -> str:
    """Extract the Workday board path prefix (locale + board) from a careers URL.

    Examples:
      https://mycareer.hsbc.com/en_GB/external/SearchJobs/   -> /en_GB/external
      https://apply.deloitte.com/en_US/careers/SearchJobs    -> /en_US/careers
      https://apply.deloitte.com/en_US/careers/JobDetail/..  -> /en_US/careers

    Returns "" when no Workday marker is present in the URL.
    """
    if not url:
        return ""
    path = urlparse(url).path
    for marker in ("/PipelineDetail/", "/JobDetail/", "/SearchJobs", "/Search", "/Jobs", "/jobs"):
        idx = path.lower().find(marker.lower())
        if idx != -1:
            return path[:idx].rstrip("/")
    return ""


def detect_ats(url: str, html_content: str = "") -> dict[str, str] | None:
    searchable = f"{url}\n{html_content or ''}"

    if "phenompeople.com" in searchable or "data-ph-id" in searchable or re.search(r'cdn\.phenompeople\.com', searchable):
        return {"platform": "phenom", "domain": url}

    # Eightfold / PCSX careers board (e.g. jobs.twilio.com, some *.eightfold.ai hosts).
    if (
        re.search(r'eightfold\.ai|eightfold\.co|static\.vscdn\.net|api/pcsx', searchable, re.IGNORECASE)
        or ("/careers" in url and "pid=" in url and "start=" in url)
    ):
        host = (urlparse(url).netloc or "").lower()
        return {
            "platform": "eightfold",
            "host": host,
            "domain": _eightfold_domain(url, html_content),
        }

    lever_match = re.search(r'https?://jobs\.lever\.co/([^/?#\s"]+)', searchable)
    if lever_match:
        return {"platform": "lever", "token": lever_match.group(1)}

    greenhouse_match = re.search(r'https?://boards\.greenhouse\.io/([^/?#\s"]+)', searchable)
    if greenhouse_match:
        return {"platform": "greenhouse", "token": greenhouse_match.group(1)}

    greenhouse_embed = re.search(r'boards\.greenhouse\.io/embed/job_board\?board_id=([^&\s"\']+)', searchable)
    if greenhouse_embed:
        return {"platform": "greenhouse", "token": greenhouse_embed.group(1)}

    ashby_match = re.search(
        r'https?://(?:jobs\.|api\.)?ashbyhq\.com/(?:posting-api/job-board/)?([^/?#\s"\']+)',
        searchable,
    )
    if ashby_match:
        return {"platform": "ashby", "token": ashby_match.group(1)}

    workday_match = re.search(r'https?://((?:[^./]+\.)*[^./]+)\.myworkdayjobs\.com/([^/?#\s"\']+)', searchable)
    if workday_match:
        host_prefix = workday_match.group(1)
        tenant = host_prefix.split(".")[0]
        return {"platform": "workday", "subdomain": host_prefix, "tenant": tenant, "board": workday_match.group(2)}

    # Workday on a custom domain (e.g. apply.deloitte.com, mycareer.hsbc.com).
    # Classic sites expose /SearchJobs and /PipelineDetail/ paths; the newer
    # experience uses /portalpacks/ assets and /careers/JobDetail/ paths.
    if (
        _workday_board_path(url)
        or re.search(r"portalpacks|/wday/cxs/|wd-browser-id|CALYPSO_CSRF_TOKEN|PLAY_SESSION", searchable, re.IGNORECASE)
    ):
        host = urlparse(url).netloc.lower().removeprefix("www.")
        board_path = _workday_board_path(url)
        board = board_path.rstrip("/").split("/")[-1] if board_path else ""
        return {
            "platform": "workday",
            "host": host,
            "tenant": host.split(".")[0] if host else "",
            "board": board,
            "board_path": board_path,
            "custom_domain": True,
        }

    smart_match = re.search(
        r'https?://(?:www\.)?smartrecruiters\.com/([^/?#\s"\']+)|'
        r'https?://jobs\.smartrecruiters\.com/([^/?#\s"\']+)|'
        r'https?://api\.smartrecruiters\.com/v1/companies/([^/?#\s"\']+)',
        searchable,
    )
    if smart_match:
        return {"platform": "smartrecruiters", "token": next(group for group in smart_match.groups() if group)}

    bamboo_match = re.search(
        r'https?://([^./]+)\.bamboohr\.com/(?:jobs|career|careers|jobsearch|api)(?:/|$)',
        searchable,
    )
    if bamboo_match:
        return {"platform": "bamboohr", "token": bamboo_match.group(1)}

    icims_match = re.search(
        r'https?://(?:www\.)?([^./]+)\.icims\.com/(?:jobs|careers|search|discover|api)(?:/|$)',
        searchable,
    )
    if icims_match:
        return {"platform": "icims", "token": icims_match.group(1)}

    jobvite_match = re.search(
        r'https?://(?:www\.)?([^./]+)\.jobvite\.com/([^/?#\s"\']*)',
        searchable,
    )
    if jobvite_match:
        return {"platform": "jobvite", "token": jobvite_match.group(1)}

    jazzhr_match = re.search(
        r'https?://(?:www\.)?([^./]+)\.jazzhr\.com/(?:jobs|job|career|career-page)(?:/|$)',
        searchable,
    )
    if jazzhr_match:
        return {"platform": "jazzhr", "token": jazzhr_match.group(1)}

    recruitee_match = re.search(
        r'https?://(?:www\.)?([^./]+)\.recruitee\.com/(?:jobs|career|companies|department)(?:/|$)',
        searchable,
    )
    if recruitee_match:
        return {"platform": "recruitee", "token": recruitee_match.group(1)}

    comeet_match = re.search(
        r'https?://(?:www\.)?([^./]+)\.comeet\.com/(?:jobs|careers|career)(?:/|$)',
        searchable,
    )
    if comeet_match:
        return {"platform": "comeet", "token": comeet_match.group(1)}

    teamtailor_match = re.search(
        r'https?://(?:www\.)?([^./]+)\.teamtailor\.com/(?:jobs|career|company)(?:/|$)',
        searchable,
    )
    if teamtailor_match:
        return {"platform": "teamtailor", "token": teamtailor_match.group(1)}

    freshteam_match = re.search(
        r'https?://(?:www\.)?([^./]+)\.freshteam\.com/(?:jobs|careers|career)(?:/|$)',
        searchable,
    )
    if freshteam_match:
        return {"platform": "freshteam", "token": freshteam_match.group(1)}

    pinboard_match = re.search(
        r'https?://pinboard\.hq\.com/(?:careers|company|jobs)(?:/|$)',
        searchable,
    )
    if pinboard_match:
        return {"platform": "pinboard", "token": "pinboard"}

    oraclecloud_match = re.search(
        r'https?://([^./]+)\.fa\.([^/]+?)/hcmUI/CandidateExperience/en/sites/([^/?#\s"\']+)',
        searchable,
    )
    if oraclecloud_match:
        return {
            "platform": "oraclecloud",
            "subdomain": oraclecloud_match.group(1),
            "domain": f"{oraclecloud_match.group(1)}.fa.{oraclecloud_match.group(2)}",
            "site": oraclecloud_match.group(3),
        }

    return None


def _extract_root_domain(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def _crawl_phenom(
    input_url: str,
    company: str,
    *,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []

    if not input_url:
        return jobs

    root = _extract_root_domain(input_url)

    # Collect job URLs from sitemaps
    job_urls: list[str] = []
    sitemap_candidates = [
        f"{root}/sitemap_index.xml",
        f"{root}/global/en/sitemap_index.xml",
        f"{root}/sitemap1.xml",
        f"{root}/global/en/sitemap1.xml",
        f"{root}/sitemap2.xml",
        f"{root}/global/en/sitemap2.xml",
    ]

    fetched_sitemaps: list[str] = []
    for sm_url in sitemap_candidates:
        try:
            sm_html = await request_with_retries(sm_url, timeout=15)
            if sm_html and "<loc>" in sm_html:
                fetched_sitemaps.append(sm_html)
                if "<sitemapindex" in sm_html:
                    for m in re.finditer(r'<loc>([^<]+)</loc>', sm_html):
                        sub = m.group(1).strip()
                        try:
                            sub_xml = await request_with_retries(sub, timeout=15)
                            if sub_xml and "<loc>" in sub_xml:
                                fetched_sitemaps.append(sub_xml)
                        except Exception:
                            continue
        except Exception:
            continue

    for xml in fetched_sitemaps:
        for m in re.finditer(r'<loc>([^<]+)</loc>', xml):
            url = m.group(1).strip()
            if "/job/" in url.lower():
                job_urls.append(url)

    if not job_urls:
        return jobs

    page_limit = limit or 20
    start = max(page - 1, 0) * page_limit
    batch = job_urls[start:start + page_limit]

    for job_url in batch:
        try:
            html = await request_with_retries(job_url, timeout=15)
            from scrapers.crawlers.universal import _extract_jsonld_jobpostings, _parse_jsonld_jobposting

            jsonld_items = _extract_jsonld_jobpostings(html)
            for item in jsonld_items:
                parsed = _parse_jsonld_jobposting(item)
                title = (parsed.get("title") or "").strip()
                if not title:
                    continue
                normalized = normalize_job_payload({
                    "job_id": parsed.get("job_id", ""),
                    "title": title,
                    "location": parsed.get("location", ""),
                    "description": parsed.get("description", ""),
                    "apply_url": job_url,
                    "employment_type": parsed.get("employment_type", ""),
                    "experience": "",
                    "skills": [],
                    "posted_date": parsed.get("posted_date", ""),
                    "valid_through": parsed.get("valid_through", ""),
                }, company, "phenom")
                if _matches_filter(normalized, keyword=keyword, location=location):
                    jobs.append(normalized)
                    break
        except Exception:
            continue

    return jobs


async def _crawl_eightfold(
    ats_info: dict[str, Any],
    company: str,
    *,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Crawl an Eightfold / PCSX careers board (e.g. jobs.twilio.com).

    Eightfold tenants expose two JSON APIs:
      * SmartApply legacy:  GET /api/apply/v2/jobs?domain={domain}&start={n}&num={n}
      * PCSX (newer):       GET /api/pcsx/search?domain={domain}&start={n}&num={n}
    Listings omit descriptions; each job's full HTML description is fetched from
    the PCSX position_details endpoint.
    """
    host = ats_info.get("host") or ""
    domain = ats_info.get("domain") or _eightfold_domain(host or "")
    if not host or not domain:
        logger.warning("Eightfold crawler requires host, but got %r", ats_info)
        return []

    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")

    page_limit = limit or 20
    start = max(page - 1, 0) * page_limit
    search_params = {
        "domain": domain,
        "location": "",
        "query": keyword or "",
        "pid": ats_info.get("pid", ""),
        "start": start,
        "num": page_limit,
        "sort_by": ats_info.get("sort_by", "timestamp"),
    }
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    jobs: list[dict[str, Any]] = []

    try:
        search_url = f"{host}/api/pcsx/search"
        data = await request_json_with_retries(search_url, params=search_params, headers=headers, timeout=25.0, client=client)
    except Exception as e:
        logger.warning("Eightfold listings failed via PCSX for %s: %s", company, e)
        raise RuntimeError(f"Eightfold (PCSX) failed for {company}: {e}") from e

    payload = data.get("data") if isinstance(data, dict) else None
    positions = payload.get("positions") if isinstance(payload, dict) else None
    if not isinstance(positions, list):
        logger.warning("Eightfold returned no positions for %s", company)
        return []

    for raw_job in positions:
        pos_id = str(raw_job.get("id") or "")
        title = raw_job.get("name") or ""
        loc_raw = raw_job.get("locations") or []
        locations = ", ".join(loc_raw) if isinstance(loc_raw, list) else str(loc_raw or "")
        department = raw_job.get("department") or ""
        position_path = raw_job.get("positionUrl") or ""
        apply_url = f"{host}{position_path}" if position_path.startswith("/") else (position_path or "")

        desc = ""
        if pos_id:
            try:
                detail_url = f"{host}/api/pcsx/position_details"
                detail = await request_json_with_retries(
                    detail_url,
                    params={"position_id": pos_id, "domain": domain},
                    headers=headers,
                    timeout=20.0,
                    client=client,
                )
                detail_data = detail.get("data") if isinstance(detail, dict) else None
                if isinstance(detail_data, dict):
                    desc = detail_data.get("jobDescription") or ""
                    create_ts = detail_data.get("creationTs") or 0
                    if not locations and detail_data.get("locations"):
                        loc_list = detail_data["locations"]
                        locations = ", ".join(loc_list) if isinstance(loc_list, list) else str(loc_list)
                    if not title:
                        title = detail_data.get("name") or ""
            except Exception as de:
                logger.warning("Eightfold detail fetch failed for %s %s: %s", company, pos_id, de)

        from bs4 import BeautifulSoup as _BS
        if desc:
            plain = _BS(desc, "lxml").get_text(" ", strip=True)
            desc = f"{desc}\n\n{plain}" if plain and plain not in desc else desc

        normalized = normalize_job_payload({
            "job_id": pos_id,
            "title": title,
            "location": locations,
            "description": desc,
            "apply_url": apply_url,
            "employment_type": "",
            "experience": "",
            "skills": [],
        }, company, "eightfold")
        if _matches_filter(normalized, keyword=keyword, location=location):
            jobs.append(normalized)
        await asyncio.sleep(0.05)

    return jobs


async def _crawl_workday_html(
    *,
    host: str,
    board_path: str,
    company: str,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Crawl a Workday career site hosted on a custom domain (e.g. apply.deloitte.com).

    Custom-domain Workday tenants usually don't expose the myworkdayjobs.com CXS
    JSON API, so we scrape the server-rendered search page and then the detail
    pages (which carry JSON-LD) instead.
    """
    search_url = f"https://{host}{board_path}/SearchJobs"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    try:
        html = await request_with_retries(search_url, headers=headers, timeout=20.0, client=client)
    except Exception as e:
        logger.error("Failed crawling Workday custom domain %s: %s", host, e)
        raise RuntimeError(f"Workday custom domain failed for {company}: {e}") from e

    from scrapers.crawlers.universal import _extract_jsonld_jobpostings, _parse_jsonld_jobposting

    job_links: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in _extract_anchor_links(html):
        href = anchor["href"]
        text = anchor["text"]
        if not href or not text:
            continue
        full_url = urljoin(search_url, href)
        if not re.search(r"/(?:PipelineDetail|JobDetail)/", full_url, re.IGNORECASE):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        if not _looks_like_job_title(text, full_url):
            continue
        path = urlparse(full_url).path.rstrip("/")
        last_seg = path.rsplit("/", 1)[-1] if path else ""
        job_id = last_seg if last_seg.isdigit() else ""
        job_links.append({
            "title": text[:160],
            "url": full_url,
            "job_id": job_id,
        })

    if not job_links:
        logger.warning("No Workday job links found on %s", search_url)
        return []

    per_page = limit or 20
    start = max(page - 1, 0) * per_page
    page_links = job_links[start:start + per_page]

    jobs: list[dict[str, Any]] = []
    for item in page_links:
        desc, loc = "", ""
        try:
            detail_html = await request_with_retries(item["url"], headers=headers, timeout=15.0, client=client)
            best: dict[str, Any] | None = None
            best_len = 0
            for ld in _extract_jsonld_jobpostings(detail_html):
                parsed = _parse_jsonld_jobposting(ld)
                if not parsed.get("title"):
                    continue
                desc_len = len(parsed.get("description") or "")
                if best is None or desc_len > best_len:
                    best, best_len = parsed, desc_len
            if best:
                desc = best.get("description") or ""
                loc = best.get("location") or ""
            if not desc:
                meta_desc = re.search(
                    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
                    detail_html,
                    re.IGNORECASE,
                )
                if meta_desc:
                    desc = _clean_text(meta_desc.group(1))
        except Exception as exc:
            logger.warning("Workday custom domain detail fetch failed (%s): %s", item["url"], exc)

        normalized = normalize_job_payload({
            "job_id": item["job_id"],
            "title": item["title"],
            "location": loc,
            "description": desc,
            "apply_url": item["url"],
            "employment_type": "",
            "experience": "",
            "skills": [],
        }, company, "workday")
        if _matches_filter(normalized, keyword=keyword, location=location):
            jobs.append(normalized)
        await asyncio.sleep(0.05)

    return jobs


async def crawl_ats_jobs(
    ats_info: dict[str, str],
    company: str,
    *,
    keyword: str | None = None,
    location: str | None = None,
    page: int = 1,
    limit: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    platform = ats_info["platform"]
    jobs = []

    _rjr = lambda url, **kw: request_json_with_retries(url, client=client, **kw)

    if platform == "lever":
        token = ats_info["token"]
        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
        try:
            listings = await _rjr(url)
            if isinstance(listings, list):
                for raw_job in listings:
                    job_id = raw_job.get("id") or ""
                    title = raw_job.get("title") or ""
                    job_location = raw_job.get("categories", {}).get("location") or ""
                    desc = raw_job.get("description") or ""
                    lists_text = ""
                    for item in raw_job.get("lists", []):
                        lists_text += f"\n\n{item.get('text')}:\n" + "\n".join(item.get("content", []))
                    full_desc = f"{desc}{lists_text}"
                    apply_url = raw_job.get("hostedUrl") or ""

                    normalized = normalize_job_payload({
                        "job_id": job_id,
                        "title": title,
                        "location": job_location,
                        "description": full_desc,
                        "apply_url": apply_url,
                        "employment_type": raw_job.get("categories", {}).get("commitment") or "",
                        "experience": "",
                        "skills": [],
                    }, company, "lever")
                    if _matches_filter(normalized, keyword=keyword, location=location):
                        jobs.append(normalized)
        except Exception as e:
            logger.error("Failed crawling Lever for %s: %s", company, e)
            raise RuntimeError(f"Lever failed for {company}: {e}") from e

    elif platform == "greenhouse":
        token = ats_info["token"]
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        try:
            data = await _rjr(url)
            listings = data.get("jobs") if isinstance(data, dict) else None
            if isinstance(listings, list):
                for raw_job in listings:
                    job_id = str(raw_job.get("id") or "")
                    title = raw_job.get("title") or ""
                    job_location = raw_job.get("location", {}).get("name") or ""
                    desc = raw_job.get("content") or ""
                    apply_url = raw_job.get("absolute_url") or ""

                    normalized = normalize_job_payload({
                        "job_id": job_id,
                        "title": title,
                        "location": job_location,
                        "description": desc,
                        "apply_url": apply_url,
                        "employment_type": "",
                        "experience": "",
                        "skills": [],
                    }, company, "greenhouse")
                    if _matches_filter(normalized, keyword=keyword, location=location):
                        jobs.append(normalized)
        except Exception as e:
            logger.error("Failed crawling Greenhouse for %s: %s", company, e)
            raise RuntimeError(f"Greenhouse failed for {company}: {e}") from e

    elif platform == "ashby":
        token = ats_info["token"]
        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
        try:
            data = await _rjr(url)
            listings = data.get("jobs") if isinstance(data, dict) else None
            if isinstance(listings, list):
                for raw_job in listings:
                    job_id = raw_job.get("id") or ""
                    title = raw_job.get("title") or ""
                    job_location = raw_job.get("location") or ""
                    desc = raw_job.get("descriptionHtml") or raw_job.get("descriptionPlain") or ""
                    apply_url = raw_job.get("jobUrl") or ""

                    normalized = normalize_job_payload({
                        "job_id": job_id,
                        "title": title,
                        "location": job_location,
                        "description": desc,
                        "apply_url": apply_url,
                        "employment_type": raw_job.get("employmentType") or "",
                        "experience": "",
                        "skills": [],
                    }, company, "ashby")
                    if _matches_filter(normalized, keyword=keyword, location=location):
                        jobs.append(normalized)
        except Exception as e:
            logger.error("Failed crawling Ashby for %s: %s", company, e)
            raise RuntimeError(f"Ashby failed for {company}: {e}") from e

    elif platform == "workday":
        if ats_info.get("custom_domain") and ats_info.get("host"):
            jobs = await _crawl_workday_html(
                host=ats_info["host"],
                board_path=ats_info.get("board_path") or "",
                company=company,
                keyword=keyword,
                location=location,
                page=page,
                limit=limit,
                client=client,
            )
            return jobs

        subdomain = ats_info["subdomain"]
        tenant = ats_info.get("tenant") or subdomain.split(".")[0]
        board = ats_info["board"]
        search_url = f"https://{subdomain}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs"
        try:
            page_limit = limit or 20
            payload = {
                "appliedFacets": {},
                "limit": page_limit,
                "offset": max(page - 1, 0) * page_limit,
                "searchText": keyword or "",
            }
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            # Workday CXS returns 422 Unprocessable Entity unless a session cookie is
            # established first. Warm it by GETting a board page via the same client so
            # cookies carry into the POST below.
            try:
                warm_url = f"https://{subdomain}.myworkdayjobs.com/en-US/{board}"
                warm_headers = {
                    "Accept": "text/html",
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                    ),
                }
                if client is not None:
                    await client.get(warm_url, headers=warm_headers)
                else:
                    await request_with_retries(warm_url, headers=warm_headers, timeout=15.0)
            except Exception:
                pass

            try:
                data = await _rjr(search_url, method="POST", json_data=payload, headers=headers)
            except Exception as workday_exc:
                status_code = None
                if isinstance(workday_exc.__cause__, httpx.HTTPStatusError):
                    status_code = workday_exc.__cause__.response.status_code
                if status_code == 422:
                    logger.warning(
                        "Workday CXS returned 422 for %s, retrying after refresh",
                        company,
                    )
                    try:
                        if client is not None:
                            await client.get(search_url, headers=warm_headers)
                        else:
                            await request_with_retries(search_url, headers=warm_headers, timeout=15.0)
                        data = await _rjr(search_url, method="POST", json_data=payload, headers=headers)
                    except Exception as retry_exc:
                        raise RuntimeError(f"Workday failed for {company}: {retry_exc}") from retry_exc
                else:
                    raise
            listings = data.get("jobPostings") if isinstance(data, dict) else None
            if isinstance(listings, list):
                for raw_job in listings:
                    external_path = raw_job.get("externalPath") or ""
                    title = raw_job.get("title") or ""
                    job_location = raw_job.get("locationsText") or ""
                    if re.search(r"^\d+\s+locations?$", job_location.strip(), re.IGNORECASE) or "multiple" in job_location.lower():
                        loc_list = raw_job.get("locations")
                        if isinstance(loc_list, list):
                            names = []
                            for loc in loc_list:
                                if isinstance(loc, dict):
                                    n = loc.get("descriptor") or loc.get("name") or loc.get("id") or ""
                                    if n:
                                        names.append(n)
                            if names:
                                job_location = ", ".join(names)
                        else:
                            parts = external_path.strip("/").split("/")
                            if len(parts) >= 2 and parts[0] == "job":
                                city = parts[1].replace("-", " ")
                                count_match = re.search(r"(\d+)", job_location)
                                if count_match:
                                    count = int(count_match.group(1))
                                    if count > 1:
                                        job_location = f"{city} + {count - 1} more"
                                    else:
                                        job_location = city
                                else:
                                    job_location = f"{city} + more"

                    desc = ""
                    if external_path:
                        detail_url = f"https://{subdomain}.myworkdayjobs.com/wday/cxs/{tenant}/{board}{external_path}"
                        try:
                            detail_data = await _rjr(detail_url, headers=headers)
                            if isinstance(detail_data, dict):
                                desc = detail_data.get("jobPostingInfo", {}).get("jobDescription") or ""
                        except Exception as de:
                            logger.warning("Failed fetching Workday job details from %s: %s", detail_url, de)

                    apply_url = f"https://{subdomain}.myworkdayjobs.com/en-US/{board}{external_path}"
                    job_id = external_path.split("_")[-1] if "_" in external_path else external_path

                    normalized = normalize_job_payload({
                        "job_id": job_id,
                        "title": title,
                        "location": job_location,
                        "description": desc,
                        "apply_url": apply_url,
                        "employment_type": raw_job.get("timeType") or "",
                        "experience": "",
                        "skills": [],
                    }, company, "workday")
                    if _matches_filter(normalized, keyword=keyword, location=location):
                        jobs.append(normalized)
        except Exception as e:
            logger.error("Failed crawling Workday for %s: %s", company, e)
            raise RuntimeError(f"Workday failed for {company}: {e}") from e

    elif platform == "smartrecruiters":
        token = ats_info["token"]
        page_limit = min(limit or 100, 100)
        offset = max(page - 1, 0) * page_limit
        params = {"limit": page_limit, "offset": offset}
        if keyword:
            params["q"] = keyword
        url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
        try:
            data = await _rjr(url, params=params)
            listings = data.get("content") if isinstance(data, dict) else None
            if isinstance(listings, list):
                for raw_job in listings:
                    job_id = str(raw_job.get("id") or raw_job.get("uuid") or "")
                    title = raw_job.get("name") or raw_job.get("title") or ""
                    location_data = raw_job.get("location") or {}
                    job_location = location_data.get("city") or location_data.get("fullLocation") or ""
                    apply_url = raw_job.get("ref") or ""
                    detail_url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{job_id}"
                    desc = raw_job.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text") or ""
                    try:
                        detail_data = await _rjr(detail_url)
                        if isinstance(detail_data, dict):
                            apply_url = detail_data.get("applyUrl") or detail_data.get("ref") or apply_url
                            detail_sections = detail_data.get("jobAd", {}).get("sections", {})
                            desc = (
                                detail_sections.get("jobDescription", {}).get("text")
                                or detail_sections.get("qualifications", {}).get("text")
                                or desc
                            )
                    except Exception as de:
                        logger.warning("Failed fetching SmartRecruiters job detail for %s: %s", job_id, de)
                    normalized = normalize_job_payload({
                        "job_id": job_id,
                        "title": title,
                        "location": job_location,
                        "description": desc,
                        "apply_url": apply_url,
                        "employment_type": raw_job.get("typeOfEmployment", {}).get("label") or "",
                        "experience": raw_job.get("experienceLevel", {}).get("label") or "",
                        "skills": [],
                    }, company, "smartrecruiters")
                    if _matches_filter(normalized, keyword=keyword, location=location):
                        jobs.append(normalized)
        except Exception as e:
            logger.error("Failed crawling SmartRecruiters for %s: %s", company, e)
            raise RuntimeError(f"SmartRecruiters failed for {company}: {e}") from e

    elif platform == "oraclecloud":
        domain = ats_info["domain"]
        site = ats_info["site"]
        limit_per_page = min(limit or 20, 200)
        oracle_headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        try:
            expand = (
                "requisitionList.workLocation,requisitionList.otherWorkLocations,"
                "requisitionList.secondaryLocations,flexFieldsFacet.values,"
                "requisitionList.requisitionFlexFields"
            )
            finder = f"findReqs;siteNumber={site},limit={limit_per_page},offset=0"
            listings_url = (
                f"https://{domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                f"?onlyData=true&expand={expand}&finder={finder}"
            )
            data = await _rjr(listings_url, headers=oracle_headers, timeout=30)
            items = data.get("items") or []
            if items:
                search_item = items[0]
                total = int(search_item.get("TotalJobsCount") or 0)
                req_list = search_item.get("requisitionList") or []

                need = min(page * limit * 5, total, 2000) if limit else min(total, 2000)
                offsets = list(range(limit_per_page, total, limit_per_page))
                for offset in offsets:
                    await asyncio.sleep(0.5)
                    pf = f"findReqs;siteNumber={site},limit={limit_per_page},offset={offset}"
                    pu = f"https://{domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand={expand}&finder={pf}"
                    try:
                        pd = await _rjr(pu, headers=oracle_headers, timeout=30)
                        pi = pd.get("items") or []

                    except Exception:
                        pass
                    if len(req_list) >= need:
                        break

                for raw in req_list:
                    job_id = str(raw.get("Id") or "")
                    title = raw.get("Title") or ""
                    loc = raw.get("PrimaryLocation") or ""
                    posted = raw.get("PostedDate") or ""
                    desc_short = raw.get("ShortDescriptionStr") or ""
                    apply_url = f"https://{domain}/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}" if job_id else ""

                    normalized = normalize_job_payload({
                        "job_id": job_id,
                        "title": title,
                        "location": loc,
                        "description": desc_short,
                        "apply_url": apply_url,
                        "posted_date": posted,
                        "employment_type": "",
                        "experience": "",
                        "skills": [],
                    }, company, "oraclecloud")
                    if _matches_filter(normalized, keyword=keyword, location=location):
                        jobs.append(normalized)
        except Exception as e:
            logger.error("Failed crawling Oracle Cloud for %s: %s", company, e)
            raise RuntimeError(f"Oracle Cloud failed for {company}: {e}") from e

    elif platform == "phenom":
        domain = ats_info.get("domain", "")
        jobs = await _crawl_phenom(domain, company, keyword=keyword, location=location, page=page, limit=limit, client=client)

    elif platform == "eightfold":
        jobs = await _crawl_eightfold(
            ats_info,
            company,
            keyword=keyword,
            location=location,
            page=page,
            limit=limit,
            client=client,
        )

    elif platform == "capgemini":
        api_url = ats_info.get("api_url", "https://cg-jobstream-api.azurewebsites.net/api/job-search")
        try:
            params: dict[str, Any] = {"page": page, "size": max(limit, 1)}
            if keyword:
                params["search"] = keyword
            if location:
                params["country_code"] = location
            if client is not None:
                resp = await client.get(api_url, params=params)
            else:
                resp = await request_with_retries(api_url, params=params, timeout=30.0)
            if resp.status_code != 200:
                raise RuntimeError(f"Capgemini API returned HTTP {resp.status_code}")
            data = resp.json().get("data") or []
            for raw in data:
                normalized = normalize_job_payload({
                    "job_id": raw.get("id") or raw.get("ref") or raw.get("hash"),
                    "title": raw.get("title"),
                    "location": raw.get("location") or raw.get("country_name"),
                    "description": raw.get("description_stripped"),
                    "apply_url": raw.get("apply_job_url"),
                    "employment_type": raw.get("contract_type"),
                    "experience": raw.get("experience_level"),
                    "department": raw.get("department") or raw.get("sbu"),
                }, company, "capgemini")
                if _matches_filter(normalized, keyword=keyword, location=location):
                    jobs.append(normalized)
        except Exception as e:
            logger.error("Failed crawling Capgemini for %s: %s", company, e)
            raise RuntimeError(f"Capgemini failed for {company}: {e}") from e

    return _slice_page(jobs, page=page, limit=limit) if platform != "workday" else jobs


def _coerce_string(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _coerce_skills(value: Any) -> list[str]:
    if isinstance(value, list):
        skills = []
        for item in value:
            if isinstance(item, str):
                skills.append(_clean_text(item))
            elif isinstance(item, dict):
                for key in ("name", "skill", "title"):
                    skill = item.get(key)
                    if skill:
                        skills.append(_clean_text(str(skill)))
        return [skill for skill in skills if skill]
    if isinstance(value, str):
        return [skill.strip() for skill in re.split(r"[,;|/]+", value) if skill.strip()]
    return []


def _find_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


_LOCATION_VALUE_RE = re.compile(
    r"^(?:Multiple\s+Cities|Remote|Anywhere|Various|Worldwide|Global|TBD)$"
    r"|^.+(?:,\s*[A-Z]{2,}(?:\s*[A-Z]+)?)$",
    re.IGNORECASE,
)

def _flexible_key_search(raw_job: dict[str, Any], *patterns: str) -> str | None:
    for key, val in raw_job.items():
        if isinstance(val, str) and val.strip():
            for pat in patterns:
                if pat in key.lower():
                    return val.strip()
    return None

def _value_location_search(raw_job: dict[str, Any]) -> str | None:
    for val in raw_job.values():
        if isinstance(val, str) and val.strip() and _LOCATION_VALUE_RE.match(val.strip()):
            return val.strip()
    return None

def normalize_job_payload(raw_job: dict[str, Any], company: str, source: str) -> dict[str, Any]:
    title = _coerce_string(_find_value(raw_job, "title", "job_title", "jobTitle", "name", "role", "jobName"))
    location = _coerce_string(_find_value(raw_job, "location", "location_string", "job_location", "jobLocation", "city", "workLocation"))
    if not location:
        location = _coerce_string(_flexible_key_search(raw_job, "location", "city", "country"))
    if not location:
        location = _coerce_string(_value_location_search(raw_job))
    description = _coerce_string(_find_value(raw_job, "description", "summary", "snippet", "content", "details"))
    requirements = _coerce_string(_find_value(raw_job, "requirements", "requirement"))
    if description and requirements:
        description = f"{description}\n\nRequirements: {requirements}" if description else requirements
    elif not description:
        description = requirements

    job_id = _coerce_string(_find_value(raw_job, "job_id", "jobId", "id", "jobNumber", "positionId"))
    apply_url = _coerce_string(_find_value(raw_job, "apply_url", "applyUrl", "apply_link", "applyLink", "url", "link", "absolute_url"))
    employment_type = _coerce_string(_find_value(raw_job, "employment_type", "employmentType", "type", "workType", "time_type"))
    if not employment_type:
        employment_type = _coerce_string(_flexible_key_search(raw_job, "employment", "work_type", "time_type"))
    experience = _coerce_string(_find_value(raw_job, "experience", "experience_level", "experienceLevel", "level"))
    if not experience:
        experience = _coerce_string(_flexible_key_search(raw_job, "experience", "seniority", "level"))
    team = _coerce_string(_find_value(raw_job, "team", "business_area", "businessArea", "department", "category"))
    if team and description:
        description = f"{description}\n\nTeam: {team}" if team not in description else description

    return {
        "company": company.title(),
        "job_id": job_id,
        "title": title,
        "location": location,
        "description": description,
        "skills": _coerce_skills(_find_value(raw_job, "skills", "technologies", "requirements")),
        "employment_type": employment_type,
        "experience": experience,
        "apply_url": apply_url,
        "source": source,
    }


def collect_job_candidates(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    if isinstance(payload, dict):
        if payload and any(key in payload for key in ("title", "job_title", "jobTitle", "name", "description", "location", "job_id", "jobId", "apply_url", "applyUrl")):
            if any(isinstance(payload.get(key), str) and payload.get(key) for key in ("title", "job_title", "jobTitle", "name", "description", "location")):
                candidates.append(payload)
        for value in payload.values():
            candidates.extend(collect_job_candidates(value))
    elif isinstance(payload, list):
        for item in payload:
            candidates.extend(collect_job_candidates(item))

    return candidates


def extract_jobs_from_html(html: str, *, company: str, base_url: str, location_hint: str = "") -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    base_domain = urlparse(base_url).netloc.lower()
    for anchor in _extract_anchor_links(html):
        href = anchor["href"]
        text = anchor["text"]
        if not href or not text:
            continue
        if not _looks_like_job_title(text, href):
            continue
        full_url = urljoin(base_url, href)
        link_domain = urlparse(full_url).netloc.lower()
        if link_domain and link_domain != base_domain:
            continue
        title = text[:120].rstrip()
        normalized_title = title.lower()
        if normalized_title in seen:
            continue
        jobs.append({"title": title, "location": location_hint, "description": f"Job listing scraped from {company}.", "url": full_url})
        seen.add(normalized_title)
    return jobs
