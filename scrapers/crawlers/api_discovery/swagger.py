from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OPENAPI_PATHS = [
    "/api/docs",
    "/api/v1/openapi.json",
    "/api/openapi.json",
    "/openapi.json",
    "/swagger.json",
    "/swagger/v1/swagger.json",
    "/api/swagger.json",
    "/api/v1/api-docs",
    "/api/api-docs",
]

_JOB_KEYWORDS = {"job", "jobs", "position", "requisition", "opening", "career", "careers", "vacancy", "hire", "recruit"}


async def detect_openapi(base_url: str) -> dict[str, Any] | None:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        for path in _OPENAPI_PATHS:
            url = f"{base_url.rstrip('/')}{path}"
            try:
                r = await c.get(url, headers=headers)
                if r.status_code != 200:
                    continue

                spec = r.json()
                endpoints = _extract_job_endpoints(spec)
                if endpoints:
                    logger.info("OpenAPI spec found at %s: %d job endpoints", url, len(endpoints))
                    return {"url": url, "endpoints": endpoints}

            except Exception:
                continue

    return None


def _extract_job_endpoints(spec: dict[str, Any]) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        lower_path = path.lower()
        if not any(kw in lower_path for kw in _JOB_KEYWORDS):
            continue
        for method, details in methods.items():
            if method.lower() not in {"get", "post"}:
                continue
            endpoints.append({
                "path": path,
                "method": method.upper(),
                "summary": details.get("summary", ""),
                "parameters": details.get("parameters", []),
            })
    return endpoints