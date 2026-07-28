# Full Codebase Audit — 85 Issues Found

A comprehensive audit of the entire codebase uncovered 85 issues across 15 categories. Each issue is tagged with severity: **CRITICAL**, **HIGH**, **MEDIUM**, **LOW**.

---

## 1. Security Issues (8)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 1.1 | **Hardcoded MongoDB credentials committed to git** — `.env` contains plaintext password `iz64rqtBBQss8iQ7` and is tracked in version control | `.env` | CRITICAL |
| 1.2 | **SSRF via `company_url`** — `is_safe_url` validates hostname format only; no DNS resolution check to ensure the host resolves to a public IP. An attacker could use DNS rebinding to hit internal services | `app/api/jobs.py:73-81`, `scrapers/crawlers/universal.py:1330` | HIGH |
| 1.3 | **NoSQL injection / Regex DoS** — MongoDB queries use `$regex` with user input via `$or` over 3 fields. Unbounded CPU exhaustion risk on large collections | `app/services/job_store.py:52-60` | MEDIUM |
| 1.4 | **CORS misconfigured with credentials** — `allow_credentials=True` with permissive `allow_origins`. No CSRF protection. No SameSite cookies | `app/main.py:34-40` | HIGH |
| 1.5 | **`noreferrer` without `noopener`** — `target="_blank"` links should use `rel="noopener noreferrer"` | `job-portal/src/pages/JobDetailPage.jsx:193` | LOW |
| 1.6 | **Error text leaks server details** — raw error response text thrown as error message to client | `job-portal/src/services/api.js:16-17` | MEDIUM |
| 1.7 | **`python-dotenv` missing from requirements** — works only via transitive dependency, could break in clean install | `requirements.txt` | MEDIUM |
| 1.8 | **API accepts URLs without `max_length` validation** — `company_url` param has no length constraint unlike other fields | `app/api/jobs.py:74` | MEDIUM |

---

## 2. Performance Problems (10)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 2.1 | **Sync PyMongo in async context** — uses `asyncio.to_thread()` to wrap synchronous `pymongo.MongoClient`. Every DB operation blocks a thread. Motor (async driver) is not in requirements | `app/db/mongo.py:19`, `app/services/job_store.py:84-85,120-121,141-142,151-152` | HIGH |
| 2.2 | **HTTP client created per request** — `request_with_retries`/`request_json_with_retries` create a new `httpx.AsyncClient()` on every call. No connection pooling, no keep-alive | `scrapers/crawlers/base.py:112-113,147` | MEDIUM |
| 2.3 | **Duplicate sleep in retry logic** — `await asyncio.sleep(min(2**attempt, 4))` called twice in `request_json_with_retries` (lines 160 and 162), doubling backoff delay | `scrapers/crawlers/base.py:160-161` | LOW |
| 2.4 | **N+1 MongoDB upserts** — each job upserted with individual `update_one()` instead of `bulk_write()` | `app/services/job_store.py:67-81` | MEDIUM |
| 2.5 | **Same N+1 pattern in migration script** — individual `update_one()` per document | `scripts/migrate_to_prod.py:55-56,62-63` | MEDIUM |
| 2.6 | **Frontend cache never evicted** — `cacheRef` Map grows unboundedly; 10-min TTL prevents stale data but not memory growth | `job-portal/src/hooks/useJobs.js:10,41` | MEDIUM |
| 2.7 | **Redundant API calls due to race condition** — `FindJobsPage.loadJobs` re-fetches when unrelated filters change; no debouncing | `job-portal/src/pages/FindJobsPage.jsx:31-55` | MEDIUM |
| 2.8 | **Filters trigger re-renders but are never sent to backend** — `employmentType` and `experience` in dependency array but NOT passed to `fetchJobs()`. Backend doesn't accept them anyway | `job-portal/src/pages/FindJobsPage.jsx:36-44` | MEDIUM |
| 2.9 | **Non-stable `hash()` in ID generation** — `abs(hash(title + location + source))` uses Python's randomized `hash()` (different per process start), causing duplicate job entries | `app/services/normalizer.py:37` | HIGH |
| 2.10 | **No connection pooling config for MongoDB** — default `MongoClient` settings, no explicit `maxPoolSize`, `serverSelectionTimeoutMS`, or `connectTimeoutMS` | `app/db/mongo.py:19` | MEDIUM |

