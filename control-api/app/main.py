from fastapi import FastAPI
import asyncio

from app.config import settings
from app.health import check_postgres, check_redis

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)


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
