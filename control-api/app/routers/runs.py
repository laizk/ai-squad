from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.db import open_ready_connection
from app.models import (
    OPTIONAL_ROLES_SKIPPED,
    WORKFLOW_STEPS,
    RunCreate,
    RunGithubRefUpdate,
    RunListResponse,
    RunResponse,
    RunStepResponse,
    RunStatus,
    RunStepStatus,
)
from app.revision_utils import utc_value

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _serialize_step(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "role": row["role"],
        "step_order": row["step_order"],
        "status": row["status"],
        "pause_after": row["pause_after"],
        "output_artifact_id": row["output_artifact_id"],
        "started_at": utc_value(row["started_at"]),
        "completed_at": utc_value(row["completed_at"]),
        "error_message": row["error_message"],
        "created_at": utc_value(row["created_at"]),
    }


def _serialize_run(row: Any, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "task_id": row["task_id"],
        "status": row["status"],
        "workflow_type": row["workflow_type"],
        "trigger_actor": row["trigger_actor"],
        "idempotency_key": row["idempotency_key"],
        "steps": steps,
        "started_at": utc_value(row["started_at"]),
        "paused_at": utc_value(row["paused_at"]),
        "completed_at": utc_value(row["completed_at"]),
        "error_message": row["error_message"],
        "created_at": utc_value(row["created_at"]),
        "github_issue_number": row["github_issue_number"],
        "github_branch": row["github_branch"],
        "github_pr_number": row["github_pr_number"],
    }


async def _fetch_steps(conn: Any, run_id: UUID) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT * FROM run_steps WHERE run_id = $1 ORDER BY step_order ASC",
        run_id,
    )
    return [_serialize_step(row) for row in rows]


