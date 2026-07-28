# End-to-End Data Flow & Scraper Resolution Strategy

## High-Level Flow

```
User Input
  ├── Company Name only (e.g. "accenture")
  │     └── No career page URL needed
  │
  ├── Career Page URL only (e.g. "https://careers.google.com")
  │     └── Bypasses company name lookup
  │
  └── Both Company Name + URL
        └── Uses URL directly, name for labeling

        │
        ▼

  ┌──────────────────────────────────────────────────┐
  │             1. RESOLVE CAREERS PAGE               │
  │  (only needed if no URL was provided directly)    │
  │                                                    │
  │  • Check company_urls.json for known URL           │
  │  • Resolve aliases ("jpm" → "jpmorgan")           │
  │  • Guess URL: https://{company}.com/careers        │
  │  • Try multiple candidate URLs                     │
  │  • Fetch homepage, extract career links from HTML  │
  │                                                    │
  │  Result: careers_url found or fallback generated    │
  └──────────────────────┬───────────────────────────┘
                         │
                         ▼

  ┌──────────────────────────────────────────────────┐
  │           2. DETECT ATS (Applicant Tracking Sys)  │
  │                                                    │
  │  • Check URL/HTML for known ATS patterns:          │
  │    - Lever (jobs.lever.co)                         │
  │    - Greenhouse (boards.greenhouse.io)             │
  │    - Workday (.myworkdayjobs.com)                  │
  │    - Ashby (ashbyhq.com)                           │
  │    - SmartRecruiters (smartrecruiters.com)         │
  │    - Oracle Cloud (...fa.oraclecloud.com)          │
  │                                                    │
  │  Result: ATS detected → use dedicated API crawler  │
  │          No ATS    → use universal fallback chain  │
  └──────────────────────┬───────────────────────────┘
                         │
                         ▼

  ┌──────────────────────────────────────────────────┐
  │       3. EXTRACT JOBS (Multi-Strategy Pipeline)   │
  │                                                    │
  │  ┌─ ATS PATH ──────────────────────────────────┐  │
  │  │  Use platform-specific API (Lever API,       │  │
  │  │  Greenhouse API, Workday CXS, etc.)          │  │
  │  │  Returns structured JSON directly            │  │
  │  └──────────────────────────────────────────────┘  │
  │                                                    │
  │  ┌─ UNIVERSAL PATH ────────────────────────────┐  │
  │  │  Try strategies in parallel (or sequence):   │  │
  │  │                                              │  │
  │  │  1. JSON-LD structured data                  │  │
  │  │     (<script type="application/ld+json">)    │  │
  │  │                                              │  │
  │  │  2. Embedded JSON (__NEXT_DATA__, Gatsby,    │  │
  │  │     inline application/json scripts)         │  │
  │  │                                              │  │
  │  │  3. Discover hidden APIs from HTML            │  │
  │  │     (scan for /api/, /graphql, /wday/cxs/    │  │
  │  │     URLs in <script>, <link>, <a> tags)      │  │
  │  │     → Fetch those APIs for job data          │  │
  │  │                                              │  │
  │  │  4. Enrich jobs via secondary API calls       │  │
  │  │     (fetch individual job details from       │  │
  │  │     discovered API patterns)                 │  │
  │  │                                              │  │
  │  │  5. Anchor link analysis                      │  │
  │  │     (<a> tags with job-like text/href)       │  │
  │  │                                              │  │
  │  │  6. BS4 heuristic (keyword-based fallback)    │  │
  │  │     (find h1/h2/h3 containing engineer,      │  │
  │  │     developer, analyst, etc.)                │  │
  │  │                                              │  │
  │  │  7. Playwright browser render (last resort)   │  │
  │  │     (captures API responses + rendered HTML) │  │
  │  └──────────────────────────────────────────────┘  │
  │                                                    │
  │  Result: list of raw job dicts                      │
  └──────────────────────┬───────────────────────────┘
                         │
                         ▼

  ┌──────────────────────────────────────────────────┐
  │          4. NORMALIZE & DEDUPLICATE               │
  │                                                    │
  │  • Deduplicate by (company + job_id/url/title+loc) │
  │  • Normalize field names (title, location, desc)   │
  │  • Enrich with AI parser (skills, experience)      │
  │  • Filter expired jobs (valid_through check)       │
  │  • Filter by keyword/location if requested         │
  │                                                    │
  │  Result: clean, deduplicated job list              │
  └──────────────────────┬───────────────────────────┘
                         │
                         ▼

  ┌──────────────────────────────────────────────────┐
  │        5. STORE TO DATABASE (optional)             │
  │                                                    │
  │  • Canonicalize to stable schema (SHA-256 ID)      │
  │  • Upsert to MongoDB (idempotent via unique id)    │
  │  • Set crawled_at timestamp                        │
  │  • Create indexes for search                       │
  │                                                    │
  │  Mode: --mode db    → stores to MongoDB             │
  │        --mode local → prints JSON preview only      │
  └──────────────────────┬───────────────────────────┘
                         │
                         ▼

  ┌──────────────────────────────────────────────────┐
  │          6. SERVE VIA API → FRONTEND              │
  │                                                    │
  │  FastAPI endpoints:                                │
  │  • GET /jobs?company=&keyword=&location=&page=     │
  │  • GET /jobs/{company}?keyword=&location=          │
  │  • GET /job/{job_id}                               │
  │  • GET /companies                                  │
  │                                                    │
  │  Caching layer:                                    │
  │  1. Check in-memory TTL cache (15 min)             │
  │  2. If miss → query MongoDB                        │
  │  3. Cache result for next request                  │
  │                                                    │
  │  Frontend (React):                                 │
  │  • HomePage: search form + popular companies        │
  │  • FindJobsPage: filters + paginated results       │
  │  • JobDetailPage: full job info + apply link       │
  └──────────────────────────────────────────────────┘
```

