# Product-Level Universal Company Career Scraper — AI Coding Prompt

## Master Prompt

You are a senior distributed-systems and web-scraping architect. I already have a working job-scraping project with company-specific crawlers and a universal ATS-aware crawler. Do **not** rebuild the project from scratch. Refactor and extend the existing architecture into a **production-grade universal company career-page discovery and job-ingestion platform**.

The core product goal is:

> Given a company name, company domain, or career-page URL, automatically discover the company's official careers portal, identify what career/job platform powers it, discover all relevant job-listing endpoints/pages, crawl the jobs, normalize them into one canonical schema, and continue working across companies with different websites, ATS providers, custom portals, APIs, JavaScript applications, and changing page structures.

The system must be designed around **adapters, detection, discovery, normalization, resilience, observability, and extensibility**, rather than maintaining one scraper per company.

---

# 1. Target Architecture

Design the scraper as these logical layers:

```text
Input
  │
  ▼
Company Resolver
  │
  ├── company name → official domain discovery
  ├── domain → careers URL discovery
  └── supplied careers URL → validation
  │
  ▼
Career Portal Discovery
  │
  ├── robots.txt / sitemap
  ├── internal-link discovery
  ├── careers/jobs URL heuristics
  ├── structured metadata
  └── search-engine-assisted discovery where appropriate
  │
  ▼
Portal / ATS Detector
  │
  ├── Lever
  ├── Greenhouse
  ├── Ashby
  ├── Workday
  ├── SmartRecruiters
  ├── iCIMS
  ├── Workable
  ├── Jobvite
  ├── BambooHR
  ├── Recruitee
  ├── Teamtailor
  ├── Pinpoint
  ├── SuccessFactors
  ├── Taleo
  ├── custom API
  ├── custom JavaScript portal
  └── unknown/custom
  │
  ▼
Capability Detection
  │
  ├── public API
  ├── GraphQL
  ├── embedded JSON
  ├── JSON-LD
  ├── HTML
  ├── XHR/fetch endpoints
  ├── pagination
  ├── cursor pagination
  ├── infinite scroll
  └── browser-only rendering
  │
  ▼
Crawler / Adapter
  │
  ▼
Job Discovery
  │
  ▼
Job Detail Extraction
  │
  ▼
Canonical Normalizer
  │
  ▼
Validation + Deduplication
  │
  ▼
Persistence
  │
  ├── raw crawl data
  ├── normalized jobs
  ├── company profiles
  ├── portal metadata
  └── crawl history / errors
```

---

# 2. Important Design Principle

Do NOT create a huge `if company == ...` router.

Use:

```text
Company
   ↓
Portal Detection
   ↓
Adapter Selection
   ↓
Capability-based crawling
```

Company-specific crawlers should only exist when a company exposes a genuinely unique API/protocol that cannot reasonably be handled by a generic adapter.

The architecture should allow a new ATS/provider to be added by implementing an adapter rather than modifying the entire scraper.

---

# 3. Adapter Architecture

Create a common interface similar to:

```python
class CareerPortalAdapter(ABC):

    async def detect(self, context) -> DetectionResult:
        ...

    async def discover_jobs(self, context) -> AsyncIterator[JobReference]:
        ...

    async def fetch_job(self, reference) -> RawJob:
        ...

    async def normalize(self, raw_job) -> Job:
        ...
```

Do not blindly copy this exact interface if the existing project has a better abstraction. Preserve compatibility with the current architecture.

Adapters should support:

- API-based crawling
- REST
- GraphQL
- embedded JSON
- JSON-LD
- HTML extraction
- JavaScript-rendered pages
- pagination
- cursor pagination
- infinite scrolling
- job-detail URL discovery
- sitemap discovery
- search/filter endpoints

---

# 4. Detection Engine

Build a deterministic portal-detection pipeline.

Detection signals should include:

### URL signals

Examples:

