from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.db import open_ready_connection
from app.models import (
    RevisionListResponse,
    RevisionReason,
    RevisionResponse,
    TeamMemberCreate,
    TeamMemberListResponse,
    TeamMemberResponse,
    TeamMemberRole,
    TeamMemberUpdate,
)
from app.revision_utils import insert_revision, json_array, json_object, utc_value

router = APIRouter(prefix="/api/v1/team-members", tags=["team-members"])


def _serialize_team_member_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "role": row["role"],
        "display_name": row["display_name"],
        "description": row["description"],
        "skills": json_array(row["skills"]),
        "provider": row["provider"],
        "model": row["model"],
        "is_active": row["is_active"],
        "current_version": row["current_version"],
        "created_at": utc_value(row["created_at"]),
        "updated_at": utc_value(row["updated_at"]),
    }


async def _fetch_team_member_or_404(conn: Any, team_member_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT * FROM team_members WHERE id = $1", team_member_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    return row


@router.post("", response_model=TeamMemberResponse, status_code=status.HTTP_201_CREATED)
async def create_team_member(payload: TeamMemberCreate) -> TeamMemberResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO team_members (
                  name,
                  role,
                  display_name,
                  description,
                  skills,
                  provider,
                  model,
                  is_active
                )
                VALUES ($1, $2, $3, $4, $5::text[], $6, $7, $8)
                RETURNING *
                """,
                payload.name,
                payload.role.value,
                payload.display_name,
                payload.description,
                payload.skills or [],
                payload.provider.value if payload.provider is not None else "ollama",
                payload.model,
                payload.is_active if payload.is_active is not None else True,
            )
            member = _serialize_team_member_row(row)
            await insert_revision(
                conn,
                entity_type="team_member",
                entity_id=member["id"],
                revision_number=1,
                actor="human:local",
                change_summary="Initial team member creation",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=None,
                after_snapshot=member,
            )
    finally:
        await conn.close()

    return TeamMemberResponse.model_validate(member)


@router.get("/{team_member_id}/revisions", response_model=RevisionListResponse)
async def get_team_member_revisions(team_member_id: UUID) -> RevisionListResponse:
    conn = await open_ready_connection()
    try:
        await _fetch_team_member_or_404(conn, team_member_id)
        rows = await conn.fetch(
            """
            SELECT *
              FROM revisions
             WHERE entity_type = 'team_member'
               AND entity_id = $1
             ORDER BY revision_number ASC
            """,
            team_member_id,
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
                references=json_array(row["reason_references"]),
            ),
            before_snapshot=json_object(row["before_snapshot"]) if row["before_snapshot"] is not None else None,
            after_snapshot=json_object(row["after_snapshot"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return RevisionListResponse(entity_type="team_member", entity_id=team_member_id, revisions=revisions)


@router.get("", response_model=TeamMemberListResponse)
async def list_team_members(
    role: TeamMemberRole | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> TeamMemberListResponse:
    conn = await open_ready_connection()
    try:
        offset = (page - 1) * per_page
        clauses: list[str] = []
        values: list[Any] = []

        if role is not None:
            clauses.append(f"role = ${len(values) + 1}")
            values.append(role.value)
        if is_active is not None:
            clauses.append(f"is_active = ${len(values) + 1}")
            values.append(is_active)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = await conn.fetchval(f"SELECT COUNT(*) FROM team_members {where_sql}", *values)
        rows = await conn.fetch(
            f"""
            SELECT * FROM team_members
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ${len(values) + 1} OFFSET ${len(values) + 2}
            """,
            *values,
            per_page,
            offset,
        )
    finally:
        await conn.close()

    items = [TeamMemberResponse.model_validate(_serialize_team_member_row(row)) for row in rows]
    return TeamMemberListResponse(total=total, page=page, per_page=per_page, items=items)


@router.get("/{team_member_id}", response_model=TeamMemberResponse)
async def get_team_member(team_member_id: UUID) -> TeamMemberResponse:
    conn = await open_ready_connection()
    try:
        row = await _fetch_team_member_or_404(conn, team_member_id)
    finally:
        await conn.close()

    return TeamMemberResponse.model_validate(_serialize_team_member_row(row))


@router.patch("/{team_member_id}", response_model=TeamMemberResponse)
async def update_team_member(team_member_id: UUID, payload: TeamMemberUpdate) -> TeamMemberResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            current_row = await _fetch_team_member_or_404(conn, team_member_id)
            current = _serialize_team_member_row(current_row)
            updated = {
                "name": payload.name if payload.name is not None else current["name"],
                "role": payload.role.value if payload.role is not None else current["role"],
                "display_name": payload.display_name if payload.display_name is not None else current["display_name"],
                "description": payload.description if payload.description is not None else current["description"],
                "skills": payload.skills if payload.skills is not None else current["skills"],
                "provider": payload.provider.value if payload.provider is not None else current["provider"],
                "model": payload.model if payload.model is not None else current["model"],
                "is_active": payload.is_active if payload.is_active is not None else current["is_active"],
            }

            if updated == {
                "name": current["name"],
                "role": current["role"],
                "display_name": current["display_name"],
                "description": current["description"],
                "skills": current["skills"],
                "provider": current["provider"],
                "model": current["model"],
                "is_active": current["is_active"],
            }:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No team member fields changed")

            next_version = current["current_version"] + 1
            row = await conn.fetchrow(
                """
                UPDATE team_members
                   SET name = $2,
                       role = $3,
                       display_name = $4,
                       description = $5,
                       skills = $6::text[],
                       provider = $7,
                       model = $8,
                       is_active = $9,
                       current_version = $10,
                       updated_at = NOW()
                 WHERE id = $1
             RETURNING *
                """,
                team_member_id,
                updated["name"],
                updated["role"],
                updated["display_name"],
                updated["description"],
                updated["skills"],
                updated["provider"],
                updated["model"],
                updated["is_active"],
                next_version,
            )
            member = _serialize_team_member_row(row)
            await insert_revision(
                conn,
                entity_type="team_member",
                entity_id=member["id"],
                revision_number=next_version,
                actor="human:local",
                change_summary="Updated team member fields",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=current,
                after_snapshot=member,
            )
    finally:
        await conn.close()

    return TeamMemberResponse.model_validate(member)