---

## Input Scenarios

### Scenario A: Company Name Only (No URL)

**Goal**: Type `"accenture"` and get jobs. No career page URL needed.

```
Input: "accenture"

Flow:
1. Check company_urls.json → found: "https://www.accenture.com/in-en/careers/jobsearch"
2. Detect ATS on that URL → None (custom careers page)
3. Fetch the careers page HTML
4. Extract jobs using universal pipeline
   a. JSON-LD? No
   b. Embedded JSON? No
   c. Discover APIs? Found job search URL patterns
   d. Extract from anchor links → found job listings
5. Enrich with AI parser
6. Return results
```

### Scenario B: Career Page URL Only

**Goal**: Pass a direct career page URL, bypass company name lookup.

```
Input: "https://jobs.apple.com/en-in/search"

Flow:
1. Skip company_urls.json lookup (URL provided directly)
2. Detect ATS on URL → None (Apple custom)
3. Fetch the page
4. GenericScraper runs extraction pipeline
5. Apple-specific: JSON-LD contains job postings
6. Return results
```

### Scenario C: Company Name + Career Page URL

**Goal**: Specify both for precise targeting.

```
Input: company="google", company_url="https://www.google.com/about/careers/applications/jobs/results/"

Flow:
1. Use provided URL directly
2. Detect ATS → None
3. Fetch page, extract via JSON-LD + embedded JSON
4. Google-specific: _patch_detail_urls for apply URLs
5. Return results
```

### Scenario D: Unknown / New Company Name

**Goal**: Type a company that's never been seen before (e.g. `"stripe"`).

```
Input: "stripe"

Flow:
1. Check company_urls.json → not found
2. Check aliases → not found
3. Generate candidate URLs:
   - https://stripe.com/careers
   - https://www.stripe.com/careers
   - https://careers.stripe.com
   - https://jobs.stripe.com
4. Try each URL until one loads successfully
5. If careers page found on homepage:
   - Extract career links from homepage HTML
   - Follow the first match
6. Detect ATS on resolved URL → Greenhouse
7. Use Greenhouse API: https://boards-api.greenhouse.io/v1/boards/stripe/jobs
8. Return structured job data
```

---

## Resolution Decision Tree

