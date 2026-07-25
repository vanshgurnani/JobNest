# TODO - job scraping intelligence layer enhancements

- [ ] Step 1: Add restricted-domain fail-safe + non-json response logging inside `scripts/scraping/crawlers/universal.py`
- [ ] Step 2: Enhance JSON/API endpoint discovery by inferring pagination/filter/list endpoints from discovered URLs
- [ ] Step 3: Enforce `max 5` additional API calls per source in `_fetch_jobs_from_candidate_apis`
- [ ] Step 4: Implement chained/secondary fetch enrichment when extracted jobs are missing description/job_id/location
- [ ] Step 5: Strengthen smart filtering criteria (title + working apply_url/url or job_id) and dedupe key
- [ ] Step 6: Run tests (`pytest -q`) and a smoke scrape for one supported + one unsupported company
