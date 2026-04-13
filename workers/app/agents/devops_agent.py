"""DevOps agent — reviews developer output for deployment and CI/CD concerns.

Produces a ci_changes artifact describing what infrastructure or pipeline work
is needed to ship the deliverable. Runs after judge as the final workflow step.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

from app.agents.pm_agent import (
    PM_API_KEY,
    PM_LLM_PROVIDER,
    PM_MODEL,
    PM_REQUEST_TIMEOUT_SECONDS,
    OPENAI_COMPAT_PROVIDERS,
    OLLAMA_URL,
    _extract_response_content,
    _local_model_call_lock,
    _parse_json,
    _resolve_base_url,
)

logger = logging.getLogger(__name__)

DEVOPS_PROVIDER = (
    os.environ.get("DEVOPS_PROVIDER", "").strip().lower()
    or os.environ.get("JUDGE_PROVIDER", "").strip().lower()
    or os.environ.get("DEV_SR_PROVIDER", "").strip().lower()
    or PM_LLM_PROVIDER
)
DEVOPS_BASE_URL = (
    os.environ.get("DEVOPS_BASE_URL", "").strip()
    or os.environ.get("JUDGE_BASE_URL", "").strip()
    or os.environ.get("DEV_SR_BASE_URL", "").strip()
)
DEVOPS_MODEL = (
    os.environ.get("DEVOPS_MODEL", "").strip()
    or os.environ.get("JUDGE_MODEL", "").strip()
    or os.environ.get("DEV_SR_MODEL", "").strip()
    or PM_MODEL
)
DEVOPS_API_KEY = (
    os.environ.get("DEVOPS_API_KEY", "").strip()
    or os.environ.get("JUDGE_API_KEY", "").strip()
    or os.environ.get("DEV_SR_API_KEY", "").strip()
)

REQUIRED_KEYS = ["changes_needed", "deployment_ready", "recommendation"]

SYSTEM_PROMPT = """\
You are a DevOps specialist agent. Review the project brief and developer output
to identify any CI/CD pipeline changes, Docker configuration updates, environment
variable additions, or deployment steps needed to ship this deliverable.

Respond with ONLY a valid JSON object with exactly these keys:

  changes_needed    (array of strings — specific CI/CD or infrastructure changes required; can be empty)
  deployment_ready  (boolean — true if the deliverable can be deployed as-is, false if changes are needed first)
  recommendation    (string, >=80 chars — actionable DevOps guidance)

Rules:
- Base your assessment on the developer output and project brief.
- If no infrastructure changes are needed, return an empty array and deployment_ready true.
- Be specific about what files or pipeline stages need updating.
"""


def run(context: dict) -> list[dict]:
    prior_artifacts = context.get("prior_artifacts", [])
    brief = context.get("brief", "No brief provided.")

    dev_output = _find_artifact(prior_artifacts, "dev_output")
    review_findings = _find_artifact(prior_artifacts, "review_findings")

    parts = ["/no_think", f"Project brief:\n{brief}"]
    if dev_output:
        parts.append(f"Developer output:\n{dev_output[:4000]}")
    if review_findings:
        parts.append(f"Reviewer findings:\n{review_findings[:2000]}")

    raw = _call_model("\n\n".join(parts))
    data = _parse_json(raw)

    changes_needed = data.get("changes_needed", [])
    if not isinstance(changes_needed, list):
        changes_needed = []

    deployment_ready = data.get("deployment_ready", True)
    if not isinstance(deployment_ready, bool):
        deployment_ready = str(deployment_ready).lower() in ("true", "1", "yes")

    recommendation = str(data.get("recommendation", "")).strip()
    if len(recommendation) < 40:
        recommendation = (
            "DevOps review complete. No critical infrastructure changes identified. "
            "Ensure standard CI/CD pipeline checks pass before deployment."
        )

    return [{
        "artifact_type": "ci_changes",
        "name": "devops_review.json",
        "body": json.dumps({
            "changes_needed": changes_needed,
            "deployment_ready": deployment_ready,
            "recommendation": recommendation,
        }, indent=2),
    }]


def validate(artifact_type: str, body: str) -> bool:
    if artifact_type != "ci_changes":
        return False
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    if not all(k in data for k in REQUIRED_KEYS):
        return False
    return isinstance(data.get("changes_needed"), list) and isinstance(data.get("deployment_ready"), bool)


def _find_artifact(prior_artifacts: list[dict], artifact_type: str) -> str | None:
    for art in reversed(prior_artifacts):
        if art.get("artifact_type") == artifact_type:
            return art.get("body")
    return None


def _resolve_devops_url() -> str:
    if DEVOPS_BASE_URL:
        return DEVOPS_BASE_URL.rstrip("/")
    if DEVOPS_PROVIDER == "ollama":
        return OLLAMA_URL.rstrip("/")
    return _resolve_base_url()


def _call_model(user_message: str) -> str:
    base_url = _resolve_devops_url()
    logger.info("DevOps agent calling provider=%s model=%s base_url=%s", DEVOPS_PROVIDER, DEVOPS_MODEL, base_url)

    with _local_model_call_lock(DEVOPS_PROVIDER):
        if DEVOPS_PROVIDER == "ollama":
            payload = {
                "model": DEVOPS_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "format": "json",
                "options": {"temperature": 0.2, "num_ctx": 8192},
            }
            try:
                resp = httpx.post(f"{base_url}/api/chat", json=payload, timeout=PM_REQUEST_TIMEOUT_SECONDS)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except Exception as exc:
                raise RuntimeError(f"Ollama DevOps call failed: {exc}") from exc

        if DEVOPS_PROVIDER in OPENAI_COMPAT_PROVIDERS:
            payload = {
                "model": DEVOPS_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
            headers = {"Content-Type": "application/json"}
            api_key = DEVOPS_API_KEY or PM_API_KEY
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            try:
                resp = httpx.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=PM_REQUEST_TIMEOUT_SECONDS)
                resp.raise_for_status()
                return _extract_response_content(resp.json())
            except Exception as exc:
                raise RuntimeError(f"OpenAI-compat DevOps call failed: {exc}") from exc

    raise RuntimeError(f"Unsupported DEVOPS_PROVIDER: {DEVOPS_PROVIDER}")
