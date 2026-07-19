from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router

app = FastAPI(title="AI Job Intelligence Crawler", version="1.0.0")
app.include_router(jobs_router)

# Allow browser-based frontend clients.
# Keep this permissive to simplify integration; tighten as needed for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "running"}

