"""Step execution task.

Each task picks up a (run_id, step_id) pair, runs the appropriate
stub agent, persists the output artifact, marks the step completed,
and either enqueues the next step or pauses the run.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

import asyncpg

from app.celery_app import app
from app.stubs import pm_stub, reviewer_stub

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "WORKER_DATABASE_URL",
    "postgresql://squad_app:squadapp-local@localhost:5432/squad",
)

# Map role → stub module
STUB_REGISTRY = {
    "pm":     pm_stub,
    "dev-jr": reviewer_stub,  # use reviewer stub for all non-PM roles in P3
    "dev-sr": reviewer_stub,
    "qa":     reviewer_stub,
    "judge":  reviewer_stub,
}


async def _run_step(run_id: str, step_id: str) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # load step
        step = await conn.fetchrow(
            "SELECT * FROM run_steps WHERE id = $1", UUID(step_id)
        )
        if step is None:
            logger.error("Step %s not found", step_id)
            return

        if step["status"] != "pending":
            logger.info("Step %s is already %s, skipping", step_id, step["status"])
            return

        # load run
        run = await conn.fetchrow(
            "SELECT * FROM runs WHERE id = $1", UUID(run_id)
        )
        if run is None or run["status"] not in ("running",):
            logger.info("Run %s is not running (status=%s), skipping step", run_id, run["status"] if run else "missing")
            return

        role = step["role"]
        stub = STUB_REGISTRY.get(role)
        if stub is None:
            logger.warning("No stub registered for role %s — marking step failed", role)
            await conn.execute(
                """
                UPDATE run_steps
                   SET status = 'failed', error_message = $1, completed_at = $2
                 WHERE id = $3
                """,
                f"No stub registered for role {role}",
                datetime.now(timezone.utc),
                UUID(step_id),
            )
            await conn.execute(
                "UPDATE runs SET status = 'failed', error_message = $1 WHERE id = $2",
                f"Step {step_id} failed: no stub for role {role}",
                UUID(run_id),
            )
            return

        # mark step running
        await conn.execute(
            "UPDATE run_steps SET status = 'running', started_at = $1 WHERE id = $2",
            datetime.now(timezone.utc),
            UUID(step_id),
        )

        # run the stub
        context = {
            "run_id": run_id,
            "step_id": step_id,
            "project_id": str(run["project_id"]),
            "task_id": str(run["task_id"]) if run["task_id"] else None,
        }
        artifacts = stub.run(context)

        # validate and persist artifacts
        last_artifact_id = None
        for art in artifacts:
            if not stub.validate(art["artifact_type"], art["body"]):
                raise ValueError(
                    f"Stub artifact validation failed for type {art['artifact_type']}"
                )
            row = await conn.fetchrow(
                """
                INSERT INTO artifacts (project_id, run_id, run_step_id, role, artifact_type, name, body)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                run["project_id"],
                UUID(run_id),
                UUID(step_id),
                role,
                art["artifact_type"],
                art["name"],
                art["body"],
            )
            last_artifact_id = row["id"]

        # mark step completed
        await conn.execute(
            """
            UPDATE run_steps
               SET status = 'completed', completed_at = $1, output_artifact_id = $2
             WHERE id = $3
            """,
            datetime.now(timezone.utc),
            last_artifact_id,
            UUID(step_id),
        )

        pause_after = step["pause_after"]

        if pause_after:
            # Conditionally pause — only if the run is still running.
            # A concurrent cancel may have already transitioned to cancelled.
            updated = await conn.execute(
                "UPDATE runs SET status = 'paused', paused_at = $1 WHERE id = $2 AND status = 'running'",
                datetime.now(timezone.utc),
                UUID(run_id),
            )
            if updated == "UPDATE 0":
                logger.info("Run %s was no longer running when pause was attempted; skipping", run_id)
            else:
                logger.info("Run %s paused after step %s (%s)", run_id, step_id, role)
            return

        # find next pending step
        next_step = await conn.fetchrow(
            """
            SELECT id FROM run_steps
             WHERE run_id = $1 AND status = 'pending'
             ORDER BY step_order ASC
             LIMIT 1
            """,
            UUID(run_id),
        )

        if next_step is None:
            await conn.execute(
                "UPDATE runs SET status = 'completed', completed_at = $1 WHERE id = $2 AND status = 'running'",
                datetime.now(timezone.utc),
                UUID(run_id),
            )
            logger.info("Run %s completed", run_id)
        else:
            next_id = str(next_step["id"])
            logger.info("Enqueuing next step %s for run %s", next_id, run_id)
            execute_step.apply_async(
                kwargs={"run_id": run_id, "step_id": next_id},
                queue="squad.steps",
            )

    except Exception as exc:
        logger.exception("Step %s failed: %s", step_id, exc)
        try:
            await conn.execute(
                """
                UPDATE run_steps
                   SET status = 'failed', error_message = $1, completed_at = $2
                 WHERE id = $3
                """,
                str(exc),
                datetime.now(timezone.utc),
                UUID(step_id),
            )
            await conn.execute(
                "UPDATE runs SET status = 'failed', error_message = $1 WHERE id = $2 AND status = 'running'",
                str(exc),
                UUID(run_id),
            )
        except Exception:
            pass
    finally:
        await conn.close()


@app.task(name="app.tasks.execute_step", bind=True, max_retries=3)
def execute_step(self, *, run_id: str, step_id: str) -> None:
    """Execute a single run step using the registered stub agent."""
    asyncio.run(_run_step(run_id, step_id))