---

## 3. Error Handling Gaps (6)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 3.1 | **Bare `except: pass` swallows all exceptions** — `MemoryError`, `KeyboardInterrupt`, programming bugs all silently hidden. Found in 10+ locations across the codebase | Multiple files | HIGH |
| 3.2 | **`_enrich_jobs` swallows enrichment failures silently** — `except Exception: pass` with zero logging of which URL failed or why | `scrapers/scrape_jobs.py:405-406` | MEDIUM |
| 3.3 | **No React Error Boundary** — any component render crash causes white screen | `job-portal/src/App.jsx` | MEDIUM |
| 3.4 | **Inconsistent error response format** — `/jobs` returns `503` with `{"detail": "Job database is not available"}`, `/jobs/{company}` uses different message | `app/api/jobs.py:96-99,158-159,180-184` | LOW |
| 3.5 | **No graceful JSON parse failure handling in enrichment** — detail page returning binary or non-HTML causes silent failure | `scrapers/scrape_jobs.py:377-405` | LOW |
| 3.6 | **No DB connection validation on startup** — app starts even with malformed MongoDB URI, only fails later at query time with 503 | `app/main.py:18-23` | LOW |

---

## 4. Type Safety (4)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 4.1 | **Heavy `Any` usage** — `dict[str, Any]` pervasive instead of TypedDicts or dataclasses for job payloads. Bypasses all type-checking benefits | All modules | MEDIUM |
| 4.2 | **`Optional[str]` instead of `str | None`** — Python 3.11 specified but uses old-style typing | `app/api/jobs.py:3`, `scrapers/crawlers/orchestrator.py:5` | LOW |
| 4.3 | **Missing return type annotations** — multiple functions lack return types | Various | LOW |
| 4.4 | **Pydantic Job model defined but never used** — `schemas/job.py:Job` not used as response model in any API route. All routes return raw dicts | `app/schemas/job.py:10-25`, `app/api/jobs.py` | MEDIUM |

---

## 5. Code Quality (9)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 5.1 | **Duplicate `timeAgo` function** — same logic defined in `JobCard.jsx` and `JobDetailPage.jsx` | `job-portal/src/components/JobCard.jsx:3-13`, `job-portal/src/pages/JobDetailPage.jsx:19-29` | LOW |
| 5.2 | **Duplicate `_company_name_from_url`** — same function in two files | `scrapers/scrape_jobs.py:494-501`, `scrapers/crawlers/orchestrator.py:13-19` | LOW |
| 5.3 | **Duplicate `detect_ats` with different signatures** — `scrape_jobs.py` returns `str | None`, `base.py` returns `dict[str, str] | None`. Confusing and error-prone | `scrapers/scrape_jobs.py:66-81`, `scrapers/crawlers/base.py:230-279` | MEDIUM |
| 5.4 | **Duplicate `supported_companies` logic** — loads same `company_urls.json` identically in two places | `scrapers/crawlers/orchestrator.py:22-39`, `app/api/jobs.py:16-34` | LOW |
| 5.5 | **Circular import workaround via lazy imports** — `scrape_jobs.py` lazy-imports from `universal.py` inside functions | `scrapers/scrape_jobs.py:106-113,378,518` | MEDIUM |
| 5.6 | **Inconsistent pagination in `crawl_ats_jobs`** — applies `_slice_page` for non-Workday but returns full list for Workday | `scrapers/crawlers/base.py:573` | MEDIUM |
| 5.7 | **Frontend filter field name mismatch** — `Filters.jsx` uses `type`, `experience`, `salary` keys; parent `FindJobsPage` uses `employmentType`, `experience`. `type` and `salary` never consumed | `job-portal/src/components/Filters.jsx:31,54,77,88`, `job-portal/src/pages/FindJobsPage.jsx:20` | MEDIUM |
| 5.8 | **Magic numbers throughout** — `15` for max enrichment, `5` for batch size, `2000` for Oracle fetch limit, `10` for pagination threshold, etc. | `scrapers/scrape_jobs.py:409-410`, `scrapers/crawlers/universal.py:222,534,536,1241` | LOW |
| 5.9 | **Module-level mutable state not thread-safe** — `_KNOWN_COMPANY_CAREERS_URLS`, `_COMPANY_ALIASES`, `_LOADED` are globals modified without locks in async context | `scrapers/crawlers/universal.py:82-84,87-141` | MEDIUM |

