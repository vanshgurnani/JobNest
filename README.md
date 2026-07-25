# JobCafe - AI Job Intelligence Portal

A modern job aggregation platform with a FastAPI backend, React frontend, and Playwright-free scraping engine. Scrapes job listings from top companies and serves them through a responsive, dark-themed UI.

## Features

- **Job Aggregation** - Scrapes jobs from Amazon, Microsoft, Meta, and any company via universal ATS-aware crawler
- **FastAPI Backend** - Async MongoDB (Motor), in-memory TTL cache, paginated REST API
- **React Frontend** - Dark theme, glassmorphic UI, animated job cards, real-time search
- **Playwright-Free Scraping** - 100% async HTTP + HTML parsing, 0.1 CPU friendly
- **Dual Scraper Modes** - `local` (preview) and `db` (MongoDB persistence)
- **Universal Crawler** - Detects Lever, Greenhouse, Workday, Ashby, SmartRecruiters ATS platforms
- **Docker Support** - One-command deployment with MongoDB + Backend + Scraper

## Quick Start

### Backend

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Scrape Jobs (Preview Mode)

```bash
python scrapers/scrape_jobs.py --mode local --companies amazon,microsoft --pages 1
```

### Scrape Jobs (Store to MongoDB)

```bash
python scrapers/scrape_jobs.py --mode db --companies all --pages 2
```

### Frontend

```bash
cd job-cafe && npm install && npm run dev
```

### Docker

```bash
docker compose up -d
docker compose --profile tools run scraper
```

## Documentation

| Document | Description |
|---|---|
| [Setup Guide](docs/SETUP.md) | Full local development setup |
| [Architecture](docs/ARCHITECTURE.md) | System design and codebase overview |
| [Scraper Guide](docs/SCRAPER_GUIDE.md) | Scraper CLI usage and crawler strategies |
| [API Reference](docs/API.md) | REST API endpoints and schemas |
| [Docker Deployment](docs/DOCKER_DEPLOYMENT.md) | Containerized deployment guide |

## Stack

### Backend
- **Python 3.11** / **FastAPI 0.115** - Async web framework
- **MongoDB 7.0** / **Motor 3.6** - Async database
- **HTTPX 0.28** - Async HTTP client
- **BeautifulSoup4 + lxml** - HTML parsing

### Frontend
- **React 18** - UI framework
- **Material UI 9** - Component library
- **Vite 5** - Build tool
- **Framer Motion 12** - Animations

### Infrastructure
- **Docker** / **Docker Compose** - Containerization

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `GET /jobs` | Paginated job listings (filters: company, keyword, location) |
| `GET /jobs/{company}` | Jobs by company |
| `GET /job/{job_id}` | Single job detail |

## Project Structure

```
app/                          # FastAPI backend
scrapers/                     # Scraper engine
  scrape_jobs.py              # CLI entry point
  crawlers/                   # Company-specific + universal crawlers
job-cafe/                     # React frontend
docs/                         # Documentation
tests/                        # Unit tests
```

## License

MIT
