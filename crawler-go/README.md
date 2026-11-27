# JobNest Go Universal Crawler

Standalone Go service. FastAPI remains the application API; Go owns all crawling and persistence.

## Run locally
```bash
cd crawler-go
export MONGO_URI='mongodb+srv://...'
export MONGO_DB_NAME='job_intelligence'
export CRAWLER_API_TOKEN='replace-with-a-long-random-secret'
go mod tidy
go run ./cmd/crawler
```

## Scan a public careers page
```bash
curl -X POST http://localhost:8081/crawl \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer replace-with-a-long-random-secret' \
  -d '{"url":"https://boards.greenhouse.io/example","company":"Example","save":true}'
```

FastAPI proxy: POST `/crawler/scan` with `{"url":"https://careers.example.com","company":"Example","save":true}`.

## Coverage
- Greenhouse, Lever and Ashby public job-board endpoints.
- Generic HTML job links and Schema.org JobPosting JSON-LD.
- SmartRecruiters and Workday currently use generic extraction; dedicated adapters are future work.
- JavaScript-only pages may require a site-specific public endpoint or a browser renderer; this service does not bypass authentication, CAPTCHAs or access controls.

## Safety
Only public HTTP(S) targets; loopback/private IPs are rejected, redirects are revalidated, response bodies are capped, and requests time out. Respect robots.txt, terms and per-site crawl policies before production scheduling. Run behind a private network and set a strong token.
