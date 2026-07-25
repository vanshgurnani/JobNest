# System Architecture & Codebase Overview

## Architectural Principles

1. **Decoupled Scraping**: Scraping runs completely outside the FastAPI request lifecycle, preventing API response delays.
2. **No Playwright**: 100% Playwright-free for 0.1 CPU free-tier compatibility. Uses async HTTP + HTML parsing.
3. **Storage & Caching**: MongoDB stores canonicalized job records; in-memory TTL cache serves repeat API requests instantly.

## Directory Structure

```
├── app/                          # FastAPI Backend
│   ├── api/jobs.py               # Route handlers
│   ├── db/mongo.py               # MongoDB connection (Motor async)
│   ├── schemas/job.py            # Pydantic Job model
│   ├── services/
│   │   ├── cache.py              # In-memory TTL/LRU cache
│   │   ├── job_store.py          # MongoDB queries
│   │   └── ai_parser.py          # Skill/experience extraction
│   ├── config.py                 # App settings
│   └── main.py                   # FastAPI app & lifespan
│
├── scrapers/                     # Scraping Engine
│   ├── scrape_jobs.py            # CLI entry point
│   └── crawlers/
│       ├── base.py               # HTTP client, ATS detection, normalization
│       ├── orchestrator.py       # Crawler registry & dispatch
│       ├── amazon.py             # Amazon Jobs API
│       ├── microsoft.py          # Microsoft PCSX API
│       ├── meta.py               # Meta GraphQL + HTML
│       └── universal.py          # Universal ATS crawler
│
├── job-cafe/                     # React Frontend
│   └── src/
│       ├── components/
│       │   ├── JobCard.jsx       # Job card component
│       │   └── SearchBar.jsx     # Search bar component
│       ├── App.jsx               # Main application
│       ├── theme.js              # MUI dark theme
│       └── styles.css            # Animations & styles
│
├── docs/                         # Documentation
├── tests/test_crawlers.py        # Unit tests
├── Dockerfile                    # Container build
├── docker-compose.yml            # Orchestration
└── requirements.txt              # Python deps
```

## Data Flow

```
                   ┌──────────────────────┐
                   │   Scraper CLI        │
                   │  scrape_jobs.py      │
                   └───────┬──────────────┘
                           │ upserts jobs
                           ▼
                   ┌──────────────────────┐
                   │     MongoDB          │
                   │   (job database)     │
                   └───────┬──────────────┘
                           │ serves jobs
                           ▼
┌──────────────┐    ┌──────────────────────┐
│   Browser    │◄───│  FastAPI Backend     │
│  (React App) │    │  (REST API)          │
└──────────────┘    └──────────────────────┘
```

## Component Details

### FastAPI Backend

- **Routes**: `/health`, `/jobs`, `/jobs/{company}`, `/job/{job_id}`
- **Caching**: TTL-based (15 min), LRU eviction (max 512 entries), keyed by query params
- **Database**: Async MongoDB via Motor, compound indexes on `id`, `company`, `source`

### Scraping Engine

- **Modes**: `local` (dry-run preview) and `db` (MongoDB upsert)
- **Strategy**: Company-specific crawlers first, universal fallback for unknown companies
- **Deduplication**: MD5 hash of (company + job_id/apply_url) as unique ID

### React Frontend

- **Theme**: Dark mode with blue/purple accent gradients
- **Pages**: Single-page app with search, pagination, job detail dialog
- **API Integration**: Fetches from `/jobs` endpoint with intelligent retry and alias resolution

## Data Schema

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique job ID (MD5 hash) |
| `company` | `str` | Company name |
| `title` | `str` | Job title |
| `location` | `str` | Job location |
| `description` | `str` | Full description |
| `employment_type` | `str` | Employment type |
| `experience` | `str` | Seniority level |
| `skills` | `list[str]` | Extracted skills |
| `apply_url` | `str` | Application URL |
| `source` | `str` | Scraper source |
| `crawled_at` | `datetime` | Scrape timestamp |
