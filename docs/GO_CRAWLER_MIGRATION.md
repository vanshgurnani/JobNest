# JobNest Go crawler migration

## Architecture

- `crawler-go/` is the only scraping runtime.
- FastAPI exposes `POST /crawler/scan` and proxies requests to Go.
- Go writes canonical JobNest job documents directly to the shared MongoDB `jobs` collection.
- Existing job listing, filtering, and detail APIs continue to read the same collection.

## Supported input

Submit either a public company careers page or an individual public job URL. The crawler detects Greenhouse, Lever, and Ashby public job boards; other sites use generic HTML and Schema.org JobPosting extraction. Generic pages are traversed for a bounded number of same-host job links.

SmartRecruiters and Workday are currently detected but use generic extraction; dedicated adapters are not yet implemented. JavaScript-rendered pages without server-rendered job data may not yield results.

## Local startup

1. Copy `.env.example` to `.env` and set a strong `CRAWLER_API_TOKEN`.
2. Start MongoDB or point `MONGO_URI` to MongoDB Atlas.
3. Start Go: `cd crawler-go && go mod tidy && go run ./cmd/crawler`.
4. Start FastAPI in another terminal: `uvicorn app.main:app --reload --port 10000`.

Alternatively use `docker compose up --build`.

## API

```http
POST /crawler/scan
Content-Type: application/json

{
  "url": "https://boards.greenhouse.io/example",
  "company": "Example",
  "save": true,
  "max_pages": 5
}
```

The legacy `POST /scrape` route returns HTTP 410 and directs clients to `/crawler/scan`.

## Limitations and safety

No universal scraper can guarantee access to every website. Respect robots.txt, terms, rate limits and public access restrictions. Login-only, CAPTCHA-protected and anti-bot blocked pages are not bypassed. The crawler rejects localhost/private IP targets, revalidates redirects, limits response size, bounds page traversal and applies request timeouts. Keep the crawler service private and configure a high-entropy shared token.
