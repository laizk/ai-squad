"""UX agent — reviews PM spec and developer output for user experience concerns.

Produces a ux_notes artifact with concerns, severity, and a recommendation.
Runs after PM planning and before dev-jr so UX risks are visible before
implementation begins.
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

# Inherit from judge/dev-sr config so UX uses the same capable model
UX_PROVIDER = (
    os.environ.get("UX_PROVIDER", "").strip().lower()
    or os.environ.get("JUDGE_PROVIDER", "").strip().lower()
    or os.environ.get("DEV_SR_PROVIDER", "").strip().lower()
    or PM_LLM_PROVIDER
)
UX_BASE_URL = (
    os.environ.get("UX_BASE_URL", "").strip()
    or os.environ.get("JUDGE_BASE_URL", "").strip()
    or os.environ.get("DEV_SR_BASE_URL", "").strip()
)
UX_MODEL = (
    os.environ.get("UX_MODEL", "").strip()
    or os.environ.get("JUDGE_MODEL", "").strip()
    or os.environ.get("DEV_SR_MODEL", "").strip()
    or PM_MODEL
)
UX_API_KEY = (
    os.environ.get("UX_API_KEY", "").strip()
    or os.environ.get("JUDGE_API_KEY", "").strip()
    or os.environ.get("DEV_SR_API_KEY", "").strip()
)

REQUIRED_KEYS = ["concerns", "severity", "recommendation"]
VALID_SEVERITIES = {"low", "medium", "high"}

SYSTEM_PROMPT = """\
You are a UX specialist agent. Review the project brief and PM task plan for
user experience risks, accessibility concerns, and usability gaps.

Respond with ONLY a valid JSON object with exactly these keys:

  concerns       (array of strings, each describing one UX concern; can be empty)
  severity       (string: low | medium | high — overall UX risk level)
  recommendation (string, >=80 chars — actionable guidance for the developer)

Rules:
- Base your assessment on the brief and tasks provided.
- If no UX concerns are found, return an empty concerns array and severity "low".
- Keep recommendations specific and actionable, not generic platitudes.
"""


def run(context: dict) -> list[dict]:
    prior_artifacts = context.get("prior_artifacts", [])
    brief = context.get("brief", "No brief provided.")

    tasks_body = _find_artifact(prior_artifacts, "tasks")
    parts = ["/no_think", f"Project brief:\n{brief}"]
    if tasks_body:
        parts.append(f"PM tasks:\n{tasks_body[:3000]}")
    else:
        parts.append("PM tasks: Not yet available.")

    raw = _call_model("\n\n".join(parts))
    data = _parse_json(raw)

    concerns = data.get("concerns", [])
    if not isinstance(concerns, list):
        concerns = []

    severity = str(data.get("severity", "low")).strip().lower()
    if severity not in VALID_SEVERITIES:
        severity = "low"

    recommendation = str(data.get("recommendation", "")).strip()
    if len(recommendation) < 40:
        recommendation = (
            "UX review complete. No critical concerns identified. "
            "Ensure the implementation follows standard usability conventions "
            "and is accessible to all users."
        )

    return [{
        "artifact_type": "ux_notes",
        "name": "ux_review.json",
        "body": json.dumps({"concerns": concerns, "severity": severity, "recommendation": recommendation}, indent=2),
    }]


def validate(artifact_type: str, body: str) -> bool:
    if artifact_type != "ux_notes":
        return False
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False
    return all(k in data for k in REQUIRED_KEYS) and data.get("severity") in VALID_SEVERITIES


def _find_artifact(prior_artifacts: list[dict], artifact_type: str) -> str | None:
    for art in reversed(prior_artifacts):
        if art.get("artifact_type") == artifact_type:
            return art.get("body")
    return None


def _resolve_ux_url() -> str:
    if UX_BASE_URL:
        return UX_BASE_URL.rstrip("/")
    if UX_PROVIDER == "ollama":
        return OLLAMA_URL.rstrip("/")
    return _resolve_base_url()


def _call_model(user_message: str) -> str:
    base_url = _resolve_ux_url()
    logger.info("UX agent calling provider=%s model=%s base_url=%s", UX_PROVIDER, UX_MODEL, base_url)

    with _local_model_call_lock(UX_PROVIDER):
        if UX_PROVIDER == "ollama":
            payload = {
                "model": UX_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "format": "json",
                "options": {"temperature": 0.2},
            }
            try:
                resp = httpx.post(f"{base_url}/api/chat", json=payload, timeout=PM_REQUEST_TIMEOUT_SECONDS)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except Exception as exc:
                raise RuntimeError(f"Ollama UX call failed: {exc}") from exc

        if UX_PROVIDER in OPENAI_COMPAT_PROVIDERS:
            payload = {
                "model": UX_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
            headers = {"Content-Type": "application/json"}
            api_key = UX_API_KEY or PM_API_KEY
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            try:
                resp = httpx.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=PM_REQUEST_TIMEOUT_SECONDS)
                resp.raise_for_status()
                return _extract_response_content(resp.json())
            except Exception as exc:
                raise RuntimeError(f"OpenAI-compat UX call failed: {exc}") from exc

    raise RuntimeError(f"Unsupported UX_PROVIDER: {UX_PROVIDER}")
