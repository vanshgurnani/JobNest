# Crawler & Scraper Improvement Plan

> **Overall Completion: ~45%** (Phases 1-4 done)

## Current State

The scraper already has a **multi-strategy extraction pipeline**:

1. **ATS Detection** → Dedicated API crawler (Lever, Greenhouse, Workday, Ashby, SmartRecruiters, Oracle Cloud) ✅
2. **JSON-LD** → Structured `JobPosting` schema extraction ✅
3. **Embedded JSON** → `__NEXT_DATA__`, Gatsby, inline `application/json` scripts ✅
4. **Anchor link analysis** → `<a>` tags with job-like hrefs/text ✅
5. **BS4 Heuristic** → Keyword-based fallback with regex location extraction ✅
6. **API Discovery** → Scans HTML for API-like URLs (`/api/`, `/graphql`, `/wday/cxs/`, etc.) ✅
7. **JS Bundle Analysis** → `discover_apis()` from `js_analyzer.py` extracts API URLs from inline/external JS ✅ *NEW*
8. **Source Map Analysis** → `extract_sourcemaps()` + `analyze_sourcemap_content()` discovers APIs from `.map` files ✅ *NEW*
9. **Sitemap & robots.txt** → `discover_job_urls()` from `sitemap.py` discovers job URLs ✅ *NEW*
10. **GraphQL Introspection** → `introspect_graphql()` auto-discovers and queries GraphQL endpoints ✅ *NEW*
11. **OpenAPI / Swagger** → `detect_openapi()` finds and queries job endpoints from OpenAPI specs ✅ *NEW*
12. **Secondary API enrichment** → Fetches job detail JSON from discovered API patterns ✅
13. **Playwright fallback** → Browser render for JS-heavy SPAs ✅
14. **Careers link text detection** → Finds career links by visible anchor text ("Join us", "We're hiring", etc.) ✅ *NEW*

**Limitations (remaining):** No monitoring (Phase 6), no advanced testing (Phase 7), security hardening incomplete (Phase 8), code quality issues remain (Phase 9), DB optimizations not done (Phase 10), frontend features not wired (Phase 11).

**Updated Pipeline** (current extraction order in `universal_crawl_jobs`):

```
company name → resolve careers URL
  → ATS API (Lever, Greenhouse, Workday, Ashby, SmartRecruiters, Oracle Cloud)
  → Amazon/Wipro specific crawlers
  → Fetch HTML
  → JSON parse (if careers URL returns JSON directly)
  → ATS detection from HTML
  → GraphQL introspection + OpenAPI/Swagger       ◄ Phase 1
  → JS bundle analysis + sourcemap extraction     ◄ Phase 1
  → JSON API candidates (regex + JS analysis)
  → Fallback (parallel: anchors, embedded JSON, JSON-LD, HTML, sitemap)  ◄ sitemap = Phase 1
  → Enrichment (chain detail API calls)
  → Playwright (JS render)
  → Pagination (try ?page=N, ?p=N, ?offset=N, ?start=N, ?cursor=N)
```

---

## Improvement Roadmap

### Phase 1: Smarter API Discovery (Deep Code Inspection) — ✅ 100% COMPLETE

**Problem**: `_extract_candidate_api_urls` only found URLs containing API-like keywords in HTML. It missed APIs embedded in JavaScript bundles, inline `<script>` blocks, or dynamically constructed at runtime.

#### 1.1 JS Bundle & Inline Script Analysis ✅

- Parse `<script>` contents with AST-level regex for:
  - `fetch("/api/...")`, `axios.get(...)`, `$.ajax(...)`, `new XMLHttpRequest()`
  - Template literals: `` `${baseUrl}/jobs/${id}` ``
  - Object configs: `{ url: "/api/jobs", method: "POST" }`
- Scan loaded JS files (from `<script src="...">`) for the same patterns
- Extract base URLs, endpoint paths, and parameter patterns
- **Integration**: `discover_apis()` called from `_fetch_jobs_from_candidate_apis` in `universal.py`
- **Files**: `scrapers/crawlers/api_discovery/js_analyzer.py` (existing), wired into `universal.py:861`

