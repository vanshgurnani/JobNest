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
  scrape_jobs.py         # CLI entry point
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

### All CLI Options

| Argument | Default | Description |
|---|---|---|
| `--mode` | `local` | `local` or `db` |
| `--companies` | `all` | Comma-separated slugs (e.g. `amazon,microsoft`) or `all` |
| `--keyword` | `None` | Keyword filter passed to crawlers |
| `--location` | `None` | Location filter passed to crawlers |
| `--pages` | `2` | Pages per company |
| `--page-size` | `20` | Items per page |
| `--delay-seconds` | `0.5` | Delay between requests (CPU protection) |

## Supported Companies & Crawlers

| Company | Crawler | Strategy |
|---|---|---|
| Amazon | `amazon.py` | Amazon Jobs public `search.json` API |
| Microsoft | `microsoft.py` | Microsoft PCSX API (search + position details + skills) |
| Meta | `meta.py` | MetaCareers GraphQL API + HTML fallback |
| Any other | `universal.py` | Multi-layer ATS detection and API discovery |

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

## Notes

- Rate limiting is handled via `delay-seconds` argument
- The scraper does NOT require MongoDB to be running in `local` mode
- All HTTP requests include retry logic with exponential backoff
- The universal crawler can handle companies not explicitly listed
