"""Prompt evaluation endpoints (P9).

POST /api/v1/prompt-evals
  Kick off an eval run for a team member against a named golden task.
  The current revision number of the team member is captured at creation time.
  Enqueues an async eval task via Redis/Celery.

GET  /api/v1/prompt-evals
  List eval runs, optionally filtered by team_member_id or golden_task_key.

GET  /api/v1/prompt-evals/{eval_id}
  Get a single eval run.

GET  /api/v1/prompt-evals/compare
  Side-by-side comparison of all eval runs for a given team_member_id +
  golden_task_key, ordered by revision_number descending.
  Returns the full result set so humans can inspect score progression.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Query, status

from app.db import open_ready_connection
from app.models import (
    EvalStatus,
    PromptEvalCreate,
    PromptEvalCompareResponse,
    PromptEvalListResponse,
    PromptEvalResponse,
)
from app.revision_utils import utc_value
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/prompt-evals", tags=["prompt-evals"])

REDIS_URL = settings.redis_url or "redis://redis:6379/0"


def _serialize_eval(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "team_member_id": row["team_member_id"],
        "revision_number": row["revision_number"],
        "golden_task_key": row["golden_task_key"],
        "status": row["status"],
        "output_artifact": row["output_artifact"],
        "scores": row["scores"],
        "error_message": row["error_message"],
        "started_at": utc_value(row["started_at"]),
        "completed_at": utc_value(row["completed_at"]),
        "created_at": utc_value(row["created_at"]),
    }


@router.post("", response_model=PromptEvalResponse, status_code=status.HTTP_201_CREATED)
async def create_eval(payload: PromptEvalCreate) -> PromptEvalResponse:
    conn = await open_ready_connection()
    try:
        # Verify team member exists and capture current revision
        member = await conn.fetchrow(
            "SELECT id, current_version FROM team_members WHERE id = $1",
            payload.team_member_id,
        )
        if member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found.")

        row = await conn.fetchrow(
            """
            INSERT INTO prompt_eval_runs
                   (team_member_id, revision_number, golden_task_key, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING *
            """,
            payload.team_member_id,
            member["current_version"],
            payload.golden_task_key,
        )
    finally:
        await conn.close()

    eval_id = str(row["id"])
    await _enqueue_eval(eval_id, str(payload.team_member_id), payload.golden_task_key)

    return PromptEvalResponse.model_validate(_serialize_eval(row))


@router.get("", response_model=PromptEvalListResponse)
async def list_evals(
    team_member_id: UUID | None = Query(default=None),
    golden_task_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> PromptEvalListResponse:
    conn = await open_ready_connection()
    try:
        filters = []
        params: list[Any] = []

        if team_member_id is not None:
            params.append(team_member_id)
            filters.append(f"team_member_id = ${len(params)}")
        if golden_task_key is not None:
            params.append(golden_task_key)
            filters.append(f"golden_task_key = ${len(params)}")

        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)

        rows = await conn.fetch(
            f"SELECT * FROM prompt_eval_runs {where} ORDER BY created_at DESC LIMIT ${len(params)}",
            *params,
        )
        total = await conn.fetchval(f"SELECT COUNT(*) FROM prompt_eval_runs {where}", *params[:-1])
    finally:
        await conn.close()

    return PromptEvalListResponse(
        total=total,
        items=[PromptEvalResponse.model_validate(_serialize_eval(r)) for r in rows],
    )


@router.get("/compare", response_model=PromptEvalCompareResponse)
async def compare_evals(
    team_member_id: UUID = Query(...),
    golden_task_key: str = Query(...),
) -> PromptEvalCompareResponse:
    conn = await open_ready_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT * FROM prompt_eval_runs
             WHERE team_member_id = $1
               AND golden_task_key = $2
               AND status = 'completed'
             ORDER BY revision_number DESC
            """,
            team_member_id,
            golden_task_key,
        )
    finally:
        await conn.close()

    return PromptEvalCompareResponse(
        team_member_id=team_member_id,
        golden_task_key=golden_task_key,
        revisions=[PromptEvalResponse.model_validate(_serialize_eval(r)) for r in rows],
    )


@router.get("/{eval_id}", response_model=PromptEvalResponse)
async def get_eval(eval_id: UUID) -> PromptEvalResponse:
    conn = await open_ready_connection()
    try:
        row = await conn.fetchrow("SELECT * FROM prompt_eval_runs WHERE id = $1", eval_id)
    finally:
        await conn.close()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval run not found.")
    return PromptEvalResponse.model_validate(_serialize_eval(row))


async def _enqueue_eval(eval_id: str, team_member_id: str, golden_task_key: str) -> None:
    """Push an eval task onto the Celery queue via Redis."""
    try:
        r = await aioredis.from_url(REDIS_URL, decode_responses=True)
        task_body = json.dumps({
            "id": eval_id,
            "task": "app.tasks.run_prompt_eval",
            "args": [],
            "kwargs": {
                "eval_id": eval_id,
                "team_member_id": team_member_id,
                "golden_task_key": golden_task_key,
            },
            "retries": 0,
        })
        await r.rpush("celery", task_body)
        await r.aclose()
        logger.info("Enqueued eval task eval_id=%s", eval_id)
    except Exception as exc:
        logger.warning("Failed to enqueue eval task: %s", exc)
