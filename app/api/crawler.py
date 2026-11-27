from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.services.go_crawler import crawl_with_go

router = APIRouter(prefix="/crawler", tags=["Go crawler"])

class CrawlRequest(BaseModel):
    url: HttpUrl
    company: str | None = Field(default=None, max_length=160)
    save: bool = True
    max_pages: int = Field(default=5, ge=1, le=25)

@router.post("/scan")
async def scan_target(payload: CrawlRequest) -> dict:
    """Submit any public careers page or job URL to the Go crawler."""
    return await crawl_with_go(url=str(payload.url), company=payload.company, save=payload.save, max_pages=payload.max_pages)

@router.get("/health")
async def crawler_health() -> dict:
    from app.services.go_crawler import CRAWLER_URL
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(f"{CRAWLER_URL}/health")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Go crawler is unavailable") from exc
