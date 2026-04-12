"""github-svc — isolated GitHub App proxy.

Workers must NOT call GitHub directly. This service holds the GitHub App
private key, mints installation tokens, and exposes a narrow API for the
operations workers need.

If GITHUB_APP_ID is not configured, all mutation endpoints return 503.
"""
from __future__ import annotations

import base64
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

app = FastAPI(title="github-svc", version="0.2.0")

_GH_API = "https://api.github.com"
_GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

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


class BranchCreate(BaseModel):
    branch: str                  # new branch name, e.g. "ai-squad/task-abc123"
    base: str = "main"           # branch to fork from


class FileContent(BaseModel):
    path: str                    # repo-relative path, e.g. "src/foo.py"
    content: str                 # raw UTF-8 content


class CommitCreate(BaseModel):
    branch: str                  # must already exist
    message: str
    files: list[FileContent]     # one or more files to write


class PullCreate(BaseModel):
    title: str
    body: str = ""
    head: str                    # branch name (not refs/heads/...)
    base: str = "main"


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/api/v1/issues", status_code=status.HTTP_201_CREATED)
async def create_issue(payload: IssueCreate) -> dict[str, Any]:
    _require_configured()
    token = _get_installation_token()
    resp = _gh_post(
        token,
        f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/issues",
        {
            "title": payload.title,
            "body": payload.body,
            "labels": payload.labels,
        },
    )
    _raise_for_gh(resp, "create issue")
    return resp.json()


@app.post("/api/v1/branches", status_code=status.HTTP_201_CREATED)
async def create_branch(payload: BranchCreate) -> dict[str, Any]:
    """Create a new branch from base. Returns the new ref object."""
    _require_configured()

    # Safety: workers may not branch off protected targets other than main/master
    if payload.base not in ("main", "master"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"base branch '{payload.base}' is not allowed; use main or master",
        )
    # Safety: ai-squad branches must be namespaced
    if not payload.branch.startswith("ai-squad/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="branch name must start with 'ai-squad/'",
        )

    token = _get_installation_token()

    # Resolve base SHA
    ref_resp = httpx.get(
        f"{_GH_API}/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/git/ref/heads/{payload.base}",
        headers={**_GH_HEADERS, "Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    if ref_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"could not resolve base branch '{payload.base}': {ref_resp.status_code}",
        )
    base_sha = ref_resp.json()["object"]["sha"]

    resp = _gh_post(
        token,
        f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/git/refs",
        {
            "ref": f"refs/heads/{payload.branch}",
            "sha": base_sha,
        },
    )
    _raise_for_gh(resp, "create branch", expected=(201,))
    return {"branch": payload.branch, "sha": base_sha, "ref": resp.json()}


@app.post("/api/v1/commits", status_code=status.HTTP_201_CREATED)
async def create_commit(payload: CommitCreate) -> dict[str, Any]:
    """Commit one or more files to an existing branch via the Git Trees API."""
    _require_configured()

    # Safety: no writes to workflow files
    for f in payload.files:
        if f.path.startswith(".github/"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"writes to .github/ are not allowed (file: {f.path})",
            )

    token = _get_installation_token()
    headers = {**_GH_HEADERS, "Authorization": f"Bearer {token}"}
    repo = f"{_GH_API}/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}"

    # 1. Get current HEAD commit SHA for the branch
    ref_resp = httpx.get(
        f"{repo}/git/ref/heads/{payload.branch}",
        headers=headers,
        timeout=10.0,
    )
    if ref_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"branch '{payload.branch}' not found: {ref_resp.status_code}",
        )
    head_sha = ref_resp.json()["object"]["sha"]

    # 2. Get the tree SHA of that commit
    commit_resp = httpx.get(
        f"{repo}/git/commits/{head_sha}",
        headers=headers,
        timeout=10.0,
    )
    commit_resp.raise_for_status()
    base_tree_sha = commit_resp.json()["tree"]["sha"]

    # 3. Create blobs for each file
    tree_items = []
    for f in payload.files:
        blob_resp = httpx.post(
            f"{repo}/git/blobs",
            headers=headers,
            json={
                "content": base64.b64encode(f.content.encode()).decode(),
                "encoding": "base64",
            },
            timeout=15.0,
        )
        blob_resp.raise_for_status()
        tree_items.append({
            "path": f.path,
            "mode": "100644",
            "type": "blob",
            "sha": blob_resp.json()["sha"],
        })

    # 4. Create new tree
    tree_resp = httpx.post(
        f"{repo}/git/trees",
        headers=headers,
        json={"base_tree": base_tree_sha, "tree": tree_items},
        timeout=15.0,
    )
    tree_resp.raise_for_status()
    new_tree_sha = tree_resp.json()["sha"]

    # 5. Create commit
    new_commit_resp = httpx.post(
        f"{repo}/git/commits",
        headers=headers,
        json={
            "message": payload.message,
            "tree": new_tree_sha,
            "parents": [head_sha],
        },
        timeout=15.0,
    )
    new_commit_resp.raise_for_status()
    new_commit_sha = new_commit_resp.json()["sha"]

    # 6. Fast-forward branch ref
    patch_resp = httpx.patch(
        f"{repo}/git/refs/heads/{payload.branch}",
        headers=headers,
        json={"sha": new_commit_sha},
        timeout=10.0,
    )
    patch_resp.raise_for_status()

    return {
        "branch": payload.branch,
        "commit_sha": new_commit_sha,
        "files_written": [f.path for f in payload.files],
    }


