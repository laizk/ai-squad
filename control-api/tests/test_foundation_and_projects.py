from __future__ import annotations

import httpx


def test_health_endpoint_reports_live_dependencies(client: httpx.Client) -> None:
    response = client.get("/health")
    response.raise_for_status()

    body = response.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "ok"
    assert body["redis"] == "ok"
    assert body["phase"] in ("P0", "P1", "P2", "P3")


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


def test_team_member_create_update_and_revisions(
    client: httpx.Client, team_member_payload: dict[str, object]
) -> None:
    create_response = client.post("/team-members", json=team_member_payload)
    create_response.raise_for_status()
    created = create_response.json()

    assert created["name"] == team_member_payload["name"]
    assert created["role"] == "pm"
    assert created["current_version"] == 1
    assert created["is_active"] is True

    member_id = created["id"]

    list_response = client.get("/team-members")
    list_response.raise_for_status()
    items = list_response.json()["items"]
    assert any(item["id"] == member_id for item in items)

    update_payload = {
        "model": "mistral-nemo:12b",
        "is_active": False,
        "reason": {
            "category": "fix",
            "detail": "Updating the integration-test team member to verify version increments and revisions.",
            "references": [f"team_member:{member_id}"],
        },
    }
    update_response = client.patch(f"/team-members/{member_id}", json=update_payload)
    update_response.raise_for_status()
    updated = update_response.json()

    assert updated["current_version"] == 2
    assert updated["model"] == "mistral-nemo:12b"
    assert updated["is_active"] is False

    revisions_response = client.get(f"/team-members/{member_id}/revisions")
    revisions_response.raise_for_status()
    revisions = revisions_response.json()["revisions"]

    assert len(revisions) == 2
    assert revisions[0]["revision_number"] == 1
    assert revisions[1]["revision_number"] == 2
    assert revisions[1]["before_snapshot"]["is_active"] is True
    assert revisions[1]["after_snapshot"]["is_active"] is False


def test_project_assignment_create_disable_and_revisions(
    client: httpx.Client,
    project_payload: dict[str, object],
    team_member_payload: dict[str, object],
) -> None:
    project_response = client.post("/projects", json=project_payload)
    project_response.raise_for_status()
    project = project_response.json()

    member_response = client.post("/team-members", json=team_member_payload)
    member_response.raise_for_status()
    member = member_response.json()

    assignment_payload = {
        "team_member_id": member["id"],
        "model_override": "mistral-nemo:12b",
        "provider_override": "ollama",
        "reason": {
            "category": "initial_creation",
            "detail": "Assigning the integration-test team member to the integration-test project.",
            "references": [f"project:{project['id']}", f"team_member:{member['id']}"],
        },
    }
    assignment_response = client.post(f"/projects/{project['id']}/team", json=assignment_payload)
    assignment_response.raise_for_status()
    assignment = assignment_response.json()

    assert assignment["project_id"] == project["id"]
    assert assignment["team_member_id"] == member["id"]
    assert assignment["current_version"] == 1
    assert assignment["is_enabled"] is True

    team_list_response = client.get(f"/projects/{project['id']}/team")
    team_list_response.raise_for_status()
    team_items = team_list_response.json()["items"]
    assert any(item["id"] == assignment["id"] for item in team_items)

    disable_payload = {
        "is_enabled": False,
        "disable_reason": "Disabled by integration test.",
        "reason": {
            "category": "scope_change",
            "detail": "Disabling the integration-test assignment to verify lifecycle and revision behavior.",
            "references": [f"project_assignment:{assignment['id']}"],
        },
    }
    disable_response = client.patch(
        f"/projects/{project['id']}/team/{member['id']}",
        json=disable_payload,
    )
    disable_response.raise_for_status()
    disabled = disable_response.json()

    assert disabled["current_version"] == 2
    assert disabled["is_enabled"] is False
    assert disabled["disabled_at"] is not None
    assert disabled["disable_reason"] == "Disabled by integration test."

    revisions_response = client.get(f"/revisions/project_assignment/{assignment['id']}")
    revisions_response.raise_for_status()
    revisions = revisions_response.json()["revisions"]

    assert len(revisions) == 2
    assert revisions[0]["revision_number"] == 1
    assert revisions[1]["revision_number"] == 2
    assert revisions[1]["before_snapshot"]["is_enabled"] is True
    assert revisions[1]["after_snapshot"]["is_enabled"] is False


