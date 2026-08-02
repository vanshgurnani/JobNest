from __future__ import annotations

from typing import Any

_SEED_URLS: dict[str, str] = {
    "accenture": "https://www.accenture.com/in-en/careers/jobsearch",
    "amazon": "https://www.amazon.jobs/en/search.json",
    "apple": "https://jobs.apple.com/en-us/search",
    "capgemini": "https://www.capgemini.com/in-en/careers/join-capgemini/job-search/",
    "cisco": "https://jobs.cisco.com",
    "cognizant": "https://careers.cognizant.com/global-en/jobs/",
    "deloitte": "https://jobsindia.deloitte.com/search/?q=&locationsearch=India",
    "google": "https://www.google.com/about/careers/applications/jobs/results/",
    "ibm": "https://www.ibm.com/careers/search",
    "infosys": "https://career.infosys.com/joblist",
    "jpmorgan": "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions",
    "ltimindtree": "https://www.ltimindtree.com/careers/",
    "mastercard": "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers",
    "meta": "https://www.metacareers.com/jobs",
    "microsoft": "https://careers.microsoft.com/us/en/search-results",
    "nvidia": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    "oracle": "https://oracle.wd12.myworkdayjobs.com/ORCL_External_Careers",
    "salesforce": "https://careers.salesforce.com/en-us/jobs/",
    "sap": "https://www.sap.com/careers.html",
    "techmahindra": "https://careers.techmahindra.com/",
    "tcs": "https://www.tcs.com/careers",
    "wipro": "https://careers.wipro.com/viewalljobs/?locale=en_US",
    "zoho": "https://www.zoho.com/careers/",
    "adobe": "https://adobe.wd5.myworkdayjobs.com/external_experienced",
    "amd": "https://amd.wd5.myworkdayjobs.com/external",
    "dell": "https://dell.wd5.myworkdayjobs.com/Dell_Careers",
    "hp": "https://hp.wd5.myworkdayjobs.com/HPCareers",
    "kpmg": "https://kpmg.wd5.myworkdayjobs.com/KPMG_External_Careers",
    "mckinsey": "https://mckinsey.wd1.myworkdayjobs.com/McKinseyCareers",
    "vmware": "https://vmware.wd1.myworkdayjobs.com/VMware_Careers",
    "airbnb": "https://careers.airbnb.com/",
    "datadog": "https://careers.datadoghq.com/",
    "shopify": "https://www.shopify.com/careers",
    "stripe": "https://stripe.com/jobs",
    "gitlab": "https://about.gitlab.com/jobs/",
    "notion": "https://www.notion.so/careers",
    "bain": "https://www.bain.com/careers/",
    "barclays": "https://search.jobs.barclays/",
    "boston consulting group": "https://careers.bcg.com/global/en/search-results",
    "ey": "https://eyglobal.yello.co/jobs/",
    "goldman sachs": "https://www.goldmansachs.com/careers/",
    "northern trust": "https://careers.northerntrust.com/",
    "pwc": "https://www.pwc.com/gx/en/careers.html",
}

_SEED_ATS: dict[str, dict[str, Any]] = {
    "airbnb": {"platform": "greenhouse", "token": "airbnb"},
    "datadog": {"platform": "greenhouse", "token": "datadoghq"},
    "shopify": {"platform": "greenhouse", "token": "shopify"},
    "gitlab": {"platform": "greenhouse", "token": "gitlab"},
    "notion": {"platform": "greenhouse", "token": "swissmadenatural"},
    "stripe": {"platform": "lever", "token": "stripe"},
    "barclays": {"platform": "workday", "subdomain": "barclays.wd3", "tenant": "barclays", "board": "External_Career_Site_Barclays"},
    "northern trust": {"platform": "workday", "subdomain": "ntrs.wd1", "tenant": "ntrs", "board": "northerntrust"},
    "capgemini": {"platform": "capgemini", "api_url": "https://cg-jobstream-api.azurewebsites.net/api/job-search"},
}

_SEED_ALIASES: dict[str, str] = {
    "jpm": "jpmorgan",
    "jp morgan": "jpmorgan",
    "j.p. morgan": "jpmorgan",
    "tca": "tcs",
    "tata": "tcs",
    "kpmg jp": "kpmg",
    "bcg": "boston consulting group",
    "goldman": "goldman sachs",
}


def _is_entry_key(key: str) -> bool:
    return bool(key) and not key.startswith("_")


def companies() -> list[str]:
    """Known company seeds in registration order (bootstrap hints only)."""
    return [k for k in _SEED_URLS if _is_entry_key(k)]


def get(name: str) -> dict[str, Any] | None:
    url = _SEED_URLS.get(name)
    if not url:
        return None
    entry: dict[str, Any] = {"careers_url": url}
    ats = _SEED_ATS.get(name)
    if ats:
        entry["ats"] = ats
    return entry


def careers_url(name: str) -> str | None:
    url = _SEED_URLS.get(name)
    return url.strip() if isinstance(url, str) and url.strip() else None


def ats_info(name: str) -> dict[str, Any] | None:
    """Return structured ATS info for a company seed.

    Resolution order:
      1. Explicit seed ATS config (greenhouse/lever tokens, custom APIs like capgemini).
      2. Auto-derived from the seeded careers_url via base.detect_ats (workday, oraclecloud,
         smartrecruiters, ashby, phenom).

    Companies not in the seed return None — the crawler falls back to dynamic
    discovery (universal scraper resolves the careers page and detects ATS at runtime).
    """
    explicit = _SEED_ATS.get(name)
    if explicit and explicit.get("platform"):
        return dict(explicit)

    url = careers_url(name)
    if not url:
        return None

    from scrapers.crawlers.base import detect_ats

    info = detect_ats(url, "")
    if isinstance(info, dict) and info.get("platform"):
        return info
    return None


def platform_for(name: str) -> str | None:
    info = ats_info(name)
    return info.get("platform") if info else None


def resolve_company(company: str | Any) -> str | None:
    """Map a possibly-cased company name to its canonical seed key."""
    if not isinstance(company, str):
        return None
    key = company.strip().lower()
    if key in _SEED_URLS:
        return key
    alias = _SEED_ALIASES.get(key)
    if alias and alias in _SEED_URLS:
        return alias
    return None


if __name__ == "__main__":  # pragma: no cover
    for c in companies():
        info = ats_info(c)
        print(f"{c:24} -> {info.get('platform') if info else 'generic'} {info or ''}")