@app.post("/api/v1/pulls", status_code=status.HTTP_201_CREATED)
async def create_pull(payload: PullCreate) -> dict[str, Any]:
    """Open a pull request. head must be an ai-squad/* branch."""
    _require_configured()

    if not payload.head.startswith("ai-squad/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="head branch must start with 'ai-squad/'",
        )
    if payload.base not in ("main", "master"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"base branch '{payload.base}' is not allowed",
        )

    token = _get_installation_token()
    resp = _gh_post(
        token,
        f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/pulls",
        {
            "title": payload.title,
            "body": payload.body,
            "head": payload.head,
            "base": payload.base,
        },
    )
    _raise_for_gh(resp, "create pull request", expected=(201,))
    data = resp.json()
    return {
        "number": data["number"],
        "html_url": data["html_url"],
        "head": payload.head,
        "base": payload.base,
    }


# ── GitHub App auth ───────────────────────────────────────────────────────────

def _load_private_key() -> str:
    with open(GITHUB_APP_PRIVATE_KEY_PATH) as f:
        return f.read()


def _make_app_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 540,
        "iss": GITHUB_APP_ID,
    }
    private_key = _load_private_key()
    return jwt.encode(payload, private_key, algorithm="RS256")


def _get_installation_token() -> str:
    app_jwt = _make_app_jwt()
    resp = httpx.post(
        f"{_GH_API}/app/installations/{GITHUB_APP_INSTALLATION_ID}/access_tokens",
        headers={**_GH_HEADERS, "Authorization": f"Bearer {app_jwt}"},
        timeout=10.0,
    )
    if resp.status_code != 201:
        raise RuntimeError(
            f"Failed to get installation token: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()["token"]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _require_configured() -> None:
    if not _configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub App is not configured. Set GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_REPO_ORG, GITHUB_REPO_NAME.",
        )


def _gh_post(token: str, path: str, body: dict) -> httpx.Response:
    return httpx.post(
        f"{_GH_API}{path}",
        headers={**_GH_HEADERS, "Authorization": f"Bearer {token}"},
        json=body,
        timeout=15.0,
    )


def _raise_for_gh(resp: httpx.Response, action: str, expected: tuple = (200, 201)) -> None:
    if resp.status_code not in expected:
        logger.error("GitHub API %s returned %s: %s", action, resp.status_code, resp.text[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API error on {action}: {resp.status_code}",
        )
