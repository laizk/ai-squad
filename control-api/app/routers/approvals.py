from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.db import open_ready_connection
from app.models import (
    ApprovalCreate,
    ApprovalEvidenceResponse,
    ApprovalListResponse,
    ApprovalResponse,
    EntityType,
)
from app.revision_utils import utc_value

router = APIRouter(prefix="/api/v1", tags=["approvals"])

ENTITY_TABLES = {
    EntityType.project.value: "projects",
    EntityType.team_member.value: "team_members",
    EntityType.project_assignment.value: "project_team_members",
    EntityType.milestone.value: "milestones",
    EntityType.task.value: "tasks",
}


def _serialize_approval_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "approved_revision_number": row["approved_revision_number"],
        "status": row["status"],
        "comment": row["comment"],
        "override_used": row["override_used"],
        "override_reason": row["override_reason"],
        "is_stale": row["is_stale"],
        "stale_at": utc_value(row["stale_at"]),
        "decided_by": row["decided_by"],
        "decided_at": utc_value(row["decided_at"]),
        "created_at": utc_value(row["created_at"]),
        "updated_at": utc_value(row["updated_at"]),
    }


def _serialize_evidence_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "approval_id": row["approval_id"],
        "evidence_type": row["evidence_type"],
        "artifact_id": row["artifact_id"],
        "external_url": row["external_url"],
        "description": row["description"],
        "created_at": utc_value(row["created_at"]),
    }


async def _fetch_entity_or_404(conn: Any, entity_type: EntityType, entity_id: UUID) -> Any:
    table_name = ENTITY_TABLES[entity_type.value]
    row = await conn.fetchrow(f"SELECT id, current_version FROM {table_name} WHERE id = $1", entity_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity_type.value} not found")
    return row


async def _fetch_approval_or_404(conn: Any, approval_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT * FROM approvals WHERE id = $1", approval_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return row


async def _ensure_artifact_exists(conn: Any, artifact_id: UUID) -> None:
    artifact = await conn.fetchrow("SELECT id FROM artifacts WHERE id = $1", artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")


async def _fetch_approval_evidence(conn: Any, approval_id: UUID) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT *
          FROM approval_evidence
         WHERE approval_id = $1
         ORDER BY created_at ASC, id ASC
        """,
        approval_id,
    )
    return [_serialize_evidence_row(row) for row in rows]


async def _build_approval_response(conn: Any, row: Any) -> ApprovalResponse:
    payload = _serialize_approval_row(row)
    payload["evidence"] = [
        ApprovalEvidenceResponse.model_validate(item) for item in await _fetch_approval_evidence(conn, row["id"])
    ]
    return ApprovalResponse.model_validate(payload)


@router.post("/approvals", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(payload: ApprovalCreate) -> ApprovalResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            entity_row = await _fetch_entity_or_404(conn, payload.entity_type, payload.entity_id)
            revision_exists = await conn.fetchval(
                """
                SELECT 1
                  FROM revisions
                 WHERE entity_type = $1
                   AND entity_id = $2
                   AND revision_number = $3
                """,
                payload.entity_type.value,
                payload.entity_id,
                payload.approved_revision_number,
            )
            if revision_exists is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approved revision not found")

            current_version = entity_row["current_version"]
            is_stale = payload.approved_revision_number < current_version
            if is_stale and not payload.override_used:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Approval targets a stale revision; set override_used with override_reason to record it.",
                )

            approval_row = await conn.fetchrow(
                """
                INSERT INTO approvals (
                  entity_type,
                  entity_id,
                  approved_revision_number,
                  status,
                  comment,
                  override_used,
                  override_reason,
                  is_stale,
                  stale_at,
                  decided_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING *
                """,
                payload.entity_type.value,
                payload.entity_id,
                payload.approved_revision_number,
                payload.status.value,
                payload.comment,
                payload.override_used,
                payload.override_reason,
                is_stale,
                datetime.now(timezone.utc) if is_stale else None,
                "human:local",
            )

            if approval_row is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Approval was not created")

            approval_id = approval_row["id"]
            for item in payload.evidence:
                if item.artifact_id is not None:
                    await _ensure_artifact_exists(conn, item.artifact_id)
                await conn.execute(
                    """
                    INSERT INTO approval_evidence (
                      approval_id,
                      evidence_type,
                      artifact_id,
                      external_url,
                      description
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    approval_id,
                    item.evidence_type.value,
                    item.artifact_id,
                    item.external_url,
                    item.description,
                )

            approval_row = await _fetch_approval_or_404(conn, approval_id)
            response = await _build_approval_response(conn, approval_row)
    finally:
        await conn.close()

    return response


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval(approval_id: UUID) -> ApprovalResponse:
    conn = await open_ready_connection()
    try:
        row = await _fetch_approval_or_404(conn, approval_id)
        response = await _build_approval_response(conn, row)
    finally:
        await conn.close()

    return response


@router.get("/entities/{entity_type}/{entity_id}/approvals", response_model=ApprovalListResponse)
async def list_entity_approvals(entity_type: EntityType, entity_id: UUID) -> ApprovalListResponse:
    conn = await open_ready_connection()
    try:
        await _fetch_entity_or_404(conn, entity_type, entity_id)
        rows = await conn.fetch(
            """
            SELECT *
              FROM approvals
             WHERE entity_type = $1
               AND entity_id = $2
             ORDER BY decided_at DESC, created_at DESC
            """,
            entity_type.value,
            entity_id,
        )
        items = [await _build_approval_response(conn, row) for row in rows]
    finally:
        await conn.close()

    return ApprovalListResponse(total=len(items), items=items)
