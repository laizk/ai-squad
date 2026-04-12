"""Eval scorer — checks agent output against golden task expected signals.

Returns a scores dict:
  {
    "overall": int (0-100),
    "pass": bool,
    "dimensions": [
      {"name": str, "passed": bool, "detail": str}
    ]
  }

The scorer is intentionally rule-based (not another LLM call) so results
are deterministic and reproducible across eval runs.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def score_output(
    artifacts: list[dict[str, Any]],
    expected_signals: dict[str, Any],
) -> dict[str, Any]:
    dimensions = []

    # 1. Required artifact types present
    required_types = expected_signals.get("required_artifact_types", [])
    if required_types:
        produced_types = {a.get("artifact_type") for a in artifacts}
        missing = [t for t in required_types if t not in produced_types]
        dimensions.append({
            "name": "required_artifact_types",
            "passed": len(missing) == 0,
            "detail": (
                f"All required types present: {required_types}"
                if not missing
                else f"Missing artifact types: {missing}"
            ),
        })

    # 2. Minimum task count (for PM evals)
    min_task_count = expected_signals.get("min_task_count")
    if min_task_count is not None:
        tasks_art = _find_artifact(artifacts, "tasks")
        count = 0
        if tasks_art:
            try:
                data = json.loads(tasks_art)
                tasks_list = data.get("tasks", data) if isinstance(data, dict) else data
                count = len(tasks_list) if isinstance(tasks_list, list) else 0
            except (json.JSONDecodeError, TypeError):
                pass
        dimensions.append({
            "name": "min_task_count",
            "passed": count >= min_task_count,
            "detail": f"Tasks found: {count} (required ≥{min_task_count})",
        })

    # 3. Tasks mention required keywords (for PM evals)
    must_mention = expected_signals.get("tasks_must_mention", [])
    if must_mention:
        tasks_art = _find_artifact(artifacts, "tasks")
        body = (tasks_art or "").lower()
        missing_kw = [kw for kw in must_mention if kw.lower() not in body]
        dimensions.append({
            "name": "tasks_keyword_coverage",
            "passed": len(missing_kw) == 0,
            "detail": (
                f"All keywords present: {must_mention}"
                if not missing_kw
                else f"Missing keywords: {missing_kw}"
            ),
        })

    # 4. dev_output has files (for dev-jr evals)
    if expected_signals.get("dev_output_must_have_files"):
        dev_art = _find_artifact(artifacts, "dev_output")
        has_files = False
        if dev_art:
            try:
                data = json.loads(dev_art)
                has_files = isinstance(data.get("files"), list) and len(data["files"]) > 0
            except (json.JSONDecodeError, TypeError):
                pass
        dimensions.append({
            "name": "dev_output_has_files",
            "passed": has_files,
            "detail": "dev_output contains at least one file" if has_files else "dev_output missing files list",
        })

    # 5. dev_output has a test file (for dev-jr evals)
    if expected_signals.get("dev_output_must_have_test_file"):
        dev_art = _find_artifact(artifacts, "dev_output")
        has_test = False
        if dev_art:
            try:
                data = json.loads(dev_art)
                files = data.get("files", [])
                has_test = any(
                    f.get("path", "").startswith("test_")
                    or "/test_" in f.get("path", "")
                    or f.get("path", "").endswith("_test.py")
                    for f in files
                )
            except (json.JSONDecodeError, TypeError):
                pass
        dimensions.append({
            "name": "dev_output_has_test_file",
            "passed": has_test,
            "detail": "dev_output includes a pytest test file" if has_test else "dev_output missing test file",
        })

    passed_count = sum(1 for d in dimensions if d["passed"])
    total = len(dimensions)
    overall = int((passed_count / total) * 100) if total > 0 else 0
    passed = overall == 100

    return {
        "overall": overall,
        "pass": passed,
        "dimensions": dimensions,
    }


def _find_artifact(artifacts: list[dict], artifact_type: str) -> str | None:
    for art in reversed(artifacts):
        if art.get("artifact_type") == artifact_type:
            return art.get("body")
    return None
