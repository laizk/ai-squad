from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "sql"


async def apply_migrations(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          filename TEXT PRIMARY KEY,
          checksum VARCHAR(64) NOT NULL,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    rows = await conn.fetch("SELECT filename, checksum FROM schema_migrations")
    applied = {row["filename"]: row["checksum"] for row in rows}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        checksum = sha256(sql.encode("utf-8")).hexdigest()
        previous = applied.get(path.name)

        if previous == checksum:
            continue

        if previous and previous != checksum:
            raise RuntimeError(f"Migration checksum mismatch for {path.name}")

        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                """
                INSERT INTO schema_migrations (filename, checksum)
                VALUES ($1, $2)
                ON CONFLICT (filename) DO NOTHING
                """,
                path.name,
                checksum,
            )
