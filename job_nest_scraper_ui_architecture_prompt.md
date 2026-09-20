# Job Nest — Product-Level Scraper UI Architecture Prompt

## Master Prompt

You are a senior product engineer and frontend architect working on **Job Nest**, an existing job-search platform with a FastAPI backend, MongoDB, and a scraping engine.

The backend scraper already has substantial functionality for company career pages, ATS platforms, job discovery, normalization, deduplication, retries, and persistence.

The goal of this task is **NOT to rebuild the scraper engine**.

The goal is to build a **product-level Scraper UI / Scraper Control Center** that allows an administrator/operator to discover companies, inspect career portals, configure crawls, run crawls, monitor progress, inspect jobs, and debug failures.

Before changing code:

1. Inspect the existing repository.
2. Understand the current frontend architecture and components.
3. Understand the current FastAPI scraper APIs/services.
4. Reuse existing APIs, schemas, components, and scraper functionality wherever possible.
5. Do not duplicate scraper logic in the frontend.
6. Do not rewrite working backend functionality unnecessarily.
7. Produce a short architecture/gap analysis before implementation.
8. Then implement incrementally with working frontend-backend integration.

---

# 1. Product Goal

Build a professional **Scraper Control Center** for Job Nest.

The UI should make the scraper feel like a real internal SaaS/product system rather than a developer debugging page.

The operator should be able to:

- Add companies
- Discover official career pages
- Detect ATS/portal providers
- Inspect detected portal information
- Configure crawling
- Start a crawl
- Stop/cancel a crawl where supported
- Monitor crawl progress in real time
- View discovered jobs
- View crawl history
- View errors
- Retry failed crawls
- Inspect raw extraction information
- See company scraping health
- Search/filter/sort companies
- Search/filter/sort discovered jobs
- Run targeted crawls
- Run bulk crawls
- Schedule recurring crawls if backend scheduling already exists
- Understand why a crawler failed
- Manually override or confirm a career URL/provider when necessary

---

# 2. UI Philosophy

The UI should be:

- Clean
- Professional
- Fast
- Desktop-first but responsive
- Data-dense without becoming cluttered
- Suitable for thousands of companies
- Suitable for long-running scraper jobs
- Easy to understand without reading backend logs
- Consistent with the existing Job Nest frontend design

Do NOT create a generic dashboard template disconnected from the existing application.

Reuse the existing:

- Design system
- Typography
- Components
- Theme
- Navigation
- API client
- Authentication
- Table components
- Toast/notification system
- Modal/drawer components

If the existing UI is MUI-based, continue using MUI rather than introducing another UI framework.

---

# 3. Main Navigation

Add a dedicated section:

```text
Job Nest
├── Dashboard
├── Jobs
├── Companies
├── Scraper
│   ├── Overview
│   ├── Companies
│   ├── Crawl Runs
│   ├── Errors
│   └── Portals / ATS
└── Settings
```

If the existing application has a different navigation structure, integrate the scraper section into it instead of replacing the navigation.

---

# 4. Scraper Overview Dashboard

Create:

```text
/scraper
```

This is the main scraper control center.

## KPI cards

Display:

- Total companies
- Active companies
- Companies successfully crawled
- Jobs discovered
- Jobs discovered today
- Crawls running
- Failed crawls
- Companies needing attention

Example:

```text
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Companies      │ │ Active Jobs    │ │ New Today      │
│ 2,481          │ │ 84,921         │ │ +1,284         │
└────────────────┘ └────────────────┘ └────────────────┘

┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Crawling       │ │ Failed        │ │ Need Attention │
│ 17             │ │ 23             │ │ 41             │
└────────────────┘ └────────────────┘ └────────────────┘
```

## Crawl activity

Show recent/active crawl runs:

```text
Company       Portal        Status       Jobs       Duration
Google        Workday       Running      1,240      02:14
Microsoft     Custom API    Completed    8,421      05:31
Acme          Greenhouse    Failed       —          00:42
```

Statuses:

- Queued
- Discovering
- Detecting
- Crawling
- Processing
- Completed
- Partial
- Failed
- Cancelled

Use clear status indicators.

---

# 5. Company Scraper Management

Create:

```text
/scraper/companies
```

