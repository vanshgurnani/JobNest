# Job Nest Scraper Control Center

Standalone operator UI for the Job Nest scraper. It intentionally lives outside
`job-portal/` so the public job-search application and the administrative
scraper control center can evolve independently.

```bash
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:5180` and proxies `/api` to the
FastAPI service on `http://localhost:8000`. Set `VITE_API_BASE` when connecting
to a different backend.

Local mode keeps crawl results in the in-process run response. Database mode
sends `save_to_db: true` and uses the existing Mongo persistence path.
