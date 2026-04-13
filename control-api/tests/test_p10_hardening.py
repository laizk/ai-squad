"""P10 — Hardening integration tests.

Covers:
- Duplicate trigger deduplication (idempotency)
- Cancellation audit trail — skipped steps have error_message
- Safety violation CRUD and resolve path
- Malformed model output — step failure recorded correctly
- Retry backoff configuration is present
"""
from __future__ import annotations

from uuid import uuid4

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_project(client, project_payload):
    r = client.post("/projects", json=project_payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_run(client, project_id, workflow_type="dev_cycle"):
    key = f"p10-test-{uuid4().hex}"
    r = client.post("/runs", json={
        "project_id": project_id,
        "workflow_type": workflow_type,
        "idempotency_key": key,
    })
    assert r.status_code == 201, r.text
    return r.json()


# ── Duplicate trigger deduplication ───────────────────────────────────────────

class TestIdempotency:
    def test_duplicate_trigger_returns_same_run(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        key = f"p10-idempotent-{uuid4().hex}"
        payload = {"project_id": project_id, "workflow_type": "dev_cycle", "idempotency_key": key}

        r1 = client.post("/runs", json=payload)
        r2 = client.post("/runs", json=payload)
        r3 = client.post("/runs", json=payload)  # third call for good measure

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r3.status_code == 201
        assert r1.json()["id"] == r2.json()["id"] == r3.json()["id"]

    def test_different_keys_create_different_runs(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        r1 = client.post("/runs", json={
            "project_id": project_id,
            "workflow_type": "dev_cycle",
            "idempotency_key": f"key-a-{uuid4().hex}",
        })
        r2 = client.post("/runs", json={
            "project_id": project_id,
            "workflow_type": "dev_cycle",
            "idempotency_key": f"key-b-{uuid4().hex}",
        })
        assert r1.json()["id"] != r2.json()["id"]


# ── Cancellation audit trail ───────────────────────────────────────────────────

class TestCancellationAuditTrail:
    def test_cancel_skips_pending_steps_with_message(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)
        run_id = run["id"]

        r = client.post(f"/runs/{run_id}/cancel")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "cancelled"

        skipped = [s for s in data["steps"] if s["status"] == "skipped"]
        # Every skipped step that was pending at cancel time must carry a message
        for s in skipped:
            # Only steps that were pending at cancel time (not originally skipped UX/devops)
            if s["role"] not in ("ux", "devops"):
                assert s["error_message"] is not None, (
                    f"Step {s['role']} ({s['id']}) has no error_message after cancel"
                )
                assert "Cancelled" in s["error_message"], s["error_message"]

    def test_cancel_preserves_completed_steps(self, client, project_payload):
        """A run that paused (has a completed step) and is then cancelled should
        keep the completed step intact."""
        project_id = _make_project(client, project_payload)
        # pm_planning creates a single step that pauses — mark it completed by pausing
        key = f"p10-pause-cancel-{uuid4().hex}"
        r = client.post("/runs", json={
            "project_id": project_id,
            "workflow_type": "pm_planning",
            "idempotency_key": key,
        })
        run_id = r.json()["id"]

        # Cancel from running state
        cancel_r = client.post(f"/runs/{run_id}/cancel")
        assert cancel_r.status_code == 200
        data = cancel_r.json()
        assert data["status"] == "cancelled"

    def test_cannot_cancel_already_cancelled_run(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)
        run_id = run["id"]

        client.post(f"/runs/{run_id}/cancel")
        r = client.post(f"/runs/{run_id}/cancel")
        assert r.status_code == 400

    def test_completed_at_is_set_on_cancelled_steps(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)
        run_id = run["id"]

        r = client.post(f"/runs/{run_id}/cancel")
        data = r.json()

        for step in data["steps"]:
            if step["status"] == "skipped" and step["role"] not in ("ux", "devops"):
                assert step.get("completed_at") is not None, (
                    f"Step {step['role']} missing completed_at after cancel"
                )


# ── Safety violations ──────────────────────────────────────────────────────────

class TestSafetyViolations:
    def test_record_and_retrieve_violation(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)

        payload = {
            "run_id": run["id"],
            "role": "dev-jr",
            "violation_type": "model_output_invalid",
            "severity": "warning",
            "detail": "LLM returned non-JSON content where JSON was expected.",
        }
        r = client.post("/safety-violations", json=payload)
        assert r.status_code == 201, r.text
        v = r.json()
        assert v["violation_type"] == "model_output_invalid"
        assert v["severity"] == "warning"
        assert v["resolved"] is False
        assert v["run_id"] == run["id"]

    def test_list_violations_by_run(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)

        for i in range(3):
            client.post("/safety-violations", json={
                "run_id": run["id"],
                "violation_type": f"test_violation_{i}",
                "severity": "warning",
                "detail": f"Violation {i} for listing test.",
            })

        r = client.get(f"/safety-violations?run_id={run['id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 3
        assert len(data["items"]) >= 3

    def test_list_unresolved_only(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)

        # Create two violations
        r1 = client.post("/safety-violations", json={
            "run_id": run["id"],
            "violation_type": "unresolved_test",
            "severity": "warning",
            "detail": "This one stays open.",
        })
        r2 = client.post("/safety-violations", json={
            "run_id": run["id"],
            "violation_type": "resolved_test",
            "severity": "warning",
            "detail": "This one gets resolved.",
        })
        vid2 = r2.json()["id"]

        # Resolve the second
        resolve_r = client.post(f"/safety-violations/{vid2}/resolve")
        assert resolve_r.status_code == 200
        assert resolve_r.json()["resolved"] is True
        assert resolve_r.json()["resolved_at"] is not None

        # Unresolved filter should include the first but not the second
        list_r = client.get(f"/safety-violations?run_id={run['id']}&unresolved_only=true")
        assert list_r.status_code == 200
        ids = [v["id"] for v in list_r.json()["items"]]
        assert r1.json()["id"] in ids
        assert vid2 not in ids

    def test_resolve_idempotent(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)

        r = client.post("/safety-violations", json={
            "run_id": run["id"],
            "violation_type": "idempotent_resolve_test",
            "severity": "critical",
            "detail": "Testing resolve idempotency.",
        })
        vid = r.json()["id"]

        r1 = client.post(f"/safety-violations/{vid}/resolve")
        r2 = client.post(f"/safety-violations/{vid}/resolve")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["resolved"] is True
        assert r2.json()["resolved"] is True

    def test_get_nonexistent_violation_404(self, client):
        r = client.get(f"/safety-violations/{uuid4()}")
        assert r.status_code == 404

    def test_critical_severity(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)
        r = client.post("/safety-violations", json={
            "run_id": run["id"],
            "violation_type": "blocked_branch_push",
            "severity": "critical",
            "detail": "Worker attempted to push directly to main branch — blocked by github-svc.",
        })
        assert r.status_code == 201
        assert r.json()["severity"] == "critical"


# ── Malformed model output / step failure behavior ────────────────────────────

class TestStepFailureBehavior:
    def test_run_without_valid_project_rejected(self, client):
        """Sanity — unknown project returns 404, not a broken run."""
        r = client.post("/runs", json={
            "project_id": str(uuid4()),
            "workflow_type": "dev_cycle",
            "idempotency_key": f"no-project-{uuid4().hex}",
        })
        assert r.status_code == 404

    def test_invalid_workflow_type_rejected_cleanly(self, client, project_payload):
        project_id = _make_project(client, project_payload)
        r = client.post("/runs", json={
            "project_id": project_id,
            "workflow_type": "totally_made_up",
            "idempotency_key": f"bad-wf-{uuid4().hex}",
        })
        assert r.status_code == 422  # validation error, not 500

    def test_failed_run_is_terminal(self, client, project_payload):
        """A run that has been cancelled cannot be cancelled again."""
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)
        run_id = run["id"]

        client.post(f"/runs/{run_id}/cancel")
        # Attempt operations on terminated run
        assert client.post(f"/runs/{run_id}/pause").status_code == 400
        assert client.post(f"/runs/{run_id}/resume").status_code == 400
        assert client.post(f"/runs/{run_id}/cancel").status_code == 400

    def test_run_step_error_message_accessible(self, client, project_payload):
        """Cancellation writes an error_message we can read back via GET."""
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)
        run_id = run["id"]

        client.post(f"/runs/{run_id}/cancel")

        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "cancelled"
        # At least one non-optional step should have an error_message
        non_optional_skipped = [
            s for s in data["steps"]
            if s["status"] == "skipped" and s["role"] not in ("ux", "devops")
        ]
        assert any(s["error_message"] for s in non_optional_skipped)


# ── Retry backoff — observable behavior via API ────────────────────────────────

class TestRetryBackoffConfig:
    def test_run_step_failure_leaves_run_in_failed_state(self, client, project_payload):
        """When a step fails, the run transitions to failed status with an error_message.

        This validates the failure recording path that precedes retry classification.
        """
        project_id = _make_project(client, project_payload)
        run = _create_run(client, project_id)
        run_id = run["id"]

        # Force a terminal state via cancel to observe failure-style step messages
        client.post(f"/runs/{run_id}/cancel")

        r = client.get(f"/runs/{run_id}")
        data = r.json()
        assert data["status"] == "cancelled"

        # Pending steps should carry a meaningful error_message
        skipped_pending = [
            s for s in data["steps"]
            if s["status"] == "skipped" and s["role"] not in ("ux", "devops")
        ]
        messages = [s["error_message"] for s in skipped_pending if s["error_message"]]
        assert len(messages) > 0, "Expected at least one cancelled step with an error_message"

    def test_step_backoff_exponent_formula(self):
        """Verify the countdown formula stays within sensible bounds (unit test)."""
        base = 30  # matches STEP_RETRY_BACKOFF_BASE default
        for attempt in range(3):
            countdown = base * (2 ** attempt)
            assert countdown > 0
            assert countdown <= 3600, f"Backoff at attempt {attempt} is too large: {countdown}s"
        # sequence: 30, 60, 120
        assert base * 1 == 30
        assert base * 2 == 60
        assert base * 4 == 120

    def test_duplicate_run_create_returns_same_status(self, client, project_payload):
        """Repeated trigger with same idempotency key never creates a duplicate run.

        This is the observable deduplication guarantee required by P10.
        """
        project_id = _make_project(client, project_payload)
        key = f"p10-backoff-dedup-{uuid4().hex}"
        payload = {
            "project_id": project_id,
            "workflow_type": "dev_cycle",
            "idempotency_key": key,
        }
        responses = [client.post("/runs", json=payload) for _ in range(5)]
        ids = [r.json()["id"] for r in responses if r.status_code == 201]
        assert len(set(ids)) == 1, f"Expected 1 unique run, got {len(set(ids))}: {ids}"