```text
boards.greenhouse.io
jobs.lever.co
jobs.ashbyhq.com
myworkdayjobs.com
smartrecruiters.com
icims.com
workable.com
jobvite.com
bamboohr.com
recruitee.com
teamtailor.com
```

### HTML signals

Inspect:

- script sources
- iframe URLs
- canonical URLs
- meta tags
- form actions
- known CSS/classes
- `data-*` attributes
- embedded JSON
- JSON-LD
- API URLs
- GraphQL endpoints
- external recruitment domains

### Network signals

When browser rendering is required, inspect:

- XHR
- fetch
- GraphQL
- API responses
- pagination requests
- job-detail requests

Return:

```json
{
  "provider": "...",
  "confidence": 0.0,
  "signals": [],
  "capabilities": []
}
```

Do not rely on a single detection signal.

---

# 5. Career Page Discovery

The system should accept:

```text
company name
company domain
company careers URL
```

For company names/domains, implement a company-resolution stage.

Discover the official careers page using multiple strategies:

1. Known company metadata
2. Homepage crawling
3. Internal links
4. `/careers`
5. `/career`
6. `/jobs`
7. `/join-us`
8. `/work-with-us`
9. `/opportunities`
10. sitemap.xml
11. robots.txt
12. structured metadata
13. external career-platform links

The discovery engine should return:

```json
{
  "company": "...",
  "official_domain": "...",
  "careers_url": "...",
  "confidence": 0.0,
  "discovery_method": "...",
  "alternatives": []
}
```

Do not assume every company follows the same URL pattern.

---

# 6. Universal Fallback Crawler

Create a strong fallback for unknown/custom career portals.

Fallback priority:

```text
Known API
↓
XHR/fetch discovery
↓
Embedded JSON
↓
JSON-LD
↓
Sitemap
↓
Job-listing links
↓
HTML semantic extraction
↓
Playwright rendered DOM
```

The fallback should attempt to identify:

- job cards
- job URLs
- job IDs
- titles
- locations
- departments
- employment type
- posting dates
- descriptions
- requirements
- compensation
- application URL

It must not depend on fixed CSS selectors wherever possible.

---

# 7. Job Schema

Define one canonical schema independent of the source.

Recommended structure:

```text
Job
├── identity
│   ├── job_id
│   ├── source_job_id
│   ├── canonical_url
│   └── apply_url
│
├── company
│   ├── company_id
│   ├── company_name
│   └── company_domain
│
├── role
│   ├── title
│   ├── department
│   ├── team
│   ├── employment_type
│   ├── seniority
│   └── workplace_type
│
├── location
│   ├── city
│   ├── state
│   ├── country
│   ├── remote
│   └── locations[]
│
├── compensation
│   ├── salary_min
│   ├── salary_max
│   ├── currency
│   └── raw_salary
│
├── content
│   ├── description
│   ├── responsibilities
│   ├── qualifications
│   ├── preferred_qualifications
│   └── benefits
│
├── timestamps
│   ├── posted_at
│   ├── updated_at
│   ├── scraped_at
│   └── expires_at
│
└── source
    ├── portal
    ├── adapter
    ├── extraction_method
    └── raw_payload_reference
```

Keep the raw source payload separately so normalization never destroys original data.

---

# 8. Company Profile Model

The product should maintain a company-level profile separately from jobs.

Suggested model:

```text
Company
├── identity
│   ├── company_id
│   ├── name
│   ├── legal_name
│   ├── domain
│   └── aliases[]
│
├── career
│   ├── careers_url
│   ├── portal_provider
│   ├── portal_type
│   ├── detection_confidence
│   └── last_verified_at
│
├── crawling
│   ├── adapter
│   ├── crawl_strategy
│   ├── capabilities
│   ├── last_crawl_at
│   ├── last_success_at
│   └── crawl_status
│
└── metadata
    ├── logo
    ├── industry
    ├── locations
    └── source_metadata
```

---

