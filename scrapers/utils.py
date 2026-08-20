from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

import tldextract
from bs4 import BeautifulSoup

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "gclsrc", "gbraid", "wbraid", "fbclid", "fbclick",
    "dclid", "msclkid", "twclid", "igshid", "mc_cid", "mc_eid",
    "gad_source", "gad_campaignid", "gad_campaign",
}


def sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in query.items() if k.lower() not in _TRACKING_PARAMS}
    if not cleaned:
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", parsed.fragment))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(cleaned, doseq=True), parsed.fragment))


_GENERIC_TLDS = {
    "com", "org", "net", "edu", "gov", "mil", "io", "co", "in", "uk", "us",
    "de", "fr", "es", "it", "nl", "se", "no", "dk", "fi", "pl", "au", "ca",
    "jp", "kr", "sg", "ae", "sa", "za", "br", "mx", "ru", "cn", "hk", "nz",
    "ch", "at", "be", "pt", "gr", "tr", "il", "th", "my", "id", "vn", "tw",
    "info", "biz", "me", "tv", "asia", "eu", "int", "xyz", "tech", "online",
    "site", "store", "app", "dev", "ai", "cloud", "data", "email", "jobs",
}


def company_name_from_url(url: str) -> str:
    extracted = tldextract.extract(url)
    suffix = (extracted.suffix or "").lower()
    last_suffix = suffix.split(".")[-1]
    if suffix and last_suffix not in _GENERIC_TLDS and not suffix.count(".") >= 1:
        # Brand TLDs (e.g. jobs.barclays, careers.google): the suffix itself is
        # the company, not a generic domain. tldextract would otherwise report
        # the subdomain label as the "domain".
        name = suffix.split(".")[-1]
    else:
        name = extracted.domain
    if not name:
        name = url.split("//")[-1].split("/")[0].split(".")[0]
    return name.replace("-", " ").replace("_", " ").title()


def supported_companies() -> list[str]:
    """Known company seeds from the in-code directory (bootstrap hints only).

    Everything not listed here is still discoverable at runtime by the
    universal scraper (careers-page resolution + ATS detection).
    """
    from scrapers.directory import companies as directory_companies

    return directory_companies()


def detect_ats(url: str, html_content: str = "") -> dict[str, Any] | str | None:
    url_lower = url.lower()

    patterns: dict[str, str] = {
        "greenhouse": r"greenhouse\.io",
        "lever": r"lever\.co",
        "workday": r"workday\.com|myworkdayjobs|wd5\.myworkdayjobs",
        "bamboohr": r"bamboohr\.com",
        "smartrecruiters": r"smartrecruiters\.com",
        "icims": r"icims\.com",
        "jobvite": r"jobvite\.com",
        "jazzhr": r"jazzhr\.com",
        "recruitee": r"recruitee\.com",
        "ashbyhq": r"ashbyhq\.com|ashby\.co",
        "pinboard": r"pinboard\.hq\.com|hq\.com/careers",
        "freshteam": r"freshteam\.com",
        "comeet": r"comeet\.com",
        "hirehive": r"hirehive\.io",
        "manatal": r"manatal\.com",
        "ceipal": r"ceipal\.com",
        "zoho_recruit": r"zoho\.com/recruit",
        "bullhorn": r"bullhorn\.com",
        "jobadder": r"jobadder\.com",
        "taleo": r"taleo\.net|oracle\.com/taleo",
        "sap_successfactors": r"sap\.com/successfactors|successfactors\.eu",
        "dice": r"dice\.com/careers",
        "recruit": r"recruit\.net",
        "personio": r"personio\.com|personio\.de",
        "factorialhr": r"factorialhr\.com|factorial\.com",
        "teamtailor": r"teamtailor\.com",
        "comeet": r"comeet\.com",
        "applytojob": r"applytojob\.com",
        "paycom": r"paycom\.com",
        "ukg": r"ukg\.com|ultimatesoftware\.com",
        "adp": r"adp\.com",
        "phenom": r"phenompeople\.com|campion\.com|phenom\.com",
        "eightfold": r"eightfold\.ai|eightfold\.co|static\.vscdn\.net|api/pcsx|pcsx\/search",
    }

    # Vanity-host Eightfold boards (e.g. jobs.twilio.com/careers?start=0&pid=...
    # &sort_by=timestamp) don't carry an *.eightfold.ai URL component. The Eightfold
    # PCSX board signature is the `pid=` portal-id query param on a /careers path.
    if "/careers" in url_lower and "pid=" in url_lower and "start=" in url_lower:
        return "eightfold"

    for name, pat in patterns.items():
        if re.search(pat, url_lower, re.IGNORECASE):
            return name

    if html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        text_lower = soup.get_text().lower()
        for name, pat in patterns.items():
            if re.search(pat, text_lower, re.IGNORECASE):
                return name

        for tag in soup.find_all(["script", "link", "meta"]):
            src = (
                tag.get("src")
                or tag.get("href")
                or tag.get("content")
                or ""
            )
            for name, pat in patterns.items():
                if re.search(pat, src, re.IGNORECASE):
                    return name

        for cls in soup.find_all(class_=True):
            for c in cls.get("class", []):
                for name, pat in patterns.items():
                    if re.search(pat, c, re.IGNORECASE):
                        return name

        if soup.find(attrs={"data-ph-id": True}):
            return "phenom"

    return None
