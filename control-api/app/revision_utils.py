from __future__ import annotations

import json
from datetime import timezone
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder


def json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def json_array(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return list(value)


def utc_value(value: Any) -> Any:
    if value is None:
        return None
    return value.astimezone(timezone.utc)


async def insert_revision(
    conn: Any,
    *,
    entity_type: str,
    entity_id: UUID,
    revision_number: int,
    actor: str,
    change_summary: str,
    reason_category: str,
    reason_detail: str,
    reason_references: list[str],
    before_snapshot: dict[str, Any] | None,
    after_snapshot: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO revisions (
          entity_type,
          entity_id,
          revision_number,
          actor,
          change_summary,
          reason_category,
          reason_detail,
          reason_references,
          before_snapshot,
          after_snapshot
        )
        VALUES (
          $1,
          $2,
          $3,
          $4,
          $5,
          $6,
          $7,
          $8::jsonb,
          $9::jsonb,
          $10::jsonb
        )
        """,
        entity_type,
        entity_id,
        revision_number,
        actor,
        change_summary,
        reason_category,
        reason_detail,
        json.dumps(reason_references),
        json.dumps(jsonable_encoder(before_snapshot)) if before_snapshot is not None else None,
        json.dumps(jsonable_encoder(after_snapshot)),
    )
