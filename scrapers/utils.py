from __future__ import annotations

import json
import re
from pathlib import Path
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


def company_name_from_url(url: str) -> str:
    extracted = tldextract.extract(url)
    domain = extracted.domain or url.split("//")[-1].split("/")[0].split(".")[0]
    return domain.replace("-", " ").replace("_", " ").title()


def supported_companies() -> list[str]:
    _path = Path(__file__).resolve().parent / "company_urls.json"
    companies: list[str] = []
    if _path.exists():
        try:
            raw = json.loads(_path.read_text(encoding="utf-8"))
            for key in raw:
                if not key.startswith("_"):
                    companies.append(key)
        except Exception:
            pass
    return companies


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
    }

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
