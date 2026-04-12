from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.db import open_ready_connection
from app.models import ArtifactContentResponse, ArtifactResponse, ArtifactType
from app.revision_utils import utc_value

router = APIRouter(prefix="/api/v1", tags=["artifacts"])


def _serialize_artifact(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "run_id": row["run_id"],
        "run_step_id": row["run_step_id"],
        "role": row["role"],
        "artifact_type": row["artifact_type"],
        "name": row["name"],
        "version": row["version"],
        "is_current": row["is_current"],
        "created_at": utc_value(row["created_at"]),
    }


async def _fetch_artifact_or_404(conn: Any, artifact_id: UUID) -> Any:
    row = await conn.fetchrow("SELECT * FROM artifacts WHERE id = $1", artifact_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return row


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(artifact_id: UUID) -> ArtifactResponse:
    conn = await open_ready_connection()
    try:
        row = await _fetch_artifact_or_404(conn, artifact_id)
        return ArtifactResponse.model_validate(_serialize_artifact(row))
    finally:
        await conn.close()


@router.get("/artifacts/{artifact_id}/content", response_model=ArtifactContentResponse)
async def get_artifact_content(artifact_id: UUID) -> ArtifactContentResponse:
    conn = await open_ready_connection()
    try:
        row = await _fetch_artifact_or_404(conn, artifact_id)
        return ArtifactContentResponse.model_validate({
            "id": row["id"],
            "artifact_type": row["artifact_type"],
            "name": row["name"],
            "body": row["body"],
            "created_at": utc_value(row["created_at"]),
        })
    finally:
        await conn.close()


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactResponse])
async def list_run_artifacts(run_id: UUID) -> list[ArtifactResponse]:
    conn = await open_ready_connection()
    try:
        run = await conn.fetchrow("SELECT id FROM runs WHERE id = $1", run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        rows = await conn.fetch(
            "SELECT * FROM artifacts WHERE run_id = $1 ORDER BY created_at ASC",
            run_id,
        )
        return [ArtifactResponse.model_validate(_serialize_artifact(row)) for row in rows]
    finally:
        await conn.close()
