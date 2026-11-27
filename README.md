# JobNest

JobNest combines a React frontend, FastAPI application backend, MongoDB, and a standalone Go universal job crawler.

## Architecture
- React frontend: job discovery, filters, and job details.
- FastAPI: existing job read/search APIs plus a `/crawler/scan` proxy.
- Go crawler: fetching, ATS detection, generic HTML and JSON-LD extraction, normalization, deduplication, and MongoDB upserts.
- MongoDB: shared `jobs` collection using JobNest's existing document fields.

The legacy Python scraper package, Python scrape manager, obsolete scraper tests, and old scraper guides have been removed. FastAPI no longer performs crawling; it proxies crawl requests to Go. Existing `GET /jobs?company_url=...` clients remain compatible and trigger the Go crawler.

## Crawler coverage
- Greenhouse, Lever, and Ashby public job-board endpoints.
- Generic career pages via same-domain job-link discovery and Schema.org `JobPosting` JSON-LD.
- Individual public job URLs.
- SmartRecruiters and Workday are detected but currently use generic extraction; dedicated adapters remain future work.
- JavaScript-only, authenticated, CAPTCHA-protected, and anti-bot pages may require additional site-specific handling. No crawler can guarantee every website.

## Local setup
Create a root `.env` file:
```env
MONGO_URI=mongodb+srv://<user>:<password>@<cluster>/
MONGO_DB_NAME=job_intelligence
CRAWLER_API_TOKEN=replace-with-a-long-random-secret
GO_CRAWLER_URL=http://localhost:8081
```

Start the Go service:
```bash
cd crawler-go
go mod tidy
go run ./cmd/crawler
```

Start FastAPI from the repository root:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 10000
```

Start the frontend:
```bash
cd job-portal
npm install
npm run dev
```

## Submit a URL
FastAPI endpoint:
```bash
curl -X POST http://localhost:10000/crawler/scan \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://boards.greenhouse.io/example","company":"Example","save":true,"max_pages":5}'
```

Direct Go endpoint (internal; bearer token required):
```bash
curl -X POST http://localhost:8081/crawl \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer replace-with-a-long-random-secret' \
  -d '{"url":"https://boards.greenhouse.io/example","company":"Example","save":true}'
```

FastAPI docs: http://localhost:10000/docs

## Docker Compose
Set `CRAWLER_API_TOKEN` in `.env`, then run:
```bash
docker compose up --build
```

Services: FastAPI on port 10000, Go crawler on port 8081, MongoDB on port 27017.

## Safety and limitations
The crawler accepts HTTP(S) targets, blocks localhost/private IP destinations, revalidates redirects, caps response size, applies timeouts, and requires a service token. Respect robots.txt, website terms, and per-site rate limits. It does not bypass authentication, CAPTCHAs, or access controls.

This is the first Go crawler foundation. Scheduled company-wide crawling, persistent crawl jobs, richer ATS adapters, and browser rendering are follow-up improvements.