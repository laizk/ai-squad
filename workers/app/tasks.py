"""Step execution task.

Each task picks up a (run_id, step_id) pair, runs the appropriate
agent module, persists the output artifact, marks the step completed,
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
import httpx

from app.agents import dev_agent, devops_agent, judge_agent, pm_agent, qa_agent, reviewer_agent, ux_agent
from app.celery_app import app

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "WORKER_DATABASE_URL",
    "postgresql://squad_app:squadapp-local@localhost:5432/squad",
)
GITHUB_SVC_URL = os.environ.get("GITHUB_SVC_URL", "http://github-svc:9000")
CONTROL_API_URL = os.environ.get("CONTROL_API_URL", "http://control-api:8000")

# How many times dev-jr may be reworked before reviewer verdict is accepted as-is
MAX_REWORK_RETRIES = int(os.environ.get("DEV_REWORK_MAX_RETRIES", "2"))

# Map role → agent/stub module
STUB_REGISTRY = {
    "pm":     pm_agent,       # real model-backed PM agent (P4)
    "dev-jr": dev_agent,       # real model-backed dev agent (P5)
    "dev-sr": reviewer_agent,  # real model-backed reviewer (P5)
    "qa":     qa_agent,        # sandbox-backed QA agent (P6)
    "judge":  judge_agent,     # real model-backed judge agent (P6)
    "ux":     ux_agent,        # UX specialist agent (P8)
    "devops": devops_agent,    # DevOps specialist agent (P8)
}


def _sync_board_issue(run_id: str, project_name: str, brief: str, existing_issue: int | None) -> int | None:
    """Create or update a GitHub issue for this run. Non-fatal — logs and returns None on failure."""
    title = f"[ai-squad] {project_name}"
    body = f"**Run:** `{run_id}`\n\n{brief[:1000]}"
    try:
        resp = httpx.post(
            f"{GITHUB_SVC_URL}/api/v1/board/sync",
            json={
                "run_id": run_id,
                "title": title,
                "body": body,
                "labels": ["ai-squad"],
                "issue_number": existing_issue,
            },
            timeout=15.0,
        )
        if resp.status_code == 200:
            return resp.json().get("issue_number")
        logger.warning("board/sync returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("board/sync call failed (non-fatal): %s", exc)
    return None


def _patch_run_github_refs(run_id: str, issue_number: int) -> None:
    """Write the GitHub issue number back to control-api. Non-fatal."""
    try:
        resp = httpx.patch(
            f"{CONTROL_API_URL}/api/v1/runs/{run_id}/github_refs",
            json={"github_issue_number": issue_number},
            timeout=10.0,
        )
        if resp.status_code != 200:
            logger.warning("PATCH github_refs returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("PATCH github_refs failed (non-fatal): %s", exc)


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

        # fetch project details so agents have the brief
        project = await conn.fetchrow(
            "SELECT name, description FROM projects WHERE id = $1",
            run["project_id"],
        )
        brief = ""
        if project:
            name = project["name"] or ""
            desc = project["description"] or ""
            brief = f"{name}\n\n{desc}".strip()

        # On the first step of a run, sync a GitHub board issue (non-fatal)
        if step["step_order"] == 0 and run.get("github_issue_number") is None:
            project_name = project["name"] if project else "AI Squad Run"
            issue_number = _sync_board_issue(run_id, project_name, brief, existing_issue=None)
            if issue_number is not None:
                await conn.execute(
                    "UPDATE runs SET github_issue_number = $1 WHERE id = $2",
                    issue_number,
                    UUID(run_id),
                )
                logger.info("Board issue #%s created for run %s", issue_number, run_id)

        # load prior artifacts for this run (gives downstream agents PM output etc.)
        prior_rows = await conn.fetch(
            """
            SELECT artifact_type, name, body
              FROM artifacts
             WHERE run_id = $1
             ORDER BY created_at ASC
            """,
            UUID(run_id),
        )
        prior_artifacts = [dict(r) for r in prior_rows]

        # run the agent/stub
        context = {
            "run_id": run_id,
            "step_id": step_id,
            "project_id": str(run["project_id"]),
            "task_id": str(run["task_id"]) if run["task_id"] else None,
            "brief": brief,
            "prior_artifacts": prior_artifacts,
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

        # Rework loop — only fires after a reviewer (dev-sr) step
        if role == "dev-sr":
            reworked = await _maybe_rework(
                conn,
                run_id,
                step["step_order"],
                artifacts,
            )
            if reworked:
                return  # new dev-jr + dev-sr inserted and dispatched

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


async def _maybe_rework(
    conn: asyncpg.Connection,
    run_id: str,
    current_step_order: int,
    new_artifacts: list[dict],
) -> bool:
    """Insert a new dev-jr + dev-sr step pair when reviewer requests changes.

    Returns True if a rework was queued (caller should return immediately).
    Returns False if verdict is not changes_requested, or retries are exhausted.
    """
    # Find review_findings in the artifacts just produced by this reviewer step
    review_body = next(
        (a["body"] for a in new_artifacts if a["artifact_type"] == "review_findings"),
        None,
    )
    if not review_body:
        return False

    try:
        review = json.loads(review_body)
    except Exception:
        return False

    if review.get("verdict") != "changes_requested":
        return False

    # Count how many dev-jr steps have already run (original + any rework steps)
    dev_jr_count = await conn.fetchval(
        "SELECT COUNT(*) FROM run_steps WHERE run_id = $1 AND role = 'dev-jr'",
        UUID(run_id),
    )
    retry_num = int(dev_jr_count)  # e.g. 1 = first rework

    if retry_num > MAX_REWORK_RETRIES:
        logger.info(
            "Run %s: rework limit reached (%d/%d) — accepting reviewer verdict as-is",
            run_id, retry_num - 1, MAX_REWORK_RETRIES,
        )
        return False

    await conn.execute(
        """
        UPDATE run_steps
           SET status = 'skipped',
               error_message = $1,
               completed_at = $2
         WHERE run_id = $3
           AND status = 'pending'
           AND step_order > $4
        """,
        "Superseded by a reviewer-requested rework cycle.",
        datetime.now(timezone.utc),
        UUID(run_id),
        current_step_order,
    )

    # Append a fresh downstream path after the current highest step_order
    max_order = await conn.fetchval(
        "SELECT MAX(step_order) FROM run_steps WHERE run_id = $1",
        UUID(run_id),
    )
    base = (max_order or 0)

    rework_metadata = json.dumps({"rework_retry": retry_num})

    roles_to_requeue = ["dev-jr", "dev-sr"]
    has_qa = await conn.fetchval(
        "SELECT 1 FROM run_steps WHERE run_id = $1 AND role = 'qa' LIMIT 1",
        UUID(run_id),
    )
    has_judge = await conn.fetchval(
        "SELECT 1 FROM run_steps WHERE run_id = $1 AND role = 'judge' LIMIT 1",
        UUID(run_id),
    )
    if has_qa:
        roles_to_requeue.append("qa")
    if has_judge:
        roles_to_requeue.append("judge")

    new_dev_jr = None
    for offset, role in enumerate(roles_to_requeue, start=1):
        row = await conn.fetchrow(
            """
            INSERT INTO run_steps (run_id, role, step_order, status, pause_after, metadata)
            VALUES ($1, $2, $3, 'pending', FALSE, $4::jsonb)
            RETURNING id
            """,
            UUID(run_id),
            role,
            base + offset,
            rework_metadata,
        )
        if role == "dev-jr":
            new_dev_jr = row

    if new_dev_jr is None:
        return False

    new_step_id = str(new_dev_jr["id"])
    logger.info(
        "Run %s: reviewer requested changes — queuing rework %d/%d (new dev-jr step %s)",
        run_id, retry_num, MAX_REWORK_RETRIES, new_step_id,
    )
    execute_step.apply_async(
        kwargs={"run_id": run_id, "step_id": new_step_id},
        queue="squad.steps",
    )
    return True


@app.task(name="app.tasks.execute_step", bind=True, max_retries=3)
def execute_step(self, *, run_id: str, step_id: str) -> None:
    """Execute a single run step using the registered agent module."""
    asyncio.run(_run_step(run_id, step_id))