This is the main company crawler management page.

## Table columns

```text
Company
Domain
Career URL
Portal / ATS
Jobs
Last Crawl
Status
Success Rate
Actions
```

Example:

```text
Google
google.com
careers.google.com
Custom
2,841
12 min ago
Healthy
98.7%
...
```

## Filters

Support:

- Company name
- Domain
- Portal/ATS
- Crawl status
- Last crawl
- Has active jobs
- Failed companies
- Needs discovery
- Remote
- Country/region if supported

## Search

Search should support:

- Company name
- Domain
- Career URL
- ATS/provider

Use debounced server-side search for large datasets.

---

# 6. Add Company Flow

Create an "Add Company" workflow.

The user should be able to enter:

```text
Company Name
Company Domain
Career URL (optional)
```

Example:

```text
Company:
Stripe

Domain:
stripe.com

Career URL:
(optional)
```

Buttons:

```text
Cancel
Discover Career Portal
```

If Career URL is omitted, the backend should perform career-page discovery.

The frontend should display:

```text
Discovering...
↓
Official domain identified
↓
Career page found
↓
Portal detected
↓
Capabilities detected
```

Example result:

```text
Company
Stripe

Career Portal
https://stripe.com/jobs

Detected Provider
Custom / Unknown

Capabilities
✓ Server-rendered jobs
✓ Job detail pages
✓ JSON-LD
✓ Sitemap
✓ Job links

Confidence
High
```

Allow the operator to confirm/edit the career URL.

---

# 7. Company Detail Page

Create:

```text
/scraper/companies/:companyId
```

This should be one of the most important screens.

## Header

Show:

```text
Company Name
Domain
Career URL
Provider
Current crawl status
```

Actions:

```text
Run Crawl
Discover Portal
Edit
Disable
```

## Tabs

```text
Overview
Jobs
Portal
Crawl History
Errors
Raw Data
Settings
```

---

# 8. Company Overview

Display:

- Company identity
- Domain
- Official career URL
- Detected provider
- Provider confidence
- Number of active jobs
- Number of expired jobs
- Last successful crawl
- Last failed crawl
- Average crawl duration
- Success rate
- Current crawl status
- Crawl frequency
- Last error

Example:

```text
Portal Health

Provider: Greenhouse
Status: Healthy
Last successful crawl: 8 minutes ago
Average duration: 41 sec
Success rate: 99.2%
```

---

# 9. Portal / ATS Information

Create a detailed portal inspection UI.

Show:

```text
Detected Provider
Provider Type
Career URL
Job Listing URL
Job Detail URL pattern
API detected
XHR detected
GraphQL detected
JSON-LD detected
Sitemap detected
Browser rendering required
```

Example:

```text
Portal Detection

Provider
Greenhouse

Detection confidence
94%

Signals

✓ greenhouse.io domain
✓ Embedded job metadata
✓ Job API endpoint
✓ JSON-LD
✗ GraphQL
✗ Browser required
```

If the backend exposes discovered endpoints, display them in a safe read-only inspection panel.

Do not expose secrets, authentication tokens, cookies, or credentials.

---

# 10. Crawl Configuration

Create a configuration panel.

Possible fields:

```text
Crawl Mode
[Automatic ▼]

Max Pages
[100]

Concurrency
[5]

Request Delay
[500 ms]

Use Browser
[Auto ▼]

Retry Count
[3]

Job Detail Enrichment
[Enabled]

Incremental Crawl
[Enabled]
```

Modes:

- Automatic
- Full crawl
- Incremental crawl
- Discovery only
- Job details only
- Debug crawl

The frontend should send these settings to the backend.

Do not implement scraping logic inside the UI.

---

# 11. Run Crawl UX

When the user clicks:

```text
Run Crawl
```

show a confirmation/configuration drawer.

Example:

```text
Run Crawl

Company:
Google

Mode:
Incremental

Job details:
Enabled

Max pages:
100

Concurrency:
5

[Start Crawl]
```

After starting, navigate to the crawl-run page.

---

# 12. Live Crawl Monitor

Create:

```text
/scraper/runs/:runId
```

This should show the crawl in real time.

## Header

```text
Google
Incremental Crawl
● Running

Started:
16:42:13

Elapsed:
02:14
```

