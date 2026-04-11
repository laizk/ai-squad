from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    with httpx.Client(base_url=API_BASE_URL, timeout=10.0) as http:
        yield http


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
