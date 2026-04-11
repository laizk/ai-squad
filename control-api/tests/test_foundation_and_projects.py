from __future__ import annotations

import httpx


def test_health_endpoint_reports_live_dependencies(client: httpx.Client) -> None:
    response = client.get("/health")
    response.raise_for_status()

    body = response.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "ok"
    assert body["redis"] == "ok"
    assert body["phase"] == "P0"


def test_bootstrap_endpoint_reports_schema_marker(client: httpx.Client) -> None:
    response = client.get("/bootstrap")
    response.raise_for_status()

    body = response.json()
    assert body["postgres"] == "ok"
    assert body["postgres_detail"] == "schema_version=p0-bootstrap"


def test_project_create_update_and_revision_history(
    client: httpx.Client, project_payload: dict[str, object]
) -> None:
    create_response = client.post("/projects", json=project_payload)
    create_response.raise_for_status()
    created = create_response.json()

    assert created["name"] == project_payload["name"]
    assert created["current_version"] == 1
    assert created["status"] == "active"
    assert created["metadata"] == {}

    project_id = created["id"]

    get_response = client.get(f"/projects/{project_id}")
    get_response.raise_for_status()
    fetched = get_response.json()
    assert fetched["id"] == project_id
    assert fetched["current_version"] == 1

    update_payload = {
        "description": "Updated by the integration suite to verify revision increments.",
        "status": "paused",
        "reason": {
            "category": "scope_change",
            "detail": "Updating the integration-test project to confirm before-after revision snapshots.",
            "references": [f"project:{project_id}"],
        },
    }
    update_response = client.patch(f"/projects/{project_id}", json=update_payload)
    update_response.raise_for_status()
    updated = update_response.json()

    assert updated["id"] == project_id
    assert updated["current_version"] == 2
    assert updated["status"] == "paused"
    assert updated["description"] == update_payload["description"]

    revisions_response = client.get(f"/revisions/project/{project_id}")
    revisions_response.raise_for_status()
    revisions = revisions_response.json()["revisions"]

    assert len(revisions) == 2
    assert revisions[0]["revision_number"] == 1
    assert revisions[0]["before_snapshot"] is None
    assert revisions[0]["after_snapshot"]["current_version"] == 1
    assert revisions[1]["revision_number"] == 2
    assert revisions[1]["before_snapshot"]["status"] == "active"
    assert revisions[1]["after_snapshot"]["status"] == "paused"
    assert revisions[1]["after_snapshot"]["current_version"] == 2


def test_project_update_with_no_changes_returns_400(
    client: httpx.Client, project_payload: dict[str, object]
) -> None:
    create_response = client.post("/projects", json=project_payload)
    create_response.raise_for_status()
    created = create_response.json()

    no_change_payload = {
        "reason": {
            "category": "other",
            "detail": "Attempting a no-op update to verify the API rejects unchanged project mutations.",
            "references": [f"project:{created['id']}"],
        }
    }
    response = client.patch(f"/projects/{created['id']}", json=no_change_payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "No project fields changed"