## Progress

```text
Discovery       ████████████████████ 100%
Portal Detection████████████████████ 100%
Job Discovery   ███████████████░░░░░  76%
Normalization   ███████████░░░░░░░░░  55%
Persistence     ███████░░░░░░░░░░░░░  31%
```

If the backend cannot provide exact progress, use stage-based progress rather than inventing percentages.

## Counters

```text
URLs scanned       1,842
Jobs discovered    1,203
New jobs           184
Updated jobs       92
Unchanged          927
Expired            12
Errors             4
```

---

# 13. Crawl Logs

Show structured logs rather than raw terminal output.

Example:

```text
16:43:10  INFO   Career portal discovered
16:43:12  INFO   Provider detected: Greenhouse
16:43:15  INFO   Discovered 243 job URLs
16:43:19  INFO   Processing job details
16:43:28  WARN   3 requests returned 429
16:43:31  INFO   Retry scheduled
```

Filters:

- All
- Info
- Warning
- Error

Search logs by text.

Do not render unbounded logs into the DOM.

Use pagination/virtualization if necessary.

---

# 14. Crawl Results

After completion show:

```text
Crawl Completed

Duration
04m 21s

Jobs Found
1,284

New
184

Updated
92

Unchanged
996

Expired
12

Errors
4
```

Actions:

```text
View Jobs
View Errors
Run Again
View Raw Data
```

---

# 15. Crawl History

Create:

```text
/scraper/runs
```

Table:

```text
Run ID
Company
Provider
Mode
Started
Duration
Jobs
New
Updated
Errors
Status
```

Filters:

- Company
- Provider
- Status
- Date range
- Crawl mode

Allow opening any crawl run.

---

# 16. Error Center

Create:

```text
/scraper/errors
```

This should make scraper failures actionable.

Columns:

```text
Company
Provider
Error Type
URL
Status Code
First Seen
Last Seen
Occurrences
Status
```

Error categories:

```text
Timeout
429 Rate Limit
403 Forbidden
5xx
Parser Error
Schema Change
JavaScript Required
Network Error
Provider Detection Failure
Career Page Not Found
Job Extraction Failure
Unknown
```

Actions:

```text
Inspect
Retry
Ignore
Mark Resolved
```

---

# 17. Error Detail

When opening an error:

Show:

```text
Company
Career URL
Provider
Crawler
Error type
HTTP status
Timestamp
Retry count
```

Then:

```text
Failure Explanation
```

Example:

```text
The crawler discovered the career page but no job records
were found using the configured extraction strategies.

Strategies attempted:

✓ JSON-LD
✓ Embedded JSON
✓ Job links
✓ Sitemap
✗ API discovery
✗ Browser extraction
```

Show relevant diagnostic information.

Never display secrets.

---

# 18. Jobs Discovered by Scraper

Create:

```text
/scraper/jobs
```

This can reuse the existing Job Nest jobs UI if available.

Filters:

- Company
- Portal
- Location
- Remote
- Department
- Employment type
- Date discovered
- Last updated
- Crawl run
- Job status

Columns:

```text
Title
Company
Location
Provider
Source
First Seen
Last Seen
Status
```

Clicking a job should open the existing job detail page.

---

# 19. Portal / ATS Analytics

Create:

```text
/scraper/portals
```

Show detected portal distribution:

```text
Provider             Companies      Jobs
Greenhouse           420            18,421
Lever                312            12,882
Workday              511            25,103
Ashby                96             4,281
SmartRecruiters      143            7,182
Custom               622            16,901
Unknown               77             1,281
```

Also show:

- Success rate per provider
- Average crawl duration
- Error rate
- Jobs discovered
- Companies using provider

Do not create arbitrary health scores unless the backend already defines a measurable metric.

---

# 20. Bulk Crawling

Add bulk selection to the company table.

Example:

```text
☐ Google
☐ Microsoft
☐ Amazon
☐ Meta
☐ Stripe
```

Actions:

```text
Run Incremental Crawl
Discover Portals
Pause
Disable
```

Before running a large batch:

```text
42 companies selected

Estimated requests:
Based on recent crawl history

Concurrency:
5

[Start Bulk Crawl]
```

