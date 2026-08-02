import asyncio
import logging
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse

from app.api.jobs import router as jobs_router
from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo, ping_mongo
from app.services.logging_setup import setup_logging
from app.services.security import RateLimitMiddleware, SecurityHeadersMiddleware

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("Starting Job Nest API (fastapi)")
    try:
        await connect_mongo()
        app.state.mongo_available = True
        logger.info("MongoDB connected: %s", get_settings().mongodb_db)
    except Exception as exc:
        logger.warning("MongoDB unavailable; running with live crawl + memory cache only: %s", exc)
        app.state.mongo_available = False

    yield

    logger.info("Shutting down Job Nest API")
    await close_mongo()
    logger.info("MongoDB connection closed")


settings = get_settings()
app = FastAPI(title="AI Job Intelligence Crawler", version="1.0.0", lifespan=lifespan)
app.include_router(jobs_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    client = request.client.host if request.client else "-"
    logger.info(
        "%s %s -> %s [%d ms] (%s)",
        request.method,
        request.url.path,
        response.status_code,
        int(duration_ms),
        client,
    )
    response.headers["X-Process-Time-Ms"] = str(int(duration_ms))
    return response


@app.on_event("startup")
async def start_scheduler():
    try:
        from scrapers.scheduler import scheduler
        scheduler.start()
    except Exception:
        logger.exception("Scheduler failed to start")


@app.get("/html")
async def index():
    return FileResponse(Path(__file__).resolve().parent.parent / "local-frontend.html")


@app.get("/realtime")
async def realtime():
    return FileResponse(Path(__file__).resolve().parent.parent / "realtime-frontend.html")


@app.route("/health", methods=["GET", "HEAD"])
async def health(request: Request) -> dict[str, str] | Response:
    if request.method == "HEAD":
        return Response(status_code=200)
    status = {"status": "running", "mongodb": "unavailable"}
    try:
        status.update(await asyncio.to_thread(ping_mongo))
    except Exception:
        logger.warning("Health check: MongoDB ping failed")
    return status
