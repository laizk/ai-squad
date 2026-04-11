from fastapi import FastAPI

from app.config import settings

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
    return {
        "status": "ok",
        "service": "control-api",
        "version": settings.app_version,
        "environment": settings.app_env,
        "phase": settings.app_phase,
    }
