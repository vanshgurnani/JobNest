# System Architecture & Codebase Overview

## Architectural Principles

1. **Decoupled Scraping** — Scraping runs completely outside the FastAPI request lifecycle, preventing API response delays.
2. **No Playwright** — 100% Playwright-free for free-tier CPU compatibility. Uses async HTTP + HTML parsing.
3. **Storage & Caching** — MongoDB stores canonicalized job records; in-memory TTL cache serves repeat API requests instantly.

## Directory Structure

```
├── app/                             # FastAPI Backend
│   ├── api/jobs.py                  # Route handlers
│   ├── db/mongo.py                  # MongoDB connection (Motor async)
│   ├── schemas/job.py               # Pydantic Job model
│   ├── schemas/user.py              # Auth/saved/search schemas
│   ├── services/
│   │   ├── cache.py                 # In-memory TTL+LRU cache
│   │   ├── job_store.py             # MongoDB queries
│   │   ├── ai_parser.py             # Skill/experience extraction
│   │   └── normalizer.py            # Field mapping
│   ├── config.py                    # App settings (JWT, CORS, cache)
│   └── main.py                      # FastAPI app, lifespan, CORS
│
├── scrapers/                        # Scraping Engine
│   ├── scrape_jobs.py               # CLI entry point (argparse)
│   └── crawlers/
│       ├── base.py                  # HTTP retry, ATS detection, normalization
│       ├── orchestrator.py          # Crawler registry & dispatch
│       ├── amazon.py                # Amazon Jobs API
│       ├── microsoft.py             # Microsoft PCSX API + skills
│       ├── meta.py                  # Meta GraphQL + HTML
│       └── universal.py             # Universal ATS-aware crawler
│
├── job-portal/                      # React Frontend
│   └── src/
│       ├── pages/                   # HomePage, FindJobsPage, JobDetailPage
│       ├── components/              # Navbar, JobCard, Filters, Pagination, etc.
│       ├── hooks/useJobs.js         # Custom hook with caching & loading states
│       └── services/api.js          # API client (fetchJobs, fetchJobById)
│
├── docs/                            # Documentation
├── tests/test_crawlers.py           # 16 unit tests
├── Dockerfile                       # Container build
├── docker-compose.yml               # 3-service orchestration
├── requirements.txt                 # Python deps
└── README.md                        # Project overview
```

## Data Flow

```
                    ┌──────────────────────┐
                    │   Scraper CLI        │
                    │  scrape_jobs.py      │
                    └───────┬──────────────┘
                            │ upserts jobs via Motor
                            ▼
                    ┌──────────────────────┐
                    │     MongoDB          │
                    │  (job_portal.jobs)   │
                    └───────┬──────────────┘
                            │ serves via async query
                            ▼
┌──────────────┐    ┌──────────────────────┐
│   Browser    │◄───│  FastAPI Backend     │
│  (React App) │    │  (REST API + cache)  │
└──────────────┘    └──────────────────────┘
                            │
                    ┌───────┴──────────────┐
                    │  In-Memory Cache     │
                    │  (TTL 15min, LRU)    │
                    └──────────────────────┘
```

## Component Details

### FastAPI Backend

- **Routes**: `GET /health`, `GET /jobs`, `GET /jobs/{company}`, `GET /job/{job_id}`
- **Caching**: TTL-based (15 min), LRU eviction (max 512 entries), async-safe, keyed by query params
- **Database**: Async MongoDB via Motor, compound indexes on `id`, `company+crawled_at`, `title`
- **Graceful degradation**: API stays up (serving cache) when MongoDB is down
- **Canonicalization**: SHA-256 hash of `apply_url` or `company:title` as stable unique ID

### Scraping Engine

- **Modes**: `local` (dry-run preview to stdout) and `db` (MongoDB upsert)
- **Strategy**: Company-specific crawlers first (Amazon, Microsoft, Meta), universal fallback for unknown
- **Deduplication**: SHA-256 hash of (company + job_id/apply_url/title+location)
- **ATS detection**: Lever, Greenhouse, Ashby, Workday, SmartRecruiters via URL + HTML patterns
- **Retry**: Exponential backoff, 3 retries
- **Rate limiting**: Configurable delay between requests

### React Frontend

- **Theme**: Dark mode with blue accent gradients, glassmorphic navbar
- **Pages**: Home (hero + search + popular companies), Find Jobs (listings + filters + pagination), Job Detail
- **Components**: JobCard (time-ago, skills tags), Filters (type/experience/salary), SkeletonCard, EmptyState, ErrorState
- **State**: Custom `useJobs` hook with client-side caching (10min TTL), race condition safety, loading/error states
- **Persistence**: LocalStorage-based job bookmarks (no auth required)
- **Animations**: CSS + Intersection Observer scroll-triggered (no Framer Motion)

## Data Schema

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique job ID (SHA-256 hash) |
| `company` | `str` | Company name |
| `title` | `str` | Job title |
| `location` | `str` | Job location |
| `description` | `str` | Full description |
| `employment_type` | `str` | Full-time, Part-time, etc. |
| `experience` | `str` | Seniority level |
| `skills` | `list[str]` | Extracted skills |
| `apply_url` | `str` | Application URL |
| `source` | `str` | Crawler identifier |
| `posted_date` | `str` | Date posted |
| `valid_through` | `str` | Expiration date |
| `crawled_at` | `datetime` | Scrape timestamp |
| `first_seen_at` | `datetime` | First insertion time |
