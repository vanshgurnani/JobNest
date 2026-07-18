from fastapi import FastAPI

from app.api.jobs import router as jobs_router

app = FastAPI(title="AI Job Intelligence Crawler", version="1.0.0")
app.include_router(jobs_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "running"}
