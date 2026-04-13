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
from typing import Any

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
DEV_SANDBOX_MAX_ATTEMPTS = max(1, int(os.environ.get("DEV_SANDBOX_MAX_ATTEMPTS", "2")))

# Per-agent provider config — falls back to shared PM_ vars when unset
DEV_JR_PROVIDER     = os.environ.get("DEV_JR_PROVIDER", "").strip().lower() or PM_LLM_PROVIDER
DEV_JR_BASE_URL     = os.environ.get("DEV_JR_BASE_URL", "").strip()
DEV_JR_MODEL        = os.environ.get("DEV_JR_MODEL",    "").strip() or PM_MODEL
DEV_JR_API_KEY      = os.environ.get("DEV_JR_API_KEY",  "").strip()
DEV_JR_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("DEV_JR_REQUEST_TIMEOUT_SECONDS", str(PM_REQUEST_TIMEOUT_SECONDS))
)

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
- File paths must be relative, no leading slash
- Do not return tests without the implementation files they exercise"""


def run(context: dict) -> list[dict]:
    """Generate implementation, push branch+commits, open PR. Return dev_output."""
    run_id = context.get("run_id", "unknown")
    project_id = context.get("project_id", "unknown")
    brief = context.get("brief", "No brief provided.")
    prior_artifacts = context.get("prior_artifacts", [])

    # Pull tasks from PM artifact
    tasks_json = _find_artifact(prior_artifacts, "tasks")
    tasks_summary = _summarise_tasks(tasks_json)
    review_json = _find_artifact(prior_artifacts, "review_findings")
    prior_sandbox_json = _find_artifact(prior_artifacts, "sandbox_result")
    tests_required = _tests_required(brief, tasks_summary)

    branch = f"ai-squad/run-{run_id[:8]}"
    user_message = _build_initial_user_message(
        project_id=project_id,
        brief=brief,
        tasks_summary=tasks_summary,
        review_json=review_json,
        sandbox_json=prior_sandbox_json,
        tests_required=tests_required,
    )

    data: dict[str, Any] = {}
    files: list[dict] = []
    commit_message = "feat: ai-squad implementation"
    pr_title = f"AI Squad: implementation for run {run_id[:8]}"
    pr_body = ""
    sandbox_result: dict[str, Any] = {"skipped": True, "exit_code": None, "job_id": None}
    attempts_used = 0

    for attempt in range(1, DEV_SANDBOX_MAX_ATTEMPTS + 1):
        attempts_used = attempt
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

        sandbox_result = _preflight_generated_files(files, tests_required=tests_required)
        if sandbox_result is None:
            # Run sandbox before committing — reviewer sees test evidence
            sandbox_result = _run_sandbox(files, tests_required=tests_required)
        if sandbox_result.get("skipped") or sandbox_result.get("exit_code") == 0:
            break
        if attempt >= DEV_SANDBOX_MAX_ATTEMPTS:
            break

        logger.info(
            "Sandbox failed on dev attempt %d/%d for run %s; requesting targeted repair",
            attempt,
            DEV_SANDBOX_MAX_ATTEMPTS,
            run_id,
        )
        user_message = _build_repair_user_message(
            project_id=project_id,
            brief=brief,
            tasks_summary=tasks_summary,
            review_json=review_json,
            tests_required=tests_required,
            files=files,
            sandbox_result=sandbox_result,
        )

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
        "sandbox_attempts": attempts_used,
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

def _run_sandbox(files: list[dict], *, tests_required: bool) -> dict:
    """Run pytest on the generated files via the control-api sandbox proxy.

    Non-fatal: returns a skipped result if the endpoint is unreachable.
    Detects test files automatically; falls back to plain python check if none found.
    """
    test_files = [
        f["path"] for f in files
        if f["path"].startswith("test_") or "/test_" in f["path"] or f["path"].endswith("_test.py")
    ]
    python_files = [f["path"] for f in files if f["path"].endswith(".py")]

    if test_files:
        command = ["pytest", "-q", "--tb=short"]
    elif tests_required:
        return {
            "job_id": None,
            "exit_code": 1,
            "stdout": "",
            "stderr": (
                "[dev-agent] No pytest-style test files were generated even though "
                "the brief or tasks require tests."
            ),
            "duration_seconds": 0.0,
            "timed_out": False,
            "error": "missing required tests",
        }
    elif python_files:
        command = ["python", "-m", "py_compile", *python_files]
    else:
        command = ["python", "-c", "print('no runnable files')"]

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


def _preflight_generated_files(files: list[dict], *, tests_required: bool) -> dict[str, Any] | None:
    if not tests_required:
        return None

    test_files = [f for f in files if _is_test_file(f.get("path", ""))]
    if not test_files:
        return None

    implementation_files = [f for f in files if _is_implementation_file(f.get("path", ""))]
    if not implementation_files:
        return _synthetic_sandbox_failure(
            error="missing implementation files",
            stderr=(
                "[dev-agent] Tests were generated without any non-test implementation files. "
                "Return the implementation and the tests together."
            ),
        )

    src_required = any(_references_src_package(str(f.get("content", ""))) for f in test_files)
    if src_required and not any(str(f.get("path", "")).startswith("src/") for f in implementation_files):
        return _synthetic_sandbox_failure(
            error="missing src implementation",
            stderr=(
                "[dev-agent] Tests import src.* but no file under src/ was generated. "
                "Return the implementation module alongside the tests."
            ),
        )

    return None


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


def _build_initial_user_message(
    *,
    project_id: str,
    brief: str,
    tasks_summary: str,
    review_json: str | None,
    sandbox_json: str | None,
    tests_required: bool,
) -> str:
    parts = [
        "/no_think",
        f"Project ID: {project_id}",
        f"Project brief:\n{brief}",
        f"Tasks to implement:\n{tasks_summary}",
    ]

    review_summary = _summarise_review_findings(review_json)
    if review_summary:
        parts.append(
            "This run is a rework. Fix the reviewer findings below instead of repeating the earlier defects:\n"
            f"{review_summary}"
        )

    sandbox_summary = _summarise_sandbox_failure(sandbox_json)
    if sandbox_summary:
        parts.append(
            "The previous implementation failed sandbox execution. Your output must fix these test failures:\n"
            f"{sandbox_summary}"
        )

    if tests_required:
        parts.append(
            "Pytest tests are required for this task. Include pytest-style test files and the implementation files they exercise, and make sure they pass together."
        )

    parts.append(
        "Return code and tests that pass together. If you include pytest tests, make sure they are consistent with the implementation."
    )
    return "\n\n".join(parts)


def _build_repair_user_message(
    *,
    project_id: str,
    brief: str,
    tasks_summary: str,
    review_json: str | None,
    tests_required: bool,
    files: list[dict],
    sandbox_result: dict[str, Any],
) -> str:
    parts = [
        "/no_think",
        "Your previous candidate failed sandbox execution. Repair the implementation and return a full replacement JSON payload.",
        f"Project ID: {project_id}",
        f"Project brief:\n{brief}",
        f"Tasks to implement:\n{tasks_summary}",
    ]

    review_summary = _summarise_review_findings(review_json)
    if review_summary:
        parts.append(f"Reviewer findings to address:\n{review_summary}")

    if tests_required:
        parts.append(
            "Pytest tests are mandatory here. Do not remove or omit tests to make the sandbox pass, and do not return tests without the implementation files they cover."
        )

    parts.append(f"Sandbox failure details:\n{_format_sandbox_result_for_prompt(sandbox_result)}")
    parts.append(f"Current candidate files:\n{_render_files_for_prompt(files)}")
    parts.append(
        "Fix the failing behavior and keep the implementation bounded to the requested task. Return complete file contents for every file you want in the final change."
    )
    return "\n\n".join(parts)


def _summarise_review_findings(review_body: str | None) -> str:
    if not review_body:
        return ""
    try:
        data = json.loads(review_body)
    except Exception:
        return review_body[:1500]

    findings = data.get("findings") or []
    lines = []
    for idx, finding in enumerate(findings[:6], start=1):
        severity = str(finding.get("severity", "info")).upper()
        area = finding.get("area", "unknown")
        detail = str(finding.get("detail", "")).strip()
        if detail:
            lines.append(f"{idx}. [{severity}] {area}: {detail}")

    recommendation = str(data.get("recommendation", "")).strip()
    if recommendation:
        lines.append(f"Recommendation: {recommendation}")
    return "\n".join(lines)


def _summarise_sandbox_failure(sandbox_body: str | None) -> str:
    if not sandbox_body:
        return ""
    try:
        data = json.loads(sandbox_body)
    except Exception:
        return sandbox_body[:1500]
    return _format_sandbox_result_for_prompt(data)


def _format_sandbox_result_for_prompt(sandbox_result: dict[str, Any]) -> str:
    lines = [
        f"exit_code={sandbox_result.get('exit_code')}",
        f"timed_out={sandbox_result.get('timed_out')}",
    ]
    stdout = str(sandbox_result.get("stdout") or "").strip()
    stderr = str(sandbox_result.get("stderr") or "").strip()
    if stdout:
        lines.append(f"stdout:\n{stdout[:2000]}")
    if stderr:
        lines.append(f"stderr:\n{stderr[:2000]}")
    return "\n".join(lines)


def _render_files_for_prompt(files: list[dict], max_chars: int = 16000) -> str:
    rendered: list[str] = []
    used = 0
    for file_info in files:
        path = file_info.get("path", "<unknown>")
        content = str(file_info.get("content", ""))
        block = f"=== {path} ===\n{content}"
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = f"=== {path} ===\n{content[: max(0, remaining - len(path) - 16)]}\n[truncated]"
        rendered.append(block)
        used += len(block) + 2
    return "\n\n".join(rendered)


def _tests_required(brief: str, tasks_summary: str) -> bool:
    haystack = f"{brief}\n{tasks_summary}".lower()
    return "pytest" in haystack or "test" in haystack or "tests" in haystack


def _is_test_file(path: str) -> bool:
    return path.startswith("test_") or "/test_" in path or path.endswith("_test.py")


def _is_implementation_file(path: str) -> bool:
    return bool(path) and not _is_test_file(path)


def _references_src_package(content: str) -> bool:
    return "from src." in content or "import src." in content


def _synthetic_sandbox_failure(*, error: str, stderr: str) -> dict[str, Any]:
    return {
        "job_id": None,
        "exit_code": 1,
        "stdout": "",
        "stderr": stderr,
        "duration_seconds": 0.0,
        "timed_out": False,
        "error": error,
    }


def _resolve_dev_jr_url() -> str:
    if DEV_JR_BASE_URL:
        return DEV_JR_BASE_URL.rstrip("/")
    if DEV_JR_PROVIDER == "ollama":
        return OLLAMA_URL.rstrip("/")
    return _resolve_base_url()


def _call_model(user_message: str) -> str:
    provider = DEV_JR_PROVIDER
    base_url = _resolve_dev_jr_url()

    logger.info(
        "Dev agent calling provider=%s model=%s base_url=%s",
        provider, DEV_JR_MODEL, base_url,
    )

    with _local_model_call_lock(provider):
        if provider == "ollama":
            return _call_ollama(base_url, user_message)
        if provider in OPENAI_COMPAT_PROVIDERS:
            return _call_openai_compat(base_url, user_message)

    raise RuntimeError(
        f"Unsupported DEV_JR_PROVIDER for dev agent: {provider}"
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
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }
    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=DEV_JR_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
    except httpx.ReadTimeout as exc:
        raise RuntimeError(
            "Ollama call timed out for dev-jr "
            f"(model={DEV_JR_MODEL}, timeout={DEV_JR_REQUEST_TIMEOUT_SECONDS}s). "
            "This usually means generation is too slow or the Ollama runner is stuck. "
            "If `ollama ps` shows `Stopping...`, restart or unload the model before retrying."
        ) from exc
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
    api_key = DEV_JR_API_KEY or PM_API_KEY
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=DEV_JR_REQUEST_TIMEOUT_SECONDS,
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