```
START
│
├─ Was a URL provided?
│   YES → Use URL directly
│   NO  → Is company name in company_urls.json?
│           YES → Use known URL
│           NO  → Try to resolve via domain guessing:
│                  1. https://{company}.com/careers
│                  2. https://www.{company}.com/careers
│                  3. https://careers.{company}.com
│                  4. https://{company}.com/jobs
│                  5. https://www.{company}.com (scrape homepage for career links)
│
├─ Resolved URL → Detect ATS
│   ├─ Lever    → https://api.lever.co/v0/postings/{token}
│   ├─ Greenhouse → https://boards-api.greenhouse.io/v1/boards/{token}/jobs
│   ├─ Workday  → POST https://{sub}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs
│   ├─ Ashby    → https://api.ashbyhq.com/posting-api/job-board/{token}
│   ├─ SmartRecruiters → https://api.smartrecruiters.com/v1/companies/{token}/postings
│   ├─ Oracle Cloud → Oracle HCM REST API (findReqs endpoint)
│   └─ None → Universal extraction pipeline
│
├─ Universal Extraction Pipeline
│   1. Try JSON fetch (if URL looks like JSON API)
│   2. Extract JSON-LD from HTML
│   3. Extract embedded JSON (Next.js, Gatsby)
│   4. Discover hidden API URLs from HTML → fetch them
│   5. Enrich jobs by fetching detail pages via API patterns
│   6. Extract from anchor links (<a> tags)
│   7. BS4 heuristic fallback (h1/h2/h3 with job keywords)
│   8. Playwright browser render (if nothing found above)
│
├─ Normalize & Deduplicate
│
└─ Output: Clean job list
```

---

## CLI Usage Examples

```bash
# 1. Company name only (auto-resolve career page)
python scrapers/scrape_jobs.py --companies accenture

# 2. Multiple companies
python scrapers/scrape_jobs.py --companies google,microsoft,stripe

# 3. All known companies
python scrapers/scrape_jobs.py --companies all

# 4. Career page URL only (bypass name resolution)
python scrapers/scrape_jobs.py --company-url "https://careers.google.com"

# 5. Multiple URLs
python scrapers/scrape_jobs.py --company-url "https://careers.google.com,https://jobs.apple.com"

# 6. Generic-only mode (skip ATS routing, force generic scraper)
python scrapers/scrape_jobs.py --generic-only --company-url "https://jobs.apple.com"

# 7. Store to MongoDB
python scrapers/scrape_jobs.py --mode db --companies accenture,google

# 8. With filters
python scrapers/scrape_jobs.py --companies google --keyword "engineer" --location "India"
```

---

## Adding a New Company (No Code Changes Needed)

Just add an entry to `scrapers/company_urls.json`:

```json
{
  "stripe": "https://stripe.com/jobs",
  "netflix": "https://jobs.netflix.com",
  "_aliases": {
    "jpm": "jpmorgan",
    "tata": "tcs"
  }
}
```

After adding, the company becomes available via:
- `--companies stripe`
- `GET /jobs?company=stripe` (API)
- Frontend company filter

If no URL is added, the system will still attempt auto-resolution as in Scenario D.

---

## Where Each Step Happens

| Step | File | Key Functions |
|------|------|---------------|
| URL resolution | `scrapers/crawlers/universal.py` | `_resolve_careers_page()`, `_common_careers_candidates()`, `_first_fetchable_careers_candidate()` |
| ATS detection | `scrapers/crawlers/base.py` | `detect_ats()` |
| Company URL database | `scrapers/company_urls.json` | Static JSON with known company URLs |
| ATS-specific scraping | `scrapers/crawlers/base.py` | `crawl_ats_jobs()` (Lever, Greenhouse, Workday, Ashby, SmartRecruiters, Oracle) |
| Universal extraction | `scrapers/crawlers/universal.py` | `universal_crawl_jobs()` |
| Generic scraping | `scrapers/scrape_jobs.py` | `GenericScraper.fetch_jobs()` |
| CLI entry point | `scrapers/scrape_jobs.py` | `main()` with argparse |
| Orchestration | `scrapers/crawlers/orchestrator.py` | `crawl_jobs()` dispatcher |
| De-duplication | `scrapers/crawlers/universal.py` | `_dedupe_jobs()` |
| Normalization | `app/schemas/job.py` | `canonicalize_job()` |
| AI enrichment | `app/services/ai_parser.py` | `parse_job_details()` |
| MongoDB store | `app/services/job_store.py` | `upsert_jobs()` |
| API endpoints | `app/api/jobs.py` | `get_jobs()`, `get_company_jobs()`, `get_job_detail()` |
| In-memory cache | `app/services/cache.py` | `TTLCache` |
| Frontend | `job-portal/` | React components consuming the API |
