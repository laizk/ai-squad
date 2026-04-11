from __future__ import annotations

import json
from datetime import timezone
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, HTTPException, Query, status

from app.db import open_ready_connection
from app.models import ProjectCreate, ProjectListResponse, ProjectResponse, ProjectStatus, ProjectUpdate

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _serialize_project_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "github_org": row["github_org"],
        "github_repo": row["github_repo"],
        "github_project_id": row["github_project_id"],
        "current_version": row["current_version"],
        "metadata": _json_object(row["metadata"]),
        "created_at": row["created_at"].astimezone(timezone.utc),
        "updated_at": row["updated_at"].astimezone(timezone.utc),
    }


async def _fetch_project_or_404(conn: Any, project_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


async def _insert_revision(
    conn: Any,
    *,
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
          'project',
          $1,
          $2,
          $3,
          $4,
          $5,
          $6,
          $7::jsonb,
          $8::jsonb,
          $9::jsonb
        )
        """,
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


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate) -> ProjectResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO projects (
                  name,
                  description,
                  github_org,
                  github_repo,
                  github_project_id,
                  metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                RETURNING *
                """,
                payload.name,
                payload.description,
                payload.github_org,
                payload.github_repo,
                payload.github_project_id,
                json.dumps(payload.metadata or {}),
            )
            project = _serialize_project_row(row)
            await _insert_revision(
                conn,
                entity_id=project["id"],
                revision_number=1,
                actor="human:local",
                change_summary="Initial project creation",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=None,
                after_snapshot=project,
            )
    finally:
        await conn.close()

    return ProjectResponse.model_validate(project)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    status_filter: ProjectStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> ProjectListResponse:
    conn = await open_ready_connection()
    try:
        offset = (page - 1) * per_page
        if status_filter is None:
            total = await conn.fetchval("SELECT COUNT(*) FROM projects")
            rows = await conn.fetch(
                """
                SELECT * FROM projects
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                per_page,
                offset,
            )
        else:
            total = await conn.fetchval("SELECT COUNT(*) FROM projects WHERE status = $1", status_filter.value)
            rows = await conn.fetch(
                """
                SELECT * FROM projects
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                status_filter.value,
                per_page,
                offset,
            )
    finally:
        await conn.close()

    items = [ProjectResponse.model_validate(_serialize_project_row(row)) for row in rows]
    return ProjectListResponse(total=total, page=page, per_page=per_page, items=items)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID) -> ProjectResponse:
    conn = await open_ready_connection()
    try:
        row = await _fetch_project_or_404(conn, project_id)
    finally:
        await conn.close()

    return ProjectResponse.model_validate(_serialize_project_row(row))


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: UUID, payload: ProjectUpdate) -> ProjectResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            current_row = await _fetch_project_or_404(conn, project_id)
            current = _serialize_project_row(current_row)

            updated = {
                "name": payload.name if payload.name is not None else current["name"],
                "description": payload.description if payload.description is not None else current["description"],
                "status": payload.status.value if payload.status is not None else current["status"],
                "github_org": payload.github_org if payload.github_org is not None else current["github_org"],
                "github_repo": payload.github_repo if payload.github_repo is not None else current["github_repo"],
                "github_project_id": (
                    payload.github_project_id
                    if payload.github_project_id is not None
                    else current["github_project_id"]
                ),
                "metadata": payload.metadata if payload.metadata is not None else current["metadata"],
            }

            if (
                updated["name"] == current["name"]
                and updated["description"] == current["description"]
                and updated["status"] == current["status"]
                and updated["github_org"] == current["github_org"]
                and updated["github_repo"] == current["github_repo"]
                and updated["github_project_id"] == current["github_project_id"]
                and updated["metadata"] == current["metadata"]
            ):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No project fields changed")

            next_version = current["current_version"] + 1
            row = await conn.fetchrow(
                """
                UPDATE projects
                   SET name = $2,
                       description = $3,
                       status = $4,
                       github_org = $5,
                       github_repo = $6,
                       github_project_id = $7,
                       metadata = $8::jsonb,
                       current_version = $9,
                       updated_at = NOW()
                 WHERE id = $1
             RETURNING *
                """,
                project_id,
                updated["name"],
                updated["description"],
                updated["status"],
                updated["github_org"],
                updated["github_repo"],
                updated["github_project_id"],
                json.dumps(updated["metadata"] or {}),
                next_version,
            )
            project = _serialize_project_row(row)
            await _insert_revision(
                conn,
                entity_id=project["id"],
                revision_number=next_version,
                actor="human:local",
                change_summary="Updated project fields",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=current,
                after_snapshot=project,
            )
    finally:
        await conn.close()

    return ProjectResponse.model_validate(project)
