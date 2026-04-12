"""Dev agent (Jr Dev) — model-backed implementation step.

Reads the PM tasks artifact, calls the local model server to generate
implementation files, then creates a branch, commits the files, and
opens a PR via github-svc.

github-svc calls are non-fatal when the service is unconfigured — the
dev_output artifact is still produced with whatever succeeded.
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx

from app.agents.pm_agent import (
    PM_LLM_PROVIDER,
    PM_MODEL,
    PM_REQUEST_TIMEOUT_SECONDS,
    OPENAI_COMPAT_PROVIDERS,
    OLLAMA_URL,
    PM_API_KEY,
    _extract_response_content,
    _local_model_call_lock,
    _parse_json,
    _resolve_base_url,
)

logger = logging.getLogger(__name__)

GITHUB_SVC_URL      = os.environ.get("GITHUB_SVC_URL",      "http://github-svc:9000")
CONTROL_API_URL     = os.environ.get("CONTROL_API_URL",     "http://control-api:8000")
SANDBOX_TIMEOUT     = float(os.environ.get("SANDBOX_TIMEOUT", "60"))
# Override PM_MODEL for dev-jr specifically when set
DEV_JR_MODEL        = os.environ.get("DEV_JR_MODEL", "") or PM_MODEL

# ── Output contract ────────────────────────────────────────────────────────────

DEV_OUTPUT_REQUIRED = ["branch", "files_written", "github"]

# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a junior software developer agent. You receive a project brief and a
list of tasks produced by the PM agent. Your job is to write the implementation.

Respond with ONLY a valid JSON object — no markdown fences, no explanation
before or after the JSON. The JSON must have exactly these top-level keys:

  files           (array, ≥1 items) — each item has:
                    path    (string) repo-relative file path, e.g. "src/foo.py"
                    content (string) complete file content

  commit_message  (string) — conventional commit message, e.g. "feat: add X"

  pr_title        (string) — concise PR title

  pr_body         (string, ≥100 chars) — PR description covering what was
                    implemented and why, with a brief test summary

Rules:
- Write real, working code — no placeholders, no TODO stubs
- Keep the implementation bounded: address the tasks given, nothing more
- Do NOT write to .github/ paths
- File paths must be relative, no leading slash"""


def run(context: dict) -> list[dict]:
    """Generate implementation, push branch+commits, open PR. Return dev_output."""
    run_id = context.get("run_id", "unknown")
    project_id = context.get("project_id", "unknown")
    brief = context.get("brief", "No brief provided.")
    prior_artifacts = context.get("prior_artifacts", [])

    # Pull tasks from PM artifact
    tasks_json = _find_artifact(prior_artifacts, "tasks")
    tasks_summary = _summarise_tasks(tasks_json)

    user_message = (
        f"/no_think\n\n"
        f"Project ID: {project_id}\n\n"
        f"Project brief:\n{brief}\n\n"
        f"Tasks to implement:\n{tasks_summary}"
    )

    raw = _call_model(user_message)
    data = _parse_json(raw)

    files = data.get("files", [])
    if not files:
        raise RuntimeError(
            "Dev agent model returned no files. "
            f"Parsed keys: {list(data.keys())}. First 300 chars of raw: {raw[:300]}"
        )
    commit_message = data.get("commit_message", "feat: ai-squad implementation")
    pr_title = data.get("pr_title", f"AI Squad: implementation for run {run_id[:8]}")
    pr_body = data.get("pr_body", "")

    branch = f"ai-squad/run-{run_id[:8]}"

    # Run sandbox before committing — reviewer sees test evidence
    sandbox_result = _run_sandbox(files)

    github_result = _push_to_github(
        run_id=run_id,
        branch=branch,
        files=files,
        commit_message=commit_message,
        pr_title=pr_title,
        pr_body=pr_body,
    )

    dev_output = {
        "branch":         branch,
        "files_written":  [f["path"] for f in files],
        # Embed contents so reviewer can read the code
        "files":          files,
        "commit_message": commit_message,
        "github":         github_result,
        "sandbox": {
            "exit_code":        sandbox_result.get("exit_code"),
            "timed_out":        sandbox_result.get("timed_out"),
            "skipped":          sandbox_result.get("skipped", False),
        },
    }

    artifacts = [
        {
            "artifact_type": "dev_output",
            "name":          "dev_output.json",
            "body":          json.dumps(dev_output, indent=2),
        }
    ]

    if not sandbox_result.get("skipped"):
        artifacts.append({
            "artifact_type": "sandbox_result",
            "name":          "sandbox_result.json",
            "body":          json.dumps(sandbox_result, indent=2),
        })

    return artifacts


