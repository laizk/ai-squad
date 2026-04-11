from __future__ import annotations

import asyncio

import asyncpg

from app.config import settings
from app.health import normalize_postgres_dsn
from app.migrations import apply_migrations

_migrations_ready = False
_migration_lock = asyncio.Lock()


async def connect_db() -> asyncpg.Connection:
    return await asyncpg.connect(normalize_postgres_dsn(settings.database_url))


async def connect_migration_db() -> asyncpg.Connection:
    dsn = settings.migration_database_url or settings.database_url
    return await asyncpg.connect(normalize_postgres_dsn(dsn))


async def ensure_database_ready() -> None:
    global _migrations_ready

    if _migrations_ready:
        return

    async with _migration_lock:
        if _migrations_ready:
            return

        conn = await connect_migration_db()
        try:
            await apply_migrations(conn)
        finally:
            await conn.close()

        _migrations_ready = True


async def open_ready_connection() -> asyncpg.Connection:
    await ensure_database_ready()
    return await connect_db()
