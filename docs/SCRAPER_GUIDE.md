# Scraper Engine & CLI Guide

## Overview

The scraper engine is a **Playwright-free** job scraping system that runs independently of the FastAPI backend. It uses async HTTP requests (via `httpx`) and HTML parsing (via `BeautifulSoup4`) to extract job listings from company career portals.

**Key Design Decisions:**
- Zero browser automation (no Playwright/Selenium) for free-tier CPU compatibility
- Fully async `asyncio`-based execution for concurrent crawling
- Two operational modes: `local` (preview) and `db` (MongoDB persistence)
- Modular crawler architecture with company-specific and universal strategies

## Directory Layout

```
scrapers/
  scrape_jobs.py         # CLI entry point (+ routing layer, ATS detection, GenericScraper)
  crawlers/
    __init__.py
    orchestrator.py      # Crawler registry and dispatcher
    base.py              # HTTP retry client, ATS detector, normalizer
    amazon.py            # Amazon Jobs API crawler
    microsoft.py         # Microsoft PCSX API crawler
    meta.py              # Meta GraphQL + HTML fallback
    universal.py         # Universal ATS-aware crawler (1049 lines)
```

## Installation

Ensure you have the Python dependencies installed:

```bash
pip install -r requirements.txt
```

Key dependencies: `httpx`, `beautifulsoup4`, `lxml`, `motor`, `pydantic`

## Usage

### Local Preview Mode (No Database Required)

Preview scraped data without connecting to MongoDB. The first 4 job entries are logged as a JSON preview.

```bash
# Scrape a single company, 1 page
python scrapers/scrape_jobs.py --mode local --companies amazon --pages 1

# Scrape multiple companies
python scrapers/scrape_jobs.py --mode local --companies amazon,microsoft,meta --pages 2

# Scrape all supported companies
python scrapers/scrape_jobs.py --mode local --companies all --pages 1
```

### Database Mode (Persist to MongoDB)

Upserts scraped jobs into MongoDB after canonicalizing and deduplicating by job ID.

```bash
# Scrape and store
python scrapers/scrape_jobs.py --mode db --companies amazon --pages 2

# Scrape all companies, 3 pages each
python scrapers/scrape_jobs.py --mode db --companies all --pages 3

# With keyword and location filters
python scrapers/scrape_jobs.py --mode db --companies microsoft --keyword engineer --location "Redmond"
```

### URL-Based Scraping (Bypass Company Name Lookup)

Scrape any company by its career page URL. The system uses a **smart routing layer** (`route_scraper`) that automatically selects the best strategy:

1. **Company-specific** — if the URL's domain matches a registered crawler (amazon, microsoft, meta)
2. **ATS-aware** — if the URL/HTML contains Lever, Greenhouse, Workday, Ashby, or SmartRecruiters markers
3. **Generic fallback** — dynamic extraction pipeline for any other site

```bash
# Scrape a single career page URL
python scrapers/scrape_jobs.py --mode local --company-url "https://careers.google.com"

# Scrape multiple URLs
python scrapers/scrape_jobs.py --mode db --company-url "https://careers.google.com,https://jobs.apple.com"

# Combine named companies and URLs
python scrapers/scrape_jobs.py --mode db --companies amazon --company-url "https://careers.google.com"
```

### Generic-Only Mode (Skip Registered Crawlers)

Bypass the routing layer entirely and force the generic dynamic scraper. Useful for testing unknown sites or avoiding registered crawlers.

```bash
# Scrape Apple with generic scraper only (no company-specific or ATS routing)
python scrapers/scrape_jobs.py --mode local --generic-only --company-url "https://jobs.apple.com/en-in/search?location=india-INDC&key=software"

# Multiple URLs in generic-only mode
python scrapers/scrape_jobs.py --mode local --generic-only --company-url "https://jobs.apple.com,https://company-site.com/careers"
```

The generic-only mode:
- Skips all registered company scrapers (amazon, meta, microsoft)
- Forces the GenericScraper cascade regardless of URL patterns
- Requires `--company-url` (exits with an error if omitted)
- Logs `[INFO] Using scraper: generic (forced)` per URL

### All CLI Options

| Argument | Default | Description |
|---|---|---|---|
| `--mode` | `local` | `local` or `db` |
| `--companies` | `all` | Comma-separated slugs (e.g. `amazon,microsoft`) or `all` |
| `--company-url` | `None` | Comma-separated career page URLs to scrape (bypasses company name lookup, uses router) |
| `--keyword` | `None` | Keyword filter passed to crawlers |
| `--location` | `None` | Location filter passed to crawlers |
| `--pages` | `2` | Pages per company |
| `--page-size` | `20` | Items per page |
| `--delay-seconds` | `0.5` | Delay between requests (CPU protection) |
| `--generic-only` | `False` | Skip registered crawlers; force generic scraper on provided URLs |

## Supported Companies & Crawlers

| Target | Crawler | Strategy |
|---|---|---|---|
| Amazon | `amazon.py` | Amazon Jobs public `search.json` API |
| Microsoft | `microsoft.py` | Microsoft PCSX API (search + position details + skills) |
| Meta | `meta.py` | MetaCareers GraphQL API + HTML fallback |
| Lever / Greenhouse / Workday / Ashby / SmartRecruiters | `base.py` (`crawl_ats_jobs`) | ATS detection → platform-specific API calls |
| Any other company (via `--company-url`) | Router → `scrape_jobs.py` (GenericScraper) | Route: company-specific → ATS → generic cascade |
| Any company (via `--generic-only`) | `scrape_jobs.py` (GenericScraper) | Forced generic: JSON-LD → embedded JSON → anchor links → BS4 heuristic |

