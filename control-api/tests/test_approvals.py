from __future__ import annotations

import httpx
from uuid import uuid4


def _approval_payload(entity_type: str, entity_id: str, revision_number: int, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "approved_revision_number": revision_number,
        "status": "approved",
        "comment": "Review evidence is sufficient and the revision is acceptable for the current planning state.",
        "override_used": False,
        "override_reason": None,
        "evidence": [
            {
                "evidence_type": "github_link",
                "external_url": "https://github.com/example/repo/issues/12",
                "description": "Representative linked evidence for the approval decision.",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_approval_create_detail_list_and_stale_invalidation(
    client: httpx.Client,
    project_payload: dict[str, object],
    milestone_payload: dict[str, object],
) -> None:
    project_response = client.post("/projects", json=project_payload)
    project_response.raise_for_status()
    project = project_response.json()

    milestone_response = client.post(f"/projects/{project['id']}/milestones", json=milestone_payload)
    milestone_response.raise_for_status()
    milestone = milestone_response.json()

    approval_response = client.post(
        "/approvals",
        json=_approval_payload("milestone", milestone["id"], 1),
    )
    approval_response.raise_for_status()
    approval = approval_response.json()

    assert approval["entity_type"] == "milestone"
    assert approval["entity_id"] == milestone["id"]
    assert approval["approved_revision_number"] == 1
    assert approval["status"] == "approved"
    assert approval["is_stale"] is False
    assert approval["override_used"] is False
    assert len(approval["evidence"]) == 1
    assert approval["evidence"][0]["evidence_type"] == "github_link"

    approval_id = approval["id"]

    detail_response = client.get(f"/approvals/{approval_id}")
    detail_response.raise_for_status()
    detail = detail_response.json()
    assert detail["id"] == approval_id
    assert detail["comment"] == approval["comment"]
    assert detail["evidence"][0]["external_url"] == "https://github.com/example/repo/issues/12"

    list_response = client.get(f"/entities/milestone/{milestone['id']}/approvals")
    list_response.raise_for_status()
    listed = list_response.json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == approval_id

    update_payload = {
        "status": "review",
        "reason": {
            "category": "scope_change",
            "detail": "Updating the approved milestone to prove older decisions become stale after later edits.",
            "references": [f"milestone:{milestone['id']}"],
        },
    }
    update_response = client.patch(f"/milestones/{milestone['id']}", json=update_payload)
    update_response.raise_for_status()
    assert update_response.json()["current_version"] == 2

    stale_response = client.get(f"/approvals/{approval_id}")
    stale_response.raise_for_status()
    stale = stale_response.json()
    assert stale["is_stale"] is True
    assert stale["stale_at"] is not None


def test_stale_revision_approval_requires_override(
    client: httpx.Client,
    project_payload: dict[str, object],
    milestone_payload: dict[str, object],
) -> None:
    project_response = client.post("/projects", json=project_payload)
    project_response.raise_for_status()
    project = project_response.json()

    milestone_response = client.post(f"/projects/{project['id']}/milestones", json=milestone_payload)
    milestone_response.raise_for_status()
    milestone = milestone_response.json()

    update_payload = {
        "status": "review",
        "reason": {
            "category": "scope_change",
            "detail": "Advancing the milestone so the earlier revision becomes stale before the approval is recorded.",
            "references": [f"milestone:{milestone['id']}"],
        },
    }
    update_response = client.patch(f"/milestones/{milestone['id']}", json=update_payload)
    update_response.raise_for_status()
    assert update_response.json()["current_version"] == 2

    stale_response = client.post(
        "/approvals",
        json=_approval_payload("milestone", milestone["id"], 1),
    )
    assert stale_response.status_code == 400
    assert stale_response.json()["detail"] == (
        "Approval targets a stale revision; set override_used with override_reason to record it."
    )

    override_response = client.post(
        "/approvals",
        json=_approval_payload(
            "milestone",
            milestone["id"],
            1,
            override_used=True,
            override_reason="Recording a human override for an earlier approved milestone revision during validation.",
        ),
    )
    override_response.raise_for_status()
    override_approval = override_response.json()

    assert override_approval["override_used"] is True
    assert override_approval["override_reason"] is not None
    assert override_approval["is_stale"] is True


def test_approval_rejects_unknown_artifact_evidence(
    client: httpx.Client,
    project_payload: dict[str, object],
) -> None:
    project_response = client.post("/projects", json=project_payload)
    project_response.raise_for_status()
    project = project_response.json()

    response = client.post(
        "/approvals",
        json=_approval_payload(
            "project",
            project["id"],
            1,
            evidence=[
                {
                    "evidence_type": "artifact",
                    "artifact_id": str(uuid4()),
                    "description": "This approval intentionally references a missing artifact to verify validation.",
                }
            ],
        ),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"
