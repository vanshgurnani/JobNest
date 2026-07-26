# Security Audit Report

*Generated from codebase analysis on 26 Jul 2026*

---

## HIGH Severity

### 1. Default JWT Secret in Production

**File:** `app/config.py:19`

```python
jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-production")
```

A hardcoded fallback `"change-me-in-production"` is used when `JWT_SECRET` env var is not set. Anyone who knows this default can forge valid JWTs. **Must be set to a strong random value in production.**

---

### 2. Authentication Schema Defined but No Auth Middleware Implemented

- `app/schemas/user.py` — defines `UserCreate`, `UserLogin`, `TokenResponse` (with `password` field)
- `app/config.py` — configures `jwt_secret`, `jwt_algorithm`, `jwt_expire_minutes`
- **No routes use authentication** — no `Depends(get_current_user)`, no OAuth2/`HTTPBearer`, no login/register endpoints found

The auth schemas exist but the auth layer is **entirely unimplemented**. Any endpoint that exposes user-specific data is completely unauthenticated.

---

### 3. No CSRF Protection on State-Changing Endpoints

No CSRF tokens, `SameSite` cookies, or origin checks are implemented. The CORS config allows credentials (`allow_credentials=True`) with permissive methods/headers (`allow_methods=["*"]`, `allow_headers=["*"]`). Any cross-origin request can be triggered on behalf of an authenticated user if/when auth is added.

**Files affected:**
- `app/main.py:32-37` — CORS config with broad allow-headers & allow-methods
- `app/api/jobs.py` — all endpoints

---

### 4. SSRF Risk — Scraper Fetches User-Provided URLs

**File:** `app/api/jobs.py:52-53`

```python
company: Optional[str] = Query(default=None, description="Optional company filter"),
company_url: Optional[str] = Query(default=None, description="Optional official company careers/base URL"),
```

The `company_url` parameter is passed through to the scraper which makes HTTP requests to the provided URL. While there is some validation (company name must be in the supported list or a URL must be provided), an attacker who can reach the API could point this at internal services (`http://localhost:27017`, `http://169.254.169.254/`, etc.) and the scraper will fetch them.

**Propagation:**
- `app/api/jobs.py:73-81` → `services/job_store.py` → `scrapers/crawlers/universal.py:1314`
- `universal.py:1330` — `await _fetch_html(fetch_url, ...)` makes the actual HTTP request

---

## MEDIUM Severity

### 5. Rate Limiting Config Exists but Not Enforced

**File:** `app/config.py:32-33`

```python
rate_limit_requests: int = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
```

Rate limit settings are defined but **no middleware or dependency applies them**. There is no import of `slowapi`, `fastapi-limiter`, or any rate-limiting library in `main.py`. The API has no protection against brute-force or DoS attacks.

---

### 6. NoSQL Injection Risk in MongoDB Queries

**File:** `app/services/job_store.py:36-45`

```python
query["company"] = {"$regex": f"^{re.escape(company.strip())}$", "$options": "i"}
...
query["$or"] = [
    {"title": {"$regex": escaped, "$options": "i"}},
    {"description": {"$regex": escaped, "$options": "i"}},
    {"skills": {"$regex": escaped, "$options": "i"}},
]
query["location"] = {"$regex": re.escape(location.strip()), "$options": "i"}
```

Input is passed through `re.escape()` which prevents regex injection, but **input size is not bounded**. An attacker could send massive query strings causing excessive CPU usage on MongoDB. Additionally, the `$or` operator with three `$regex` fields on large collections is expensive and could be exploited as a resource-exhaustion vector.

---

### 7. HTTP Exceptions May Leak Internal State

**File:** `app/api/jobs.py:82-86`

```python
except RuntimeError as exc:
    raise HTTPException(
        status_code=503,
        detail="Job database is not available. Run the scraper in db mode before serving the portal.",
    ) from exc
```

The `from exc` clause preserves the original traceback in the exception chain. In debug mode, FastAPI will expose the full traceback including internal paths. Additionally, the 503 detail message reveals the application's internal workflow ("Run the scraper in db mode").

---

### 8. No Security Headers

No `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`, or `Referrer-Policy` headers are set on API responses. This makes the application susceptible to clickjacking, MIME-type sniffing, and other browser-based attacks.

**File:** `app/main.py:28-38` — app setup with no security middleware

---

### 9. Error Response Text Leaks Server Details

**File:** `job-portal/src/services/api.js:16-17`

```javascript
const text = await res.text().catch(() => '');
throw new Error(text || `Request failed (${res.status})`);
```

If the server returns an error with a body (e.g., validation errors, stack traces), the full text is thrown as an error message. This could leak internal error details to the client/browser console.

---

## LOW Severity

### 10. Deprecated/Stale Code Duplicated in `scripts/scraping/`

**Directory:** `scripts/scraping/crawlers/`

This directory contains a full copy of the scraper codebase (`base.py`, `universal.py`, `orchestrator.py`) that is **not used by the main application**. It is an older stale version that is:
- Out of date with the active `scrapers/crawlers/` code
- Not maintained
- Creates confusion about which code is authoritative

Issues found in stale code would not be exploitable through the running application, but could mislead developers.

---

### 11. MongoDB Connection String May Log in Plain Text

**File:** `app/db/mongo.py:22`

```python
logger.info("Connected to MongoDB database: %s", settings.mongodb_db)
```

While this logs only the database name (not the full URI), if MongoDB URIs are logged elsewhere or if the database name contains sensitive information, it could leak in logs.

---

### 12. No Input Size Validation on `company_url`

**File:** `app/api/jobs.py:53`

```python
company_url: Optional[str] = Query(default=None, ...)
```

The `company_url` parameter has no `max_length` constraint. A URL of several megabytes could be passed, potentially causing memory issues. Additionally, the scraper's HTTP client has no explicit maximum response size.

---

## Summary

| # | Issue | Severity | File |
|---|-------|----------|------|
| 1 | Default JWT secret | **HIGH** | `app/config.py:19` |
| 2 | Auth schema with no auth layer | **HIGH** | `app/schemas/user.py` |
| 3 | No CSRF protection | **HIGH** | `app/main.py:32-37` |
| 4 | SSRF via `company_url` parameter | **HIGH** | `app/api/jobs.py:52-53` |
| 5 | Rate limiting not enforced | **MEDIUM** | `app/config.py:32-33` |
| 6 | NoSQL injection risk (unbounded regex) | **MEDIUM** | `app/services/job_store.py:36-45` |
| 7 | HTTP exceptions leak internal state | **MEDIUM** | `app/api/jobs.py:82-86` |
| 8 | Missing security headers | **MEDIUM** | `app/main.py:28-38` |
| 9 | Error text leaks server details | **MEDIUM** | `job-portal/src/services/api.js:16` |
| 10 | Stale duplicate code | **LOW** | `scripts/scraping/` |
| 11 | MongoDB info in logs | **LOW** | `app/db/mongo.py:22` |
| 12 | No input size validation on URLs | **LOW** | `app/api/jobs.py:53` |
