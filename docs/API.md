# API Reference

## Base URL

```
http://localhost:8000
```

In Docker setup: `http://localhost:10000`

## Endpoints

### Health Check

```
GET /health
```

Returns the server status and MongoDB connection state.

**Response:**
```json
{
  "status": "running",
  "mongodb": "available"
}
```

### List Jobs

```
GET /jobs?company=&keyword=&location=&page=1&limit=20
```

Returns paginated job listings. All query parameters are optional.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `company` | string | - | Filter by company name/slug |
| `company_url` | string | - | Company careers page URL |
| `keyword` | string | - | Keyword search (e.g. "engineer") |
| `location` | string | - | Location filter (e.g. "remote", "Seattle") |
| `page` | integer | 1 | Page number (1-indexed) |
| `limit` | integer | 20 | Items per page (1-100) |

**Response:**
```json
{
  "total": 150,
  "latest_jobs": [...],
  "jobs": [...],
  "page": 1,
  "limit": 20,
  "cache": "live"
}
```

### List Jobs by Company

```
GET /jobs/{company}?keyword=&location=&page=1&limit=20
```

Shorthand for filtering by company. Same response format as `/jobs`.

### Get Job Detail

```
GET /job/{job_id}
```

Returns a single job by its unique ID.

**Response:**
```json
{
  "job": {
    "id": "abc123",
    "company": "Amazon",
    "title": "Software Engineer",
    "location": "Seattle, WA",
    "description": "...",
    "skills": ["Java", "AWS"],
    "apply_url": "https://...",
    "source": "amazon",
    "employment_type": "Full-time",
    "experience": "Mid-Senior level",
    "posted_date": "2025-01-15"
  },
  "cache": "mongo"
}
```

**Error Responses:**
- `404` - Job not found
- `503` - Database unavailable

## Caching

Responses are cached in-memory with a 15-minute TTL. The `cache` field in the response indicates whether the result was served from memory cache (`memory`) or freshly fetched from MongoDB (`live` or `mongo`).

Cache is automatically invalidated after 15 minutes and evicted under LRU pressure (max 512 entries).

## Data Schema

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique job identifier (MD5 hash) |
| `company` | string | Company name |
| `title` | string | Job title |
| `location` | string | Job location |
| `description` | string | Full description |
| `employment_type` | string | Full-time, Part-time, etc. |
| `experience` | string | Seniority level |
| `skills` | array[string] | Extracted skills |
| `apply_url` | string | Application link |
| `source` | string | Crawler source identifier |
| `posted_date` | string | Date posted |
| `crawled_at` | datetime | When it was scraped |
