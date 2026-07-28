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

---

## Priority Matrix

| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| JS bundle analysis for API discovery | High | High | P0 |
| Parallel strategy execution | Low | Medium | P0 |
| Pagination auto-detection | Medium | High | P1 |
| API signature profiles (learning) | High | High | P1 |
| Sitemap/robots.txt parsing | Low | Medium | P1 |
| Schedule/automation service | Medium | High | P1 |
| Proactive Playwright mode | Low | Medium | P2 |
| GraphQL introspection | Medium | Medium | P2 |
| Source map analysis | High | Low | P3 |
| Webhook support | Medium | Medium | P3 |
| Circuit breaker pattern | Low | Medium | P2 |
| Metrics dashboard | Medium | Low | P2 |
| OpenAPI detection | Low | Low | P3 |

---

## Architecture Changes

```
scrapers/
├── scrape_jobs.py              # CLI entry (unchanged)
├── scheduler.py                # NEW: background scheduler
├── company_urls.json           # Existing
└── crawlers/
    ├── __init__.py
    ├── base.py                 # Existing
    ├── orchestrator.py         # Minor: parallel dispatch
    ├── universal.py            # Minor: parallel extraction
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
```

## Quick Wins (Implement First)

1. **Parallel extraction** — minimal code change, immediate speedup
2. **Sitemap/robots.txt parsing** — ~50 lines, discovers job URLs for many sites
3. **Pagination auto-detection** — eliminates hardcoded page params
4. **Proactive Playwright for known SPAs** — reduces silent empty results
