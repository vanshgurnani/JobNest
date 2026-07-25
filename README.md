# Job Nest — AI Job Intelligence Platform

**Job Nest** is an intelligent job aggregation platform that scrapes, normalizes, and serves job listings from hundreds of companies through a unified, searchable API and a modern React frontend. Built to solve the problem of fragmented job hunting — where opportunities are scattered across hundreds of company career portals, each with its own format, ATS, and search interface.

## Why Job Nest?

Job hunting today means checking 20+ career sites, each with different UX, filters, and update cycles. Job Nest consolidates everything into one place:

- **Unified schema** — every job, from any company or ATS, stored in a consistent format
- **ATS-aware scraping** — automatically detects and adapts to Lever, Greenhouse, Workday, Ashby, SmartRecruiters, and custom career portals
- **Company-specific crawlers** — optimized scrapers for Amazon, Microsoft, and Meta that use their internal APIs
- **Intelligent parsing** — extracts role, skills, and experience level from raw titles and descriptions
- **Dual mode** — preview scraped jobs locally or persist to MongoDB
- **Clean frontend** — search, filter, save, and explore jobs with a fast, responsive UI

## What's Built

### Backend (FastAPI / Python)

- **REST API** — `GET /jobs`, `GET /jobs/{company}`, `GET /job/{job_id}`, `GET /health`
- **Async MongoDB** — Motor driver with automatic indexing on startup
- **In-memory cache** — TTL (15 min) + LRU eviction (512 entries), async-safe
- **CORS middleware** — configurable origins for dev and production
- **Graceful degradation** — API remains available (serving cache) when MongoDB is down
- **Job canonicalization** — stable SHA-256 based job IDs for deduplication
- **Title parser** — regex-based extraction of role, skills, and experience level

### Scraping Engine (Async Python)

- **3 company-specific crawlers**: Amazon (Jobs API), Microsoft (PCSX API + skills), Meta (GraphQL + HTML fallback)
- **Universal ATS-aware crawler**: detects and scrapes Lever, Greenhouse, Workday, Ashby, SmartRecruiters
- **Multi-strategy extraction**: JSON-LD, embedded JSON, HTML anchor analysis, secondary API enrichment
- **Auto-retry** with exponential backoff (3 retries)
- **Deduplication** by (company + job_id/url/title+location)
- **Expired job detection** via `valid_through` and keyword matching
- **10+ known company career URLs**: Accenture, Cognizant, Google, Infosys, JPMorgan, Mastercard, TCS, Wipro, KPMG, Zoho
- **CLI entry point** with argparse: `--companies`, `--keyword`, `--location`, `--pages`, `--mode`

### Frontend (React / Tailwind)

- **Responsive UI** with glassmorphic sticky header and dark theme
- **Hero section** with keyword + location search form
- **Popular companies** quick-filter (Google, Microsoft, Amazon, Meta, Apple, Netflix, Stripe, Shopify, GitHub)
- **Paginated listings** (20 per page) with loading skeletons
- **Sidebar filters**: Job Type, Experience Level, Salary Range
- **Job detail page** with company icon, metadata, skills tags, save/bookmark, apply link
- **LocalStorage-based bookmarks** — persisted across sessions
- **Time-ago display** ("2h ago", "3d ago")
- **Scroll-triggered animations** via Intersection Observer
- **Client-side caching** with 10-minute TTL and race-condition-safe requests

### Infrastructure

- **Docker Compose** — 3 services: MongoDB, Web API, Scraper (optional profile)
- **Dockerfile** — Python 3.11-slim, ASGI via Uvicorn
- **MongoDB health checks** and named volume for data persistence
- **Vite proxy** config for local frontend dev (port 5174 → 8000)
- **Tests** — 16 unit tests covering ATS detection, JSON-LD parsing, deduplication, URL resolution, error handling

### Authentication (Scaffolded — Not Yet Wired)

- User schemas (`UserCreate`, `UserLogin`, `UserPublic`, `TokenResponse`) defined in Pydantic
- JWT config (`HS256`, 7-day expiry) in settings
- MongoDB indexes for `users`, `saved_jobs`, `search_history` collections
- No auth middleware, routes, or password hashing implemented yet

## Quick Start

### Backend

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Scrape Jobs (Preview — no DB required)

```bash
python scrapers/scrape_jobs.py --mode local --companies amazon,microsoft --pages 1
```

### Scrape Jobs (Store to MongoDB)

```bash
python scrapers/scrape_jobs.py --mode db --companies all --pages 2
```

### Frontend

```bash
cd job-portal && npm install && npm run dev
```

### Docker (full stack)

