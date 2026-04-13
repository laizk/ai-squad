"""github-svc — isolated GitHub App proxy.

Workers must NOT call GitHub directly. This service holds the GitHub App
private key, mints installation tokens, and exposes a narrow API for the
operations workers need.

If GITHUB_APP_ID is not configured, all mutation endpoints return 503.
"""
from __future__ import annotations

import base64
import json
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
    actual_base, base_sha = _resolve_base_branch(token, payload.base)

    resp = _gh_post(
        token,
        f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/git/refs",
        {
            "ref": f"refs/heads/{payload.branch}",
            "sha": base_sha,
        },
    )
    if _is_existing_ref_error(resp):
        return {
            "branch": payload.branch,
            "base": actual_base,
            "sha": base_sha,
            "ref": None,
            "already_exists": True,
        }

    _raise_for_gh(resp, "create branch", expected=(201,))
    return {
        "branch": payload.branch,
        "base": actual_base,
        "sha": base_sha,
        "ref": resp.json(),
        "already_exists": False,
    }


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
    actual_base, _ = _resolve_base_branch(token, payload.base)
    resp = _gh_post(
        token,
        f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/pulls",
        {
            "title": payload.title,
            "body": payload.body,
            "head": payload.head,
            "base": actual_base,
        },
    )
    if _is_existing_pull_error(resp):
        existing = _find_existing_pull(token, head=payload.head, base=actual_base)
        if existing is not None:
            return {
                "number": existing["number"],
                "html_url": existing["html_url"],
                "head": payload.head,
                "base": actual_base,
                "already_exists": True,
            }
    _raise_for_gh(resp, "create pull request", expected=(201,))
    data = resp.json()
    return {
        "number": data["number"],
        "html_url": data["html_url"],
        "head": payload.head,
        "base": actual_base,
        "already_exists": False,
    }


# ── Board sync ───────────────────────────────────────────────────────────────

class BoardSyncRequest(BaseModel):
    run_id: str
    title: str
    body: str = ""
    labels: list[str] = []
    issue_number: int | None = None   # if set, update existing issue; else create


@app.post("/api/v1/board/sync", status_code=status.HTTP_200_OK)
async def board_sync(payload: BoardSyncRequest) -> dict[str, Any]:
    """Create or update a GitHub issue representing a run on the project board.

    - If issue_number is None, creates a new issue and returns its number.
    - If issue_number is set, updates the title and body of the existing issue.

    The caller (workers) is responsible for storing the returned issue_number
    back on the run via PATCH /api/v1/runs/{run_id}/github_refs.
    """
    _require_configured()
    token = _get_installation_token()

    if payload.issue_number is None:
        resp = _gh_post(
            token,
            f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/issues",
            {"title": payload.title, "body": payload.body, "labels": payload.labels},
        )
        _raise_for_gh(resp, "create board issue", expected=(201,))
        data = resp.json()
        return {
            "action": "created",
            "issue_number": data["number"],
            "html_url": data["html_url"],
            "run_id": payload.run_id,
        }
    else:
        resp = httpx.patch(
            f"{_GH_API}/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/issues/{payload.issue_number}",
            headers={**_GH_HEADERS, "Authorization": f"Bearer {token}"},
            json={"title": payload.title, "body": payload.body},
            timeout=15.0,
        )
        _raise_for_gh(resp, "update board issue", expected=(200,))
        data = resp.json()
        return {
            "action": "updated",
            "issue_number": data["number"],
            "html_url": data["html_url"],
            "run_id": payload.run_id,
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


def _gh_get(token: str, path: str) -> httpx.Response:
    return httpx.get(
        f"{_GH_API}{path}",
        headers={**_GH_HEADERS, "Authorization": f"Bearer {token}"},
        timeout=15.0,
    )


def _resolve_base_branch(token: str, requested_base: str) -> tuple[str, str]:
    requested_resp = _gh_get(
        token,
        f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/git/ref/heads/{requested_base}",
    )
    if requested_resp.status_code == 200:
        return requested_base, requested_resp.json()["object"]["sha"]
    if requested_resp.status_code == 409:
        return requested_base, _bootstrap_base_branch(token, requested_base)

    repo_resp = _gh_get(token, f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}")
    _raise_for_gh(repo_resp, "load repository", expected=(200,))
    default_branch = repo_resp.json().get("default_branch")
    if (
        requested_resp.status_code == 404
        and isinstance(default_branch, str)
        and default_branch in ("main", "master")
        and default_branch != requested_base
    ):
        fallback_resp = _gh_get(
            token,
            f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/git/ref/heads/{default_branch}",
        )
        if fallback_resp.status_code == 200:
            return default_branch, fallback_resp.json()["object"]["sha"]
        if fallback_resp.status_code == 409:
            return default_branch, _bootstrap_base_branch(token, default_branch)

    detail = _extract_error_detail(requested_resp)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=(
            f"could not resolve base branch '{requested_base}': "
            f"{requested_resp.status_code} {detail}"
        ),
    )


