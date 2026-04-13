"""Safety violations router (P10 — Hardening).

Workers POST violations when they detect blocked actions or unsafe output.
Admin-web GETs violations for display on the safety dashboard.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.db import open_ready_connection
from app.models import (
    SafetyViolationCreate,
    SafetyViolationListResponse,
    SafetyViolationResponse,
    ViolationSeverity,
)
from app.revision_utils import utc_value

router = APIRouter(prefix="/api/v1", tags=["safety"])


def _serialize_violation(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "step_id": row["step_id"],
        "role": row["role"],
        "violation_type": row["violation_type"],
        "severity": row["severity"],
        "detail": row["detail"],
        "resolved": row["resolved"],
        "resolved_at": utc_value(row["resolved_at"]),
        "created_at": utc_value(row["created_at"]),
    }


@router.post(
    "/safety-violations",
    response_model=SafetyViolationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_violation(payload: SafetyViolationCreate) -> SafetyViolationResponse:
    conn = await open_ready_connection()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO safety_violations
              (run_id, step_id, role, violation_type, severity, detail)
            VALUES ($1, $2, $3, $4, $5::violation_severity, $6)
            RETURNING *
            """,
            payload.run_id,
            payload.step_id,
            payload.role,
            payload.violation_type,
            payload.severity.value,
            payload.detail,
        )
        return SafetyViolationResponse.model_validate(_serialize_violation(row))
    finally:
        await conn.close()


@router.get("/safety-violations", response_model=SafetyViolationListResponse)
async def list_violations(
    run_id: UUID | None = Query(default=None),
    unresolved_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> SafetyViolationListResponse:
    conn = await open_ready_connection()
    try:
        conditions: list[str] = []
        args: list[Any] = []
        idx = 1

        if run_id is not None:
            conditions.append(f"run_id = ${idx}")
            args.append(run_id)
            idx += 1

        if unresolved_only:
            conditions.append("resolved = FALSE")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * per_page

        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM safety_violations {where}", *args
        )
        rows = await conn.fetch(
            f"""
            SELECT * FROM safety_violations
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *args,
            per_page,
            offset,
        )

        items = [
            SafetyViolationResponse.model_validate(_serialize_violation(r)) for r in rows
        ]
        return SafetyViolationListResponse(total=total, items=items)
    finally:
        await conn.close()


@router.get("/safety-violations/{violation_id}", response_model=SafetyViolationResponse)
async def get_violation(violation_id: UUID) -> SafetyViolationResponse:
    conn = await open_ready_connection()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM safety_violations WHERE id = $1", violation_id
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Safety violation not found",
            )
        return SafetyViolationResponse.model_validate(_serialize_violation(row))
    finally:
        await conn.close()


@router.post(
    "/safety-violations/{violation_id}/resolve",
    response_model=SafetyViolationResponse,
)
async def resolve_violation(violation_id: UUID) -> SafetyViolationResponse:
    """Mark a violation as resolved (human acknowledges it)."""
    from datetime import datetime, timezone

    conn = await open_ready_connection()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM safety_violations WHERE id = $1", violation_id
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Safety violation not found",
            )
        if row["resolved"]:
            return SafetyViolationResponse.model_validate(_serialize_violation(row))

        row = await conn.fetchrow(
            """
            UPDATE safety_violations
               SET resolved = TRUE, resolved_at = $1
             WHERE id = $2
            RETURNING *
            """,
            datetime.now(timezone.utc),
            violation_id,
        )
        return SafetyViolationResponse.model_validate(_serialize_violation(row))
    finally:
        await conn.close()
