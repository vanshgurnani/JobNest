from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    types { name kind fields { name type { name kind ofType { name kind } } } }
    queryType { name }
  }
}
"""

_JOB_TYPE_KEYWORDS = {"job", "jobs", "position", "position", "requisition", "opening", "career", "careers", "vacancy"}


async def introspect_graphql(base_url: str) -> dict[str, Any] | None:
    graphql_urls = [
        f"{base_url.rstrip('/')}/graphql",
        f"{base_url.rstrip('/')}/api/graphql",
        f"{base_url.rstrip('/')}/v1/graphql",
    ]

    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        for url in graphql_urls:
            try:
                r = await c.post(url, json={"query": _INTROSPECTION_QUERY}, headers=headers)
                if r.status_code != 200:
                    r = await c.get(url, params={"query": _INTROSPECTION_QUERY}, headers=headers)
                if r.status_code != 200:
                    continue

                data = r.json()
                schema = data.get("data", {}).get("__schema")
                if not schema:
                    continue

                job_types = _find_job_types(schema)
                if job_types:
                    queries = _generate_job_queries(schema, job_types)
                    logger.info("GraphQL introspection succeeded for %s: %d job types", url, len(job_types))
                    return {
                        "url": url,
                        "job_types": job_types,
                        "queries": queries,
                    }
            except Exception:
                continue

    return None


def _find_job_types(schema: dict[str, Any]) -> list[str]:
    job_types: list[str] = []
    for t in schema.get("types", []):
        name = t.get("name", "")
        if name.startswith("__") or name in {"Query", "Mutation", "Subscription"}:
            continue
        lower = name.lower()
        if any(kw in lower for kw in _JOB_TYPE_KEYWORDS):
            job_types.append(name)
    return job_types


def _generate_job_queries(schema: dict[str, Any], job_types: list[str]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    query_type = schema.get("queryType", {}).get("name", "Query")
    for t in schema.get("types", []):
        if t.get("name") != query_type:
            continue
        for field in t.get("fields", []):
            fname = field.get("name", "")
            lower = fname.lower()
            if any(kw in lower for kw in _JOB_TYPE_KEYWORDS):
                queries.append({
                    "query": f"query {{ {fname} {{ id title location }} }}",
                    "field": fname,
                })
    return queries