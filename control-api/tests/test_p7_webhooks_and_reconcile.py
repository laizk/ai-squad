"""P7 integration tests — webhook ingestion, replay idempotency, and reconciler.

Three scenarios:
1. Ingest a webhook event and verify it is stored with correct fields.
2. Replay the same delivery_id and verify it is stored again
   (append-only — no dedup by design; replay is the caller's responsibility).
3. Call the reconciler and verify the report shape is correct.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from uuid import uuid4

import httpx
import pytest

# When running inside the control-api container, github-svc is on the Docker
# internal network. Override with GITHUB_SVC_TEST_URL for external test runs.
GITHUB_SVC_BASE = os.getenv("GITHUB_SVC_TEST_URL", "http://github-svc:9000")

# Match the secret configured in the container
_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "ai-squad-local-secret")


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _webhook_headers(body: bytes, event: str, delivery: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": _sign(body),
    }


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
    body = json.dumps(_webhook_payload(issue_number=999)).encode()

    resp = client.post(
        "/webhooks/github",
        content=body,
        headers=_webhook_headers(body, "issues", delivery_id),
    )
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["event_type"] == "issues"
    assert "id" in data
    assert "received_at" in data


def test_webhook_ingest_bad_signature_is_rejected(client: httpx.Client) -> None:
    body = json.dumps({"action": "ping"}).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": uuid4().hex,
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )
    assert resp.status_code == 401, resp.text


def test_webhook_replay_is_stored_again(client: httpx.Client) -> None:
    """Replaying the same delivery_id stores a second row (append-only)."""
    delivery_id = f"p7-replay-{uuid4().hex}"
    body = json.dumps(_webhook_payload(issue_number=1001)).encode()
    headers = _webhook_headers(body, "issues", delivery_id)

    r1 = client.post("/webhooks/github", content=body, headers=headers)
    r2 = client.post("/webhooks/github", content=body, headers=headers)

    assert r1.status_code == 202
    assert r2.status_code == 202
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