#### 1.2 GraphQL Introspection ✅

- If a `/graphql` endpoint is found:
  - Send an introspection query to discover available types/queries/mutations
  - Generate valid queries for `jobs`, `positions`, `openings`, `requisitions` and execute them
- **Integration**: New `_try_graphql_and_openapi_discovery()` function called in `universal_crawl_jobs`
- **Files**: `scrapers/crawlers/api_discovery/graphql.py` (existing), wired into `universal.py:1768`

#### 1.3 OpenAPI / Swagger Detection ✅

- Check common paths: `/api/docs`, `/swagger.json`, `/openapi.json`, `/api/v1/openapi.json`
- If found, extract all job-related endpoints automatically
- **Integration**: Same `_try_graphql_and_openapi_discovery()` function handles both
- **Files**: `scrapers/crawlers/api_discovery/swagger.py` (existing), wired into `universal.py:1776`

#### 1.4 Sitemap & robots.txt Parsing ✅

- Fetch `/sitemap.xml` and `/robots.txt` for every company
- Extract job listing URLs from sitemap entries
- For each discovered URL, attempts JSON-LD, HTML, and search URL extraction
- **Integration**: New `_from_sitemap()` strategy inside `_extract_jobs_by_fallback`
- **Files**: `scrapers/crawlers/api_discovery/sitemap.py` (existing), wired into `universal.py:1014`

#### 1.5 Source Map Analysis ✅

- Fetch `.map` files referenced in bundled JS
- Extract original source code to find API endpoints
- **Integration**: `extract_sourcemaps()` + `analyze_sourcemap_content()` called in `_fetch_jobs_from_candidate_apis`
- **Files**: `scrapers/crawlers/api_discovery/sourcemap.py` (existing), wired into `universal.py:871`

### Phase 2: Adaptive Pattern Learning ✅ COMPLETE

**Problem**: The scraper treats every company as a new unknown. Successful patterns from one scrape are never reused.

#### 2.1 API Signature Profiles

- Store discovered API patterns per domain in a JSON file/SQLite:
  ```json
  {
    "greenhouse.io": {
      "base_url": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
      "auth": "none",
      "pagination": "?page={n}",
      "response_path": "$.jobs[*]",
      "field_map": { "title": "title", "location": "location.name" }
    }
  }
  ```
- On next scrape, check if the domain matches a known profile → use saved pattern directly

#### 2.2 Self-Healing Selectors

- When a selector/extraction strategy returns 0 results:
  - Try alternative selectors (CSS classes often change on site updates)
  - Log the failure and mark the selector as stale
  - Auto-retry with AI-generated alternative selectors (e.g., find all `<div>` elements with text matching job keywords)

#### 2.3 Automatic Pagination Detection

- After fetching page 1, analyze response for:
  - `nextPageToken`, `cursor`, `offset`, `page` params
  - `totalPages`, `totalCount`, `hasMore` fields
  - `Link` headers with `rel="next"`
- Store the pagination pattern per company for future scrapes

### Phase 3: Browser Automation Upgrade ✅ COMPLETE

**Problem**: Playwright is used only as a last resort. Many modern career sites are SPAs that require JS execution.

#### 3.1 Proactive Playwright Mode

- New CLI flag: `--browser-first` — uses Playwright immediately for known SPA-heavy sites
- Maintain a list of SPA-detected sites (auto-learned from failed HTTP-only scrapes)

#### 3.2 Network Request Capture

- Use Playwright's request interception to capture all XHR/fetch calls during page load
- Auto-detect which requests return job data by analyzing response payloads
- Replay captured API calls directly (no browser needed for subsequent scrapes)

#### 3.3 Cookie & Session Persistence

- Store cookies per domain after first browser scrape
- Reuse sessions to avoid re-authentication

### Phase 4: Automation & Scheduling ✅ COMPLETE

#### 4.1 Scraper Scheduler Service

```python
# scrapers/scheduler.py
class ScrapeScheduler:
    def __init__(self):
        self.jobs = {
            "amazon": {"interval": 86400, "last_run": None},
            "google": {"interval": 43200, "last_run": None},
            ...
        }

    async def run_loop(self):
        while True:
            for company, config in self.jobs.items():
                if self._should_run(config):
                    await self._scrape_company(company)
            await asyncio.sleep(60)
```

