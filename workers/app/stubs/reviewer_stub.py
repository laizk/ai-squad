"""Deterministic Sr Reviewer stub agent."""
from __future__ import annotations

import json


FINDINGS_CONTRACT = {
    "required": ["verdict", "findings", "recommendation"],
}


def run(context: dict) -> list[dict]:
    findings_body = json.dumps({
        "verdict": "approved",
        "findings": [
            {
                "severity": "info",
                "area": "code structure",
                "detail": (
                    "Stub reviewer finding: implementation follows the existing "
                    "router pattern consistently. No structural issues detected."
                ),
            },
            {
                "severity": "info",
                "area": "test coverage",
                "detail": (
                    "Stub reviewer finding: integration tests exercise the golden "
                    "path and key error cases. Coverage is acceptable for P3."
                ),
            },
        ],
        "recommendation": (
            "Approved. The stub reviewer confirms the implementation structure is "
            "sound and tests provide sufficient evidence for this phase."
        ),
    }, indent=2)

    return [
        {
            "artifact_type": "review_findings",
            "name": "reviewer_findings_stub.json",
            "body": findings_body,
        }
    ]


def validate(artifact_type: str, body: str) -> bool:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False

    if artifact_type == "review_findings":
        return all(k in data for k in FINDINGS_CONTRACT["required"])
    return False