## Smart Routing Layer

The routing layer lives in `scrapers/scrape_jobs.py` and decides which scraper handles each URL:

```
route_scraper(url, html="")
  │
  ├─ 1. URL domain matches _REGISTRY (amazon, meta, microsoft)?
  │      → _CompanyScraper (delegates to orchestrator)
  │
  ├─ 2. URL or HTML contains ATS markers?
  │      → _ATSScraper (delegates to base.py ATS crawlers)
  │
  └─ 3. Fallback
         → GenericScraper (dynamic extraction pipeline)
```

Every decision is logged: `[INFO] Using scraper: amazon (company-specific)` / `greenhouse (ATS)` / `generic`.

When `--generic-only` is set, the router is bypassed entirely and `GenericScraper` is used directly.

## GenericScraper Extraction Pipeline

The `GenericScraper` (`scrape_jobs.py`) dynamically extracts jobs from any HTML page without a dedicated crawler. It runs a cascading pipeline that stops at the first successful method:

1. **JSON-LD** — parses `application/ld+json` `<script>` tags containing `JobPosting` schema. Catches structured data used by Apple, Google, and others.
2. **Embedded JSON** — extracts `__NEXT_DATA__` (Next.js), Gatsby, and inline JSON payloads. Filters candidates through `_looks_like_job_title()` to reject navigation labels, code identifiers, and single-word metadata.
3. **Anchor links** — uses the existing `extract_jobs_from_html()` from `base.py` to find `<a>` tags with job-like hrefs (`/job`, `/career`, `/position`) or job-keyword text. Results are quality-filtered again through `_looks_like_job_title()`.
4. **BS4 heuristic** — scans all `h1`-`h4` and `<a>` tags for job-title keywords (engineer, developer, manager, etc.), skipping navigation phrases ("join", "culture", "sign in"). Extracts nearby location text via sibling traversal.

Each extracted job includes the inferred company name (from the URL host), the extraction source tag (`generic-jsonld`, `generic-embedded`, `generic-anchor`, `generic-heuristic`), and any discovered location text.

## How the Universal Crawler Works

The universal crawler (`crawlers/universal.py`) is a sophisticated multi-strategy engine:

1. **Company URL Resolution** - Maps company names to known career page URLs
2. **ATS Detection** - Detects Lever, Greenhouse, Ashby, Workday, SmartRecruiters from HTML
3. **ATS-Specific API Calls** - Uses dedicated API endpoints for each ATS platform
4. **JSON Discovery** - Scans HTML for embedded JSON data and JSON-LD schemas
5. **Anchor Analysis** - Falls back to parsing job links from HTML anchor elements
6. **Job Enrichment** - Enriches incomplete job data via secondary API requests
7. **Deduplication** - Filters duplicates by job ID across all strategies

## Output Schema

Each job is normalized to this structure:

```json
{
  "id": "sha256_hash_of_apply_url_or_company_title",
  "company": "Amazon",
  "title": "Software Development Engineer",
  "location": "Seattle, WA",
  "description": "Full job description...",
  "employment_type": "Full-time",
  "experience": "Mid-Senior level",
  "skills": ["Java", "AWS", "Distributed Systems"],
  "apply_url": "https://amazon.jobs/...",
  "source": "amazon",
  "crawled_at": "2025-01-15T10:30:00Z"
}
```

## Adding a New Company Crawler

### Option A — Dedicated Crawler (for companies with custom APIs)

1. Create `scrapers/crawlers/<company>.py`
2. Implement an async function matching the signature:
   ```python
   async def crawl_<company>(
       company: str,
       keyword: str | None = None,
       location: str | None = None,
       page: int = 1,
       limit: int = 20,
   ) -> list[dict]:
   ```
3. Register the crawler in `scrapers/crawlers/orchestrator.py`
4. Return a list of job dicts with the standard schema fields

### Option B — No Code Required (Dynamic Generic Scraper)

For any company not in the registry, the routing layer automatically falls through to `GenericScraper`. No registration needed — it extracts jobs from:

- **JSON-LD** structured data (`JobPosting` schema)
- **Embedded JSON** (Next.js, Gatsby, inline scripts)
- **Anchor links** with job-like URLs/text
- **BS4 heuristic** scanning for job title keywords

Test with `--generic-only` to force generic scraping:
```bash
python scrapers/scrape_jobs.py --mode local --generic-only --company-url "https://company-site.com/careers"
```

## Notes

- Rate limiting is handled via `delay-seconds` argument
- The scraper does NOT require MongoDB to be running in `local` mode
- All HTTP requests include retry logic with exponential backoff
- The routing layer logs which scraper was selected: `[INFO] Using scraper: amazon (company-specific)` / `greenhouse (ATS)` / `generic`
- Use `--generic-only` to bypass the routing layer and force the generic scraper
- The generic scraper extracts location text from sibling elements alongside job headings
- Job quality filtering via `_looks_like_job_title()` rejects navigation labels, code identifiers, and single-word metadata
- The universal crawler can handle companies not explicitly listed