- Runs as a background task in the FastAPI app
- Configurable intervals per company
- Auto-detects stale jobs and prioritizes re-scrape

#### 4.2 Webhook Support

- Accept webhook registrations via API
- Clients get notified when new jobs matching their criteria are scraped
- Implement polling fallback if no webhook transport available

#### 4.3 Intelligent Re-scrape Logic

- Only re-scrape if the careers page has changed (check `Last-Modified` / `ETag`)
- Prioritize companies that historically have high job turnover
- Rate-limit scraping per domain to avoid IP blocks

### Phase 5: Extraction Pipeline Optimization ⬜ NOT STARTED (except 5.1)

#### 5.1 Parallel Strategy Execution ✅ ALREADY DONE

`_extract_jobs_by_fallback` in `universal.py` already runs all strategies in parallel via `asyncio.gather`:

```python
results = await asyncio.gather(
    _from_anchors(),
    _from_embedded(),
    _from_html(),
    _from_jsonld(),
    _from_sitemap(),  # added in Phase 1
    return_exceptions=True,
)
```

#### 5.2 Real Browserless.io / ScrapingBee Integration

- Add support for external rendering services as alternatives to Playwright
- Use when running in Docker (no Chromium needed)

#### 5.3 Adaptive Timeouts & Retries

- Track response times per domain
- Adjust timeouts based on history (faster for fast sites, slower for slow ones)
- Implement circuit breaker: skip a company after N consecutive failures for M minutes

### Phase 6: Monitoring & Observability ⬜ NOT STARTED

#### 6.1 Scrape Metrics Dashboard

- Track per-company: success rate, jobs found, avg response time, strategy used
- Expose `/metrics` endpoint (Prometheus format)

#### 6.2 Failure Classification

```python
FAILURE_TYPES = {
    "BLOCKED": "Received 403/429 — likely IP blocked",
    "CHANGED": "HTML structure changed — selectors stale",
    "TIMEOUT": "Page did not load within timeout",
    "NO_JOBS": "Scrape succeeded but 0 jobs found",
    "PARSE_ERROR": "Response was not parseable as expected",
}
```

- Classify failures and auto-adjust strategy
- Alert on BLOCKED / CHANGED patterns

#### 6.3 Scrape Audit Log

- Log every scrape attempt to MongoDB: company, timestamp, duration, jobs found, strategy used, errors
- Queryable from the API for debugging

### Phase 7: Testing & Reliability ⬜ NOT STARTED

#### 7.1 Snapshot Testing

- Save HTML snapshots of known career pages
- Test that extraction strategies continue to work after code changes
- Auto-detect when a snapshot's structure has drifted (site redesign)

#### 7.2 Integration Tests with Mock Server

- Set up a mock HTTP server that serves test career pages
- Test the full pipeline: URL → HTML → extracted jobs
- Test ATS-specific crawlers with realistic mock responses

#### 7.3 Chaos Testing

- Randomly inject failures (timeouts, 403s, malformed HTML)
- Verify fallback chains work correctly

### Phase 8: Security Hardening ⬜ NOT STARTED

#### 8.1 Rotate & Remove Hardcoded Credentials