async def _fetch_run_or_404(conn: Any, run_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return row


async def _build_run_response(conn: Any, row: Any) -> RunResponse:
    steps = await _fetch_steps(conn, row["id"])
    data = _serialize_run(row, [RunStepResponse.model_validate(s) for s in steps])
    return RunResponse.model_validate(data)


async def _enqueue_step(conn: Any, run_id: UUID, step_id: UUID) -> None:
    """Push a step execution task onto the Celery queue via send_task."""
    import os
    from celery import Celery

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    celery_app = Celery(broker=redis_url)
    celery_app.send_task(
        "app.tasks.execute_step",
        kwargs={"run_id": str(run_id), "step_id": str(step_id)},
        queue="squad.steps",
    )
    celery_app.close()


@router.post("/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(payload: RunCreate) -> RunResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            # idempotency check — return existing run if key already exists
            existing = await conn.fetchrow(
                "SELECT * FROM runs WHERE idempotency_key = $1",
                payload.idempotency_key,
            )
            if existing is not None:
                return await _build_run_response(conn, existing)

            # verify project exists
            project = await conn.fetchrow(
                "SELECT id FROM projects WHERE id = $1", payload.project_id
            )
            if project is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
                )

            # verify task if provided
            if payload.task_id is not None:
                task = await conn.fetchrow(
                    "SELECT id FROM tasks WHERE id = $1", payload.task_id
                )
                if task is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
                    )

            run_row = await conn.fetchrow(
                """
                INSERT INTO runs (project_id, task_id, workflow_type, idempotency_key)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                payload.project_id,
                payload.task_id,
                payload.workflow_type,
                payload.idempotency_key,
            )
            run_id = run_row["id"]

            # create active steps
            active_steps = WORKFLOW_STEPS[payload.workflow_type]
            first_step_id = None
            for order, (role, pause_after) in enumerate(active_steps, start=1):
                step_row = await conn.fetchrow(
                    """
                    INSERT INTO run_steps (run_id, role, step_order, pause_after, status)
                    VALUES ($1, $2, $3, $4, 'pending')
                    RETURNING id
                    """,
                    run_id,
                    role,
                    order,
                    pause_after,
                )
                if order == 1:
                    first_step_id = step_row["id"]

            # create skipped optional steps at the end
            skip_order = len(active_steps) + 1
            for role in OPTIONAL_ROLES_SKIPPED:
                await conn.execute(
                    """
                    INSERT INTO run_steps (run_id, role, step_order, status)
                    VALUES ($1, $2, $3, 'skipped')
                    """,
                    run_id,
                    role,
                    skip_order,
                )
                skip_order += 1

        # enqueue first step outside the transaction
        if first_step_id is not None:
            await _enqueue_step(conn, run_id, first_step_id)

        async with conn.transaction():
            await conn.execute(
                "UPDATE runs SET status = 'running', started_at = $1 WHERE id = $2",
                datetime.now(timezone.utc),
                run_id,
            )
            run_row = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)

        return await _build_run_response(conn, run_row)
    finally:
        await conn.close()


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    project_id: UUID | None = Query(default=None),
    run_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> RunListResponse:
    conn = await open_ready_connection()
    try:
        conditions = []
        args: list[Any] = []
        idx = 1

        if project_id is not None:
            conditions.append(f"project_id = ${idx}")
            args.append(project_id)
            idx += 1

        if run_status is not None:
            conditions.append(f"status = ${idx}")
            args.append(run_status)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * per_page

        total = await conn.fetchval(f"SELECT COUNT(*) FROM runs {where}", *args)
        rows = await conn.fetch(
            f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
            *args,
            per_page,
            offset,
        )

        items = []
        for row in rows:
            items.append(await _build_run_response(conn, row))
    finally:
        await conn.close()

    return RunListResponse(total=total, items=items)


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: UUID) -> RunResponse:
    conn = await open_ready_connection()
    try:
        row = await _fetch_run_or_404(conn, run_id)
        return await _build_run_response(conn, row)
    finally:
        await conn.close()


@router.post("/runs/{run_id}/pause", response_model=RunResponse)
async def pause_run(run_id: UUID) -> RunResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            row = await _fetch_run_or_404(conn, run_id)
            if row["status"] != RunStatus.running.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot pause a run with status '{row['status']}'",
                )
            await conn.execute(
                "UPDATE runs SET status = 'paused', paused_at = $1 WHERE id = $2",
                datetime.now(timezone.utc),
                run_id,
            )
            row = await _fetch_run_or_404(conn, run_id)
        return await _build_run_response(conn, row)
    finally:
        await conn.close()


@router.post("/runs/{run_id}/reject", response_model=RunResponse)
async def reject_run(run_id: UUID) -> RunResponse:
    """Human rejects the paused run entirely — marks it failed, skips remaining steps."""
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            row = await _fetch_run_or_404(conn, run_id)
            if row["status"] != RunStatus.paused.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot reject a run with status '{row['status']}'",
                )
            await conn.execute(
                """
                UPDATE runs
                   SET status = 'failed', completed_at = $1
                 WHERE id = $2
                """,
                datetime.now(timezone.utc),
                run_id,
            )
            await conn.execute(
                """
                UPDATE run_steps
                   SET status = 'skipped'
                 WHERE run_id = $1 AND status = 'pending'
                """,
                run_id,
            )
            row = await _fetch_run_or_404(conn, run_id)
        return await _build_run_response(conn, row)
    finally:
        await conn.close()


@router.post("/runs/{run_id}/request-changes", response_model=RunResponse)
async def request_changes(run_id: UUID) -> RunResponse:
    """Human requests changes on the last completed step — resets it to pending and re-enqueues."""
    conn = await open_ready_connection()
    try:
        step_to_retry = None
        async with conn.transaction():
            row = await _fetch_run_or_404(conn, run_id)
            if row["status"] != RunStatus.paused.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot request changes on a run with status '{row['status']}'",
                )
            last_step = await conn.fetchrow(
                """
                SELECT * FROM run_steps
                 WHERE run_id = $1 AND status = 'completed'
                 ORDER BY step_order DESC
                 LIMIT 1
                """,
                run_id,
            )
            if last_step is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No completed step found to request changes on",
                )
            await conn.execute(
                """
                UPDATE run_steps
                   SET status = 'pending',
                       started_at = NULL,
                       completed_at = NULL,
                       output_artifact_id = NULL,
                       error_message = NULL
                 WHERE id = $1
                """,
                last_step["id"],
            )
            await conn.execute(
                "UPDATE runs SET status = 'running', paused_at = NULL WHERE id = $1",
                run_id,
            )
            step_to_retry = last_step
            row = await _fetch_run_or_404(conn, run_id)

        await _enqueue_step(conn, run_id, step_to_retry["id"])
        return await _build_run_response(conn, row)
    finally:
        await conn.close()


@router.post("/runs/{run_id}/resume", response_model=RunResponse)
async def resume_run(run_id: UUID) -> RunResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            row = await _fetch_run_or_404(conn, run_id)
            if row["status"] != RunStatus.paused.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot resume a run with status '{row['status']}'",
                )
            # find next pending step
            next_step = await conn.fetchrow(
                """
                SELECT * FROM run_steps
                 WHERE run_id = $1 AND status = 'pending'
                 ORDER BY step_order ASC
                 LIMIT 1
                """,
                run_id,
            )
            if next_step is None:
                # no more steps — mark completed
                await conn.execute(
                    "UPDATE runs SET status = 'completed', completed_at = $1 WHERE id = $2",
                    datetime.now(timezone.utc),
                    run_id,
                )
            else:
                await conn.execute(
                    "UPDATE runs SET status = 'running', paused_at = NULL WHERE id = $1",
                    run_id,
                )
            row = await _fetch_run_or_404(conn, run_id)

        if next_step is not None:
            await _enqueue_step(conn, run_id, next_step["id"])

        return await _build_run_response(conn, row)
    finally:
        await conn.close()


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(run_id: UUID) -> RunResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            row = await _fetch_run_or_404(conn, run_id)
            if row["status"] in (
                RunStatus.completed.value,
                RunStatus.failed.value,
                RunStatus.cancelled.value,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot cancel a run with status '{row['status']}'",
                )
            await conn.execute(
                """
                UPDATE runs
                   SET status = 'cancelled', completed_at = $1
                 WHERE id = $2
                """,
                datetime.now(timezone.utc),
                run_id,
            )
            # mark remaining pending steps as skipped
            await conn.execute(
                """
                UPDATE run_steps
                   SET status = 'skipped'
                 WHERE run_id = $1 AND status = 'pending'
                """,
                run_id,
            )
            row = await _fetch_run_or_404(conn, run_id)
        return await _build_run_response(conn, row)
    finally:
        await conn.close()


@router.patch("/{run_id}/github_refs", response_model=RunResponse)
async def update_github_refs(run_id: UUID, payload: RunGithubRefUpdate) -> RunResponse:
    """Store GitHub issue, branch, and PR references on a run.

    Called by workers after github-svc creates issues/branches/PRs.
    Only provided (non-None) fields are written; others are left unchanged.
    """
    conn = await open_ready_connection()
    try:
        row = await _fetch_run_or_404(conn, run_id)
        updates: dict[str, Any] = {}
        if payload.github_issue_number is not None:
            updates["github_issue_number"] = payload.github_issue_number
        if payload.github_branch is not None:
            updates["github_branch"] = payload.github_branch
        if payload.github_pr_number is not None:
            updates["github_pr_number"] = payload.github_pr_number

        if updates:
            set_clause = ", ".join(
                f"{col} = ${i + 2}" for i, col in enumerate(updates)
            )
            await conn.execute(
                f"UPDATE runs SET {set_clause} WHERE id = $1",
                run_id,
                *updates.values(),
            )
            row = await _fetch_run_or_404(conn, run_id)

        return await _build_run_response(conn, row)
    finally:
        await conn.close()
