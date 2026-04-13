from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
TEST_RUN_KEY_PREFIXES = (
    "test-",
    "idempotent-",
    "p4-test-",
    "p5-test-",
    "p5-reviewer-",
    "p6-qa-judge-",
    "p6-approval-evidence-",
    "p8-",
    "p10-test-",
    "p10-idempotent-",
    "p10-pause-cancel-",
    "p10-backoff-dedup-",
    "key-a-",
    "key-b-",
)


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    with httpx.Client(base_url=API_BASE_URL, timeout=10.0) as http:
        yield http


def _cancel_non_terminal_test_runs() -> None:
    try:
        with httpx.Client(base_url=API_BASE_URL, timeout=10.0) as cleanup_client:
            response = cleanup_client.get("/runs?per_page=200")
            response.raise_for_status()

            for run in response.json().get("items", []):
                key = run.get("idempotency_key") or ""
                if not key.startswith(TEST_RUN_KEY_PREFIXES):
                    continue
                if run.get("status") not in {"running", "paused"}:
                    continue
                try:
                    cleanup_client.post(f"/runs/{run['id']}/cancel")
                except Exception:
                    pass
    except Exception:
        return


@pytest.fixture(autouse=True)
def cancel_created_runs() -> None:
    """Keep integration-test runs from accumulating in the shared worker queue."""
    _cancel_non_terminal_test_runs()
    yield
    _cancel_non_terminal_test_runs()


@pytest.fixture
def project_payload() -> dict[str, object]:
    suffix = uuid4().hex[:8]
    return {
        "name": f"Integration Project {suffix}",
        "description": "Project created by integration tests against the live control API.",
        "github_org": "ai-squad",
        "github_repo": "integration-tests",
        "reason": {
            "category": "initial_creation",
            "detail": "Creating an integration-test project to verify project CRUD and revision history.",
            "references": [f"test:{suffix}"],
        },
    }


@pytest.fixture
def team_member_payload() -> dict[str, object]:
    suffix = uuid4().hex[:8]
    return {
        "name": f"pm-{suffix}",
        "role": "pm",
        "display_name": f"PM {suffix}",
        "description": "Team member created by integration tests against the live control API.",
        "skills": ["planning", "requirements"],
        "provider": "ollama",
        "model": "qwen2.5-coder:14b",
        "reason": {
            "category": "initial_creation",
            "detail": "Creating an integration-test team member to verify CRUD and revision behavior.",
            "references": [f"test:{suffix}"],
        },
    }


@pytest.fixture
def milestone_payload() -> dict[str, object]:
    suffix = uuid4().hex[:8]
    return {
        "title": f"Milestone {suffix}",
        "description": "Milestone created by integration tests against the live control API.",
        "status": "planned",
        "display_order": 1,
        "acceptance_criteria": [
            "The planning graph persists milestones in the control API.",
            "Milestone changes create append-only revision history entries.",
        ],
        "due_date": "2026-05-15",
        "reason": {
            "category": "initial_creation",
            "detail": "Creating an integration-test milestone to verify planning CRUD and revision behavior.",
            "references": [f"test:{suffix}"],
        },
    }


@pytest.fixture
def task_payload() -> dict[str, object]:
    suffix = uuid4().hex[:8]
    return {
        "title": f"Task {suffix}",
        "description": "Task created by integration tests against the live control API.",
        "status": "backlog",
        "priority": "high",
        "assigned_role": "dev-jr",
        "acceptance_criteria": [
            "The task is stored under the milestone.",
            "Task updates create revision history with before and after snapshots.",
        ],
        "display_order": 1,
        "reason": {
            "category": "initial_creation",
            "detail": "Creating an integration-test task to verify nested planning CRUD and revisions.",
            "references": [f"test:{suffix}"],
        },
    }