```bash
docker compose up -d
docker compose --profile tools run scraper
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)           │
│  job-portal/src/                                     │
│  ├── pages/       HomePage, FindJobsPage, JobDetail  │
│  ├── components/  Navbar, JobCard, Filters, etc.     │
│  ├── hooks/       useJobs (caching, loading state)   │
│  └── services/    api.js (fetch wrapper)             │
└──────────────┬──────────────────────────────────────┘
               │  HTTP (proxy / Vite dev)
               ▼
┌──────────────────────────────────────────────────────┐
│                   Backend (FastAPI / Python)          │
│  app/                                                 │
│  ├── main.py          App setup, CORS, lifespan       │
│  ├── api/jobs.py      Route handlers + caching        │
│  ├── services/                                         │
│  │   ├── job_store.py  MongoDB queries                │
│  │   ├── cache.py      TTL + LRU cache                │
│  │   ├── ai_parser.py  Title → role/skills/exp        │
│  │   └── normalizer.py Field mapping                  │
│  ├── schemas/job.py    Pydantic models                │
│  ├── schemas/user.py   Auth/saved/search schemas      │
│  ├── db/mongo.py       Motor connection + indexes     │
│  └── config.py         Settings (env vars)            │
└──────────────┬───────────────────────────────────────┘
               │  read/write
               ▼
┌───────────────────────────────────────────────────────┐
│                    MongoDB (Motor async)               │
│  Collections: jobs, users, saved_jobs, search_history  │
└──────────────┬────────────────────────────────────────┘
               │  upsert
┌──────────────▼────────────────────────────────────────┐
│                   Scraper Engine (Async Python)        │
│  scrapers/                                             │
│  ├── scrape_jobs.py     CLI entry point (argparse)     │
│  └── crawlers/                                         │
│      ├── orchestrator.py  Company → crawler dispatch   │
│      ├── base.py          HTTP retry, ATS detection    │
│      ├── amazon.py        Amazon Jobs API              │
│      ├── microsoft.py     Microsoft PCSX API + skills  │
│      ├── meta.py          Meta GraphQL + HTML          │
│      └── universal.py     Universal ATS-aware crawler  │
└────────────────────────────────────────────────────────┘
```

## API Endpoints

| Method | Endpoint | Description | Params |
|--------|----------|-------------|--------|
| GET | `/health` | Health check (includes MongoDB status) | — |
| GET | `/jobs` | Paginated job listings | `company`, `keyword`, `location`, `page`, `limit` |
| GET | `/jobs/{company}` | Jobs filtered by company | `keyword`, `location`, `page`, `limit` |
| GET | `/job/{job_id}` | Single job detail | — |

## Supported Companies

| Company | Crawler Strategy |
|---------|-----------------|
| Amazon | Custom API crawler (`amazon.py`) |
| Microsoft | Custom API crawler with skills (`microsoft.py`) |
| Meta | GraphQL + HTML fallback (`meta.py`) |
| Lever shops | Universal ATS detection + API |
| Greenhouse shops | Universal ATS detection + API |
| Workday shops | Universal ATS detection + HTML parsing |
| Ashby shops | Universal ATS detection + API |
| SmartRecruiters | Universal ATS detection + API |
| Any other career portal | Universal fallback (JSON-LD, anchor analysis, embedded JSON) |

## Project Structure

```
├── app/                     FastAPI backend
│   ├── api/                 Route handlers
│   ├── db/                  MongoDB connection
│   ├── schemas/             Pydantic models
│   └── services/            Business logic (cache, store, parser)
├── scrapers/                Async scraping engine
│   └── crawlers/            Company-specific + universal crawlers
├── job-portal/              React + Vite frontend
├── scripts/                 Helper scripts
├── tests/                   Pytest unit tests (16 tests)
├── docs/                    Documentation (ARCHITECTURE, API, SETUP, etc.)
├── docker-compose.yml       3-service orchestration
├── Dockerfile               Backend container
└── requirements.txt         Python dependencies
```

## Stack

### Backend
- **Python 3.11** / **FastAPI 0.115** — async web framework
- **MongoDB 7** / **Motor 3.6** — async database driver
- **HTTPX 0.28** — async HTTP client
- **BeautifulSoup4 + lxml** — HTML parsing
- **Pydantic 2.10** — data validation

### Frontend
- **React 18** — UI framework
- **React Router 6** — client-side routing
- **Tailwind CSS 3.4** — utility-first styling
- **Vite 5** — build tool and dev server

### Infrastructure
- **Docker** / **Docker Compose** — containerization
- **Pytest** — unit testing

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | System design and codebase walkthrough |
| [API Reference](docs/API.md) | REST endpoints, schemas, examples |
| [Scraper Guide](docs/SCRAPER_GUIDE.md) | CLI usage and crawler internals |
| [Setup Guide](docs/SETUP.md) | Local development setup |
| [Docker Deployment](docs/DOCKER_DEPLOYMENT.md) | Containerized deployment |

## What's Next (Scaffolded but Not Yet Implemented)

- **User authentication** — register/login with JWT (schemas, indexes, and config exist)
- **Saved jobs** — persisted bookmarks per user
- **Search history** — per-user search tracking
- **Rate limiting** — config-based (settings exist, middleware not wired)
- **Frontend serving** — FastAPI serving `job-portal/dist/` in production
- **Frontend tests** — no test runner configured for the React app

## License

MIT