If no reliable estimate exists, do not invent one.

---

# 21. Crawl Queue

If the backend exposes a queue, create:

```text
/scraper/queue
```

Show:

```text
Position
Company
Task
Priority
Queued At
Started At
Status
```

Actions:

- Cancel queued task
- Change priority if supported
- Retry failed task

Do not expose implementation-specific queue internals unless useful.

---

# 22. Scheduling UI

If recurring scheduling exists in the backend, expose it.

Example:

```text
Crawl Schedule

Frequency:
Every 6 hours

Mode:
Incremental

Active:
✓

Next run:
18:00
```

Allow:

- Enable/disable
- Change frequency
- Configure crawl windows
- Configure company groups

Do not implement a frontend-only scheduler. Scheduling must be backed by the backend worker/scheduler.

---

# 23. Real-Time Updates

Use the best mechanism already supported by the backend:

Priority:

1. WebSocket
2. Server-Sent Events
3. Polling

For polling:

- Poll active crawl status every few seconds
- Stop polling when the crawl completes
- Refresh relevant data after completion
- Avoid polling every page simultaneously

Create a reusable hook such as:

```text
useCrawlRun(runId)
useCrawlProgress(runId)
useScraperStats()
```

Adapt naming to the existing frontend conventions.

---

# 24. API Integration

Create or reuse a dedicated scraper API client.

Conceptually:

```text
GET    /api/scraper/stats
GET    /api/scraper/companies
POST   /api/scraper/companies
GET    /api/scraper/companies/:id
PATCH  /api/scraper/companies/:id

POST   /api/scraper/discover
POST   /api/scraper/crawls
GET    /api/scraper/crawls
GET    /api/scraper/crawls/:id
POST   /api/scraper/crawls/:id/retry
POST   /api/scraper/crawls/:id/cancel

GET    /api/scraper/errors
GET    /api/scraper/portals
GET    /api/scraper/jobs
```

IMPORTANT:

These are conceptual API boundaries.

Inspect the existing backend first and use the actual endpoints if they already exist.

Do not create duplicate APIs.

---

# 25. Frontend State Architecture

Keep server state separate from local UI state.

Prefer the existing project approach.

If React Query/TanStack Query is already installed, use it.

Suggested conceptual structure:

```text
scraper/
├── api/
│   ├── scraperApi.ts
│   ├── companyApi.ts
│   ├── crawlApi.ts
│   └── errorApi.ts
│
├── components/
│   ├── ScraperStats.tsx
│   ├── CompanyTable.tsx
│   ├── CompanyForm.tsx
│   ├── PortalCard.tsx
│   ├── CrawlProgress.tsx
│   ├── CrawlLogs.tsx
│   ├── CrawlHistory.tsx
│   ├── ErrorTable.tsx
│   └── CrawlConfigDrawer.tsx
│
├── pages/
│   ├── ScraperDashboard.tsx
│   ├── ScraperCompanies.tsx
│   ├── ScraperCompanyDetail.tsx
│   ├── ScraperRuns.tsx
│   ├── ScraperRunDetail.tsx
│   ├── ScraperErrors.tsx
│   └── ScraperPortals.tsx
│
├── hooks/
│   ├── useScraperStats.ts
│   ├── useCompanies.ts
│   ├── useCrawlRun.ts
│   └── useCrawlProgress.ts
│
└── types/
    └── scraper.ts
```

Adapt this structure to the existing repository instead of blindly creating it.

---

# 26. UX States

Every major screen must support:

### Loading

Use skeletons/spinners appropriately.

### Empty state

Example:

```text
No companies configured

Add a company to start discovering career portals.

[Add Company]
```

### Error state

Show actionable errors.

Example:

```text
Unable to load crawl history.

[Retry]
```

### Partial data

Do not hide valid data because one API call failed.

### Long-running state

Clearly communicate that crawling is still running.

### Completed state

Provide next actions.

---

# 27. Tables

The company, crawl, job, and error tables should support:

- Server-side pagination
- Sorting
- Filtering
- Search
- Column truncation
- Tooltips for long URLs
- Sticky headers where appropriate
- Row actions
- Responsive behavior

For thousands of records, do not load everything into the browser.

---

# 28. Company Career URL Editing

Allow manual override:

