# AI Job Intelligence Crawler

A lightweight **FastAPI** backend that fetches real-time job data for **Amazon, Microsoft, and Meta** using their available public/undocumented endpoints and returns **normalized job payloads**.

- **No database** (fresh crawl on each request)
- **Concurrent crawling** (one crawler failure does not break the others)
- **Python 3.11** + async HTTP (`httpx`)

> Note: Crawling strategies rely on endpoints discovered/observed via network inspection and may change.

---

## Features

- `GET /jobs` returns aggregated job results across supported companies
- `GET /jobs/{company}` returns results for a single company; unsupported companies use the universal fallback crawler
- Concurrent orchestrator with per-company error isolation
- Normalization into a common schema:
  - company, job_id, title, location, description, skills, employment_type, experience, apply_url, source
- Enrichment step:
  - `app/services/ai_parser.py` backfills `skills` and `experience` from the job title when missing

---

## Project Structure

```text
app/
  api/
    jobs.py                 # API routes (/health, /jobs, /jobs/{company})
  crawler/
    orchestrator.py         # Runs crawlers concurrently + enrichment
    base.py                # Shared helpers: HTTP retries, normalization, HTML parsing, ATS utilities
    amazon.py              # Amazon jobs via search.json API
    microsoft.py           # Microsoft jobs via PCSX JSON endpoints
    meta.py                # Meta jobs via GraphQL + per-job detail parsing
  services/
    ai_parser.py           # Heuristic parsing from job title (skills/experience)
    normalizer.py          # Additional normalization utility
  schemas/
    job.py                 # Pydantic Job model
main.py                     # FastAPI app wiring
run.py                       # Uvicorn entrypoint
Dockerfile                   # Container build
tests/
  test_crawlers.py           # Unit test for HTML anchor job link extraction
requirements.txt
```

---

## API

### `GET /health`
Health check endpoint.

**Response**
```json
{ "status": "running" }
```

### `GET /jobs`
Aggregates jobs across all supported companies.

**Query params (optional):**
- `company`: if provided, crawls only that company (e.g. `amazon`)
- `company_url`: optional official company careers/base URL for unsupported companies
- `keyword`: overrides default query keyword used by that company crawler
- `location`: overrides default location used by that company crawler
- `page`: 1-indexed pagination page (default: `1`)
- `limit`: number of jobs to return for the page (default: `20`, max: `100`)


**Response format**
```json
{
  "total": 123,
  "latest_jobs": [ ... ],
  "jobs": [ ... ]
}
```

### `GET /jobs/{company}`
Crawls a single company.

**Path params**
- `company`: any company name. `amazon`, `microsoft`, and `meta` use dedicated crawlers; others use the universal fallback.

**Query params (optional):**
- `company_url`: optional official company careers/base URL for unsupported companies
- `keyword`, `location`
- `page`: 1-indexed pagination page (default: `1`)
- `limit`: number of jobs to return for the page (default: `20`, max: `100`)


**Response format**
```json
{
  "company": "Amazon",
  "jobs": [ ... ]
}
```

---

## Crawling Logic (High Level)

### Orchestrator: `app/crawler/orchestrator.py`
- Maintains a registry:
  - `amazon` → `fetch_amazon_jobs`
  - `microsoft` → `fetch_microsoft_jobs`
  - `meta` → `fetch_meta_jobs`
- If `company` is provided:
  - runs only that crawler
- If `company` is not in the registry:
  - resolves an official careers page or uses `company_url`
  - detects Greenhouse, Lever, Workday, SmartRecruiters, and Ashby
  - falls back through JSON APIs, embedded JSON, HTML job links, and JSON-LD JobPosting data
- Otherwise:
  - runs all crawlers concurrently via `asyncio.gather`
  - failures are isolated per company using `_safe_crawl()`
- After crawling, `_enrich_jobs()` backfills `skills` and `experience` from the job title when missing.

### Shared utilities: `app/crawler/base.py`
Key responsibilities:
- `request_with_retries()` / `request_json_with_retries()`
  - async HTTP with retries + exponential backoff
- `normalize_job_payload()`
  - maps raw fields from each crawler into a common schema
- `extract_jobs_from_html()`
  - scans HTML for candidate `<a href=...>` links that look like job links
  - validated by `tests/test_crawlers.py`
- ATS utilities (`detect_ats()`, `crawl_ats_jobs()`)
  - support for known ATS platforms via public APIs (present in shared code)

---

## Company Implementations

### Amazon: `app/crawler/amazon.py`
- Uses Amazon’s `search.json` endpoint.
- Paginates with `page=1..max_pages`.
- Builds a detailed description from description + basic/preferred qualifications.
- Normalizes each job via `normalize_job_payload(...)`.

