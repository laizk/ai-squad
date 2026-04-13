"""Reviewer agent (Sr Dev) — model-backed code review step.

Reads the dev_output artifact from prior run steps, reviews the
implementation files and commit, and produces a review_findings artifact
with a real verdict and substantive findings.

Verdict values: approved | changes_requested | rejected
"""
from __future__ import annotations

import json
import logging
import os
import re

from app.agents.pm_agent import (
    PM_LLM_PROVIDER,
    PM_MODEL,
    PM_REQUEST_TIMEOUT_SECONDS,
    OPENAI_COMPAT_PROVIDERS,
    PM_API_KEY,
    _extract_response_content,
    _local_model_call_lock,
    _parse_json,
    _resolve_base_url,
)
import httpx

logger = logging.getLogger(__name__)

# Per-agent provider config — falls back to shared PM_ vars when unset
DEV_SR_PROVIDER     = os.environ.get("DEV_SR_PROVIDER", "").strip().lower() or PM_LLM_PROVIDER
DEV_SR_BASE_URL     = os.environ.get("DEV_SR_BASE_URL", "").strip()
DEV_SR_MODEL        = os.environ.get("DEV_SR_MODEL",    "").strip() or PM_MODEL
DEV_SR_API_KEY      = os.environ.get("DEV_SR_API_KEY",  "").strip()
DEV_SR_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("DEV_SR_REQUEST_TIMEOUT_SECONDS", str(PM_REQUEST_TIMEOUT_SECONDS))
)

VALID_VERDICTS = {"approved", "changes_requested", "rejected"}
VALID_SEVERITIES = {"info", "warning", "critical"}

REVIEW_FINDINGS_REQUIRED = ["verdict", "findings", "recommendation"]

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior software developer agent performing a code review.

You receive a project brief, a list of tasks from the PM, and the
implementation produced by a junior developer agent. Your job is to review
the implementation critically and produce a structured review.

Respond with ONLY a valid JSON object — no markdown fences, no explanation
before or after the JSON. The JSON must have exactly these top-level keys:

  verdict        (string) — one of exactly: approved | changes_requested | rejected
                   - approved:           implementation is acceptable as-is
                   - changes_requested:  implementation has issues that must be fixed before merge
                   - rejected:           implementation is fundamentally wrong or unsafe

  findings       (array, ≥1 items) — each item has:
                   severity (string): info | warning | critical
                   area     (string): e.g. correctness, test coverage, security, style
                   detail   (string, ≥20 chars): specific, actionable observation

  recommendation (string, ≥100 chars) — overall summary of the review explaining
                   the verdict and what the developer should do next (if anything)