```text
Detected Career URL:
https://example.com/careers

[Edit]

Manual Career URL:
https://jobs.example.com
```

When changed:

```text
Save
Re-detect portal
```

Record the override in the backend if supported.

Do not silently overwrite automatically discovered URLs.

---

# 29. Portal Detection UI

Represent provider detection clearly.

Example badges:

```text
Greenhouse
Lever
Workday
Ashby
SmartRecruiters
iCIMS
Workable
Jobvite
BambooHR
Recruitee
Teamtailor
Pinpoint
SuccessFactors
Taleo
Custom API
Unknown
```

Unknown should not automatically mean failure.

It means the system has not confidently classified the portal.

---

# 30. Discovery Workflow UI

Create a visual stepper:

```text
Company
   ↓
Domain Discovery
   ↓
Career Page Discovery
   ↓
Portal Detection
   ↓
Capability Detection
   ↓
Ready to Crawl
```

Each step should expose status:

```text
✓ Complete
● Running
○ Pending
! Failed
```

This should map to actual backend states where available.

---

# 31. Debug / Inspection Mode

For authorized admin users, provide an inspection mode.

Show:

```text
URL
HTTP status
Content type
Detected signals
Extraction strategies attempted
Jobs found
Provider
Parser used
```

Potential extraction signals:

```text
JSON-LD
Embedded JSON
API
XHR
GraphQL
Sitemap
Job anchors
HTML semantics
Browser rendering
```

Do not expose:

- Cookies
- Authorization headers
- API keys
- Session tokens
- Passwords
- Internal secrets

---

# 32. Raw Data Viewer

If the backend stores raw job payloads, provide a read-only viewer.

Use:

- JSON tree viewer
- Search
- Copy button
- Expand/collapse

Never render untrusted HTML directly.

Escape/sanitize content.

---

# 33. Security

The scraper UI is an administrative interface.

Implement or reuse:

- Authentication
- Authorization
- Admin/operator permissions
- CSRF protection where applicable
- API authorization
- Rate limiting for control endpoints

Dangerous actions should require confirmation:

- Disable company
- Bulk crawl
- Delete data
- Cancel crawl
- Remove configuration

Do not put secrets into frontend code.

---

# 34. Performance

The scraper UI may contain:

- Thousands of companies
- Hundreds of thousands/millions of jobs
- Large crawl histories
- Large error logs

Therefore:

- Server-side pagination
- Server-side filtering
- Debounced search
- Virtualized long logs where necessary
- Lazy-load company detail tabs
- Lazy-load raw payloads
- Avoid unnecessary global state
- Avoid refetching unchanged data
- Cache stable portal metadata

---

# 35. Responsive Design

Desktop is the primary target.

Still support:

- Laptop
- Tablet
- Smaller screens

On smaller screens:

- Convert wide tables into cards where appropriate
- Move secondary actions into menus
- Keep primary actions accessible
- Preserve readable status information

---

# 36. Accessibility

Implement:

- Keyboard navigation
- Proper labels
- Accessible dialogs
- Accessible tables
- Visible focus states
- Semantic buttons
- Tooltips for icon-only actions
- Status announcements for important crawl state changes where appropriate

---

# 37. Notifications

Use the existing toast/notification system.

Examples:

```text
Company added successfully
Portal discovered successfully
Crawl started
Crawl cancelled
Crawl completed
Retry started
Failed to start crawl
```

Do not show notifications for every scraper log event.

---

# 38. Product-Level Visual Hierarchy

The UI should visually distinguish:

### Healthy

Successful recent crawl and no unresolved errors.

### Running

Currently processing.

### Attention

Recent partial failures or stale crawl.

### Failed

Latest crawl failed.

### Unknown

Insufficient crawl information.

Use existing theme colors/design tokens rather than hardcoding arbitrary colors.

---

# 39. Important Backend Boundary

The frontend must NOT contain:

- Scraping logic
- HTML parsing
- ATS detection algorithms
- Retry algorithms
- Rate limiting logic
- Deduplication logic
- Job normalization logic
- Browser automation

Those belong to the scraper/backend.

The UI is responsible for:

```text
Configuration
Command
Observation
Inspection
Management
```

The backend is responsible for:

