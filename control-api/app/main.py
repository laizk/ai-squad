from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
import asyncio

from app.config import settings
from app.db import ensure_database_ready
from app.health import check_postgres, check_redis
from app.routers.projects import router as projects_router
from app.routers.revisions import router as revisions_router
from app.routers.team_members import router as team_members_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await ensure_database_ready()
    except Exception as exc:
        logger.warning("Database migrations were not applied during startup: %s", exc)

    yield

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(projects_router)
app.include_router(revisions_router)
app.include_router(team_members_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "message": settings.app_name,
        "phase": settings.app_phase,
        "docs": "/docs",
    }


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    postgres, redis = await asyncio.gather(check_postgres(), check_redis())
    status = "ok" if postgres.state == "ok" and redis.state == "ok" else "degraded"

    return {
        "status": status,
        "service": "control-api",
        "version": settings.app_version,
        "environment": settings.app_env,
        "phase": settings.app_phase,
        "postgres": postgres.state,
        "postgres_detail": postgres.detail or "",
        "redis": redis.state,
        "redis_detail": redis.detail or "",
    }


@app.get("/api/v1/bootstrap")
async def bootstrap() -> dict[str, str]:
    postgres = await check_postgres()
    return {
        "service": "control-api",
        "phase": settings.app_phase,
        "postgres": postgres.state,
        "postgres_detail": postgres.detail or "",
    }
