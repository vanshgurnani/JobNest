# Job Scraping Scripts

Scraping is intentionally outside the FastAPI request path. The deployed API should
serve MongoDB data plus in-memory cache only, which keeps the free 0.1 CPU tier from
running browser-heavy work during user searches.

## Modes

Local test mode logs counts and the first 4 normalized jobs per company:

```bash
python3 scripts/scraping/scrape_jobs.py --mode local --companies amazon,microsoft --pages 1
```

DB mode scrapes sequentially and upserts into MongoDB:

```bash
MONGODB_URI=mongodb://localhost:27017 \
python3 scripts/scraping/scrape_jobs.py --mode db --companies all --pages 3
```

By default, `all` excludes browser-based crawlers such as Meta. To test Meta locally:

```bash
python3 -m pip install -r requirements-scraping.txt
python3 -m playwright install chromium
python3 scripts/scraping/scrape_jobs.py --mode local --companies meta --include-browser --pages 1
```

Do not install `requirements-scraping.txt` in production unless the deployment target
is intended to run browser scraping.