def _bootstrap_base_branch(token: str, branch: str) -> str:
    logger.warning(
        "Repository %s/%s is empty; bootstrapping base branch %s",
        GITHUB_REPO_ORG,
        GITHUB_REPO_NAME,
        branch,
    )
    repo = f"/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}"

    resp = httpx.put(
        f"{_GH_API}{repo}/contents/README.md",
        headers={**_GH_HEADERS, "Authorization": f"Bearer {token}"},
        json={
            "message": f"chore: bootstrap {branch} branch",
            "content": base64.b64encode(
                b"# AI Squad Test Workspace\n\nBootstrapped by github-svc.\n"
            ).decode(),
            "branch": branch,
        },
        timeout=20.0,
    )
    if resp.status_code not in (200, 201):
        detail = _extract_error_detail(resp)
        existing = _gh_get(token, f"{repo}/git/ref/heads/{branch}")
        if existing.status_code == 200:
            return existing.json()["object"]["sha"]
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API error on bootstrap base branch: {resp.status_code} {detail}",
        )

    ref_resp = _gh_get(token, f"{repo}/git/ref/heads/{branch}")
    _raise_for_gh(ref_resp, "load bootstrapped branch ref", expected=(200,))
    return ref_resp.json()["object"]["sha"]


def _find_existing_pull(token: str, *, head: str, base: str) -> dict[str, Any] | None:
    resp = httpx.get(
        f"{_GH_API}/repos/{GITHUB_REPO_ORG}/{GITHUB_REPO_NAME}/pulls",
        headers={**_GH_HEADERS, "Authorization": f"Bearer {token}"},
        params={"state": "open", "head": f"{GITHUB_REPO_ORG}:{head}", "base": base},
        timeout=15.0,
    )
    _raise_for_gh(resp, "list existing pull requests", expected=(200,))
    pulls = resp.json()
    if pulls:
        return pulls[0]
    return None


def _extract_error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        return resp.text[:200]

    if isinstance(data, dict):
        parts = []
        if data.get("message"):
            parts.append(str(data["message"]))
        errors = data.get("errors")
        if isinstance(errors, list):
            rendered = []
            for item in errors[:3]:
                if isinstance(item, dict):
                    rendered.append(
                        ", ".join(
                            str(item.get(key))
                            for key in ("resource", "field", "code", "message")
                            if item.get(key)
                        )
                    )
                else:
                    rendered.append(str(item))
            if rendered:
                parts.append("; ".join(rendered))
        if parts:
            return " | ".join(parts)
    return json.dumps(data)[:200]


def _is_existing_ref_error(resp: httpx.Response) -> bool:
    if resp.status_code != 422:
        return False
    detail = _extract_error_detail(resp).lower()
    return "reference already exists" in detail or "ref already exists" in detail


def _is_existing_pull_error(resp: httpx.Response) -> bool:
    if resp.status_code != 422:
        return False
    detail = _extract_error_detail(resp).lower()
    return "a pull request already exists" in detail


def _raise_for_gh(resp: httpx.Response, action: str, expected: tuple = (200, 201)) -> None:
    if resp.status_code not in expected:
        logger.error("GitHub API %s returned %s: %s", action, resp.status_code, _extract_error_detail(resp))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API error on {action}: {resp.status_code} {_extract_error_detail(resp)}",
        )
