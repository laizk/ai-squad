"""Real PM agent — local model-server-backed planning step.

Replaces the PM stub with a model call that produces:
- spec artifact:        brief_summary, milestones, rationale
- tasks artifact:       tasks with roles, priorities, and AC
- decision_log artifact: design decisions and github issue links

GitHub issue creation is delegated to github-svc. If github-svc is
unavailable or unconfigured the agent continues without issues.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PM_LLM_PROVIDER = os.environ.get("PM_LLM_PROVIDER", "lmstudio").strip().lower()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
PM_BASE_URL = os.environ.get("PM_BASE_URL", "").strip()
PM_API_KEY = os.environ.get("PM_API_KEY", "").strip()
PM_MODEL = os.environ.get("PM_MODEL", "qwen2.5-coder:7b")
PM_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("PM_REQUEST_TIMEOUT_SECONDS", "600"))
PM_SERIALIZE_LOCAL_CALLS = os.environ.get("PM_SERIALIZE_LOCAL_CALLS", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}
PM_LOCAL_CALL_LOCK_PATH = os.environ.get(
    "PM_LOCAL_CALL_LOCK_PATH",
    "/tmp/ai-squad-pm-llm.lock",
)
GITHUB_SVC_URL = os.environ.get("GITHUB_SVC_URL", "http://github-svc:9000")

OPENAI_COMPAT_PROVIDERS = {"lmstudio", "mlx_lm", "llama_cpp", "openai_compat"}
PROVIDER_BASE_URLS = {
    "lmstudio": "http://host.docker.internal:1234/v1",
    "mlx_lm": "http://host.docker.internal:8080/v1",
    "llama_cpp": "http://host.docker.internal:8080/v1",
    "openai_compat": "http://host.docker.internal:1234/v1",
}

# ── Output contract ────────────────────────────────────────────────────────────

SPEC_REQUIRED = ["brief_summary", "milestones", "rationale"]
TASKS_REQUIRED = ["tasks"]
TASKS_MIN_COUNT = 3
TASKS_MIN_AC = 2
MILESTONES_MIN = 2
RATIONALE_MIN_LEN = 100
BRIEF_SUMMARY_MIN_LEN = 50
DECISION_LOG_MIN = 1

# ── Prompt ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a product manager (PM) agent. Your job is to turn a project brief into
a structured delivery plan.

Respond with ONLY a valid JSON object — no markdown fences, no explanation before
or after the JSON. The JSON must have exactly these top-level keys:

  brief_summary   (string, ≥50 chars) — what is being built and why
  milestones      (array, ≥2 items)   — each item has: title, description,
                                         acceptance_criteria (array ≥2 strings)
  tasks           (array, ≥3 items)   — each item has: title,
                                         role (one of: dev-jr, dev-sr, qa, devops, ux),
                                         priority (critical/high/medium/low),
                                         acceptance_criteria (array ≥2 strings)
  rationale       (string, ≥100 chars) — explain the milestone/task breakdown
                                         and sequencing decisions
  decision_log    (array, ≥3 items)   — each item has: decision (string),
                                         reason (string)

Produce specific, actionable content. Do not use placeholder text."""


def run(context: dict) -> list[dict]:
    """Call the configured model server and return the three PM artifacts."""
    project_id = context.get("project_id", "unknown")
    run_id = context.get("run_id")
    brief = context.get("brief", "No brief provided.")

    user_message = (
        f"Project ID: {project_id}\n\n"
        f"Project brief:\n{brief}"
    )
    raw = _call_model(user_message)
    data = _parse_json(raw)

    failures = _sanity_check(data)
    if failures:
        logger.warning("PM output sanity failures: %s", failures)

    spec_body = json.dumps(
        {
            "brief_summary": data.get("brief_summary", ""),
            "milestones": data.get("milestones", []),
            "rationale": data.get("rationale", ""),
        },
        indent=2,
    )
    tasks_data: dict[str, Any] = {"tasks": data.get("tasks", [])}

    # Try to create GitHub issues (non-fatal if unavailable)
    issues = _create_github_issues(
        project_id=project_id,
        run_id=run_id,
        tasks=tasks_data["tasks"],
    )
    if issues:
        for task, issue in zip(tasks_data["tasks"], issues):
            task["github_issue_url"] = issue.get("html_url")
            task["github_issue_number"] = issue.get("number")

    tasks_body = json.dumps(tasks_data, indent=2)

    dl_body = json.dumps(
        {
            "decision_log": data.get("decision_log", []),
            "github_issues_created": len(issues),
            "sanity_check": {
                "passed": len(failures) == 0,
                "failures": failures,
            },
        },
        indent=2,
    )

    return [
        {"artifact_type": "spec", "name": "pm_spec.json", "body": spec_body},
        {"artifact_type": "tasks", "name": "pm_tasks.json", "body": tasks_body},
        {"artifact_type": "decision_log", "name": "pm_decision_log.json", "body": dl_body},
    ]


