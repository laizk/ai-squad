from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter

from app.db import open_ready_connection
from app.models import EntityType, RevisionListResponse, RevisionReason, RevisionResponse
from app.revision_utils import json_array

router = APIRouter(prefix="/api/v1/revisions", tags=["revisions"])


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return value


@router.get("/{entity_type}/{entity_id}", response_model=RevisionListResponse)
async def list_revisions(entity_type: EntityType, entity_id: UUID) -> RevisionListResponse:
    conn = await open_ready_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT *
              FROM revisions
             WHERE entity_type = $1
               AND entity_id = $2
             ORDER BY revision_number ASC
            """,
            entity_type.value,
            entity_id,
        )
    finally:
        await conn.close()

    revisions = [
        RevisionResponse(
            revision_number=row["revision_number"],
            actor=row["actor"],
            change_summary=row["change_summary"],
            reason=RevisionReason(
                category=row["reason_category"],
                detail=row["reason_detail"],
                references=json_array(_json_value(row["reason_references"])),
            ),
            before_snapshot=_json_value(row["before_snapshot"]),
            after_snapshot=_json_value(row["after_snapshot"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]

    return RevisionListResponse(entity_type=entity_type, entity_id=entity_id, revisions=revisions)
