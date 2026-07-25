# AI Job Intelligence Job Portal

A lightweight **FastAPI** backend, React frontend, and dedicated Playwright-free scraping engine for serving normalized job data from MongoDB.

Scraping runs outside the request path via dedicated CLI scripts (`scrapers/scrape_jobs.py`), keeping production deployments small, fast, and optimized for low-CPU free tiers (0.1 CPU limit).

- **MongoDB-backed jobs** with in-memory response cache
- **No Playwright dependency** in production or scraping
- **Frontend pagination** with interactive page controls
- **Sequential scraper scripts** with `local` preview and `db` modes
- **Docker & Docker Compose** setup for containerized MongoDB + FastAPI backend

---

## Features

- **Frontend Pagination**: Intuitive numbered pagination, previous/next page navigation, and job item counts (`job-cafe`).
- `GET /jobs`: Returns paginated stored job results.
- `GET /jobs/{company}`: Returns paginated stored results for a single company.
- `GET /job/{job_id}`: Returns a stored job detail.
- **Scraper Engine**:
  - `local` mode: Tests data retrieval, outputs structured logs, previews the **first 4 data points**, and logs total scraped job count without requiring MongoDB.
  - `db` mode: Connects to MongoDB and sequentially upserts scraped job records.

---

## Project Structure

```text
app/
  api/
    jobs.py                 # API routes (/health, /jobs, /jobs/{company}, /job/{job_id})
  db/
    mongo.py                # Mongo connection + indexes
  services/
    cache.py                # In-memory TTL cache
    job_store.py            # Mongo job read/upsert helpers
    ai_parser.py           # Parsing skills/experience from title
  schemas/
    job.py                 # Pydantic Job model
scrapers/                   # DEDICATED SCRAPING DIRECTORY
  scrape_jobs.py            # CLI entry point (local / db modes)
  crawlers/
    orchestrator.py         # Crawler orchestrator
    base.py                 # Async HTTP retries, normalization, ATS utils
    universal.py            # Universal fallback scraper
    amazon.py               # Amazon API crawler
    microsoft.py            # Microsoft PCSX API crawler
    meta.py                 # Meta HTTP crawler (Playwright-free)
job-cafe/                   # React Vite Frontend
  src/
    App.jsx                 # Main application UI with Pagination
docker-compose.yml          # Container orchestration (MongoDB + FastAPI + Scraper)
Dockerfile                  # Backend container build
tests/
  test_crawlers.py          # Unit tests
```

---

## Running Scrapers

Execute the scraper from the project root:

### Local Preview Mode (No DB required)
Scrapes data sequentially, logs progress, previews the **first 4 data points**, and logs total job count:
```bash
python scrapers/scrape_jobs.py --mode local --companies amazon,microsoft,meta --pages 1
```

### Production Database Mode (Populates MongoDB)
Connects to MongoDB and upserts scraped job records:
```bash
python scrapers/scrape_jobs.py --mode db --companies all --pages 2
```

---

## Running with Docker & MongoDB

To run MongoDB alongside the FastAPI backend using Docker Compose:

1. **Start MongoDB and FastAPI Backend**:
   ```bash
   docker compose up -d
   ```
   - MongoDB will run on port `27017` with volume persistence.
   - FastAPI Backend will run on port `10000`.

2. **Populate MongoDB via Containerized Scraper**:
   ```bash
   docker compose --profile tools run scraper
   ```

3. **Stop Docker Services**:
   ```bash
   docker compose down
   ```

---

## API Endpoints

- `GET /health` – Health check endpoint
- `GET /jobs?page=1&limit=20` – Returns paginated stored job listings
- `GET /jobs/{company}?page=1&limit=20` – Returns paginated jobs for a specific company
- `GET /job/{job_id}` – Returns specific job details
