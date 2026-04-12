"""P9 — Prompt evaluation endpoint tests.

Hits the live control-api (same pattern as other integration tests).

Covers:
  POST /api/v1/prompt-evals       — create eval run
  GET  /api/v1/prompt-evals       — list, with filters
  GET  /api/v1/prompt-evals/{id}  — get single
  GET  /api/v1/prompt-evals/compare — side-by-side across revisions
"""
from __future__ import annotations

import uuid

import httpx
import pytest


API_BASE = "http://localhost:8000/api/v1"


# ── helpers ──────────────────────────────────────────────────────────────────

def _create_team_member(client: httpx.Client) -> dict:
    """Create a PM team member; return the response payload."""
    suffix = uuid.uuid4().hex[:8]
    member = client.post("/team-members", json={
        "role": "pm",
        "name": f"pm-eval-{suffix}",
        "display_name": f"PM Eval {suffix}",
        "provider": "ollama",
        "model": "qwen3.5:9b",
        "reason": {"category": "initial_creation", "detail": "Creating PM agent for prompt eval integration test."},
    })
    assert member.status_code == 201, member.text
    return member.json()


# ── create eval run ───────────────────────────────────────────────────────────

def test_create_eval_returns_201_and_pending(client: httpx.Client) -> None:
    """POST creates a pending eval run and captures current revision."""
    member = _create_team_member(client)

    resp = client.post("/prompt-evals", json={
        "team_member_id": member["id"],
        "golden_task_key": "pm_basic_planning",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["team_member_id"] == member["id"]
    assert body["golden_task_key"] == "pm_basic_planning"
    assert body["status"] == "pending"
    assert body["revision_number"] >= 0
    assert body["scores"] is None
    assert body["output_artifact"] is None
    assert body["id"] is not None


def test_create_eval_unknown_task_key_accepted(client: httpx.Client) -> None:
    """Unknown golden_task_key is stored; worker will fail it — API accepts."""
    member = _create_team_member(client)

    resp = client.post("/prompt-evals", json={
        "team_member_id": member["id"],
        "golden_task_key": "nonexistent_golden_task",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["golden_task_key"] == "nonexistent_golden_task"


def test_create_eval_missing_member_returns_404(client: httpx.Client) -> None:
    resp = client.post("/prompt-evals", json={
        "team_member_id": str(uuid.uuid4()),
        "golden_task_key": "pm_basic_planning",
    })
    assert resp.status_code == 404


# ── get single ───────────────────────────────────────────────────────────────

def test_get_eval_by_id(client: httpx.Client) -> None:
    member = _create_team_member(client)
    create = client.post("/prompt-evals", json={
        "team_member_id": member["id"],
        "golden_task_key": "dev_jr_basic_implementation",
    })
    assert create.status_code == 201
    eval_id = create.json()["id"]

    resp = client.get(f"/prompt-evals/{eval_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == eval_id


def test_get_eval_not_found(client: httpx.Client) -> None:
    resp = client.get(f"/prompt-evals/{uuid.uuid4()}")
    assert resp.status_code == 404


# ── list evals ───────────────────────────────────────────────────────────────

def test_list_evals_unfiltered(client: httpx.Client) -> None:
    resp = client.get("/prompt-evals")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert isinstance(body["items"], list)


def test_list_evals_filtered_by_team_member(client: httpx.Client) -> None:
    member = _create_team_member(client)
    member_id = member["id"]

    for _ in range(2):
        client.post("/prompt-evals", json={
            "team_member_id": member_id,
            "golden_task_key": "pm_basic_planning",
        })

    resp = client.get(f"/prompt-evals?team_member_id={member_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    assert all(item["team_member_id"] == member_id for item in body["items"])


def test_list_evals_filtered_by_golden_task(client: httpx.Client) -> None:
    member = _create_team_member(client)

    client.post("/prompt-evals", json={
        "team_member_id": member["id"],
        "golden_task_key": "pm_basic_planning",
    })
    client.post("/prompt-evals", json={
        "team_member_id": member["id"],
        "golden_task_key": "dev_jr_basic_implementation",
    })

    resp = client.get("/prompt-evals?golden_task_key=pm_basic_planning")
    assert resp.status_code == 200
    body = resp.json()
    for item in body["items"]:
        assert item["golden_task_key"] == "pm_basic_planning"


# ── compare ──────────────────────────────────────────────────────────────────

def test_compare_excludes_non_completed(client: httpx.Client) -> None:
    """compare endpoint returns only completed runs (pending run excluded)."""
    member = _create_team_member(client)
    member_id = member["id"]

    client.post("/prompt-evals", json={
        "team_member_id": member_id,
        "golden_task_key": "pm_basic_planning",
    })

    resp = client.get(
        f"/prompt-evals/compare"
        f"?team_member_id={member_id}&golden_task_key=pm_basic_planning"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["team_member_id"] == member_id
    assert body["golden_task_key"] == "pm_basic_planning"
    # pending run must not appear
    assert all(r["status"] == "completed" for r in body["revisions"])


def test_compare_requires_both_params(client: httpx.Client) -> None:
    """compare with missing required query params returns 422."""
    resp = client.get(f"/prompt-evals/compare?team_member_id={uuid.uuid4()}")
    assert resp.status_code == 422