def test_milestone_create_update_list_and_revisions(
    client: httpx.Client,
    project_payload: dict[str, object],
    milestone_payload: dict[str, object],
) -> None:
    project_response = client.post("/projects", json=project_payload)
    project_response.raise_for_status()
    project = project_response.json()

    create_response = client.post(f"/projects/{project['id']}/milestones", json=milestone_payload)
    create_response.raise_for_status()
    milestone = create_response.json()

    assert milestone["project_id"] == project["id"]
    assert milestone["title"] == milestone_payload["title"]
    assert milestone["current_version"] == 1
    assert milestone["status"] == "planned"

    list_response = client.get(f"/projects/{project['id']}/milestones")
    list_response.raise_for_status()
    items = list_response.json()["items"]
    assert any(item["id"] == milestone["id"] for item in items)

    get_response = client.get(f"/milestones/{milestone['id']}")
    get_response.raise_for_status()
    fetched = get_response.json()
    assert fetched["id"] == milestone["id"]
    assert fetched["acceptance_criteria"] == milestone_payload["acceptance_criteria"]

    update_payload = {
        "status": "review",
        "display_order": 2,
        "reason": {
            "category": "scope_change",
            "detail": "Updating the integration-test milestone to verify version increments and milestone revisions.",
            "references": [f"milestone:{milestone['id']}"],
        },
    }
    update_response = client.patch(f"/milestones/{milestone['id']}", json=update_payload)
    update_response.raise_for_status()
    updated = update_response.json()

    assert updated["current_version"] == 2
    assert updated["status"] == "review"
    assert updated["display_order"] == 2

    revisions_response = client.get(f"/revisions/milestone/{milestone['id']}")
    revisions_response.raise_for_status()
    revisions = revisions_response.json()["revisions"]

    assert len(revisions) == 2
    assert revisions[0]["revision_number"] == 1
    assert revisions[1]["revision_number"] == 2
    assert revisions[1]["before_snapshot"]["status"] == "planned"
    assert revisions[1]["after_snapshot"]["status"] == "review"


def test_task_create_update_list_and_revisions(
    client: httpx.Client,
    project_payload: dict[str, object],
    milestone_payload: dict[str, object],
    task_payload: dict[str, object],
) -> None:
    project_response = client.post("/projects", json=project_payload)
    project_response.raise_for_status()
    project = project_response.json()

    milestone_response = client.post(f"/projects/{project['id']}/milestones", json=milestone_payload)
    milestone_response.raise_for_status()
    milestone = milestone_response.json()

    create_response = client.post(f"/milestones/{milestone['id']}/tasks", json=task_payload)
    create_response.raise_for_status()
    task = create_response.json()

    assert task["project_id"] == project["id"]
    assert task["milestone_id"] == milestone["id"]
    assert task["priority"] == "high"
    assert task["assigned_role"] == "dev-jr"
    assert task["current_version"] == 1

    list_response = client.get(f"/milestones/{milestone['id']}/tasks")
    list_response.raise_for_status()
    items = list_response.json()["items"]
    assert any(item["id"] == task["id"] for item in items)

    get_response = client.get(f"/tasks/{task['id']}")
    get_response.raise_for_status()
    fetched = get_response.json()
    assert fetched["id"] == task["id"]
    assert fetched["status"] == "backlog"

    update_payload = {
        "status": "in_progress",
        "priority": "critical",
        "assigned_role": "dev-sr",
        "reason": {
            "category": "fix",
            "detail": "Updating the integration-test task to verify nested task revisions and state changes.",
            "references": [f"task:{task['id']}"],
        },
    }
    update_response = client.patch(f"/tasks/{task['id']}", json=update_payload)
    update_response.raise_for_status()
    updated = update_response.json()

    assert updated["current_version"] == 2
    assert updated["status"] == "in_progress"
    assert updated["priority"] == "critical"
    assert updated["assigned_role"] == "dev-sr"

    revisions_response = client.get(f"/revisions/task/{task['id']}")
    revisions_response.raise_for_status()
    revisions = revisions_response.json()["revisions"]

    assert len(revisions) == 2
    assert revisions[0]["revision_number"] == 1
    assert revisions[1]["revision_number"] == 2
    assert revisions[1]["before_snapshot"]["status"] == "backlog"
    assert revisions[1]["after_snapshot"]["status"] == "in_progress"