---

## 6. Testing Gaps (5)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 6.1 | **No frontend tests** — zero tests for any React component (JobCard, Filters, Pagination, Navbar, SkeletonCard, ErrorState, EmptyState, all pages) | Entire `job-portal/` | HIGH |
| 6.2 | **No API endpoint tests** — no tests for `GET /health`, `GET /jobs`, `GET /jobs/{company}`, `GET /job/{job_id}`, or any error cases (503, 404, 400) | `tests/` | HIGH |
| 6.3 | **No MongoDB operation tests** — `_upsert_jobs_sync`, `_find_jobs_sync`, `_find_companies_sync`, `_find_job_by_id_sync` all untested | `app/services/job_store.py` | MEDIUM |
| 6.4 | **No error handling tests** — network timeouts, malformed HTML/JSON, rate limiting, empty responses, DB failures, cache hit/miss all untested | `tests/test_crawlers.py` | HIGH |
| 6.5 | **No tests for `useJobs` hook** — caching, race condition safety, TTL management untested | `job-portal/src/hooks/useJobs.js` | MEDIUM |

---

## 7. Missing Features (6)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 7.1 | **`app/schemas/user.py` does not exist** — README and ARCHITECTURE.md reference `UserCreate`, `UserLogin`, `UserPublic`, `TokenResponse` but file is missing | `app/schemas/` | HIGH |
| 7.2 | **JWT config missing from `config.py`** — docs claim `jwt_secret`, `jwt_algorithm`, `jwt_expire_minutes` exist but they don't | `app/config.py` | HIGH |
| 7.3 | **MongoDB indexes for `users`, `saved_jobs`, `search_history` missing** — claimed in docs but `_ensure_indexes` only creates jobs indexes | `app/db/mongo.py:39-43` | MEDIUM |
| 7.4 | **Rate limiter unreliable** — in-memory only (no shared state across workers), uses `request.client.host` (unreliable behind proxies), list-based approach is inefficient for high traffic | `app/services/security.py:67-94` | MEDIUM |
| 7.5 | **No production frontend serving** — FastAPI does not serve `job-portal/dist/` despite being listed as planned feature | `app/main.py` | MEDIUM |
| 7.6 | **Playwright not in dependencies** — `_extract_jobs_with_playwright` properly implemented but Playwright not listed in `requirements.txt`. Any usage results in silent ImportError | `requirements.txt`, `scrapers/crawlers/universal.py:963-1057` | LOW |

---

## 8. Data Validation (5)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 8.1 | **`company_url` missing `max_length`** — all other query params have `max_length=200` but `company_url` has none | `app/api/jobs.py:74` | MEDIUM |
| 8.2 | **No control character validation** — `_validate_search_param` checks length but not null bytes, control chars, or unicode normalization attacks | `app/api/jobs.py:37-43` | LOW |
| 8.3 | **No Pydantic validation on scraped data** — `canonicalize_job` uses `str(job.get(...) or "")` which produces `"{}"` or `"None"` for nested objects | `app/schemas/job.py:40-65` | MEDIUM |
| 8.4 | **`urljoin` with `javascript:` URLs** — `urljoin("https://example.com", "javascript:alert(1)")` returns `"javascript:alert(1)"`, a potential XSS vector | `scrapers/crawlers/universal.py:408,477,650,655,731` | MEDIUM |
| 8.5 | **Naive HTML stripping** — `re.sub(r"<[^>]+>", " ", text)` leaves script content artifacts | `app/schemas/job.py:47`, `app/services/normalizer.py:6` | LOW |