Rules:
- Be honest. Do not approve bad code.
- findings must be specific to the actual files provided, not generic.
- If verdict is changes_requested or rejected, at least one finding must be warning or critical.
- If verdict is approved, you may still include info-severity improvement notes."""


def run(context: dict) -> list[dict]:
    prior_artifacts = context.get("prior_artifacts", [])
    brief = context.get("brief", "No brief provided.")

    tasks_json    = _find_artifact(prior_artifacts, "tasks")
    dev_output    = _find_artifact(prior_artifacts, "dev_output")
    sandbox_json  = _find_artifact(prior_artifacts, "sandbox_result")

    user_message = _build_user_message(
        brief=brief,
        tasks_json=tasks_json,
        dev_output=dev_output,
        sandbox_json=sandbox_json,
    )

    raw = _call_model(user_message)
    data = _parse_json(raw)

    # Normalise and validate
    verdict = data.get("verdict", "changes_requested").strip().lower()
    if verdict not in VALID_VERDICTS:
        logger.warning("Model returned unknown verdict %r — defaulting to changes_requested", verdict)
        verdict = "changes_requested"

    findings = data.get("findings", [])
    if not findings:
        findings = [{
            "severity": "info",
            "area": "review",
            "detail": "No specific findings were returned by the model.",
        }]
    for f in findings:
        if f.get("severity") not in VALID_SEVERITIES:
            f["severity"] = "info"

    recommendation = data.get("recommendation", "")
    if len(recommendation) < 50:
        recommendation = (
            f"Review complete. Verdict: {verdict}. "
            + recommendation
        )

    body = json.dumps({
        "verdict":        verdict,
        "findings":       findings,
        "recommendation": recommendation,
        "reviewed_branch": _extract_branch(dev_output),
        "reviewed_commit": _extract_commit(dev_output),
    }, indent=2)

    return [{
        "artifact_type": "review_findings",
        "name":          "reviewer_findings.json",
        "body":          body,
    }]


def validate(artifact_type: str, body: str) -> bool:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    if artifact_type == "review_findings":
        return all(k in data for k in REVIEW_FINDINGS_REQUIRED)
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_artifact(prior_artifacts: list[dict], artifact_type: str) -> str | None:
    for art in reversed(prior_artifacts):
        if art.get("artifact_type") == artifact_type:
            return art.get("body")
    return None


def _extract_branch(dev_output_body: str | None) -> str | None:
    if not dev_output_body:
        return None
    try:
        return json.loads(dev_output_body).get("branch")
    except Exception:
        return None


def _extract_commit(dev_output_body: str | None) -> str | None:
    if not dev_output_body:
        return None
    try:
        return json.loads(dev_output_body).get("github", {}).get("commit_sha")
    except Exception:
        return None


def _build_user_message(
    *,
    brief: str,
    tasks_json: str | None,
    dev_output: str | None,
    sandbox_json: str | None,
) -> str:
    parts = ["/no_think", f"Project brief:\n{brief}"]

    if tasks_json:
        try:
            tasks = json.loads(tasks_json).get("tasks", [])
            lines = []
            for i, t in enumerate(tasks, 1):
                lines.append(
                    f"{i}. [{t.get('priority','?').upper()}] {t.get('title','?')} "
                    f"(role: {t.get('role','?')})"
                )
            parts.append("Tasks from PM:\n" + "\n".join(lines))
        except Exception:
            parts.append(f"Tasks (raw):\n{tasks_json[:500]}")

    if dev_output:
        try:
            d = json.loads(dev_output)
            parts.append(
                f"Developer output:\n"
                f"  Branch: {d.get('branch','?')}\n"
                f"  Commit message: {d.get('commit_message','?')}\n"
                f"  Files written: {', '.join(d.get('files_written', []))}"
            )
            # Include file contents if present (added by slice 5)
            for f in d.get("files", []):
                parts.append(
                    f"\n--- {f['path']} ---\n{f['content'][:3000]}"
                )
        except Exception:
            parts.append(f"Developer output (raw):\n{dev_output[:1000]}")

    if sandbox_json:
        try:
            s = json.loads(sandbox_json)
            status = "PASSED" if s.get("exit_code") == 0 else "FAILED"
            parts.append(
                f"Sandbox execution ({status}):\n"
                f"  exit_code: {s.get('exit_code')}\n"
                f"  duration: {s.get('duration_seconds')}s\n"
                f"  stdout:\n{s.get('stdout','')[:1000]}\n"
                f"  stderr:\n{s.get('stderr','')[:500]}"
            )
        except Exception:
            parts.append(f"Sandbox result (raw):\n{sandbox_json[:500]}")
    else:
        parts.append("Sandbox execution: not available for this review.")

    return "\n\n".join(parts)


def _resolve_dev_sr_url() -> str:
    if DEV_SR_BASE_URL:
        return DEV_SR_BASE_URL.rstrip("/")
    if DEV_SR_PROVIDER == "ollama":
        from app.agents.pm_agent import OLLAMA_URL
        return OLLAMA_URL.rstrip("/")
    return _resolve_base_url()


def _call_model(user_message: str) -> str:
    provider = DEV_SR_PROVIDER
    base_url = _resolve_dev_sr_url()

    logger.info(
        "Reviewer agent calling provider=%s model=%s base_url=%s",
        provider, DEV_SR_MODEL, base_url,
    )

    with _local_model_call_lock(provider):
        if provider == "ollama":
            return _call_ollama(base_url, user_message)
        if provider in OPENAI_COMPAT_PROVIDERS:
            return _call_openai_compat(base_url, user_message)

    raise RuntimeError(f"Unsupported DEV_SR_PROVIDER for reviewer agent: {provider}")


def _call_ollama(base_url: str, user_message: str) -> str:
    payload = {
        "model": DEV_SR_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "format": "json",
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }
    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=DEV_SR_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
    except httpx.ReadTimeout as exc:
        raise RuntimeError(
            "Ollama call timed out for dev-sr "
            f"(model={DEV_SR_MODEL}, timeout={DEV_SR_REQUEST_TIMEOUT_SECONDS}s). "
            "This usually means generation is too slow or the Ollama runner is stuck. "
            "If `ollama ps` shows `Stopping...`, restart or unload the model before retrying."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Ollama call failed: {exc}") from exc


def _call_openai_compat(base_url: str, user_message: str) -> str:
    payload = {
        "model": DEV_SR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    api_key = DEV_SR_API_KEY or PM_API_KEY
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=DEV_SR_REQUEST_TIMEOUT_SECONDS,
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
            "Reviewer model call failed status=%s body=%s",
            exc.response.status_code, body[:2000],
        )
        raise RuntimeError(
            f"Reviewer model call failed: {exc}; response: {body[:500]}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Reviewer model call failed: {exc}") from exc