```text
Discovery
Detection
Crawling
Extraction
Normalization
Deduplication
Persistence
Queueing
Retries
Scheduling
```

---

# 40. Existing Scraper Compatibility

The existing scraper already supports multiple strategies/providers.

The UI must surface those capabilities instead of replacing them.

Expected provider examples include:

```text
Amazon
Microsoft
Meta
Greenhouse
Lever
Workday
Ashby
SmartRecruiters
iCIMS
Workable
Jobvite
BambooHR
Recruitee
Teamtailor
Pinpoint
SuccessFactors
Taleo
Custom API
Universal fallback
```

Do not assume every company belongs to one of these providers.

---

# 41. Suggested User Journey

The complete product journey should feel like:

```text
Add Company
     ↓
Discover Career Page
     ↓
Detect Portal
     ↓
Inspect Capabilities
     ↓
Confirm Configuration
     ↓
Start Crawl
     ↓
Monitor Progress
     ↓
View Results
     ↓
Inspect Errors
     ↓
Retry / Fix
     ↓
Company becomes part of recurring crawl system
```

---

# 42. Implementation Plan

Implement in phases.

## Phase 1 — Foundation

- Inspect existing frontend
- Add scraper navigation
- Add routes
- Add scraper API client
- Add shared types
- Add overview dashboard

## Phase 2 — Company Management

- Company list
- Search/filter
- Add company
- Discovery flow
- Company detail page
- Portal information

## Phase 3 — Crawl Management

- Crawl configuration
- Start crawl
- Crawl history
- Crawl detail
- Live progress
- Logs
- Results

## Phase 4 — Error Management

- Error center
- Error detail
- Retry
- Resolution state

## Phase 5 — Jobs and Portals

- Scraped jobs
- Provider analytics
- Portal inspection

## Phase 6 — Bulk Operations

- Multi-select
- Bulk crawl
- Bulk discovery
- Queue visibility

## Phase 7 — Scheduling

Only if backend support exists.

- Recurring crawls
- Schedule management
- Crawl windows

## Phase 8 — Polish

- Performance
- Accessibility
- Responsive behavior
- Loading states
- Empty states
- Error states
- Permissions
- Tests

---

# 43. Testing Requirements

Add tests for:

### Components

- Company table
- Company form
- Crawl configuration
- Crawl progress
- Error table

### API

- Fetch companies
- Create company
- Start crawl
- Fetch crawl
- Retry crawl
- Fetch errors

### User flows

```text
Add company
→ discover portal
→ start crawl
→ monitor
→ completion
→ inspect results
```

Test failure cases:

```text
Discovery failed
Crawl failed
API timeout
Unauthorized
Empty result
Partial crawl
Network interruption
```

---

# 44. Final Engineering Requirements

Before implementation:

1. Inspect the current repository.
2. Identify existing frontend stack.
3. Identify existing scraper API endpoints.
4. Identify existing authentication.
5. Identify existing design system.
6. Identify reusable components.
7. Identify current scraper data models.
8. Identify which requested UI features already have backend support.
9. Do not invent backend functionality when an equivalent already exists.
10. Clearly mark frontend features that require new backend endpoints.

Then provide:

```text
1. Current architecture
2. Existing scraper capabilities
3. Existing frontend capabilities
4. Missing APIs
5. Target UI architecture
6. Component architecture
7. Route architecture
8. API mapping
9. Data flow
10. Implementation plan
```

After that, implement the UI incrementally.

---

# 45. Definition of Done

The scraper UI is considered complete when an operator can:

```text
✓ Add a company
✓ Discover its official career page
✓ Detect its portal/provider
✓ Inspect detection results
✓ Configure a crawl
✓ Start a crawl
✓ See crawl progress
✓ See discovered job counts
✓ View crawl history
✓ Inspect crawl logs
✓ View scraper errors
✓ Retry failures
✓ View discovered jobs
✓ Filter/search companies
✓ Filter/search crawl runs
✓ Inspect portal distribution
✓ Run multiple companies
✓ Understand crawler health
```

The result should feel like a **production-grade scraper management product**, not a collection of developer debugging pages.

Prioritize reliability, clarity, reusability, and compatibility with the existing Job Nest scraper/backend architecture.
