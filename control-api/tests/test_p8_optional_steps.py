"""P8 tests — optional UX and DevOps steps.

Covers:
1. Run with no optional_steps: ux and devops appear as 'skipped' in the plan.
2. Run with optional_steps=["ux","devops"]: both appear as 'pending' then execute.
3. Invalid optional_step value is rejected with 422.
4. Skip logic is visible — skipped steps are present in the response, not hidden.
"""
from __future__ import annotations

import time
from uuid import uuid4

import pytest
import httpx

POLL_INTERVAL = 3.0
POLL_TIMEOUT = 60.0   # unit-style checks only; no live model run here


def _run_payload(project_id: str, optional_steps: list[str] | None = None) -> dict:
    payload = {
        "project_id": project_id,
        "workflow_type": "dev_cycle",
        "idempotency_key": f"p8-{uuid4().hex}",
    }
    if optional_steps is not None:
        payload["optional_steps"] = optional_steps
    return payload


@pytest.fixture
def p8_project(client, project_payload):
    resp = client.post("/projects", json={
        **project_payload,
        "name": "P8 Optional Steps Test",
        "description": "Minimal project for testing UX and DevOps optional step visibility.",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── Skip visibility ───────────────────────────────────────────────────────────

def test_default_run_has_ux_and_devops_as_skipped(client, p8_project):
    """Without optional_steps, ux and devops must appear as 'skipped' — not absent."""
    resp = client.post("/runs", json=_run_payload(p8_project))
    assert resp.status_code == 201, resp.text
    run = resp.json()

    steps = run["steps"]
    roles = {s["role"]: s["status"] for s in steps}

    assert "ux" in roles, f"ux step missing from run plan: {roles}"
    assert "devops" in roles, f"devops step missing from run plan: {roles}"
    assert roles["ux"] == "skipped", f"expected ux=skipped, got {roles['ux']}"
    assert roles["devops"] == "skipped", f"expected devops=skipped, got {roles['devops']}"


def test_enabled_optional_steps_are_pending(client, p8_project):
    """With optional_steps=[ux, devops], both must be 'pending' at run creation."""
    resp = client.post("/runs", json=_run_payload(p8_project, optional_steps=["ux", "devops"]))
    assert resp.status_code == 201, resp.text
    run = resp.json()

    steps = run["steps"]
    roles = {s["role"]: s["status"] for s in steps}

    assert "ux" in roles, f"ux step missing: {roles}"
    assert "devops" in roles, f"devops step missing: {roles}"
    assert roles["ux"] == "pending", f"expected ux=pending, got {roles['ux']}"
    assert roles["devops"] == "pending", f"expected devops=pending, got {roles['devops']}"


def test_ux_only_enabled(client, p8_project):
    resp = client.post("/runs", json=_run_payload(p8_project, optional_steps=["ux"]))
    assert resp.status_code == 201, resp.text
    roles = {s["role"]: s["status"] for s in resp.json()["steps"]}
    assert roles["ux"] == "pending"
    assert roles["devops"] == "skipped"


def test_devops_only_enabled(client, p8_project):
    resp = client.post("/runs", json=_run_payload(p8_project, optional_steps=["devops"]))
    assert resp.status_code == 201, resp.text
    roles = {s["role"]: s["status"] for s in resp.json()["steps"]}
    assert roles["ux"] == "skipped"
    assert roles["devops"] == "pending"


def test_invalid_optional_step_is_rejected(client, p8_project):
    resp = client.post("/runs", json={
        **_run_payload(p8_project),
        "optional_steps": ["not-a-real-role"],
    })
    assert resp.status_code == 422, resp.text


# ── Step ordering ─────────────────────────────────────────────────────────────

def test_ux_step_order_is_after_pm_and_before_dev_jr(client, p8_project):
    """UX must slot in after pm (if present) and before dev-jr."""
    resp = client.post("/runs", json=_run_payload(p8_project, optional_steps=["ux"]))
    assert resp.status_code == 201
    steps = sorted(resp.json()["steps"], key=lambda s: s["step_order"])
    roles_ordered = [s["role"] for s in steps]

    # dev_cycle has no pm step, so ux should come first (before dev-jr)
    assert roles_ordered.index("ux") < roles_ordered.index("dev-jr"), roles_ordered


def test_devops_step_order_is_after_judge(client, p8_project):
    """DevOps must slot in after judge."""
    resp = client.post("/runs", json=_run_payload(p8_project, optional_steps=["devops"]))
    assert resp.status_code == 201
    steps = sorted(resp.json()["steps"], key=lambda s: s["step_order"])
    roles_ordered = [s["role"] for s in steps]

    assert roles_ordered.index("devops") > roles_ordered.index("judge"), roles_ordered


# Agent contract validation tests live in workers/tests/test_p8_agent_contracts.py
# (workers agents are not importable from the control-api container)