# 9. Deduplication

Implement multiple deduplication levels.

### Job identity

Prefer:

```text
provider + source_job_id
```

Fallback:

```text
canonical_url
```

Fallback:

```text
company + normalized_title + normalized_location
```

Normalize:

- URL parameters
- trailing slashes
- tracking parameters
- title whitespace
- Unicode
- location formatting

The same job appearing through multiple career pages should not create duplicate records.

---

# 10. Incremental Crawling

Do not scrape every job detail unnecessarily on every run.

Maintain crawl state:

```text
company
portal
last_crawl
last_success
etag
last_modified
job count
known job IDs
crawl hash
```

Support:

- new-job detection
- changed-job detection
- removed/expired-job detection
- periodic full refresh
- incremental refresh

Use content hashes where useful.

---

# 11. Failure Handling

A production scraper must expect:

- timeout
- 403
- 429
- CAPTCHA
- bot protection
- malformed HTML
- changed selectors
- API changes
- JavaScript-only rendering
- empty responses
- temporary 5xx errors
- expired URLs
- redirect chains
- geo-specific pages

Implement:

```text
retry
→ exponential backoff
→ adapter fallback
→ browser fallback
→ mark crawl degraded
→ record structured error
```

Do not endlessly retry.

Never bypass authentication, CAPTCHA, or access controls. Respect robots.txt, provider terms, rate limits, and applicable laws.

---

# 12. Browser Strategy

Use HTTP clients first for speed and scale.

Use Playwright only when required.

Recommended strategy:

```text
HTTP
 ↓
HTML/JSON inspection
 ↓
API detection
 ↓
Playwright only if necessary
```

The browser layer should support:

- request interception
- response inspection
- network endpoint discovery
- JavaScript rendering
- pagination
- infinite scrolling
- lazy-loaded jobs

Avoid launching a browser for every individual job when the listing API already exposes complete data.

---

# 13. Rate Limiting and Politeness

Implement per-domain controls:

```text
request rate
concurrency
delay
retry budget
timeout
```

Do not use aggressive parallelism by default.

Have a configurable domain-level rate limiter so thousands of companies can be crawled without overwhelming individual sites.

---

# 14. Observability

Every crawl should produce structured metrics:

```text
crawl_started
crawl_finished
crawl_duration
company
portal
adapter
requests
successful_requests
failed_requests
jobs_discovered
jobs_parsed
jobs_inserted
jobs_updated
jobs_removed
duplicates
fallback_count
browser_used
errors
```

Use structured logging rather than random `print()` statements.

Add crawl IDs so a complete crawl can be traced.

---

# 15. Adapter Registry

Create an adapter registry:

```text
AdapterRegistry
├── greenhouse
├── lever
├── ashby
├── workday
├── smartrecruiters
├── icims
├── workable
├── jobvite
├── bamboohr
├── recruitee
├── teamtailor
├── pinpoint
├── successfactors
├── taleo
├── custom_api
└── universal
```

Selection should be based on detection capabilities rather than company name.

---

# 16. API / Service Boundary

Keep scraping independent from the FastAPI API layer.

Recommended:

```text
FastAPI
  │
  ├── Company API
  ├── Job API
  ├── Search API
  └── Crawl API
        │
        ▼
     Queue / Job Runner
        │
        ▼
   Crawl Orchestrator
        │
        ▼
   Adapter Registry
        │
        ▼
      Adapters
```

The API should never contain scraping logic.

---

# 17. Queue / Background Execution

Design the scraper so crawling can eventually run through:

- Celery
- Redis queue
- RQ
- Dramatiq
- or another worker system

Do not tightly couple the scraper to a single queue implementation.

A crawl request should become a job such as:

```json
{
  "crawl_id": "...",
  "company_id": "...",
  "priority": "normal",
  "requested_at": "..."
}
```

---

# 18. Storage

Use MongoDB if that matches the existing project.

Recommended collections:

