from __future__ import annotations

from uuid import uuid4

import pytest


def _make_run_payload(project_id: str, workflow_type: str = "pm_planning") -> dict:
    return {
        "project_id": project_id,
        "workflow_type": workflow_type,
        "idempotency_key": f"test-{uuid4().hex}",
    }


@pytest.fixture
def project_id(client, project_payload):
    resp = client.post("/projects", json=project_payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestRunCreation:
    def test_create_pm_planning_run(self, client, project_id):
        payload = _make_run_payload(project_id, "pm_planning")
        resp = client.post("/runs", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["project_id"] == project_id
        assert data["workflow_type"] == "pm_planning"
        assert data["status"] == "running"
        assert data["idempotency_key"] == payload["idempotency_key"]
        # steps: 1 active (pm, pause_after=True) + 2 skipped (ux, devops)
        assert len(data["steps"]) == 3
        active = [s for s in data["steps"] if s["status"] != "skipped"]
        skipped = [s for s in data["steps"] if s["status"] == "skipped"]
        assert len(active) == 1
        assert active[0]["role"] == "pm"
        assert active[0]["pause_after"] is True
        assert len(skipped) == 2
        skipped_roles = {s["role"] for s in skipped}
        assert skipped_roles == {"ux", "devops"}

    def test_create_full_sequential_run(self, client, project_id):
        payload = _make_run_payload(project_id, "full_sequential")
        resp = client.post("/runs", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        active = [s for s in data["steps"] if s["status"] != "skipped"]
        assert len(active) == 5
        roles = [s["role"] for s in active]
        assert roles == ["pm", "dev-jr", "dev-sr", "qa", "judge"]
        assert active[0]["pause_after"] is True
        # all others should not pause
        for step in active[1:]:
            assert step["pause_after"] is False

    def test_idempotent_create_returns_same_run(self, client, project_id):
        key = f"idempotent-{uuid4().hex}"
        payload = {**_make_run_payload(project_id), "idempotency_key": key}
        r1 = client.post("/runs", json=payload)
        r2 = client.post("/runs", json=payload)
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]

    def test_invalid_workflow_type_rejected(self, client, project_id):
        payload = {**_make_run_payload(project_id), "workflow_type": "invalid_type"}
        resp = client.post("/runs", json=payload)
        assert resp.status_code == 422

    def test_unknown_project_returns_404(self, client):
        payload = _make_run_payload(str(uuid4()))
        resp = client.post("/runs", json=payload)
        assert resp.status_code == 404


class TestRunLifecycle:
    def test_get_run(self, client, project_id):
        payload = _make_run_payload(project_id)
        run_id = client.post("/runs", json=payload).json()["id"]
        resp = client.get(f"/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == run_id

    def test_list_runs_by_project(self, client, project_id):
        client.post("/runs", json=_make_run_payload(project_id))
        resp = client.get(f"/runs?project_id={project_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert all(r["project_id"] == project_id for r in data["items"])

    def test_pause_running_run(self, client, project_id):
        run_id = client.post("/runs", json=_make_run_payload(project_id)).json()["id"]
        resp = client.post(f"/runs/{run_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"
        assert resp.json()["paused_at"] is not None

    def test_resume_paused_run(self, client, project_id):
        run_id = client.post("/runs", json=_make_run_payload(project_id)).json()["id"]
        client.post(f"/runs/{run_id}/pause")
        resp = client.post(f"/runs/{run_id}/resume")
        assert resp.status_code == 200
        # pm_planning has only one step which was already running, so after resume
        # there are no more pending steps → should complete
        assert resp.json()["status"] in ("running", "completed")

    def test_cancel_run(self, client, project_id):
        run_id = client.post("/runs", json=_make_run_payload(project_id)).json()["id"]
        resp = client.post(f"/runs/{run_id}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["completed_at"] is not None
        pending = [s for s in data["steps"] if s["status"] == "pending"]
        assert len(pending) == 0

    def test_cannot_pause_non_running_run(self, client, project_id):
        run_id = client.post("/runs", json=_make_run_payload(project_id)).json()["id"]
        client.post(f"/runs/{run_id}/pause")
        resp = client.post(f"/runs/{run_id}/pause")
        assert resp.status_code == 400

    def test_cannot_cancel_completed_run(self, client, project_id):
        run_id = client.post("/runs", json=_make_run_payload(project_id)).json()["id"]
        client.post(f"/runs/{run_id}/cancel")
        resp = client.post(f"/runs/{run_id}/cancel")
        assert resp.status_code == 400

    def test_get_nonexistent_run_returns_404(self, client):
        resp = client.get(f"/runs/{uuid4()}")
        assert resp.status_code == 404
