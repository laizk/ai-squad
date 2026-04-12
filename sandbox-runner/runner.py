"""Sandbox runner — isolated code execution.

Runs with network_mode: none. Polls /sandbox-io/jobs/ for job files,
executes the requested command in an ephemeral workspace, writes results
to /sandbox-io/results/, then cleans up.

Allowed commands (first token only):
  pytest  python  python3

No network access. No writes outside the ephemeral workspace.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s runner %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

SANDBOX_IO    = Path(os.environ.get("SANDBOX_IO_PATH", "/sandbox-io"))
JOBS_DIR      = SANDBOX_IO / "jobs"
RESULTS_DIR   = SANDBOX_IO / "results"
POLL_INTERVAL = float(os.environ.get("SANDBOX_POLL_INTERVAL", "0.5"))
MAX_OUTPUT    = int(os.environ.get("SANDBOX_MAX_OUTPUT_BYTES", str(64 * 1024)))  # 64 KB

ALLOWED_COMMANDS = {"pytest", "python", "python3"}


def main() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Sandbox runner started. Polling %s", JOBS_DIR)

    while True:
        for job_path in sorted(JOBS_DIR.glob("*.json")):
            try:
                _process_job(job_path)
            except Exception:
                logger.exception("Unhandled error processing %s", job_path)
                job_path.unlink(missing_ok=True)
        time.sleep(POLL_INTERVAL)


def _process_job(job_path: Path) -> None:
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read job file %s — skipping", job_path)
        job_path.unlink(missing_ok=True)
        return

    job_id  = job.get("job_id", job_path.stem)
    files   = job.get("files", [])
    command = job.get("command", [])
    timeout = float(job.get("timeout", 30))

    logger.info("Processing job %s command=%s files=%d", job_id, command, len(files))

    result = _execute(job_id=job_id, files=files, command=command, timeout=timeout)

    result_path = RESULTS_DIR / f"{job_id}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info(
        "Job %s done exit_code=%s duration=%.2fs",
        job_id, result["exit_code"], result["duration_seconds"],
    )

    # Remove job file last — dispatcher polls results, not job absence
    job_path.unlink(missing_ok=True)


def _execute(*, job_id: str, files: list[dict], command: list[str], timeout: float) -> dict:
    if not command:
        return _error_result(job_id, "empty command")

    first_token = Path(command[0]).name  # strip any path prefix
    if first_token not in ALLOWED_COMMANDS:
        return _error_result(
            job_id,
            f"command '{first_token}' is not in the allowed list: {sorted(ALLOWED_COMMANDS)}",
        )

    workspace = tempfile.mkdtemp(prefix=f"sq-{job_id[:8]}-")
    try:
        # Write files into workspace
        for f in files:
            path = Path(workspace) / f["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f["content"], encoding="utf-8")

        # Inherit a minimal env and set PYTHONPATH so src/ layouts resolve
        run_env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": workspace}

        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                command,
                cwd=workspace,
                env=run_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            exit_code = proc.returncode
            stdout    = proc.stdout[-MAX_OUTPUT:] if proc.stdout else ""
            stderr    = proc.stderr[-MAX_OUTPUT:] if proc.stderr else ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout    = (exc.stdout or b"")[:MAX_OUTPUT].decode(errors="replace")
            stderr    = f"[runner] execution timed out after {timeout}s"
        duration = time.monotonic() - start

        return {
            "job_id":            job_id,
            "exit_code":         exit_code,
            "stdout":            stdout,
            "stderr":            stderr,
            "duration_seconds":  round(duration, 3),
            "timed_out":         timed_out,
            "error":             None,
        }
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _error_result(job_id: str, message: str) -> dict:
    logger.warning("Job %s rejected: %s", job_id, message)
    return {
        "job_id":            job_id,
        "exit_code":         -1,
        "stdout":            "",
        "stderr":            f"[runner] {message}",
        "duration_seconds":  0.0,
        "timed_out":         False,
        "error":             message,
    }


if __name__ == "__main__":
    main()