---

## 9. Concurrency Issues (3)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 9.1 | **Race condition in rate limiter** — `self._requests[client_ip]` list mutation not protected by lock. Concurrent requests cause lost updates and incorrect counts | `app/services/security.py:77-93` | MEDIUM |
| 9.2 | **Shared mutable `_db` module variable** — `connect_mongo()`, `close_mongo()`, `get_db()` all access `_db` without synchronization. Called from multiple threads via `asyncio.to_thread()` | `app/db/mongo.py:12-13,16-30,33-36` | HIGH |
| 9.3 | **`_ensure_company_urls_loaded()` races** — called from async code without lock. Multiple concurrent calls can race on `_LOADED` flag | `scrapers/crawlers/universal.py:87-141` | MEDIUM |

---

## 10. Logging Gaps (3)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 10.1 | **Sensitive data potentially logged** — database name, URLs with query parameters logged at info/warning level | `app/db/mongo.py:22`, `scrapers/crawlers/base.py:122,157,190,221` | LOW |
| 10.2 | **Missing logs at critical decision points** — no logging on cache hit/miss/eviction, no logging during job upsert, no fallback attempt logging | `app/services/cache.py:22-48`, `app/services/job_store.py:67-81` | MEDIUM |
| 10.3 | **Inconsistent log levels** — `logger.error` used for recoverable failures (should be `warning`), `LOGGER.info` used for verbose per-page fetch logs | `scrapers/scrape_jobs.py:574`, `scrapers/crawlers/base.py:326,355,384,458,505,570` | LOW |

---

## 11. Database Issues (5)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 11.1 | **No text index for keyword searches** — `$or` with `$regex` on `title`, `skills`, `location` causes collection scans. No compound text index exists | `app/db/mongo.py:39-43` | HIGH |
| 11.2 | **Missing index on `location`** — location filter uses `$regex` but no index, causing slow queries | `app/db/mongo.py:39-43` | MEDIUM |
| 11.3 | **No explicit cursor management** — `db.jobs.find(query)` cursor consumed implicitly in list comprehension | `app/services/job_store.py:107` | LOW |
| 11.4 | **Heath check `ping` without timeout** — default `serverSelectionTimeoutMS` (30s) could cause health endpoint to hang | `app/db/mongo.py:48` | LOW |
| 11.5 | **Migration script N+1** — individual `update_one` instead of `bulk_write` | `scripts/migrate_to_prod.py:55-56,62-63` | MEDIUM |

---

## 12. API Design (4)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 12.1 | **Inconsistent response shape** — `/jobs` returns both `latest_jobs` and `jobs` (identical data); `/jobs/{company}` returns only `jobs`; `/job/{job_id}` returns singular `job`. Cache status field alternates between `"live"` and `"mongo"` | `app/api/jobs.py:111-118,161-168,186` | MEDIUM |
| 12.2 | **Missing pagination metadata** — no `total_pages`, no `next`/`prev` URLs in response | `app/api/jobs.py:111-118,161-168` | LOW |
| 12.3 | **No input validation on `job_id` path param** — `job_id: str` has no pattern, length, or character constraints | `app/api/jobs.py:171` | LOW |
| 12.4 | **Duplicate `GET /jobs` and `GET /jobs/{company}`** — both do the same work, logic is duplicated | `app/api/jobs.py:71,121` | LOW |

---