def validate(artifact_type: str, body: str) -> bool:
    """Validate an artifact body against the PM output contract."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False

    if artifact_type == "spec":
        return all(k in data for k in SPEC_REQUIRED)

    if artifact_type == "tasks":
        tasks = data.get("tasks", [])
        return (
            all(k in data for k in TASKS_REQUIRED)
            and isinstance(tasks, list)
            and len(tasks) >= TASKS_MIN_COUNT
        )

    if artifact_type == "decision_log":
        return "decision_log" in data

    return False


# ── Internal helpers ──────────────────────────────────────────────────────────


def _resolve_base_url() -> str:
    if PM_BASE_URL:
        return PM_BASE_URL.rstrip("/")

    if PM_LLM_PROVIDER == "ollama":
        return OLLAMA_URL.rstrip("/")

    return PROVIDER_BASE_URLS.get(PM_LLM_PROVIDER, PROVIDER_BASE_URLS["lmstudio"])


def _call_model(user_message: str) -> str:
    provider = PM_LLM_PROVIDER
    base_url = _resolve_base_url()

    logger.info(
        "PM agent calling provider=%s model=%s base_url=%s",
        provider,
        PM_MODEL,
        base_url,
    )

    with _local_model_call_lock(provider):
        if provider == "ollama":
            return _call_ollama(base_url, user_message)

        if provider in OPENAI_COMPAT_PROVIDERS:
            return _call_openai_compat(base_url, user_message)

    raise RuntimeError(
        "Unsupported PM_LLM_PROVIDER. Expected one of: "
        "ollama, lmstudio, mlx_lm, llama_cpp, openai_compat"
    )


def _call_ollama(base_url: str, user_message: str) -> str:
    payload = {
        "model": PM_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "format": "json",
        "options": {"temperature": 0.3},
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
        "model": PM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.3,
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
        body = response.json()
        return body["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        response_text = ""
        try:
            response_text = exc.response.text
        except Exception:
            response_text = "<unavailable>"
        logger.error(
            "OpenAI-compatible model call failed with status=%s body=%s",
            exc.response.status_code,
            response_text[:2000],
        )
        raise RuntimeError(
            "OpenAI-compatible model call failed: "
            f"{exc}; response body: {response_text[:500]}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"OpenAI-compatible model call failed: {exc}") from exc


@contextlib.contextmanager
def _local_model_call_lock(provider: str):
    if not PM_SERIALIZE_LOCAL_CALLS or provider == "openai_compat":
        yield
        return

    lock_path = PM_LOCAL_CALL_LOCK_PATH
    logger.info("Waiting for local model lock at %s", lock_path)
    with open(lock_path, "w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        logger.info("Acquired local model lock at %s", lock_path)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            logger.info("Released local model lock at %s", lock_path)


def _parse_json(raw: str) -> dict:
    """Parse JSON from the model response, tolerating minor preamble."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # try to extract a JSON object in case the model added surrounding text
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise RuntimeError(
        f"PM model did not return valid JSON. First 500 chars: {raw[:500]}"
    )


def _sanity_check(data: dict) -> list[str]:
    """Return a list of content sanity failures. Empty = all clear."""
    failures: list[str] = []

    brief = data.get("brief_summary", "")
    if len(brief) < BRIEF_SUMMARY_MIN_LEN:
        failures.append(
            f"brief_summary too short ({len(brief)} < {BRIEF_SUMMARY_MIN_LEN})"
        )

    rationale = data.get("rationale", "")
    if len(rationale) < RATIONALE_MIN_LEN:
        failures.append(
            f"rationale too short ({len(rationale)} < {RATIONALE_MIN_LEN})"
        )

    milestones = data.get("milestones", [])
    if len(milestones) < MILESTONES_MIN:
        failures.append(
            f"too few milestones ({len(milestones)} < {MILESTONES_MIN})"
        )

    tasks = data.get("tasks", [])
    if len(tasks) < TASKS_MIN_COUNT:
        failures.append(
            f"too few tasks ({len(tasks)} < {TASKS_MIN_COUNT})"
        )
    for i, task in enumerate(tasks):
        ac = task.get("acceptance_criteria", [])
        if len(ac) < TASKS_MIN_AC:
            failures.append(
                f"task[{i}] '{task.get('title', '?')}' "
                f"has too few AC ({len(ac)} < {TASKS_MIN_AC})"
            )

    dl = data.get("decision_log", [])
    if len(dl) < DECISION_LOG_MIN:
        failures.append(
            f"decision_log too short ({len(dl)} < {DECISION_LOG_MIN})"
        )

    return failures


def _create_github_issues(
    project_id: str,
    run_id: str | None,
    tasks: list[dict],
) -> list[dict]:
    """Call github-svc to create one issue per task. Returns created issue dicts."""
    if not tasks:
        return []
    created: list[dict] = []
    for task in tasks:
        ac_lines = "\n".join(
            f"- {ac}" for ac in task.get("acceptance_criteria", [])
        )
        body = (
            f"**Role:** {task.get('role', 'unassigned')}\n"
            f"**Priority:** {task.get('priority', 'medium')}\n\n"
            f"**Acceptance Criteria:**\n{ac_lines}\n\n"
            f"---\n"
            f"_AI Squad run: {run_id}_  \n"
            f"_Project: {project_id}_"
        )
        try:
            resp = httpx.post(
                f"{GITHUB_SVC_URL}/api/v1/issues",
                json={
                    "title": task.get("title", "Untitled task"),
                    "body": body,
                    "labels": [
                        task.get("role", "task"),
                        task.get("priority", "medium"),
                    ],
                },
                timeout=15.0,
            )
            if resp.status_code == 201:
                created.append(resp.json())
            else:
                logger.warning(
                    "github-svc returned %s for issue creation: %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as exc:
            logger.warning("github-svc call failed (non-fatal): %s", exc)
            break  # if service is down, don't keep retrying for every task
    return created
