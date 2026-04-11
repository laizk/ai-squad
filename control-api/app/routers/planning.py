from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.db import open_ready_connection
from app.models import (
    MilestoneCreate,
    MilestoneListResponse,
    MilestoneResponse,
    MilestoneUpdate,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)
from app.revision_utils import insert_revision, json_array, utc_value

router = APIRouter(prefix="/api/v1", tags=["planning"])


def _serialize_milestone_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "display_order": row["display_order"],
        "acceptance_criteria": json_array(row["acceptance_criteria"]),
        "due_date": row["due_date"],
        "current_version": row["current_version"],
        "created_at": utc_value(row["created_at"]),
        "updated_at": utc_value(row["updated_at"]),
    }


def _serialize_task_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "milestone_id": row["milestone_id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "priority": row["priority"],
        "assigned_role": row["assigned_role"],
        "acceptance_criteria": json_array(row["acceptance_criteria"]),
        "display_order": row["display_order"],
        "current_version": row["current_version"],
        "created_at": utc_value(row["created_at"]),
        "updated_at": utc_value(row["updated_at"]),
    }


async def _fetch_project_or_404(conn: Any, project_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT id FROM projects WHERE id = $1", project_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


async def _fetch_milestone_or_404(conn: Any, milestone_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT * FROM milestones WHERE id = $1", milestone_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found")
    return row


async def _fetch_task_or_404(conn: Any, task_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return row


@router.post("/projects/{project_id}/milestones", response_model=MilestoneResponse, status_code=status.HTTP_201_CREATED)
async def create_milestone(project_id: UUID, payload: MilestoneCreate) -> MilestoneResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            await _fetch_project_or_404(conn, project_id)
            row = await conn.fetchrow(
                """
                INSERT INTO milestones (
                  project_id,
                  title,
                  description,
                  status,
                  display_order,
                  acceptance_criteria,
                  due_date
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                RETURNING *
                """,
                project_id,
                payload.title,
                payload.description,
                payload.status.value if payload.status is not None else "planned",
                payload.display_order if payload.display_order is not None else 0,
                json.dumps(payload.acceptance_criteria or []),
                payload.due_date,
            )
            milestone = _serialize_milestone_row(row)
            await insert_revision(
                conn,
                entity_type="milestone",
                entity_id=milestone["id"],
                revision_number=1,
                actor="human:local",
                change_summary="Initial milestone creation",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=None,
                after_snapshot=milestone,
            )
    finally:
        await conn.close()

    return MilestoneResponse.model_validate(milestone)


@router.get("/projects/{project_id}/milestones", response_model=MilestoneListResponse)
async def list_project_milestones(project_id: UUID) -> MilestoneListResponse:
    conn = await open_ready_connection()
    try:
        await _fetch_project_or_404(conn, project_id)
        rows = await conn.fetch(
            """
            SELECT * FROM milestones
             WHERE project_id = $1
             ORDER BY display_order ASC, created_at ASC
            """,
            project_id,
        )
    finally:
        await conn.close()

    items = [MilestoneResponse.model_validate(_serialize_milestone_row(row)) for row in rows]
    return MilestoneListResponse(total=len(items), items=items)


@router.get("/milestones/{milestone_id}", response_model=MilestoneResponse)
async def get_milestone(milestone_id: UUID) -> MilestoneResponse:
    conn = await open_ready_connection()
    try:
        row = await _fetch_milestone_or_404(conn, milestone_id)
    finally:
        await conn.close()

    return MilestoneResponse.model_validate(_serialize_milestone_row(row))


@router.patch("/milestones/{milestone_id}", response_model=MilestoneResponse)
async def update_milestone(milestone_id: UUID, payload: MilestoneUpdate) -> MilestoneResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            current_row = await _fetch_milestone_or_404(conn, milestone_id)
            current = _serialize_milestone_row(current_row)
            updated = {
                "title": payload.title if payload.title is not None else current["title"],
                "description": payload.description if payload.description is not None else current["description"],
                "status": payload.status.value if payload.status is not None else current["status"],
                "display_order": (
                    payload.display_order if payload.display_order is not None else current["display_order"]
                ),
                "acceptance_criteria": (
                    payload.acceptance_criteria
                    if payload.acceptance_criteria is not None
                    else current["acceptance_criteria"]
                ),
                "due_date": payload.due_date if payload.due_date is not None else current["due_date"],
            }

            if updated == {
                "title": current["title"],
                "description": current["description"],
                "status": current["status"],
                "display_order": current["display_order"],
                "acceptance_criteria": current["acceptance_criteria"],
                "due_date": current["due_date"],
            }:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No milestone fields changed")

            next_version = current["current_version"] + 1
            row = await conn.fetchrow(
                """
                UPDATE milestones
                   SET title = $2,
                       description = $3,
                       status = $4,
                       display_order = $5,
                       acceptance_criteria = $6::jsonb,
                       due_date = $7,
                       current_version = $8,
                       updated_at = NOW()
                 WHERE id = $1
             RETURNING *
                """,
                milestone_id,
                updated["title"],
                updated["description"],
                updated["status"],
                updated["display_order"],
                json.dumps(updated["acceptance_criteria"] or []),
                updated["due_date"],
                next_version,
            )
            milestone = _serialize_milestone_row(row)
            await insert_revision(
                conn,
                entity_type="milestone",
                entity_id=milestone["id"],
                revision_number=next_version,
                actor="human:local",
                change_summary="Updated milestone fields",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=current,
                after_snapshot=milestone,
            )
    finally:
        await conn.close()

    return MilestoneResponse.model_validate(milestone)


@router.post("/milestones/{milestone_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(milestone_id: UUID, payload: TaskCreate) -> TaskResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            milestone_row = await _fetch_milestone_or_404(conn, milestone_id)
            milestone = _serialize_milestone_row(milestone_row)
            row = await conn.fetchrow(
                """
                INSERT INTO tasks (
                  project_id,
                  milestone_id,
                  title,
                  description,
                  status,
                  priority,
                  assigned_role,
                  acceptance_criteria,
                  display_order
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                RETURNING *
                """,
                milestone["project_id"],
                milestone_id,
                payload.title,
                payload.description,
                payload.status.value if payload.status is not None else "backlog",
                payload.priority.value if payload.priority is not None else "medium",
                payload.assigned_role.value if payload.assigned_role is not None else None,
                json.dumps(payload.acceptance_criteria or []),
                payload.display_order if payload.display_order is not None else 0,
            )
            task = _serialize_task_row(row)
            await insert_revision(
                conn,
                entity_type="task",
                entity_id=task["id"],
                revision_number=1,
                actor="human:local",
                change_summary="Initial task creation",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=None,
                after_snapshot=task,
            )
    finally:
        await conn.close()

    return TaskResponse.model_validate(task)


@router.get("/milestones/{milestone_id}/tasks", response_model=TaskListResponse)
async def list_milestone_tasks(milestone_id: UUID) -> TaskListResponse:
    conn = await open_ready_connection()
    try:
        await _fetch_milestone_or_404(conn, milestone_id)
        rows = await conn.fetch(
            """
            SELECT * FROM tasks
             WHERE milestone_id = $1
             ORDER BY display_order ASC, created_at ASC
            """,
            milestone_id,
        )
    finally:
        await conn.close()

    items = [TaskResponse.model_validate(_serialize_task_row(row)) for row in rows]
    return TaskListResponse(total=len(items), items=items)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID) -> TaskResponse:
    conn = await open_ready_connection()
    try:
        row = await _fetch_task_or_404(conn, task_id)
    finally:
        await conn.close()

    return TaskResponse.model_validate(_serialize_task_row(row))


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: UUID, payload: TaskUpdate) -> TaskResponse:
    conn = await open_ready_connection()
    try:
        async with conn.transaction():
            current_row = await _fetch_task_or_404(conn, task_id)
            current = _serialize_task_row(current_row)
            updated = {
                "title": payload.title if payload.title is not None else current["title"],
                "description": payload.description if payload.description is not None else current["description"],
                "status": payload.status.value if payload.status is not None else current["status"],
                "priority": payload.priority.value if payload.priority is not None else current["priority"],
                "assigned_role": (
                    payload.assigned_role.value if payload.assigned_role is not None else current["assigned_role"]
                ),
                "acceptance_criteria": (
                    payload.acceptance_criteria
                    if payload.acceptance_criteria is not None
                    else current["acceptance_criteria"]
                ),
                "display_order": (
                    payload.display_order if payload.display_order is not None else current["display_order"]
                ),
            }

            if updated == {
                "title": current["title"],
                "description": current["description"],
                "status": current["status"],
                "priority": current["priority"],
                "assigned_role": current["assigned_role"],
                "acceptance_criteria": current["acceptance_criteria"],
                "display_order": current["display_order"],
            }:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No task fields changed")

            next_version = current["current_version"] + 1
            row = await conn.fetchrow(
                """
                UPDATE tasks
                   SET title = $2,
                       description = $3,
                       status = $4,
                       priority = $5,
                       assigned_role = $6,
                       acceptance_criteria = $7::jsonb,
                       display_order = $8,
                       current_version = $9,
                       updated_at = NOW()
                 WHERE id = $1
             RETURNING *
                """,
                task_id,
                updated["title"],
                updated["description"],
                updated["status"],
                updated["priority"],
                updated["assigned_role"],
                json.dumps(updated["acceptance_criteria"] or []),
                updated["display_order"],
                next_version,
            )
            task = _serialize_task_row(row)
            await insert_revision(
                conn,
                entity_type="task",
                entity_id=task["id"],
                revision_number=next_version,
                actor="human:local",
                change_summary="Updated task fields",
                reason_category=payload.reason.category.value,
                reason_detail=payload.reason.detail,
                reason_references=payload.reason.references,
                before_snapshot=current,
                after_snapshot=task,
            )
    finally:
        await conn.close()

    return TaskResponse.model_validate(task)