def validate(artifact_type: str, body: str) -> bool:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    if artifact_type == "dev_output":
        return all(k in data for k in DEV_OUTPUT_REQUIRED)
    if artifact_type == "sandbox_result":
        return "exit_code" in data and "job_id" in data
    return False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _run_sandbox(files: list[dict]) -> dict:
    """Run pytest on the generated files via the control-api sandbox proxy.

    Non-fatal: returns a skipped result if the endpoint is unreachable.
    Detects test files automatically; falls back to plain python check if none found.
    """
    has_tests = any(
        f["path"].startswith("test_") or "/test_" in f["path"] or f["path"].endswith("_test.py")
        for f in files
    )
    command = ["pytest", "-q", "--tb=short"] if has_tests else ["python", "-c", "print('no tests')"]

    try:
        resp = httpx.post(
            f"{CONTROL_API_URL}/api/v1/sandbox/execute",
            json={
                "files":   files,
                "command": command,
                "timeout": SANDBOX_TIMEOUT,
            },
            timeout=SANDBOX_TIMEOUT + 30,
        )
        if resp.status_code == 503:
            logger.info("Sandbox unavailable — skipping sandbox execution")
            return {"skipped": True, "exit_code": None, "job_id": None}
        resp.raise_for_status()
        result = resp.json()
        status = "PASSED" if result.get("exit_code") == 0 else "FAILED"
        logger.info(
            "Sandbox %s exit_code=%s duration=%.2fs",
            status, result.get("exit_code"), result.get("duration_seconds", 0),
        )
        return result
    except Exception as exc:
        logger.warning("Sandbox call failed (non-fatal): %s", exc)
        return {"skipped": True, "exit_code": None, "job_id": None, "error": str(exc)}


def _find_artifact(prior_artifacts: list[dict], artifact_type: str) -> str | None:
    """Return the body of the most recent artifact matching artifact_type."""
    for art in reversed(prior_artifacts):
        if art.get("artifact_type") == artifact_type:
            return art.get("body")
    return None


def _summarise_tasks(tasks_body: str | None) -> str:
    if not tasks_body:
        return "No tasks artifact found — implement based on the brief alone."
    try:
        data = json.loads(tasks_body)
        tasks = data.get("tasks", [])
        lines = []
        for i, t in enumerate(tasks, 1):
            ac = "; ".join(t.get("acceptance_criteria", []))
            lines.append(
                f"{i}. [{t.get('priority','?').upper()}] {t.get('title','?')} "
                f"(role: {t.get('role','?')}) — AC: {ac}"
            )
        return "\n".join(lines) if lines else "Empty tasks list."
    except Exception:
        return tasks_body[:1000]


def _call_model(user_message: str) -> str:
    provider = PM_LLM_PROVIDER
    base_url = _resolve_base_url()

    logger.info(
        "Dev agent calling provider=%s model=%s base_url=%s",
        provider,
        DEV_JR_MODEL,
        base_url,
    )

    with _local_model_call_lock(provider):
        if provider == "ollama":
            return _call_ollama(base_url, user_message)
        if provider in OPENAI_COMPAT_PROVIDERS:
            return _call_openai_compat(base_url, user_message)

    raise RuntimeError(
        f"Unsupported PM_LLM_PROVIDER for dev agent: {provider}"
    )


def _call_ollama(base_url: str, user_message: str) -> str:
    payload = {
        "model": DEV_JR_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "format": "json",
        "options": {"temperature": 0.2},
    }
    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=PM_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Ollama call failed: {exc}") from exc


def _call_openai_compat(base_url: str, user_message: str) -> str:
    payload = {
        "model": DEV_JR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if PM_API_KEY:
        headers["Authorization"] = f"Bearer {PM_API_KEY}"

    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=PM_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return _extract_response_content(response.json())
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.text
        except Exception:
            pass
        logger.error(
            "Dev agent model call failed status=%s body=%s",
            exc.response.status_code,
            body[:2000],
        )
        raise RuntimeError(
            f"Dev agent model call failed: {exc}; response: {body[:500]}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Dev agent model call failed: {exc}") from exc




def _push_to_github(
    run_id: str,
    branch: str,
    files: list[dict],
    commit_message: str,
    pr_title: str,
    pr_body: str,
) -> dict:
    """Create branch, commit files, open PR. Returns a dict of outcomes."""
    result: dict = {
        "branch_created": False,
        "commit_sha": None,
        "pr_url": None,
        "pr_number": None,
        "skipped": False,
        "error": None,
    }

    try:
        # 1. Create branch
        br = httpx.post(
            f"{GITHUB_SVC_URL}/api/v1/branches",
            json={"branch": branch, "base": "main"},
            timeout=15.0,
        )
        if br.status_code == 503:
            result["skipped"] = True
            logger.info("github-svc unconfigured — skipping GitHub ops")
            return result
        br.raise_for_status()
        result["branch_created"] = True
        logger.info("Dev agent created branch %s", branch)

        # 2. Commit files
        if files:
            co = httpx.post(
                f"{GITHUB_SVC_URL}/api/v1/commits",
                json={
                    "branch": branch,
                    "message": commit_message,
                    "files": files,
                },
                timeout=30.0,
            )
            co.raise_for_status()
            result["commit_sha"] = co.json().get("commit_sha")
            logger.info("Dev agent committed %d file(s) to %s", len(files), branch)

        # 3. Open PR
        pr = httpx.post(
            f"{GITHUB_SVC_URL}/api/v1/pulls",
            json={
                "title": pr_title,
                "body": pr_body,
                "head": branch,
                "base": "main",
            },
            timeout=15.0,
        )
        pr.raise_for_status()
        pr_data = pr.json()
        result["pr_url"] = pr_data.get("html_url")
        result["pr_number"] = pr_data.get("number")
        logger.info("Dev agent opened PR #%s: %s", result["pr_number"], result["pr_url"])

    except Exception as exc:
        logger.warning("Dev agent GitHub ops failed (non-fatal): %s", exc)
        result["error"] = str(exc)

    return result
