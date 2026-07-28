# Crawler & Scraper Improvement Plan

## Current State

The scraper already has a **multi-strategy extraction pipeline**:

1. **ATS Detection** → Dedicated API crawler (Lever, Greenhouse, Workday, Ashby, SmartRecruiters, Oracle Cloud)
2. **JSON-LD** → Structured `JobPosting` schema extraction
3. **Embedded JSON** → `__NEXT_DATA__`, Gatsby, inline `application/json` scripts
4. **Anchor link analysis** → `<a>` tags with job-like hrefs/text
5. **BS4 Heuristic** → Keyword-based fallback with regex location extraction
6. **API Discovery** → Scans HTML for API-like URLs (`/api/`, `/graphql`, `/wday/cxs/`, etc.)
7. **Secondary API enrichment** → Fetches job detail JSON from discovered API patterns
8. **Playwright fallback** → Browser render for JS-heavy SPAs

**Limitations**: Sequential fallbacks are slow, API discovery is naive (just URL pattern matching), no JS bundle analysis, no sitemap parsing, no learning/adaptation.

---

## Improvement Roadmap

### Phase 1: Smarter API Discovery (Deep Code Inspection)

**Problem**: Current `_extract_candidate_api_urls` only finds URLs containing API-like keywords in HTML. It misses APIs embedded in JavaScript bundles, inline `<script>` blocks, or dynamically constructed at runtime.

#### 1.1 JS Bundle & Inline Script Analysis

- Parse `<script>` contents with AST-level regex for:
  - `fetch("/api/...")`, `axios.get(...)`, `$.ajax(...)`, `new XMLHttpRequest()`
  - Template literals: `` `${baseUrl}/jobs/${id}` ``
  - Object configs: `{ url: "/api/jobs", method: "POST" }`
- Scan loaded JS files (from `<script src="...">`) for the same patterns
- Extract base URLs, endpoint paths, and parameter patterns

#### 1.2 GraphQL Introspection

- If a `/graphql` endpoint is found:
  - Send an introspection query to discover available types/queries/mutations
  - Cache the schema per company
  - Generate valid queries for `jobs`, `positions`, `openings`, `requisitions`

#### 1.3 OpenAPI / Swagger Detection

- Check common paths: `/api/docs`, `/swagger.json`, `/openapi.json`, `/api/v1/openapi.json`
- If found, extract all job-related endpoints automatically

#### 1.4 Sitemap & robots.txt Parsing

- Fetch `/sitemap.xml` and `/robots.txt` for every company
- Extract job listing URLs from sitemap entries
- Parse `Disallow` rules to avoid blocked paths

#### 1.5 Source Map Analysis

- Fetch `.map` files referenced in bundled JS
- Extract original source code to find API endpoints
- Prioritize by file size (larger bundles = more likely to contain API calls)

### Phase 2: Adaptive Pattern Learning

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

### Phase 3: Browser Automation Upgrade

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

### Phase 4: Automation & Scheduling

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

### Phase 5: Extraction Pipeline Optimization

#### 5.1 Parallel Strategy Execution

Current pipeline is sequential: JSON-LD → Embedded → Anchor → BS4 Heuristic.

Change to **parallel**: Run all strategies concurrently, merge results, deduplicate.

```python
async def extract_all(html, url, company):
    results = await asyncio.gather(
        extract_jsonld(html, company),
        extract_embedded(html, company),
        extract_anchors(html, company, url),
        extract_bs4_heuristic(html, company, url),
        return_exceptions=True,
    )
    return deduplicate(flatten(results))
```

#### 5.2 Real Browserless.io / ScrapingBee Integration

- Add support for external rendering services as alternatives to Playwright
- Use when running in Docker (no Chromium needed)

#### 5.3 Adaptive Timeouts & Retries

- Track response times per domain
- Adjust timeouts based on history (faster for fast sites, slower for slow ones)
- Implement circuit breaker: skip a company after N consecutive failures for M minutes

### Phase 6: Monitoring & Observability

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

### Phase 7: Testing & Reliability

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

### Phase 8: Security Hardening

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

### Phase 9: Code Quality & Consistency

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

### Phase 10: Database & Performance

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

### Phase 11: Frontend Improvements

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

## Priority Matrix

| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| 🔴 Rotate exposed MongoDB credentials + remove from git | Low | Critical | P0 |
| 🔴 SSRF prevention (DNS resolution check) | Low | High | P0 |
| 🔴 Fix non-stable `hash()` ID generation | Low | High | P0 |
| 🔴 JS bundle analysis for API discovery | High | High | P0 |
| 🔴 Parallel strategy execution | Low | Medium | P0 |
| Fix CORS Docker config (`["*"]` → `*`) | Low | High | P0 |
| Fix port consistency (8000 vs 10000) | Low | Medium | P0 |
| Add `max_length` to `company_url` param | Low | Medium | P0 |
| Replace `urljoin` with safe URL validator | Low | Medium | P0 |
| Migrate PyMongo → Motor (async driver) | High | High | P1 |
| Pagination auto-detection | Medium | High | P1 |
| API signature profiles (learning) | High | High | P1 |
| Sitemap/robots.txt parsing | Low | Medium | P1 |
| Schedule/automation service | Medium | High | P1 |
| Batch MongoDB upserts (bulk_write) | Low | Medium | P1 |
| HTTP connection pooling | Medium | Medium | P1 |
| Add MongoDB text indexes | Low | High | P1 |
| Wire up `useJobs` hook in frontend | Medium | Medium | P1 |
| Implement server-side filtering | Medium | High | P1 |
| Add React Error Boundary | Low | Medium | P1 |
| Proactive Playwright mode | Low | Medium | P2 |
| GraphQL introspection | Medium | Medium | P2 |
| Circuit breaker pattern | Low | Medium | P2 |
| Metrics dashboard | Medium | Low | P2 |
| Self-healing selectors | High | Medium | P2 |
| Fix rate limiter race condition | Low | Medium | P2 |
| Fix duplicate sleep in retry logic | Low | Low | P2 |
| Frontend cache eviction (LRU) | Low | Medium | P2 |
| Add bundle splitting | Medium | Low | P2 |
| Eliminate duplicate code | Medium | Low | P2 |
| Source map analysis | High | Low | P3 |
| Webhook support | Medium | Medium | P3 |
| OpenAPI detection | Low | Low | P3 |
| Pydantic response models | Medium | Low | P3 |
| Frontend tests | High | Medium | P3 |
| Chaos testing | High | Low | P3 |

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

## Quick Wins (Implement First)

1. **Rotate exposed MongoDB credentials + delete `.env` from git** — CRITICAL security issue
2. **Fix non-stable `hash()` ID generation** — prevents duplicate job entries across restarts
3. **Add `max_length` to `company_url` param** — prevents DoS via oversized URLs
4. **Fix CORS Docker config** — `["*"]` → `*` so CORS works in deployment
5. **Parallel extraction** — minimal code change, immediate speedup
6. **Sitemap/robots.txt parsing** — ~50 lines, discovers job URLs for many sites
7. **Pagination auto-detection** — eliminates hardcoded page params
8. **Fix duplicate sleep in retry logic** — removes accidental double backoff
9. **Replace `urljoin` with safe URL validator** — prevents `javascript:` XSS vector
10. **Add React Error Boundary** — prevents white screen crashes


