from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import reviewer_agent


def test_build_user_message_includes_extended_review_context():
    spec_json = json.dumps(
        {
            "brief_summary": "Build a minimal Python URL shortener with tests and a simple function API.",
            "milestones": [
                {
                    "title": "Core implementation",
                    "acceptance_criteria": [
                        "Short codes are generated deterministically.",
                        "Mappings are stored in memory.",
                    ],
                }
            ],
        }
    )
    tasks_json = json.dumps(
        {
            "tasks": [
                {
                    "title": "Implement shortening logic",
                    "role": "dev-jr",
                    "priority": "high",
                    "acceptance_criteria": [
                        "Create short codes for long URLs.",
                        "Resolve short codes back to original URLs.",
                    ],
                }
            ]
        }
    )
    decision_json = json.dumps(
        {
            "decision_log": [
                {
                    "decision": "Use in-memory storage",
                    "reason": "The brief explicitly avoids persistence.",
                }
            ]
        }
    )
    review_json = json.dumps(
        {
            "verdict": "changes_requested",
            "findings": [
                {
                    "severity": "warning",
                    "area": "test coverage",
                    "detail": "Missing coverage for duplicate URL shortening and unknown short codes.",
                }
            ],
            "recommendation": "Add the missing tests and verify lookup edge cases before approval.",
        }
    )
    dev_output = json.dumps(
        {
            "branch": "ai-squad/run-12345678",
            "commit_message": "feat: add url shortener",
            "files_written": ["shortener.py", "test_shortener.py"],
            "files": [
                {
                    "path": "shortener.py",
                    "content": "def shorten(url):\n    return 'abc123'\n",
                },
                {
                    "path": "test_shortener.py",
                    "content": "def test_shorten():\n    assert shorten(\"https://example.com\") == \"abc123\"\n",
                },
            ],
            "github": {
                "commit_sha": "abc123def456",
                "pr_number": 42,
            },
        }
    )
    sandbox_json = json.dumps(
        {
            "exit_code": 0,
            "duration_seconds": 1.2,
            "stdout": "2 passed",
            "stderr": "",
        }
    )

    message = reviewer_agent._build_user_message(
        brief="Build a minimal Python URL shortener with tests.",
        spec_json=spec_json,
        tasks_json=tasks_json,
        decision_json=decision_json,
        review_json=review_json,
        dev_output=dev_output,
        sandbox_json=sandbox_json,
    )

    assert "PM spec:" in message
    assert "PM decision log:" in message
    assert "Previous review context:" in message
    assert "This is a re-review after requested changes." in message
    assert "Files written (2): shortener.py, test_shortener.py" in message
    assert "--- shortener.py ---" in message
    assert "Sandbox execution (PASSED):" in message
    assert "Review checklist:" in message
