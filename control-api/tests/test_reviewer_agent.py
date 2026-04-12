"""P5 integration tests — real reviewer agent run.

Runs a full dev_cycle (PM stub → dev-jr → dev-sr) and verifies the
review_findings artifact has a real verdict and substantive findings.
"""
from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest


POLL_INTERVAL = 3.0
POLL_TIMEOUT  = 900.0  # three model calls: pm (skipped) + dev-jr + dev-sr


def _make_run_payload(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "workflow_type": "dev_cycle",
        "idempotency_key": f"p5-reviewer-{uuid4().hex}",
    }


@pytest.fixture
def reviewer_project(client, project_payload):
    payload = {
        **project_payload,
        "name": "URL Shortener",
        "description": (
            "Build a minimal URL shortener in Python. "
            "Given a long URL, return a short code. "
            "Store mappings in memory. "
            "Expose a simple function interface, not a web server. "
            "Include at least two pytest tests covering the core mapping logic."
        ),
    }
    resp = client.post("/projects", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _wait_for_terminal(client, run_id: str) -> dict | None:
    terminal = {"paused", "completed", "failed", "cancelled"}
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        data = client.get(f"/runs/{run_id}").json()
        if data["status"] in terminal:
            return data
        time.sleep(POLL_INTERVAL)
    return None


class TestRealReviewerAgent:
    def test_dev_cycle_produces_review_findings(self, client, reviewer_project):
        run_id = client.post("/runs", json=_make_run_payload(reviewer_project)).json()["id"]
        run = _wait_for_terminal(client, run_id)

        if run is None:
            pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s")
        if run["status"] == "failed":
            pytest.fail(f"Dev cycle run failed: {run.get('error_message')}")

        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        types = {a["artifact_type"] for a in artifacts}
        assert "review_findings" in types, f"review_findings missing; got: {types}"

    def test_review_findings_has_valid_verdict(self, client, reviewer_project):
        run_id = client.post("/runs", json=_make_run_payload(reviewer_project)).json()["id"]
        run = _wait_for_terminal(client, run_id)

        if run is None:
            pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s")
        if run["status"] == "failed":
            pytest.fail(f"Dev cycle run failed: {run.get('error_message')}")

        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        rev_art = next((a for a in artifacts if a["artifact_type"] == "review_findings"), None)
        assert rev_art is not None

        content = client.get(f"/artifacts/{rev_art['id']}/content").json()
        body = json.loads(content["body"])

        assert body["verdict"] in ("approved", "changes_requested", "rejected"), (
            f"unexpected verdict: {body['verdict']!r}"
        )
        assert len(body["findings"]) >= 1, "no findings"
        for f in body["findings"]:
            assert f.get("severity") in ("info", "warning", "critical"), (
                f"bad severity: {f.get('severity')}"
            )
            assert len(f.get("detail", "")) >= 20, (
                f"finding detail too short: {f.get('detail')!r}"
            )
        assert len(body.get("recommendation", "")) >= 50, "recommendation too short"
