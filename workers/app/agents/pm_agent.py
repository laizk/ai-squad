"""Real PM agent — Ollama-backed planning step.

Replaces the PM stub with a model call that produces:
- spec artifact:        brief_summary, milestones, rationale
- tasks artifact:       tasks with roles, priorities, and AC
- decision_log artifact: design decisions and github issue links

GitHub issue creation is delegated to github-svc. If github-svc is
unavailable or unconfigured the agent continues without issues.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
PM_MODEL = os.environ.get("PM_MODEL", "qwen2.5-coder:7b")
GITHUB_SVC_URL = os.environ.get("GITHUB_SVC_URL", "http://github-svc:9000")

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
    """Call Ollama and return the three PM artifacts."""
    project_id = context.get("project_id", "unknown")
    run_id = context.get("run_id")
    brief = context.get("brief", "No brief provided.")

    user_message = (
        f"Project ID: {project_id}\n\n"
        f"Project brief:\n{brief}"
    )

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

    logger.info("PM agent calling Ollama model=%s url=%s", PM_MODEL, OLLAMA_URL)
    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=600.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Ollama call failed: {exc}") from exc

    raw = resp.json()["message"]["content"]
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
