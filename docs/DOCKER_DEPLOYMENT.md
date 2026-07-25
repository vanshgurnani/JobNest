# Docker & MongoDB Deployment Guide

## Overview

The project supports containerized deployment using Docker Compose with three services:

- **MongoDB 7.0** - Database server with persistent volume
- **FastAPI Backend** - Python web server (port 10000)
- **Scraper** - CLI tool (profile: tools)

## Prerequisites

- Docker Engine 24+
- Docker Compose v2+

## Quick Start

### 1. Start MongoDB and Backend

```bash
docker compose up -d
```

This starts:
- MongoDB on port `27017` (internal, not exposed to host)
- FastAPI backend on port `10000` (mapped to host)

### 2. Populate Jobs Data

Run the scraper to scrape jobs and store them in MongoDB:

```bash
docker compose --profile tools run scraper
```

By default this scrapes all supported companies with 2 pages each.

### 3. Verify

Check the health endpoint:

```bash
curl http://localhost:10000/health
```

List available jobs:

```bash
curl http://localhost:10000/jobs?limit=5
```

### 4. Stop Services

```bash
docker compose down
```

To also remove the MongoDB data volume:

```bash
docker compose down -v
```

## Environment Variables

Create a `.env` file in the project root:

```env
MONGO_URI=mongodb://mongo:27017
MONGO_DB_NAME=job_db
MONGO_COLLECTION_NAME=jobs
```

The backend container reads these at startup. In the Docker network, the MongoDB hostname is `mongo`.

## Custom Scraper Run

Override the default scraper command:

```bash
docker compose --profile tools run scraper \
  python scrapers/scrape_jobs.py \
  --mode db \
  --companies amazon,microsoft \
  --pages 3
```

## Production Considerations

### MongoDB Persistence

Data is stored in a named Docker volume (`mongo-data`) mapped to `/data/db` inside the container. This persists across restarts.

### Backend Scaling

The FastAPI backend uses `uvicorn` with a single worker. For production, consider:

```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000", "--workers", "4"]
```

### Health Checks

The Docker Compose file includes health checks for MongoDB. The backend gracefully degrades if MongoDB is unavailable.

## Troubleshooting

**Backend fails to start (MongoDB unavailable):**
- Wait for MongoDB to initialize (usually 5-10 seconds on first run)
- Check logs: `docker compose logs mongo`

**Scraper reports no jobs:**
- Verify the scraper can reach the internet from within the container
- Try `local` mode first: `docker compose --profile tools run scraper python scrapers/scrape_jobs.py --mode local`
