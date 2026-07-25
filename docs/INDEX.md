# Job Intelligence Portal Documentation Index

Welcome to the documentation for **Job Intelligence Portal & Scraper Platform**.

This documentation outlines the codebase architecture, Playwright-free scraping engine, database models, frontend UI, and Docker MongoDB deployment setup.

---

## Documentation Sections

1. 📄 **[System Architecture & Overview](ARCHITECTURE.md)**
   - Complete codebase structure and component flow.
   - FastAPI backend routes, MongoDB database layer, and in-memory TTL cache.
   - Low-CPU optimization principles (0.1 CPU limit friendly).

2. 🕷️ **[Scraper Engine & CLI Guide](SCRAPER_GUIDE.md)**
   - Overview of `scrapers/scrape_jobs.py` and `scrapers/crawlers/`.
   - Detailed usage of `--mode local` (preview mode with logs and 4-point data preview).
   - Detailed usage of `--mode db` (sequential MongoDB upserts).
   - Supported company scrapers and ATS detection ladder.

3. 🐳 **[Docker & MongoDB Deployment](DOCKER_DEPLOYMENT.md)**
   - Complete guide to deploying MongoDB and FastAPI backend using Docker Compose.
   - Running containerized scrapers (`docker compose --profile tools run scraper`).
   - Environment variables and data volume persistence.

---

## Quick Reference Commands

### Local Scraper Run (Dry Run Preview)
```bash
python scrapers/scrape_jobs.py --mode local --companies amazon,microsoft,meta --pages 1
```

### Production Database Populate
```bash
python scrapers/scrape_jobs.py --mode db --companies all --pages 2
```

### Docker Compose Start
```bash
docker compose up -d
```
