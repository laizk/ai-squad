"""github-svc — isolated GitHub App proxy.

Workers must NOT call GitHub directly. This service holds the GitHub App
private key, mints installation tokens, and exposes a narrow API for the
operations workers need.

If GITHUB_APP_ID is not configured, all mutation endpoints return 503.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
import jwt
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
GITHUB_APP_INSTALLATION_ID = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")
GITHUB_APP_PRIVATE_KEY_PATH = os.environ.get(
    "GITHUB_APP_PRIVATE_KEY_PATH", "/secrets/github-app.pem"
)
GITHUB_REPO_ORG = os.environ.get("GITHUB_REPO_ORG", "")
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME", "")

_configured = bool(GITHUB_APP_ID and GITHUB_APP_INSTALLATION_ID and GITHUB_REPO_ORG and GITHUB_REPO_NAME)

app = FastAPI(title="github-svc", version="0.1.0")


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "github-svc",
        "configured": _configured,
    }


# ── Models ─────────────────────────────────────────────────────────────────────

class IssueCreate(BaseModel):
    title: str
    body: str = ""
    labels: list[str] = []


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/api/v1/issues", status_code=status.HTTP_201_CREATED)
async def create_issue(payload: IssueCreate) -> dict[str, Any]:
    if not _configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App is not configured. Set GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_REPO_ORG, GITHUB_REPO_NAME.",
        )

    token = _get_installation_token()

    resp = httpx.post(
        f"https://api.github.com/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "title": payload.title,
            "body": payload.body,
            "labels": payload.labels,
        },
        timeout=15.0,
    )

    if resp.status_code not in (200, 201):
        logger.error("GitHub API returned %s: %s", resp.status_code, resp.text[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API error {resp.status_code}",
        )

    return resp.json()


# ── GitHub App auth ───────────────────────────────────────────────────────────

def _load_private_key() -> str:
    with open(GITHUB_APP_PRIVATE_KEY_PATH) as f:
        return f.read()


def _make_app_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,   # issued 60s ago to account for clock skew
        "exp": now + 540,  # 9 minutes (max 10)
        "iss": GITHUB_APP_ID,
    }
    private_key = _load_private_key()
    return jwt.encode(payload, private_key, algorithm="RS256")


def _get_installation_token() -> str:
    app_jwt = _make_app_jwt()
    resp = httpx.post(
        f"https://api.github.com/app/installations/{GITHUB_APP_INSTALLATION_ID}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=10.0,
    )
    if resp.status_code != 201:
        raise RuntimeError(
            f"Failed to get installation token: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()["token"]
