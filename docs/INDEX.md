# Job Nest Documentation

Welcome to the documentation for **Job Nest** — an AI-powered job aggregation platform.

## Documentation Sections

| Document | Description |
|---|---|
| [Setup Guide](SETUP.md) | Local development setup instructions |
| [System Architecture](ARCHITECTURE.md) | Codebase structure and component flow |
| [Scraper Engine Guide](SCRAPER_GUIDE.md) | Scraper CLI usage, crawlers, and strategies |
| [API Reference](API.md) | REST API endpoints, parameters, and schemas |
| [Docker Deployment](DOCKER_DEPLOYMENT.md) | Containerized deployment with Docker Compose |

## Quick Reference

### Start Backend
```bash
python run.py
```

### Start Frontend
```bash
cd job-portal && npm run dev
```

### Run Scraper (Preview)
```bash
python scrapers/scrape_jobs.py --mode local --companies amazon --pages 1
```

### Run Scraper (Store to DB)
```bash
python scrapers/scrape_jobs.py --mode db --companies all --pages 2
```

### Docker Compose
```bash
docker compose up -d
docker compose --profile tools run scraper
```

## Tech Stack

- **Backend**: Python 3.11, FastAPI 0.115, Uvicorn
- **Database**: MongoDB 7.0 (Motor 3.6 async driver)
- **Scraping**: HTTPX 0.28, BeautifulSoup4, lxml
- **Frontend**: React 18, Tailwind CSS 3.4, Vite 5
- **Infrastructure**: Docker, Docker Compose
