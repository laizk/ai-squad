"""sandbox-dispatcher — accepts sandbox execution requests from workers.

Sits on the main platform network. Workers call POST /execute.
Writes a job file to the shared volume, polls for the result file written
by sandbox-runner (which has network_mode: none), then returns the result.

sandbox-runner never talks to this service directly — communication is
purely through files on the shared volume.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SANDBOX_IO      = Path(os.environ.get("SANDBOX_IO_PATH", "/sandbox-io"))
JOBS_DIR        = SANDBOX_IO / "jobs"
RESULTS_DIR     = SANDBOX_IO / "results"
POLL_INTERVAL   = float(os.environ.get("SANDBOX_POLL_INTERVAL",   "0.5"))
DISPATCH_TIMEOUT = float(os.environ.get("SANDBOX_DISPATCH_TIMEOUT", "120"))

app = FastAPI(title="sandbox-dispatcher", version="0.1.0")


# ── Models ─────────────────────────────────────────────────────────────────────

class FileContent(BaseModel):
    path: str
    content: str


class ExecuteRequest(BaseModel):
    files:   list[FileContent]
    command: list[str]
    timeout: float = 30.0       # execution timeout for the runner


class ExecuteResponse(BaseModel):
    job_id:           str
    exit_code:        int
    stdout:           str
    stderr:           str
    duration_seconds: float
    timed_out:        bool
    error:            str | None


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "sandbox-dispatcher"}


# ── Execute ────────────────────────────────────────────────────────────────────

@app.post("/execute", response_model=ExecuteResponse, status_code=status.HTTP_200_OK)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex
    job = {
        "job_id":  job_id,
        "files":   [f.model_dump() for f in req.files],
        "command": req.command,
        "timeout": req.timeout,
    }

    job_path    = JOBS_DIR    / f"{job_id}.json"
    result_path = RESULTS_DIR / f"{job_id}.json"

    job_path.write_text(json.dumps(job), encoding="utf-8")
    logger.info("Dispatched job %s command=%s files=%d", job_id, req.command, len(req.files))

    # Poll for result — runner has no network so it can't call us back
    deadline = time.monotonic() + DISPATCH_TIMEOUT
    while time.monotonic() < deadline:
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                result_path.unlink(missing_ok=True)
                logger.info(
                    "Job %s complete exit_code=%s duration=%.2fs",
                    job_id, result.get("exit_code"), result.get("duration_seconds", 0),
                )
                return ExecuteResponse(**result)
            except (json.JSONDecodeError, OSError, TypeError):
                # Result file may still be mid-write — wait one more tick
                pass
        time.sleep(POLL_INTERVAL)

    # Timed out waiting for runner
    job_path.unlink(missing_ok=True)
    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail=f"sandbox runner did not return result within {DISPATCH_TIMEOUT}s",
    )