- Immediately rotate the MongoDB password (`iz64rqtBBQss8iQ7`)
- Remove `.env` from git history (`git filter-branch` / `git filter-repo`)
- Add `.env` to `.gitignore` (verify it's already there but file was force-tracked)

#### 8.2 SSRF Prevention

- Add DNS resolution check to `is_safe_url` — resolve the hostname and verify IP is not private
- Add allowlist of permitted domains for scraping
- Add timeout to DNS resolution to prevent hanging

#### 8.3 Input Validation & Sanitization

- Add `max_length` to `company_url` query parameter
- Add regex pattern validation for `job_id` path parameter
- Validate URLs from scraped HTML before passing to `urljoin` (reject `javascript:`, `data:`, `vbscript:`)

#### 8.4 Move from PyMongo to Motor (Async Driver)

- Replace `pymongo.MongoClient` with `motor.motor_asyncio.AsyncIOMotorClient`
- Remove all `asyncio.to_thread()` wrappers around DB operations
- Add `motor` to `requirements.txt`

#### 8.5 Fix Rate Limiter Race Condition

- Add `asyncio.Lock` around rate limiter state mutations
- Consider using a shared Redis-backed rate limiter for multi-worker deployments

### Phase 9: Code Quality & Consistency ⬜ NOT STARTED

#### 9.1 Eliminate Duplicate Code

- Extract `timeAgo` to a shared utility in `job-portal/src/utils/`
- Consolidate `_company_name_from_url` into one importable location
- Consolidate `detect_ats` into a single implementation
- Consolidate `supported_companies` loading into a shared module

#### 9.2 Fix Non-Stable Job ID Generation

- Replace `abs(hash(title + location + source))` with `hashlib.sha256()` based ID in `normalizer.py`
- This matches the approach already used in `canonicalize_job` in `schemas/job.py`

#### 9.3 Use Pydantic Response Models in API

- Apply the existing `Job` Pydantic model as `response_model` in FastAPI route decorators
- Ensure consistent `job`/`jobs` key naming across all endpoints

#### 9.4 Fix the CORS Docker Configuration

- Change `CORS_ORIGINS=["*"]` to `CORS_ORIGINS=*` (without brackets) or set proper origin values
- Verify `config.py` parsing handles both formats correctly

#### 9.5 Add Type Safety

- Replace `dict[str, Any]` with TypedDicts for job payload types
- Add concrete return type annotations to all functions
- Run `mypy` in CI

### Phase 10: Database & Performance ⬜ NOT STARTED

#### 10.1 MongoDB Index Optimization

- Add compound text index on `title`, `skills`, `location` for keyword search
- Add index on `location` for location-only queries
- Add indexes for `users`, `saved_jobs`, `search_history` collections

#### 10.2 Batch Database Operations

- Replace individual `update_one()` calls with `bulk_write()` using `UpdateOne` operations
- Apply the same fix to migration script

#### 10.3 HTTP Connection Pooling

- Create a shared `httpx.AsyncClient` singleton per domain instead of per-request clients
- Configure connection limits (`max_connections`, `max_keepalive_connections`)
- Use client lifecycle management in the scraper

#### 10.4 Fix Duplicate Sleep in Retry Logic

- Remove the redundant `await asyncio.sleep(...)` call in `request_json_with_retries`

#### 10.5 Frontend Cache Eviction

- Add LRU eviction to the frontend `cacheRef` Map (limit to e.g. 50 entries)
- Or migrate to a proper caching library

### Phase 11: Frontend Improvements ⬜ NOT STARTED

#### 11.1 Wire Up `useJobs` Hook

- Replace manual data fetching in `FindJobsPage` with the existing `useJobs` hook (which has caching + race condition safety)
- Remove redundant re-fetch logic

#### 11.2 Implement Server-Side Filtering

- Add `employment_type` and `experience` query params to backend API
- Send filter values from frontend to backend
- Remove unused filter fields (`type`, `salary`) or implement them

#### 11.3 Add React Error Boundary

- Wrap the app in an Error Boundary component
- Show a fallback UI instead of white screen on component crashes

#### 11.4 Add Bundle Splitting

- Use `React.lazy()` + `Suspense` for route-level code splitting
- Lazy load heavy dependencies

#### 11.5 Fix Vite Proxy Configuration

- Align proxy target port with Docker port or make it configurable via env var
- Use relative API paths (`/api/jobs`) instead of hardcoded `localhost:8000` in `.env`

---

## Priority Matrix — Updated with Completion Status

| Feature | Effort | Impact | Priority | Status |
|---------|--------|--------|----------|--------|
| 🔴 Rotate exposed MongoDB credentials + remove from git | Low | Critical | P0 | ⬜ |
| 🔴 SSRF prevention (DNS resolution check) | Low | High | P0 | ⬜ |
| 🔴 Fix non-stable `hash()` ID generation | Low | High | P0 | ⬜ |
| 🔴 JS bundle analysis for API discovery | High | High | P0 | ✅ |
| 🔴 Parallel strategy execution | Low | Medium | P0 | ✅ |
| Fix CORS Docker config (`["*"]` → `*`) | Low | High | P0 | ⬜ |
| Fix port consistency (8000 vs 10000) | Low | Medium | P0 | ⬜ |
| Add `max_length` to `company_url` param | Low | Medium | P0 | ⬜ |
| Replace `urljoin` with safe URL validator | Low | Medium | P0 | ⬜ |
| Migrate PyMongo → Motor (async driver) | High | High | P1 | ⬜ |
| Pagination auto-detection | Medium | High | P1 | ⬜ |
| API signature profiles (learning) | High | High | P1 | ⬜ |
| Sitemap/robots.txt parsing | Low | Medium | P1 | ✅ |
| Schedule/automation service | Medium | High | P1 | ⬜ |
| Batch MongoDB upserts (bulk_write) | Low | Medium | P1 | ⬜ |
| HTTP connection pooling | Medium | Medium | P1 | ⬜ |
| Add MongoDB text indexes | Low | High | P1 | ⬜ |
| Wire up `useJobs` hook in frontend | Medium | Medium | P1 | ⬜ |
| Implement server-side filtering | Medium | High | P1 | ⬜ |
| Add React Error Boundary | Low | Medium | P1 | ⬜ |
| Proactive Playwright mode | Low | Medium | P2 | ⬜ |
| GraphQL introspection | Medium | Medium | P2 | ✅ |
| Circuit breaker pattern | Low | Medium | P2 | ⬜ |
| Metrics dashboard | Medium | Low | P2 | ⬜ |
| Self-healing selectors | High | Medium | P2 | ⬜ |
| Fix rate limiter race condition | Low | Medium | P2 | ⬜ |
| Fix duplicate sleep in retry logic | Low | Low | P2 | ⬜ |
| Frontend cache eviction (LRU) | Low | Medium | P2 | ⬜ |
| Add bundle splitting | Medium | Low | P2 | ⬜ |
| Eliminate duplicate code | Medium | Low | P2 | ⬜ |
| Source map analysis | High | Low | P3 | ✅ |
| Webhook support | Medium | Medium | P3 | ⬜ |
| OpenAPI detection | Low | Low | P3 | ✅ |
| Pydantic response models | Medium | Low | P3 | ⬜ |
| Frontend tests | High | Medium | P3 | ⬜ |
| Chaos testing | High | Low | P3 | ⬜ |

---

## Architecture Changes

```
scrapers/
├── scrape_jobs.py              # CLI entry (minor fixes: stable ID gen, url validation)
├── scheduler.py                # NEW: background scheduler
├── company_urls.json           # Existing
└── crawlers/
    ├── __init__.py
    ├── base.py                 # FIX: HTTP pooling, retry sleep, safe urljoin, detect_ats dedup
    ├── orchestrator.py         # Minor: parallel dispatch
    ├── universal.py            # FIX: ensure_company_urls lock, parallel extraction
    ├── api_discovery/
    │   ├── __init__.py
    │   ├── js_analyzer.py      # NEW: JS bundle / AST analysis
    │   ├── graphql.py          # NEW: introspection queries
    │   ├── sitemap.py          # NEW: sitemap/robots parsing
    │   ├── swagger.py          # NEW: OpenAPI detection
    │   └── sourcemap.py        # NEW: source map extraction
    ├── learning/
    │   ├── __init__.py
    │   ├── profile_store.py    # NEW: API signature profiles
    │   ├── selector_learner.py # NEW: self-healing selectors
    │   └── pagination.py       # NEW: pagination pattern detection
    └── monitoring/
        ├── __init__.py
        ├── metrics.py          # NEW: Prometheus metrics
        └── audit.py            # NEW: scrape audit logger

app/
├── main.py                     # FIX: add Error Boundary, serve frontend in prod
├── config.py                   # FIX: add JWT settings, fix CORS parsing
├── api/jobs.py                 # FIX: max_length validation, Pydantic responses, consistent shapes
├── schemas/
│   ├── job.py                  # Existing (canonicalize_job stays)
│   └── user.py                 # NEW: UserCreate, UserLogin, UserPublic, TokenResponse
├── db/mongo.py                 # FIX: migrate to Motor, add indexes, fix ping timeout
└── services/
    ├── job_store.py            # FIX: bulk_write, Motor async, add indexes
    ├── cache.py                # FIX: add logging on hit/miss/eviction
    ├── ai_parser.py            # Existing
    ├── normalizer.py           # FIX: stable hashlib-based ID
    └── security.py             # FIX: DNS rebinding check, rate limiter lock

job-portal/src/
├── utils/
│   └── timeAgo.js              # NEW: shared utility
├── hooks/
│   └── useJobs.js              # FIX: LRU eviction
├── components/
│   ├── ErrorBoundary.jsx       # NEW
│   └── Filters.jsx             # FIX: remove unused fields
├── pages/
│   ├── FindJobsPage.jsx        # FIX: use useJobs hook, send filters to API
│   └── JobDetailPage.jsx       # FIX: import timeAgo from utils, noopener
├── .env                        # FIX: use relative API paths
└── vite.config.js              # FIX: align proxy target with Docker port
```

## Quick Wins — Progress

| # | Task | Status |
|---|------|--------|
| 1 | Rotate exposed MongoDB credentials + delete `.env` from git | ⬜ |
| 2 | Fix non-stable `hash()` ID generation | ⬜ |
| 3 | Add `max_length` to `company_url` param | ⬜ |
| 4 | Fix CORS Docker config (`["*"]` → `*`) | ⬜ |
| 5 | **Parallel extraction** — already done in `_extract_jobs_by_fallback` | ✅ |
| 6 | **Sitemap/robots.txt parsing** — integrated into `_extract_jobs_by_fallback` | ✅ |
| 7 | Pagination auto-detection | ⬜ |
| 8 | Fix duplicate sleep in retry logic | ⬜ |
| 9 | Replace `urljoin` with safe URL validator | ⬜ |
| 10 | Add React Error Boundary | ⬜ |

## Completed in This Session

**Phase 1 (Smarter API Discovery)** — all 5 modules integrated into the live scraping pipeline:

| Module | Integration Point | What It Does |
|--------|-------------------|-------------|
| `sitemap.py` | `_extract_jobs_by_fallback` → `_from_sitemap()` | Fetches sitemaps/robots.txt, discovers job URLs |
| `graphql.py` | `_try_graphql_and_openapi_discovery()` | Introspects GraphQL endpoints, executes job queries |
| `swagger.py` | `_try_graphql_and_openapi_discovery()` | Detects OpenAPI specs, fetches job endpoints |
| `js_analyzer.py` | `_fetch_jobs_from_candidate_apis` | Extracts API URLs from inline/external JS bundles |
| `sourcemap.py` | `_fetch_jobs_from_candidate_apis` | Analyzes JS sourcemaps for hidden API endpoints |

Plus: `_extract_official_career_links` improved to detect career links by visible anchor text.

**Phases 2-4** — all implemented in the same session:

| Phase | Module | What It Does |
|-------|--------|-------------|
| 2.1 | `learning/profile_store.py` | Saves API URL patterns, response paths, field maps per domain; reuses on next scrape |
| 2.2 | `learning/selector_learner.py` | `guess_alternative_selectors()` finds job-like text when primary extraction fails |
| 2.3 | `learning/pagination.py` | Auto-detects pagination params from URL/JSON; integrated into `universal_crawl_jobs` |
| 3.1 | `scrape_jobs.py` | `--browser-first` CLI flag for proactive Playwright mode |
| 3.2 | `universal.py` → `_extract_jobs_with_playwright` | Captures all XHR/fetch during page load, replays pagination via HTTP |
| 3.3 | `learning/cookie_store.py` | Persists cookies per domain to `cookies.json`; auto-applies on subsequent scrapes |
| 4.1 | `scheduler.py` | `ScrapeScheduler` background task with configurable intervals, priority queue |
| 4.2 | `scheduler.py` → `notify_webhooks()` | POSTs new jobs to registered URLs from `webhooks.json` |
| 4.3 | `learning/etag_store.py` | Stores ETag/Last-Modified; scheduler checks via HEAD before re-scraping |


