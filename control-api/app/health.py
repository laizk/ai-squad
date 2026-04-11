from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from redis.asyncio import Redis

from app.config import settings


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    state: str
    detail: str | None = None


def _normalize_postgres_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    if dsn.startswith("postgres+asyncpg://"):
        return dsn.replace("postgres+asyncpg://", "postgres://", 1)

    parts = urlsplit(dsn)
    if parts.scheme in {"postgresql", "postgres"}:
        return urlunsplit(parts)

    return dsn


async def check_postgres() -> DependencyStatus:
    if not settings.database_url:
        return DependencyStatus("postgres", "error", "DATABASE_URL is not configured")

    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(_normalize_postgres_dsn(settings.database_url)),
            timeout=settings.health_timeout_seconds,
        )
        value = await conn.fetchval("SELECT schema_version FROM platform_bootstrap LIMIT 1;")
        detail = f"schema_version={value}" if value else "schema marker missing"
        return DependencyStatus("postgres", "ok", detail)
    except Exception as exc:
        return DependencyStatus("postgres", "error", str(exc))
    finally:
        if conn is not None:
            await conn.close()


async def check_redis() -> DependencyStatus:
    if not settings.redis_url:
        return DependencyStatus("redis", "error", "REDIS_URL is not configured")

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        pong = await asyncio.wait_for(client.ping(), timeout=settings.health_timeout_seconds)
        detail = "pong" if pong else "unexpected ping response"
        state = "ok" if pong else "error"
        return DependencyStatus("redis", state, detail)
    except Exception as exc:
        return DependencyStatus("redis", "error", str(exc))
    finally:
        await client.aclose()