### Microsoft: `app/crawler/microsoft.py`
- Uses internal JSON endpoints discovered via Playwright inspection:
  - search endpoint returns positions
  - details endpoint returns full description
  - insights endpoint returns skills
- Fetches details concurrently in small batches (size 5) to reduce throttling.
- Normalizes into common schema.

### Meta: `app/crawler/meta.py`
- Step 1: `GET https://www.metacareers.com/jobsearch/`
  - extracts an embedded **LSD token**
- Step 2: `POST https://www.metacareers.com/graphql`
  - uses `doc_id = 27129360303422352`
  - critical detail: `results_per_page` **must be null**
- Step 3: for each returned job id:
  - fetches job detail page
  - parses **Schema.org JobPosting JSON-LD** to extract description and related fields
- Normalizes each job into common schema.

---

## Data Model

`app/schemas/job.py` defines a Pydantic model:

- `id: str`
- `company: str`
- `title: str`
- `location: str`
- `description: str`
- `employment_type: str`
- `experience: str`
- `skills: list[str]`
- `url: str`
- `source: str`

Crawlers currently return plain dicts, but normalization/enrichment is designed to match these concepts.

---

## Testing

`tests/test_crawlers.py`
- Validates `extract_jobs_from_html()` prioritization of anchors that look like job links
- Ensures `location_hint` propagation

Run tests:
```bash
pytest -q
```

---

## Backend Flow (End-to-End)

1. **HTTP request** hits one of the routes in `app/api/jobs.py`:
   - `GET /health`
   - `GET /jobs`
   - `GET /jobs/{company}`
2. The route calls `crawl_jobs(...)` from `app/crawler/orchestrator.py`, forwarding:
   - `company`, `company_url`
   - `keyword`, `location`
   - `page`, `limit`
3. The **orchestrator** decides which crawler(s) to run:
   - If `company_url` is provided but `company` is not, it infers a company name from the URL and uses the universal crawler.
   - If `company` is one of the dedicated crawlers (`amazon`, `microsoft`, `meta`), it runs that crawler.
   - If `company` is unknown, it uses the universal fallback/ATS-based approach.
   - When `company` is not provided, it runs supported crawlers **concurrently** via `asyncio.gather`.
   - Each company crawl is wrapped by `_safe_crawl()` so failures are isolated per company.
4. Each company crawler fetches raw job data and returns **normalized** job dicts using shared helpers in `app/crawler/base.py`.
5. After crawling, the orchestrator enriches the normalized jobs:
   - `_enrich_jobs()` uses `app/services/ai_parser.py` to backfill `skills` / `experience` from the job title when missing.
6. Pagination semantics:
   - The API passes `page` and `limit` into each crawler.
   - Crawler implementations apply pagination when possible; for Meta, the Playwright-collect-then-slice approach is used (`start=(page-1)*limit`, `raw_jobs[start:start+limit]`).
7. The API returns:
   - aggregated results for `GET /jobs` (`total`, `latest_jobs`, `jobs`, plus `page`/`limit`)
   - a single company’s result set for `GET /jobs/{company}` (`company`, `total`, `jobs`, plus `page`/`limit`).


---

## Local Setup / Run


```bash
cd /Users/vansh-gurnani/Desktop/job
python3 -m pip install -r requirements.txt
python3 run.py
```

Open:
- http://localhost:8000/health
- http://localhost:8000/jobs
- http://localhost:8000/jobs/amazon

Run tests:
```bash
PYTHONPATH=. pytest -q
```


---

## Docker

Build and run:
```bash
docker build -t job-crawler .
docker run -p 8000:8000 job-crawler
```

Then open:
- http://localhost:8000/health
- http://localhost:8000/jobs

---

## Notes / Caveats

- Crawling relies on endpoints that may change without notice.
- No persistence is used; each request triggers a fresh crawl.
- Network failures are handled with retries and per-company failure isolation.
- `ai_parser` is heuristic (keyword-based), not an actual ML model.

---

## Main Files (Quick Reference)

- `run.py` – runs Uvicorn
- `app/main.py` – FastAPI app initialization
- `app/api/jobs.py` – routes
- `app/crawler/orchestrator.py` – concurrency + enrichment
- `app/crawler/amazon.py`, `app/crawler/microsoft.py`, `app/crawler/meta.py` – crawlers
- `app/crawler/base.py` – HTTP helpers + normalization
- `app/services/ai_parser.py` – heuristic parsing
- `tests/test_crawlers.py` – unit test
