# Setup Guide

## Prerequisites

- Python 3.11+
- Node.js 18+
- MongoDB 7.0 (optional for local dev)
- npm 9+

## Backend Setup

### 1. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy the example environment file:

```bash
cp .env.example .env  # if available
```

Edit `.env`:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=job_scraper
MONGO_COLLECTION_NAME=jobs
```

### 4. Start MongoDB (Required for DB Mode)

Using Docker:

```bash
docker run -d -p 27017:27017 --name mongo mongo:7
```

Or install MongoDB locally via Homebrew:

```bash
brew tap mongodb/brew
brew install mongodb-community
brew services start mongodb-community
```

### 5. Run the Backend

```bash
python run.py
```

Server starts at `http://localhost:8000`. Health check: `curl http://localhost:8000/health`

### 6. Scrape Some Jobs

**Scrape by company name** (uses registered crawlers for amazon, microsoft, meta):

```bash
python scrapers/scrape_jobs.py --mode db --companies amazon,microsoft --pages 1
```

**Scrape by career page URL** (smart routing → company-specific → ATS → generic fallback):

```bash
python scrapers/scrape_jobs.py --mode db --company-url "https://careers.google.com"
```

**Scrape with generic scraper only** (skips registered crawlers):

```bash
python scrapers/scrape_jobs.py --mode db --generic-only --company-url "https://jobs.apple.com/en-in/search"
```

**CLI Options:**

| Argument | Default | Description |
|---|---|---|
| `--mode` | `local` | `local` (preview) or `db` (MongoDB) |
| `--companies` | `all` | Comma-separated slugs or `all` |
| `--company-url` | — | Comma-separated career page URLs |
| `--keyword` | — | Keyword filter |
| `--location` | — | Location filter |
| `--pages` | `2` | Pages per target |
| `--page-size` | `20` | Items per page |
| `--delay-seconds` | `0.5` | Delay between requests |
| `--generic-only` | `False` | Force generic scraper, skip registered crawlers |

## Frontend Setup

### 1. Install Dependencies

```bash
cd job-portal
npm install
```

### 2. Configure API URL

Edit `job-portal/.env`:

```env
VITE_API_BASE=http://localhost:8000
```

### 3. Start Dev Server

```bash
npm run dev
```

Frontend runs at `http://localhost:5173` with API requests proxied to `localhost:8000`.

### 4. Build for Production

```bash
npm run build
```

Output is in `job-portal/dist/`.

## Docker Setup

For production deployment with Docker:

```bash
docker compose up -d
docker compose --profile tools run scraper
```

See [Docker Deployment Guide](DOCKER_DEPLOYMENT.md) for details.

## Testing

Run Python tests:

```bash
pytest tests/ -v
```

## Troubleshooting

**MongoDB connection refused:**
- Ensure MongoDB is running: `mongosh --eval "db.runCommand({ ping: 1 })"`
- Check `MONGO_URI` in `.env`

**Frontend can't reach backend:**
- Ensure backend is running on port 8000
- Check Vite proxy config in `job-cafe/vite.config.js`
- Open browser dev tools Network tab to inspect requests

**Scraper finds no jobs:**
- Verify internet connectivity
- Try `local` mode first to debug
- Check company-specific crawler configuration
