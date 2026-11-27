from __future__ import annotations

import os
import httpx
from fastapi import HTTPException

CRAWLER_URL = os.getenv("GO_CRAWLER_URL", "http://localhost:8081").rstrip("/")
CRAWLER_TOKEN = os.getenv("CRAWLER_API_TOKEN", "")

async def crawl_with_go(*, url: str, company: str | None = None, save: bool = True, max_pages: int = 5) -> dict:
    headers = {"Authorization": f"Bearer {CRAWLER_TOKEN}"} if CRAWLER_TOKEN else {}
    payload = {"url": url, "company": company or "", "save": save, "max_pages": max_pages}
    try:
        async with httpx.AsyncClient(timeout=190.0) as client:
            response = await client.post(f"{CRAWLER_URL}/crawl", json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Go crawler timed out") from exc
    except httpx.HTTPStatusError as exc:
        detail = "Go crawler rejected the target"
        try:
            detail = exc.response.json().get("error", detail)
        except ValueError:
            pass
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Go crawler is unavailable") from exc
