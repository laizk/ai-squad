"""P5 integration tests — real dev agent run.

These tests create a dev_cycle run and wait for the workers to complete it.
They verify:
- dev_output artifact is produced
- artifact contains branch, files_written, github fields
- files_written is non-empty
- github-svc ops are either completed or skipped (not errored fatally)

These tests are slower than unit tests (two model inference calls: PM + dev).
They are skipped if the run does not complete within the timeout.
"""
from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest


POLL_INTERVAL = 3.0
POLL_TIMEOUT  = 600.0  # two model calls — allow up to 10 min


def _make_run_payload(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "workflow_type": "dev_cycle",
        "idempotency_key": f"p5-test-{uuid4().hex}",
    }


@pytest.fixture
def p5_project(client, project_payload):
    payload = {
        **project_payload,
        "name": "CLI Todo App",
        "description": (
            "Build a minimal command-line todo app in Python. "
            "Users can add tasks, list them, and mark them as done. "
            "Tasks persist to a local JSON file. "
            "The app must have at least one test that can be run with pytest."
        ),
    }
    resp = client.post("/projects", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _wait_for_terminal(client, run_id: str) -> dict | None:
    """Poll until run reaches paused/completed/failed/cancelled or timeout."""
    terminal = {"paused", "completed", "failed", "cancelled"}
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        data = client.get(f"/runs/{run_id}").json()
        if data["status"] in terminal:
            return data
        time.sleep(POLL_INTERVAL)
    return None


class TestRealDevAgent:
    def test_dev_cycle_produces_dev_output_artifact(self, client, p5_project):
        run_id = client.post("/runs", json=_make_run_payload(p5_project)).json()["id"]
        run = _wait_for_terminal(client, run_id)

        if run is None:
            pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s — model server may be slow or offline")
        if run["status"] == "failed":
            pytest.fail(f"Dev cycle run failed: {run.get('error_message')}")

        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        types = {a["artifact_type"] for a in artifacts}
        assert "dev_output" in types, f"dev_output artifact missing; got: {types}"

    def test_dev_output_has_required_fields(self, client, p5_project):
        run_id = client.post("/runs", json=_make_run_payload(p5_project)).json()["id"]
        run = _wait_for_terminal(client, run_id)

        if run is None:
            pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s")
        if run["status"] == "failed":
            pytest.fail(f"Dev cycle run failed: {run.get('error_message')}")

        artifacts = client.get(f"/runs/{run_id}/artifacts").json()
        dev_art = next((a for a in artifacts if a["artifact_type"] == "dev_output"), None)
        assert dev_art is not None

        content = client.get(f"/artifacts/{dev_art['id']}/content").json()
        body = json.loads(content["body"])

        assert "branch" in body, "dev_output missing 'branch'"
        assert body["branch"].startswith("ai-squad/"), f"unexpected branch: {body['branch']}"

        assert "files_written" in body, "dev_output missing 'files_written'"
        assert len(body["files_written"]) >= 1, "no files written"

        assert "github" in body, "dev_output missing 'github'"
        github = body["github"]
        # either succeeded (pr_url set) or skipped (configured=false) — never a hard error
        assert github.get("skipped") or github.get("pr_url") or github.get("branch_created"), (
            f"github result looks like an unexpected failure: {github}"
        )
