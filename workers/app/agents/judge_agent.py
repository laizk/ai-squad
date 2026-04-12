"""Judge agent — structured delivery scoring across prior workflow evidence."""
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

JUDGE_PROVIDER = os.environ.get("JUDGE_PROVIDER", "").strip().lower() or os.environ.get("DEV_SR_PROVIDER", "").strip().lower() or PM_LLM_PROVIDER
JUDGE_BASE_URL = os.environ.get("JUDGE_BASE_URL", "").strip() or os.environ.get("DEV_SR_BASE_URL", "").strip()
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "").strip() or os.environ.get("DEV_SR_MODEL", "").strip() or PM_MODEL
JUDGE_API_KEY = os.environ.get("JUDGE_API_KEY", "").strip() or os.environ.get("DEV_SR_API_KEY", "").strip()

VALID_DECISIONS = {"ready_for_approval", "needs_changes", "rejected"}
REQUIRED_KEYS = ["score", "decision", "dimension_scores", "recommendation"]

SYSTEM_PROMPT = """\
You are a judge agent that scores delivery evidence before human approval.

Review the project brief, PM tasks, developer output, reviewer findings, and QA
test evidence. Respond with ONLY a valid JSON object with exactly these keys:

  score            (integer, 0-100)
  decision         (string: ready_for_approval | needs_changes | rejected)
  dimension_scores (array, >=3 items) where each item has:
                     dimension (string)
                     score     (integer, 0-5)
                     rationale (string, >=20 chars)
  recommendation   (string, >=100 chars)

Rules:
- Base the score on the actual evidence provided.
- If tests failed or were skipped, the decision must not be ready_for_approval.
- Keep rationales specific and actionable.
"""


def run(context: dict) -> list[dict]:
    prior_artifacts = context.get("prior_artifacts", [])
    brief = context.get("brief", "No brief provided.")

    user_message = _build_user_message(
        brief=brief,
        tasks_json=_find_artifact(prior_artifacts, "tasks"),
        dev_output=_find_artifact(prior_artifacts, "dev_output"),
        review_findings=_find_artifact(prior_artifacts, "review_findings"),
        test_results=_find_artifact(prior_artifacts, "test_results"),
    )

    raw = _call_model(user_message)
    data = _parse_json(raw)

    score = data.get("score", 0)
    try:
        score = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        score = 0

    decision = str(data.get("decision", "needs_changes")).strip().lower()
    if decision not in VALID_DECISIONS:
        decision = "needs_changes"

    dimension_scores = data.get("dimension_scores", [])
    if not isinstance(dimension_scores, list) or not dimension_scores:
        dimension_scores = [{
            "dimension": "overall_quality",
            "score": 0,
            "rationale": "Judge output was malformed, so the run requires human review before approval.",
        }]

    recommendation = str(data.get("recommendation", "")).strip()
    if len(recommendation) < 50:
        recommendation = (
            f"Judge review complete. Decision: {decision}. "
            "The generated scoring output was shorter than expected, so treat this as a conservative signal and inspect the linked artifacts directly."
        )

    body = json.dumps({
        "score": score,
        "decision": decision,
        "dimension_scores": dimension_scores,
        "recommendation": recommendation,
    }, indent=2)

    return [{
        "artifact_type": "rubric_score",
        "name": "judge_rubric_score.json",
        "body": body,
    }]


def validate(artifact_type: str, body: str) -> bool:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return False

    if artifact_type != "rubric_score":
        return False

    return all(key in data for key in REQUIRED_KEYS)


def _find_artifact(prior_artifacts: list[dict], artifact_type: str) -> str | None:
    for art in reversed(prior_artifacts):
        if art.get("artifact_type") == artifact_type:
            return art.get("body")
    return None


def _build_user_message(
    *,
    brief: str,
    tasks_json: str | None,
    dev_output: str | None,
    review_findings: str | None,
    test_results: str | None,
) -> str:
    parts = ["/no_think", f"Project brief:\n{brief}"]

    if tasks_json:
        parts.append(f"PM tasks:\n{tasks_json[:2000]}")
    if dev_output:
        parts.append(f"Developer output:\n{dev_output[:4000]}")
    if review_findings:
        parts.append(f"Reviewer findings:\n{review_findings[:2500]}")
    if test_results:
        parts.append(f"QA test results:\n{test_results[:2500]}")
    else:
        parts.append("QA test results:\nNo QA artifact was available.")

    return "\n\n".join(parts)


def _resolve_judge_url() -> str:
    if JUDGE_BASE_URL:
        return JUDGE_BASE_URL.rstrip("/")
    if JUDGE_PROVIDER == "ollama":
        return OLLAMA_URL.rstrip("/")
    return _resolve_base_url()


def _call_model(user_message: str) -> str:
    provider = JUDGE_PROVIDER
    base_url = _resolve_judge_url()

    logger.info(
        "Judge agent calling provider=%s model=%s base_url=%s",
        provider,
        JUDGE_MODEL,
        base_url,
    )

    with _local_model_call_lock(provider):
        if provider == "ollama":
            return _call_ollama(base_url, user_message)
        if provider in OPENAI_COMPAT_PROVIDERS:
            return _call_openai_compat(base_url, user_message)

    raise RuntimeError(f"Unsupported JUDGE_PROVIDER for judge agent: {provider}")


def _call_ollama(base_url: str, user_message: str) -> str:
    payload = {
        "model": JUDGE_MODEL,
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
        "model": JUDGE_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if JUDGE_API_KEY:
        headers["Authorization"] = f"Bearer {JUDGE_API_KEY}"
    elif PM_API_KEY:
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
    except Exception as exc:
        raise RuntimeError(f"OpenAI-compatible judge call failed: {exc}") from exc
