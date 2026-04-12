"""P7 integration tests — webhook ingestion, replay idempotency, and reconciler.

Three scenarios:
1. Ingest a webhook event and verify it is stored with correct fields.
2. Replay the same delivery_id and verify it is stored again
   (append-only — no dedup by design; replay is the caller's responsibility).
3. Call the reconciler and verify the report shape is correct.
"""
from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx
import pytest

# When running inside the control-api container, github-svc is on the Docker
# internal network. Override with GITHUB_SVC_TEST_URL for external test runs.
GITHUB_SVC_BASE = os.getenv("GITHUB_SVC_TEST_URL", "http://github-svc:9000")


# ── Webhook ingestion ─────────────────────────────────────────────────────────

def _webhook_payload(issue_number: int) -> dict:
    return {
        "action": "opened",
        "issue": {
            "number": issue_number,
            "title": f"P7 test issue #{issue_number}",
            "state": "open",
            "html_url": f"https://github.com/laizk/ai-squad-test-workspace/issues/{issue_number}",
        },
        "repository": {
            "full_name": "laizk/ai-squad-test-workspace",
        },
        "sender": {"login": "ai-squad-test-app[bot]"},
    }


def test_webhook_ingest_stores_event(client: httpx.Client) -> None:
    delivery_id = f"p7-test-{uuid4().hex}"
    payload = _webhook_payload(issue_number=999)

    resp = client.post(
        "/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery_id,
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["event_type"] == "issues"
    assert "id" in body
    assert "received_at" in body


def test_webhook_ingest_missing_content_type_still_works(client: httpx.Client) -> None:
    """Raw JSON body without explicit headers should still be accepted."""
    resp = client.post(
        "/webhooks/github",
        content=json.dumps({"action": "ping", "zen": "P7 test"}),
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
        },
    )
    assert resp.status_code == 202, resp.text


def test_webhook_replay_is_stored_again(client: httpx.Client) -> None:
    """Replaying the same delivery_id stores a second row (append-only)."""
    delivery_id = f"p7-replay-{uuid4().hex}"
    payload = _webhook_payload(issue_number=1001)
    headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": delivery_id,
    }

    r1 = client.post("/webhooks/github", json=payload, headers=headers)
    r2 = client.post("/webhooks/github", json=payload, headers=headers)

    assert r1.status_code == 202
    assert r2.status_code == 202
    # Both calls succeed; ids must differ (two rows stored)
    assert r1.json()["id"] != r2.json()["id"]


# ── Reconciler ───────────────────────────────────────────────────────────────

def test_reconciler_returns_report_shape(client: httpx.Client) -> None:
    resp = client.get("/reconcile")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "generated_at" in data
    assert isinstance(data["runs_inspected"], int)
    assert isinstance(data["mismatches"], list)
    assert "summary" in data

    summary = data["summary"]
    assert "total" in summary
    assert "missing_github_ref" in summary
    assert "missing_webhook_event" in summary
    assert "ok" in summary
    assert summary["total"] == data["runs_inspected"]


def test_reconciler_project_scoped(client: httpx.Client, project_payload: dict) -> None:
    """Reconciler with a valid project_id should return a scoped report."""
    proj = client.post("/projects", json=project_payload)
    assert proj.status_code == 201
    project_id = proj.json()["id"]

    resp = client.get(f"/reconcile?project_id={project_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["runs_inspected"] == 0   # new project, no runs yet
    assert data["mismatches"] == []


def test_reconciler_invalid_project_id_is_422(client: httpx.Client) -> None:
    resp = client.get("/reconcile?project_id=not-a-uuid")
    assert resp.status_code == 422


# ── Board sync endpoint on github-svc ────────────────────────────────────────


def test_board_sync_creates_issue() -> None:
    """Board sync creates a GitHub issue and returns its number."""
    run_id = uuid4().hex
    with httpx.Client(base_url=GITHUB_SVC_BASE, timeout=15.0) as gh:
        resp = gh.post(
            "/api/v1/board/sync",
            json={
                "run_id": run_id,
                "title": f"[ai-squad] P7 board sync test {run_id[:8]}",
                "body": "Created by P7 integration test.",
                "labels": [],
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["action"] == "created"
    assert isinstance(data["issue_number"], int)
    assert data["issue_number"] > 0
    assert "html_url" in data
    assert data["run_id"] == run_id


def test_board_sync_updates_existing_issue() -> None:
    """Board sync with issue_number updates the issue instead of creating a new one."""
    run_id = uuid4().hex
    with httpx.Client(base_url=GITHUB_SVC_BASE, timeout=15.0) as gh:
        # create first
        create_resp = gh.post(
            "/api/v1/board/sync",
            json={
                "run_id": run_id,
                "title": f"[ai-squad] P7 update test {run_id[:8]}",
                "body": "Original body.",
            },
        )
        assert create_resp.status_code == 200
        issue_number = create_resp.json()["issue_number"]

        # update
        update_resp = gh.post(
            "/api/v1/board/sync",
            json={
                "run_id": run_id,
                "title": f"[ai-squad] P7 update test {run_id[:8]} (updated)",
                "body": "Updated body.",
                "issue_number": issue_number,
            },
        )
    assert update_resp.status_code == 200, update_resp.text
    data = update_resp.json()
    assert data["action"] == "updated"
    assert data["issue_number"] == issue_number
