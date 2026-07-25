# System Architecture & Codebase Overview

This document provides a technical walkthrough of the **Job Intelligence Portal & Scraper Platform**.

---

## Architectural Principles

1. **Decoupled Scraping Execution**: Scraping runs completely outside the FastAPI request lifecycle. This prevents API response delays and eliminates heavy background CPU spikes during web traffic.
2. **0.1 CPU Free-Tier Friendly**: Scrapers are **100% Playwright-free**, relying on fast async HTTP requests (`httpx`, `beautifulsoup4`, JSON REST & GraphQL APIs) to operate smoothly within 0.1 CPU resource limits.
3. **Storage & Caching Layer**:
   - **MongoDB** stores canonicalized job records with unique compound indexing (`id`).
   - **In-memory TTL Cache** (`app/services/cache.py`) serves repetitive API requests instantly without hitting MongoDB on every request.

---

## Directory Structure

```text
├── app/                        # FastAPI Web Backend Application
│   ├── api/
│   │   └── jobs.py             # Route handlers (/health, /jobs, /jobs/{company}, /job/{job_id})
│   ├── db/
│   │   └── mongo.py            # Motor AsyncIOMotorClient connection & index creation
│   ├── schemas/
│   │   └── job.py              # Pydantic Job data schema
│   ├── services/
│   │   ├── ai_parser.py        # Heuristic skills & experience extraction from title
│   │   ├── cache.py            # In-memory TTL response cache
│   │   ├── job_store.py        # MongoDB find/upsert async queries
│   │   └── normalizer.py       # Job data standardization utility
│   ├── config.py               # Application configuration settings
│   └── main.py                 # FastAPI application initialization & middleware
│
├── scrapers/                   # Dedicated Scraping Module
│   ├── scrape_jobs.py          # Main CLI Scraper Script (local / db modes)
│   └── crawlers/               # Company-Specific & Universal Crawlers
│       ├── base.py             # HTTP retry client, ATS detector, base normalizer
│       ├── orchestrator.py     # Concurrent crawler loader & registry
│       ├── amazon.py           # Amazon jobs search.json API crawler
│       ├── microsoft.py        # Microsoft PCSX API crawler
│       ├── meta.py             # Meta HTTP GraphQL / HTML fallback crawler
│       └── universal.py        # Universal crawler for arbitrary company URLs / ATS
│
├── job-cafe/                   # React + Vite Frontend Application
│   └── src/
│       ├── components/
│       │   ├── JobCard.jsx     # Modern Glassmorphic Job Card
│       │   └── SearchBar.jsx   # Interactive Search Bar with instant filters
│       ├── App.jsx             # Main Application Container & Pagination
│       ├── styles.css          # Global styling & keyframe animations
│       └── theme.js            # MUI Dark Theme & Gradients
│
├── docs/                       # Project Documentation Directory
│   ├── INDEX.md                # Documentation Hub Index
│   ├── ARCHITECTURE.md         # Architecture & Code Structure (This file)
│   ├── SCRAPER_GUIDE.md        # Scraper Execution & Developer Guide
│   └── DOCKER_DEPLOYMENT.md    # Docker & MongoDB Deployment Guide
│
├── Dockerfile                  # Production container definition
├── docker-compose.yml          # Container orchestration (MongoDB + FastAPI + Scraper)
├── requirements.txt            # Python dependencies (Playwright-free)
├── run.py                      # Uvicorn launcher
└── README.md                   # Project overview & quick start
```

---

## Data Schema (`app/schemas/job.py`)

All scraped jobs are normalized into the following schema:

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique job identifier (MD5 hash of company + job_id / apply_url) |
| `company` | `str` | Company display name (e.g. Amazon, Microsoft, Meta) |
| `title` | `str` | Job position title |
| `location` | `str` | City, State, Country, or Remote |
| `description` | `str` | Full text or summary description |
| `employment_type` | `str` | Full-time, Part-time, Contract, etc. |
| `experience` | `str` | Seniority / Experience requirements |
| `skills` | `list[str]` | Array of extracted technical skills |
| `apply_url` | `str` | Direct application URL |
| `source` | `str` | Scraper source identifier (e.g. `amazon`, `microsoft`, `meta`, `workday`) |
| `crawled_at` | `datetime` | UTC timestamp when scraped |

---

## FastAPI Backend Endpoints

### 1. `GET /health`
Returns the status of FastAPI server and MongoDB connection status.

### 2. `GET /jobs`
Returns paginated job listings across all companies in MongoDB.
- **Parameters**: `company`, `keyword`, `location`, `page` (default 1), `limit` (default 20).
- **Response**: `{ "total": 120, "page": 1, "limit": 20, "jobs": [...] }`

### 3. `GET /jobs/{company}`
Returns paginated job listings for a specific company slug (e.g. `/jobs/amazon`).

### 4. `GET /job/{job_id}`
Returns details for a single job by `id` or `job_id`.
