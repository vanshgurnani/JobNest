from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urlencode, urljoin
import httpx

logger = logging.getLogger(__name__)


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

    keywords = [
        "engineer", "developer", "program", "analyst", "scientist",
        "intern", "manager", "designer", "product", "support",
        "operations", "specialist", "coordinator", "consultant",
        "associate", "director", "architect", "vp", "lead",
    ]
    if any(keyword in text_lower for keyword in keywords):
        return True

    job_path_patterns = [
        "/job/", "/jobs/", "/position/", "/requisition/",
        "/opening/", "/careers/job", "/careers/position",
    ]
    if any(pattern in href_lower for pattern in job_path_patterns):
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
        return 400 <= exc.response.status_code < 500
    return False


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
                    response = await c.post(url, params=params, headers=headers, json=json_data, data=data)
                else:
                    response = await c.get(url, params=params, headers=headers)
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
                    response = await c.post(url, params=params, headers=headers, json=json_data, data=data)
                else:
                    response = await c.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            last_error = exc
            exc_msg = str(exc) or f"[{type(exc).__name__}]"
            logger.warning("JSON request attempt %s failed for %s: %s", attempt + 1, url, exc_msg)
            if _is_client_error(exc) or attempt >= max_retries - 1:
                raise RuntimeError(str(last_error)) from last_error
            await asyncio.sleep(min(2**attempt, 4))
            if attempt < max_retries - 1:
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
                response = await client.post(url, params=params, headers=headers, json=json_data, data=data)
            else:
                response = await client.get(url, params=params, headers=headers)
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
                response = await client.post(url, params=params, headers=headers, json=json_data, data=data)
            else:
                response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            exc_msg = str(exc) or f"[{type(exc).__name__}]"
            logger.warning("Client JSON request attempt %s failed for %s: %s", attempt + 1, url, exc_msg)
            if _is_client_error(exc) or attempt >= max_retries - 1:
                raise RuntimeError(str(last_error)) from last_error
            await asyncio.sleep(min(2**attempt, 4))
            if attempt < max_retries - 1:
                await asyncio.sleep(min(2**attempt, 4))
    raise RuntimeError(str(last_error)) from last_error


def detect_ats(url: str, html_content: str = "") -> dict[str, str] | None:
    searchable = f"{url}\n{html_content or ''}"

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

    smart_match = re.search(
        r'https?://(?:www\.)?smartrecruiters\.com/([^/?#\s"\']+)|'
        r'https?://jobs\.smartrecruiters\.com/([^/?#\s"\']+)|'
        r'https?://api\.smartrecruiters\.com/v1/companies/([^/?#\s"\']+)',
        searchable,
    )
    if smart_match:
        return {"platform": "smartrecruiters", "token": next(group for group in smart_match.groups() if group)}

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

    elif platform == "workday":
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
            data = await _rjr(search_url, method="POST", json_data=payload, headers=headers)
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

    return _slice_page(jobs, page=page, limit=limit) if platform != "workday" else jobs


def _coerce_string(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, (int, float)):
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


def normalize_job_payload(raw_job: dict[str, Any], company: str, source: str) -> dict[str, Any]:
    title = _coerce_string(_find_value(raw_job, "title", "job_title", "jobTitle", "name", "role", "jobName"))
    location = _coerce_string(_find_value(raw_job, "location", "job_location", "jobLocation", "city", "workLocation"))
    description = _coerce_string(_find_value(raw_job, "description", "summary", "snippet", "content", "details"))
    requirements = _coerce_string(_find_value(raw_job, "requirements", "requirement"))
    if description and requirements:
        description = f"{description}\n\nRequirements: {requirements}" if description else requirements
    elif not description:
        description = requirements

    job_id = _coerce_string(_find_value(raw_job, "job_id", "jobId", "id", "jobNumber", "positionId"))
    apply_url = _coerce_string(_find_value(raw_job, "apply_url", "applyUrl", "apply_link", "applyLink", "url", "link"))
    employment_type = _coerce_string(_find_value(raw_job, "employment_type", "employmentType", "type", "workType"))
    experience = _coerce_string(_find_value(raw_job, "experience", "experience_level", "experienceLevel", "level"))
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
    for anchor in _extract_anchor_links(html):
        href = anchor["href"]
        text = anchor["text"]
        if not href or not text:
            continue
        if not _looks_like_job_title(text, href):
            continue
        full_url = urljoin(base_url, href)
        title = text[:120].rstrip()
        normalized_title = title.lower()
        if normalized_title in seen:
            continue
        jobs.append({"title": title, "location": location_hint, "description": f"Job listing scraped from {company}.", "url": full_url})
        seen.add(normalized_title)
    return jobs