## 13. Frontend Issues (7)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 13.1 | **`useJobs` hook completely unused** — custom hook with caching, race-condition safety, and TTL management sits unused. `FindJobsPage` implements its own manual fetching without caching | `job-portal/src/hooks/useJobs.js`, `job-portal/src/pages/FindJobsPage.jsx` | MEDIUM |
| 13.2 | **Filters not actually used by backend** — `employmentType`, `experience`, `salary`, `type` are computed in UI but backend API (`GET /jobs`) only accepts `company`, `keyword`, `location`, `page`, `limit`. Filter values are silently ignored | `job-portal/src/pages/FindJobsPage.jsx:36-44` | HIGH |
| 13.3 | **Race condition on unmounted component** — `fetchCompanies().then(setCompanies)` fires on unmount (React state update warning) | `job-portal/src/pages/HomePage.jsx:58` | LOW |
| 13.4 | **Stale data flash in detail page** — when `id` changes, previous job data briefly shows before loading state appears | `job-portal/src/pages/JobDetailPage.jsx:38-48` | LOW |
| 13.5 | **No bundle splitting** — all routes eagerly loaded, `React.lazy`/`Suspense` not used | `job-portal/src/App.jsx` | LOW |
| 13.6 | **`useCallback` unnecessary** — `loadJobs` wrapped in `useCallback` but only called from `useEffect` and `handlePageChange`, providing no real benefit | `job-portal/src/pages/FindJobsPage.jsx:31` | LOW |
| 13.7 | **`VITE_API_BASE` bypasses Vite proxy** — env var directly calls `localhost:8000` instead of going through the Vite proxy which rewrites `/api` paths | `job-portal/.env` | MEDIUM |

---

## 14. Configuration (5)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 14.1 | **Port mismatch: dev=8000, Docker=10000** — `run.py` runs on 8000, Dockerfile exposes 10000, Vite proxy targets 8000. Confusing and inconsistent | `run.py:4`, `Dockerfile:13`, `docker-compose.yml:28`, `job-portal/vite.config.js:10` | MEDIUM |
| 14.2 | **CORS origin value `["*"]` is a JSON array literal** — `docker-compose.yml` sets `CORS_ORIGINS=["*"]` which `config.py` splits on `,` produces literal `["*"]` string, never matching any actual origin. CORS breaks in Docker deployment | `docker-compose.yml:32`, `app/config.py:22-26` | HIGH |
| 14.3 | **`.env` committed to git** — MongoDB credentials with password exposed in version history | `.env` | CRITICAL |
| 14.4 | **Vite proxy targets port 8000 but Docker uses 10000** — developers using Docker backend + local frontend have broken API requests | `job-portal/vite.config.js:10` | MEDIUM |
| 14.5 | **`motor` missing from requirements** — async MongoDB driver absent from `requirements.txt`; code works around it with `asyncio.to_thread` | `requirements.txt` | HIGH |

---

## 15. Dependency Issues (5)

| # | Issue | File(s) | Severity |
|---|-------|---------|----------|
| 15.1 | **`motor` not in `requirements.txt`** — sync PyMongo used as workaround, blocking thread pool on every DB operation | `requirements.txt` | HIGH |
| 15.2 | **`python-dotenv` not in `requirements.txt`** — imported by `config.py` and `migrate_to_prod.py` but only present as transitive dependency | `requirements.txt` | MEDIUM |
| 15.3 | **`playwright` not in `requirements.txt`** — production code imports it with `try/except ImportError`, silently falling back | `requirements.txt`, `scrapers/crawlers/universal.py:963-1057` | LOW |
| 15.4 | **HTTPX connection pooling not used** — `httpx` is installed but every call creates/destroys a new `AsyncClient` | `scrapers/crawlers/base.py:112-113,147` | LOW |
| 15.5 | **`pytest-asyncio` not installed** — tests use manual `asyncio.run()` instead of `pytest.mark.asyncio` fixtures | `requirements.txt` | LOW |

---

## Summary

| Category | Count | Key Severities |
|----------|-------|----------------|
| Security | 8 | 2 CRITICAL, 2 HIGH |
| Performance | 10 | 2 HIGH |
| Error Handling | 6 | 1 HIGH |
| Type Safety | 4 | — |
| Code Quality | 9 | — |
| Testing Gaps | 5 | 2 HIGH |
| Missing Features | 6 | 2 HIGH |
| Data Validation | 5 | — |
| Concurrency | 3 | 1 HIGH |
| Logging | 3 | — |
| Database | 5 | 1 HIGH |
| API Design | 4 | — |
| Frontend | 7 | 1 HIGH |
| Configuration | 5 | 1 CRITICAL, 1 HIGH |
| Dependencies | 5 | 1 HIGH |
| **TOTAL** | **85** | **18 HIGH/CRITICAL** |
