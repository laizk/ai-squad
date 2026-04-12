"""P6 integration test — real QA and judge agent run.

Runs a full dev_cycle and verifies the new QA and judge artifacts are produced
with the expected structured fields.
"""
from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest


POLL_INTERVAL = 3.0
POLL_TIMEOUT = 1200.0  # dev-jr + dev-sr + qa + judge, plus possible rework


def _make_run_payload(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "workflow_type": "dev_cycle",
        "idempotency_key": f"p6-qa-judge-{uuid4().hex}",
    }


@pytest.fixture
def p6_project(client, project_payload):
    payload = {
        **project_payload,
        "name": "Markdown Notes Organizer",
        "description": (
            "Build a minimal Python notes organizer for markdown files. "
            "Users can add notes, list notes by tag, and search note titles. "
            "Store data in memory only. "
            "Expose functions and a tiny CLI entrypoint. "
            "Include at least two pytest tests covering note creation and search behavior."
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


def _artifact_body(client, artifact_id: str) -> dict:
    content = client.get(f"/artifacts/{artifact_id}/content").json()
    return json.loads(content["body"])


def test_dev_cycle_produces_qa_and_judge_artifacts(client, p6_project):
    run_id = client.post("/runs", json=_make_run_payload(p6_project)).json()["id"]
    run = _wait_for_terminal(client, run_id)

    if run is None:
        pytest.skip(f"Run did not complete within {POLL_TIMEOUT}s")
    if run["status"] == "failed":
        pytest.fail(f"Dev cycle run failed: {run.get('error_message')}")

    artifacts = client.get(f"/runs/{run_id}/artifacts").json()
    qa_art = next((a for a in artifacts if a["artifact_type"] == "test_results"), None)
    judge_art = next((a for a in artifacts if a["artifact_type"] == "rubric_score"), None)

    assert qa_art is not None, "test_results artifact missing"
    assert judge_art is not None, "rubric_score artifact missing"

    qa_body = _artifact_body(client, qa_art["id"])
    assert qa_body["status"] in ("passed", "failed", "skipped"), qa_body
    assert len(qa_body.get("summary", "")) >= 20, qa_body
    assert isinstance(qa_body.get("files_checked"), list), qa_body
    assert "sandbox" in qa_body, qa_body

    judge_body = _artifact_body(client, judge_art["id"])
    assert isinstance(judge_body.get("score"), int), judge_body
    assert 0 <= judge_body["score"] <= 100, judge_body
    assert judge_body["decision"] in ("ready_for_approval", "needs_changes", "rejected"), judge_body
    assert isinstance(judge_body.get("dimension_scores"), list), judge_body
    assert len(judge_body["dimension_scores"]) >= 1, judge_body
    for item in judge_body["dimension_scores"]:
        assert isinstance(item.get("dimension"), str) and item["dimension"], item
        assert isinstance(item.get("score"), int), item
        assert 0 <= item["score"] <= 5, item
        assert len(item.get("rationale", "")) >= 20, item
    assert len(judge_body.get("recommendation", "")) >= 50, judge_body
