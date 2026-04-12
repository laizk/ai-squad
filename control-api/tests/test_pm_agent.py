"""P4 integration tests — real PM agent run.

These tests create a pm_planning run and wait for the workers to complete it
(with the real Ollama-backed PM agent). They verify:
- all three artifacts are produced (spec, tasks, decision_log)
- artifacts pass content sanity checks
- the spec has a substantive brief_summary and rationale
- the tasks artifact has at least 3 tasks with acceptance criteria
- the decision_log artifact contains at least one decision entry

These tests are slower than unit tests (Ollama call can take 10–60s).
They are skipped if the PM agent does not complete within the timeout.
"""
from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest


POLL_INTERVAL = 2.0   # seconds between status checks
POLL_TIMEOUT = 120.0  # seconds to wait for a pm_planning run to pause


def _make_run_payload(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "workflow_type": "pm_planning",
        "idempotency_key": f"p4-test-{uuid4().hex}",
    }


@pytest.fixture
def p4_project(client, project_payload):
    """A project with a meaningful description so the PM has a real brief."""
    payload = {
        **project_payload,
        "name": "Weather Dashboard",
        "description": (
            "Build a simple web dashboard that shows current weather and a 5-day "
            "forecast for any city. Users can search by city name. Data comes from "
            "a public weather API. The app must load in under 2 seconds and work "
            "on mobile devices."
        ),
    }
    resp = client.post("/projects", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _wait_for_paused(client, run_id: str) -> dict | None:
    """Poll until run reaches paused state or timeout. Returns run dict or None."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        data = client.get(f"/runs/{run_id}").json()
        if data["status"] == "paused":
            return data
        if data["status"] in ("failed", "cancelled"):
            return data
        time.sleep(POLL_INTERVAL)
    return None


class TestRealPMAgent:
    def test_pm_planning_run_produces_three_artifacts(self, client, p4_project):
        run_id = client.post("/runs", json=_make_run_payload(p4_project)).json()["id"]
        run = _wait_for_paused(client, run_id)

        if run is None:
            pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s — Ollama may be slow or offline")
        if run["status"] == "failed":
            pytest.fail(f"PM agent run failed: {run.get('error_message')}")

        # fetch artifacts
        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        types = {a["artifact_type"] for a in artifacts}
        assert "spec" in types, f"spec artifact missing; got: {types}"
        assert "tasks" in types, f"tasks artifact missing; got: {types}"
        assert "decision_log" in types, f"decision_log artifact missing; got: {types}"

    def test_spec_artifact_passes_sanity_checks(self, client, p4_project):
        run_id = client.post("/runs", json=_make_run_payload(p4_project)).json()["id"]
        run = _wait_for_paused(client, run_id)

        if run is None:
            pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s")
        if run["status"] == "failed":
            pytest.fail(f"PM agent run failed: {run.get('error_message')}")

        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        spec = next((a for a in artifacts if a["artifact_type"] == "spec"), None)
        assert spec is not None

        # fetch artifact content
        content = client.get(f"/artifacts/{spec['id']}/content").json()
        body = json.loads(content["body"])

        assert len(body.get("brief_summary", "")) >= 50, (
            f"brief_summary too short: {body.get('brief_summary', '')!r}"
        )
        assert len(body.get("rationale", "")) >= 100, (
            f"rationale too short: {body.get('rationale', '')!r}"
        )
        assert len(body.get("milestones", [])) >= 2, "too few milestones"

    def test_tasks_artifact_has_substantive_tasks(self, client, p4_project):
        run_id = client.post("/runs", json=_make_run_payload(p4_project)).json()["id"]
        run = _wait_for_paused(client, run_id)

        if run is None:
            pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s")
        if run["status"] == "failed":
            pytest.fail(f"PM agent run failed: {run.get('error_message')}")

        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        tasks_artifact = next((a for a in artifacts if a["artifact_type"] == "tasks"), None)
        assert tasks_artifact is not None

        content = client.get(f"/artifacts/{tasks_artifact['id']}/content").json()
        body = json.loads(content["body"])
        tasks = body.get("tasks", [])

        assert len(tasks) >= 3, f"too few tasks: {len(tasks)}"
        for task in tasks:
            ac = task.get("acceptance_criteria", [])
            assert len(ac) >= 2, (
                f"task '{task.get('title')}' has too few AC: {ac}"
            )
            assert task.get("role") in ("dev-jr", "dev-sr", "qa", "devops", "ux"), (
                f"unexpected role: {task.get('role')}"
            )

    def test_decision_log_has_substantive_entries(self, client, p4_project):
        run_id = client.post("/runs", json=_make_run_payload(p4_project)).json()["id"]
        run = _wait_for_paused(client, run_id)

        if run is None:
            pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s")
        if run["status"] == "failed":
            pytest.fail(f"PM agent run failed: {run.get('error_message')}")

        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        dl_artifact = next((a for a in artifacts if a["artifact_type"] == "decision_log"), None)
        assert dl_artifact is not None

        content = client.get(f"/artifacts/{dl_artifact['id']}/content").json()
        body = json.loads(content["body"])
        dl = body.get("decision_log", [])

        assert len(dl) >= 1, "decision_log has no entries"
        for entry in dl:
            assert "decision" in entry, f"entry missing 'decision' key: {entry}"
            assert "reason" in entry, f"entry missing 'reason' key: {entry}"
            assert len(entry["decision"]) > 10, f"decision too short: {entry['decision']!r}"
