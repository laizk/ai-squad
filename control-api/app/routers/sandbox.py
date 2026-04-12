"""Sandbox execution proxy.

Workers call POST /api/v1/sandbox/execute. This router forwards the
request to sandbox-dispatcher and returns its response. Workers never
talk to sandbox-dispatcher directly.
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SANDBOX_DISPATCHER_URL = os.environ.get(
    "SANDBOX_DISPATCHER_URL", "http://sandbox-dispatcher:8090"
)

router = APIRouter(prefix="/api/v1/sandbox", tags=["sandbox"])


class FileContent(BaseModel):
    path: str
    content: str


class SandboxExecuteRequest(BaseModel):
    files:   list[FileContent]
    command: list[str]
    timeout: float = 30.0


@router.post("/execute", status_code=status.HTTP_200_OK)
async def sandbox_execute(req: SandboxExecuteRequest) -> dict:
    try:
        resp = httpx.post(
            f"{SANDBOX_DISPATCHER_URL}/execute",
            json=req.model_dump(),
            timeout=req.timeout + 30.0,  # extra headroom for dispatcher overhead
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sandbox-dispatcher is not reachable",
        )

    if resp.status_code == 504:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="sandbox runner timed out",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"sandbox-dispatcher returned {resp.status_code}",
        )

    return resp.json()
