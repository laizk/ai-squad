"""P8 unit tests — ux_agent and devops_agent artifact contract validation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import ux_agent, devops_agent


def test_ux_validate_good():
    body = json.dumps({
        "concerns": ["No keyboard navigation on modal"],
        "severity": "medium",
        "recommendation": (
            "Ensure all interactive elements are reachable via keyboard. "
            "Add aria-labels to icon buttons and verify color contrast meets "
            "WCAG AA standards before shipping."
        ),
    })
    assert ux_agent.validate("ux_notes", body)


def test_ux_validate_bad_severity():
    body = json.dumps({"concerns": [], "severity": "critical", "recommendation": "x" * 80})
    assert not ux_agent.validate("ux_notes", body)


def test_ux_validate_wrong_artifact_type():
    body = json.dumps({"concerns": [], "severity": "low", "recommendation": "x" * 80})
    assert not ux_agent.validate("rubric_score", body)


def test_ux_validate_missing_key():
    body = json.dumps({"concerns": [], "severity": "low"})  # missing recommendation
    assert not ux_agent.validate("ux_notes", body)


def test_devops_validate_good():
    body = json.dumps({
        "changes_needed": ["Add PYTHONPATH to Dockerfile", "Update CI to run pytest"],
        "deployment_ready": False,
        "recommendation": (
            "Update the Dockerfile to set PYTHONPATH and add a CI step that runs "
            "the pytest suite before merging. Without these the pipeline will not "
            "catch regressions introduced during this iteration."
        ),
    })
    assert devops_agent.validate("ci_changes", body)


def test_devops_validate_no_changes():
    body = json.dumps({
        "changes_needed": [],
        "deployment_ready": True,
        "recommendation": "No infrastructure changes required. Standard CI pipeline will handle this deliverable without modifications.",
    })
    assert devops_agent.validate("ci_changes", body)


def test_devops_validate_wrong_artifact_type():
    body = json.dumps({"changes_needed": [], "deployment_ready": True, "recommendation": "x" * 80})
    assert not devops_agent.validate("rubric_score", body)


def test_devops_validate_deployment_ready_not_bool():
    body = json.dumps({"changes_needed": [], "deployment_ready": "yes", "recommendation": "x" * 80})
    assert not devops_agent.validate("ci_changes", body)
