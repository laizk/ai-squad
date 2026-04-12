"""Deterministic PM stub agent.

Produces a spec artifact and a tasks artifact for P3 validation.
Output is structured but generated without a live model so the
workflow mechanics can be proven before real model quality matters.
"""
from __future__ import annotations

import json


SPEC_CONTRACT = {
    "required": ["brief_summary", "milestones", "rationale"],
}

TASKS_CONTRACT = {
    "required": ["tasks"],
    "tasks_min_length": 3,
}


def run(context: dict) -> list[dict]:
    """Return a list of artifact dicts for the PM step.

    Each dict has: artifact_type, name, body.
    """
    project_id = context.get("project_id", "unknown")
    task_id = context.get("task_id", "unknown")

    spec_body = json.dumps({
        "brief_summary": (
            "Stub PM output for project validation. "
            "This spec was produced by the deterministic PM stub to prove "
            "the orchestration pipeline works end-to-end without relying on "
            "live model quality."
        ),
        "milestones": [
            {
                "title": "M1: Foundation validated",
                "description": "Core data model and API are in place and tested.",
                "acceptance_criteria": [
                    "Health endpoint returns 200 with real dependency state.",
                    "All P1 CRUD endpoints have passing integration tests.",
                    "Revision history is append-only and enforced at the DB level.",
                ],
            },
            {
                "title": "M2: Orchestration proven",
                "description": "Stub agents drive a full run through the queue.",
                "acceptance_criteria": [
                    "Run creation respects idempotency keys.",
                    "Step sequencing and pause-for-human flow works end-to-end.",
                    "Artifacts are persisted and retrievable.",
                ],
            },
        ],
        "rationale": (
            "Breaking delivery into two milestones: the first proves the data layer "
            "and the second proves the orchestration layer. This order keeps risk "
            "surface small — each milestone can be approved independently."
        ),
    }, indent=2)

    tasks_body = json.dumps({
        "tasks": [
            {
                "title": "Implement health endpoint",
                "role": "dev-jr",
                "priority": "high",
                "acceptance_criteria": [
                    "GET /health returns postgres and redis states truthfully.",
                    "Degraded state is returned when a dependency is unreachable.",
                ],
            },
            {
                "title": "Write project CRUD integration tests",
                "role": "qa",
                "priority": "high",
                "acceptance_criteria": [
                    "Create, read, update are covered with real DB assertions.",
                    "Revision history is verified for each mutation.",
                ],
            },
            {
                "title": "Implement run orchestration step sequencing",
                "role": "dev-jr",
                "priority": "high",
                "acceptance_criteria": [
                    "Steps execute in order and respect pause_after flag.",
                    "Idempotent run creation deduplicates by idempotency_key.",
                    "Cancel marks remaining pending steps as skipped.",
                ],
            },
        ]
    }, indent=2)

    return [
        {"artifact_type": "spec", "name": "pm_spec_stub.json", "body": spec_body},
        {"artifact_type": "tasks", "name": "pm_tasks_stub.json", "body": tasks_body},
    ]


def validate(artifact_type: str, body: str) -> bool:
    """Validate artifact body against this stub's output contract."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False

    if artifact_type == "spec":
        return all(k in data for k in SPEC_CONTRACT["required"])
    if artifact_type == "tasks":
        tasks = data.get("tasks", [])
        return (
            all(k in data for k in TASKS_CONTRACT["required"])
            and isinstance(tasks, list)
            and len(tasks) >= TASKS_CONTRACT["tasks_min_length"]
        )
    return False