```text
companies
jobs
crawl_runs
crawl_errors
portal_profiles
raw_job_payloads
```

Create appropriate indexes for:

```text
company_id
source_job_id
canonical_url
portal_provider
location
title
posted_at
updated_at
crawl status
```

Avoid storing unnecessary duplicate raw HTML for every request.

---

# 19. Search Architecture

The scraper is the ingestion layer, not the search layer.

Design the normalized job data so the product can later support:

```text
keyword
company
location
remote
employment type
experience
department
salary
posted date
portal
skills
```

Search should work consistently regardless of which ATS produced the job.

---

# 20. Testing Strategy

Create fixtures for multiple portal types.

Tests should cover:

```text
company discovery
career-page discovery
ATS detection
adapter selection
API extraction
JSON-LD extraction
embedded JSON extraction
HTML fallback
pagination
cursor pagination
infinite scroll
job normalization
location normalization
salary extraction
deduplication
URL canonicalization
expired-job detection
retry behavior
rate limiting
malformed pages
unknown portals
```

Use saved HTML/JSON fixtures rather than live websites for most unit tests.

Add integration tests for selected real providers where practical.

---

# 21. Self-Healing / Future Extensibility

Design the architecture so that when an unknown portal is encountered:

```text
Unknown portal
    ↓
Collect signals
    ↓
Identify capabilities
    ↓
Attempt universal extraction
    ↓
Persist detection result
    ↓
Create adapter candidate metadata
```

Do not make AI/LLMs mandatory for normal crawling.

If an LLM is added later, use it only as an optional **schema/selector discovery or extraction fallback**, never as the primary mechanism for every request.

The deterministic path must remain fast and predictable.

---

# 22. Existing Project Compatibility

Before modifying code:

1. Inspect the current repository structure.
2. Identify existing crawlers.
3. Identify existing models/schemas.
4. Identify existing MongoDB repositories.
5. Identify existing FastAPI routes.
6. Identify existing async HTTP utilities.
7. Identify current retry and caching logic.
8. Preserve working company-specific crawlers.
9. Refactor shared logic into reusable abstractions.
10. Avoid unnecessary rewrites.

Do not duplicate existing functionality.

---

# 23. Migration Strategy

Implement in phases:

### Phase 1
Refactor current scraper into:

```text
orchestrator
base adapter
detector
normalizer
registry
```

### Phase 2
Add ATS adapters.

### Phase 3
Add company/career discovery.

### Phase 4
Add universal fallback.

### Phase 5
Add incremental crawling and crawl state.

### Phase 6
Add observability and structured errors.

### Phase 7
Add worker/queue execution.

### Phase 8
Add broader provider coverage.

Each phase must keep the existing system runnable.

---

# 24. Expected Engineering Quality

The resulting implementation must be:

- async-first
- modular
- testable
- typed
- observable
- rate-limit aware
- fault tolerant
- extensible
- production-oriented
- compatible with the current FastAPI/MongoDB architecture

Avoid:

- giant scraper files
- company-specific `if/elif` chains
- hardcoded CSS selectors everywhere
- browser automation when HTTP/API is sufficient
- duplicated parsing logic
- silent exceptions
- infinite retries
- uncontrolled concurrency
- storing only normalized data without raw-source traceability

---

# 25. Final Instruction to the Coding AI

First analyze the existing codebase and produce:

1. Current architecture map
2. Existing functionality that must be preserved
3. Architectural gaps
4. Proposed target architecture
5. Migration plan
6. File-by-file implementation plan

Then implement incrementally.

For every modification:

- explain why the file changes
- preserve backward compatibility where possible
- reuse existing utilities
- add tests
- do not remove working crawlers without replacement
- do not introduce unnecessary dependencies
- keep provider-specific code isolated
- make the universal crawler progressively stronger

The final result should behave like a **career-page intelligence and job-ingestion engine**, not merely a collection of individual company scrapers.
