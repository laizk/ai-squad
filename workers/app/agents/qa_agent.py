"""QA agent — sandbox-backed test execution for generated code."""
from __future__ import annotations

import json
import logging

from app.agents.dev_agent import _run_sandbox

logger = logging.getLogger(__name__)

TEST_RESULTS_REQUIRED = ["status", "summary", "files_checked"]


def run(context: dict) -> list[dict]:
    prior_artifacts = context.get("prior_artifacts", [])
    dev_output = _find_artifact(prior_artifacts, "dev_output")

    files = _extract_files(dev_output)
    if not files:
        return [_test_results_artifact(
            status="failed",
            summary="QA could not run because the developer output did not include any files to validate.",
            files_checked=[],
            sandbox_result=None,
        )]

    test_files = [f["path"] for f in files if _is_test_file(f.get("path", ""))]
    if not test_files:
        return [_test_results_artifact(
            status="failed",
            summary="QA failed because the developer output did not include any pytest-style test files.",
            files_checked=[f.get("path", "") for f in files],
            sandbox_result=None,
        )]

    sandbox_result = _run_sandbox(files)
    status = "passed" if sandbox_result.get("exit_code") == 0 else "failed"
    if sandbox_result.get("skipped"):
        status = "skipped"

    summary = _build_summary(sandbox_result, test_files)
    return [_test_results_artifact(
        status=status,
        summary=summary,
        files_checked=[f.get("path", "") for f in files],
        sandbox_result=sandbox_result,
    )]


def validate(artifact_type: str, body: str) -> bool:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False

    if artifact_type != "test_results":
        return False

    if not all(key in data for key in TEST_RESULTS_REQUIRED):
        return False

    return data.get("status") in {"passed", "failed", "skipped"}


def _find_artifact(prior_artifacts: list[dict], artifact_type: str) -> str | None:
    for art in reversed(prior_artifacts):
        if art.get("artifact_type") == artifact_type:
            return art.get("body")
    return None


def _extract_files(dev_output_body: str | None) -> list[dict]:
    if not dev_output_body:
        return []
    try:
        payload = json.loads(dev_output_body)
    except json.JSONDecodeError:
        logger.warning("QA agent could not parse dev_output JSON")
        return []
    files = payload.get("files", [])
    return files if isinstance(files, list) else []


def _is_test_file(path: str) -> bool:
    return path.startswith("test_") or "/test_" in path or path.endswith("_test.py")


def _build_summary(sandbox_result: dict, test_files: list[str]) -> str:
    if sandbox_result.get("skipped"):
        return (
            "QA could not execute sandbox-backed tests because the sandbox endpoint "
            "was unavailable for this run."
        )

    exit_code = sandbox_result.get("exit_code")
    duration = sandbox_result.get("duration_seconds")
    return (
        f"Executed pytest against {len(test_files)} test file(s). "
        f"exit_code={exit_code}, duration_seconds={duration}."
    )


def _test_results_artifact(
    *,
    status: str,
    summary: str,
    files_checked: list[str],
    sandbox_result: dict | None,
) -> dict:
    body = {
        "status": status,
        "summary": summary,
        "files_checked": files_checked,
        "sandbox": sandbox_result,
    }
    return {
        "artifact_type": "test_results",
        "name": "qa_test_results.json",
        "body": json.dumps(body, indent=2),
    }
