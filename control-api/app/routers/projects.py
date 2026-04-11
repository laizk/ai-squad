from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Query, status

from app.db import open_ready_connection
from app.models import (
    ProjectAssignmentCreate,
    ProjectAssignmentDelete,
    ProjectAssignmentListResponse,
    ProjectAssignmentModelUpdate,
    ProjectAssignmentResponse,
    ProjectAssignmentUpdate,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectStatus,
    ProjectUpdate,
)
from app.revision_utils import insert_revision, json_object, utc_value

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


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
        "metadata": json_object(row["metadata"]),
        "created_at": utc_value(row["created_at"]),
        "updated_at": utc_value(row["updated_at"]),
    }


async def _fetch_project_or_404(conn: Any, project_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _serialize_assignment_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "team_member_id": row["team_member_id"],
        "is_enabled": row["is_enabled"],
        "provider_override": row["provider_override"],
        "model_override": row["model_override"],
        "disabled_at": utc_value(row["disabled_at"]),
        "disable_reason": row["disable_reason"],
        "current_version": row["current_version"],
        "created_at": utc_value(row["created_at"]),
        "updated_at": utc_value(row["updated_at"]),
    }


async def _fetch_assignment_or_404(conn: Any, project_id: UUID, member_id: UUID) -> Any:
    row = await conn.fetchrow(
        """
        SELECT *
          FROM project_team_members
         WHERE project_id = $1
           AND team_member_id = $2
        """,
        project_id,
        member_id,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project assignment not found")
    return row


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
            await insert_revision(
                conn,
                entity_type="project",
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
            await insert_revision(
                conn,
                entity_type="project",
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


@router.get("/{project_id}/team", response_model=ProjectAssignmentListResponse)
async def list_project_team(project_id: UUID) -> ProjectAssignmentListResponse:
    conn = await open_ready_connection()
    try:
        await _fetch_project_or_404(conn, project_id)
        rows = await conn.fetch(
            """
            SELECT *
              FROM project_team_members
             WHERE project_id = $1
             ORDER BY created_at ASC
            """,
            project_id,
        )
    finally:
        await conn.close()

    items = [ProjectAssignmentResponse.model_validate(_serialize_assignment_row(row)) for row in rows]
    return ProjectAssignmentListResponse(total=len(items), items=items)


@router.post("/{project_id}/team", response_model=ProjectAssignmentResponse, status_code=status.HTTP_201_CREATED)
async def add_team_member_to_project(project_id: UUID, payload: ProjectAssignmentCreate) -> ProjectAssignmentResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            await _fetch_project_or_404(conn, project_id)
            member = await conn.fetchrow("SELECT id FROM team_members WHERE id = $1", payload.team_member_id)
            if member is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

            existing = await conn.fetchrow(
                """
                SELECT id
                  FROM project_team_members
                 WHERE project_id = $1
                   AND team_member_id = $2
                """,
                project_id,
                payload.team_member_id,
            )
            if existing is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team member already assigned")

            row = await conn.fetchrow(
                """
                INSERT INTO project_team_members (
                  project_id,
                  team_member_id,
                  provider_override,
                  model_override
                )
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                project_id,
                payload.team_member_id,
                payload.provider_override.value if payload.provider_override is not None else None,
                payload.model_override,
            )
            assignment = _serialize_assignment_row(row)
            await insert_revision(
                conn,
                entity_type="project_assignment",
                entity_id=assignment["id"],
                revision_number=1,
                actor="human:local",
                change_summary="Initial project assignment",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=None,
                after_snapshot=assignment,
            )
    finally:
        await conn.close()

    return ProjectAssignmentResponse.model_validate(assignment)


@router.patch("/{project_id}/team/{member_id}", response_model=ProjectAssignmentResponse)
async def update_project_team_member(
    project_id: UUID, member_id: UUID, payload: ProjectAssignmentUpdate
) -> ProjectAssignmentResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            current_row = await _fetch_assignment_or_404(conn, project_id, member_id)
            current = _serialize_assignment_row(current_row)

            updated = {
                "is_enabled": payload.is_enabled if payload.is_enabled is not None else current["is_enabled"],
                "provider_override": (
                    payload.provider_override.value
                    if payload.provider_override is not None
                    else current["provider_override"]
                ),
                "model_override": payload.model_override if payload.model_override is not None else current["model_override"],
                "disable_reason": payload.disable_reason if payload.disable_reason is not None else current["disable_reason"],
            }
            if payload.is_enabled is False:
                # database-side timestamp keeps the event time authoritative
                disabled_at_expr = "NOW()"
            elif payload.is_enabled is True:
                disabled_at_expr = "NULL"
            else:
                disabled_at_expr = "disabled_at"

            if (
                updated["is_enabled"] == current["is_enabled"]
                and updated["provider_override"] == current["provider_override"]
                and updated["model_override"] == current["model_override"]
                and updated["disable_reason"] == current["disable_reason"]
            ):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No assignment fields changed")

            next_version = current["current_version"] + 1
            row = await conn.fetchrow(
                f"""
                UPDATE project_team_members
                   SET is_enabled = $3,
                       provider_override = $4,
                       model_override = $5,
                       disable_reason = $6,
                       disabled_at = {disabled_at_expr},
                       current_version = $7,
                       updated_at = NOW()
                 WHERE project_id = $1
                   AND team_member_id = $2
             RETURNING *
                """,
                project_id,
                member_id,
                updated["is_enabled"],
                updated["provider_override"],
                updated["model_override"],
                updated["disable_reason"],
                next_version,
            )
            assignment = _serialize_assignment_row(row)
            await insert_revision(
                conn,
                entity_type="project_assignment",
                entity_id=assignment["id"],
                revision_number=next_version,
                actor="human:local",
                change_summary="Updated project assignment",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=current,
                after_snapshot=assignment,
            )
    finally:
        await conn.close()

    return ProjectAssignmentResponse.model_validate(assignment)


@router.patch("/{project_id}/team/{member_id}/model", response_model=ProjectAssignmentResponse)
async def update_project_team_member_model(
    project_id: UUID, member_id: UUID, payload: ProjectAssignmentModelUpdate
) -> ProjectAssignmentResponse:
    update_payload = ProjectAssignmentUpdate(
        model_override=payload.model_override,
        provider_override=payload.provider_override,
        reason=payload.reason,
    )
    return await update_project_team_member(project_id, member_id, update_payload)


@router.delete("/{project_id}/team/{member_id}", response_model=ProjectAssignmentResponse)
async def disable_project_team_member(
    project_id: UUID,
    member_id: UUID,
    payload: ProjectAssignmentDelete = Body(...),
) -> ProjectAssignmentResponse:
    update_payload = ProjectAssignmentUpdate(
        is_enabled=False,
        reason=payload.reason,
        disable_reason="Disabled via delete endpoint",
    )
    return await update_project_team_member(project_id, member_id, update_payload)
