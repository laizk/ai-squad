"""Reconciler — surfaces mismatches between internal run state and GitHub refs.

Does NOT auto-mutate. Returns a report for human review.

GET /api/v1/reconcile
  Query params:
    limit   (int, default 50) — how many recent completed runs to inspect
    project_id (UUID, optional) — scope to one project

Report shape:
  {
    "generated_at": "...",
    "runs_inspected": N,
    "mismatches": [...],
    "summary": { "total": N, "missing_github_ref": N, "missing_issue": N, "ok": N }
  }

A mismatch is reported when:
  - run.github_issue_number is set but no webhook_event with that issue number exists
  - run.github_pr_number is set but no webhook_event with that PR number exists
  - run completed but has no github_issue_number at all (board gap)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.db import open_ready_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["reconcile"])


@router.get("/reconcile")
async def reconcile(
    limit: int = Query(default=50, ge=1, le=500),
    project_id: UUID | None = Query(default=None),
) -> dict[str, Any]:
    conn = await open_ready_connection()
    try:
        return await _build_report(conn, limit, project_id)
    finally:
        await conn.close()


async def _build_report(conn, limit: int, project_id: UUID | None) -> dict[str, Any]:
    # Fetch recent completed runs with their GitHub refs
    if project_id:
        runs = await conn.fetch(
            """
            SELECT id, project_id, workflow_type, status,
                   github_issue_number, github_branch, github_pr_number,
                   completed_at, created_at
              FROM runs
             WHERE status = 'completed'
               AND project_id = $1
             ORDER BY completed_at DESC NULLS LAST
             LIMIT $2
            """,
            project_id,
            limit,
        )
    else:
        runs = await conn.fetch(
            """
            SELECT id, project_id, workflow_type, status,
                   github_issue_number, github_branch, github_pr_number,
                   completed_at, created_at
              FROM runs
             WHERE status = 'completed'
             ORDER BY completed_at DESC NULLS LAST
             LIMIT $1
            """,
            limit,
        )

    # Collect all issue/PR numbers present in webhook_events for fast lookup
    seen_issues: set[int] = set()
    seen_prs: set[int] = set()

    issue_rows = await conn.fetch(
        """
        SELECT DISTINCT (payload->'issue'->>'number')::int AS num
          FROM webhook_events
         WHERE event_type IN ('issues', 'issue_comment')
           AND (payload->'issue'->>'number') IS NOT NULL
        """
    )
    for row in issue_rows:
        if row["num"] is not None:
            seen_issues.add(row["num"])

    pr_rows = await conn.fetch(
        """
        SELECT DISTINCT (payload->'pull_request'->>'number')::int AS num
          FROM webhook_events
         WHERE event_type IN ('pull_request', 'pull_request_review')
           AND (payload->'pull_request'->>'number') IS NOT NULL
        """
    )
    for row in pr_rows:
        if row["num"] is not None:
            seen_prs.add(row["num"])

    mismatches = []
    ok_count = 0

    for run in runs:
        run_id = str(run["id"])
        issues = []

        if run["github_issue_number"] is None:
            issues.append("no_github_issue_ref")
        elif run["github_issue_number"] not in seen_issues:
            issues.append(f"issue_{run['github_issue_number']}_not_in_webhook_events")

        if run["github_pr_number"] is not None and run["github_pr_number"] not in seen_prs:
            issues.append(f"pr_{run['github_pr_number']}_not_in_webhook_events")

        if issues:
            mismatches.append({
                "run_id": run_id,
                "project_id": str(run["project_id"]),
                "workflow_type": run["workflow_type"],
                "github_issue_number": run["github_issue_number"],
                "github_pr_number": run["github_pr_number"],
                "github_branch": run["github_branch"],
                "issues": issues,
            })
        else:
            ok_count += 1

    missing_ref = sum(1 for m in mismatches if "no_github_issue_ref" in m["issues"])
    missing_issue = sum(
        1 for m in mismatches
        if any("not_in_webhook_events" in i for i in m["issues"])
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_inspected": len(runs),
        "mismatches": mismatches,
        "summary": {
            "total": len(runs),
            "missing_github_ref": missing_ref,
            "missing_webhook_event": missing_issue,
            "ok": ok_count,
        },
    }
