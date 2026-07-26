import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo, ping_mongo

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await connect_mongo()
        app.state.mongo_available = True
    except Exception as exc:  # pragma: no cover - depends on local service availability
        logger.warning("MongoDB unavailable; running with live crawl + memory cache only: %s", exc)
        app.state.mongo_available = False

    yield

    await close_mongo()


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


@app.route("/health", methods=["GET", "HEAD"])
async def health(request: Request) -> dict[str, str] | Response:
    if request.method == "HEAD":
        return Response(status_code=200)
    status = {"status": "running", "mongodb": "unavailable"}
    try:
        status.update(await ping_mongo())
    except Exception:
        pass
    return status
