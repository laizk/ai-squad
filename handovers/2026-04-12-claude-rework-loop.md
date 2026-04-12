# AI Squad — Claude Handover (P5 Complete + Rework Loop)

**From:** Claude Sonnet 4.6  
**For:** Codex or follow-on model  
**Date:** 2026-04-12  
**Repo:** `/Users/klaiz/Documents/Github/ai-squad`

---

## Read this first

- User preference: no overengineering, real validation, short direct answers
- Sequential Docker rebuilds only: `build` first, then `up -d`
- llama-server is the production inference backend (not mlx-lm)
- Model split: dev-jr → Ollama `qwen2.5-coder:7b`, dev-sr + PM → llama-server 35B Q4

---

## Current repo state

**Uncommitted:**
- `workers/app/tasks.py` — rework loop added (not yet committed)

**Untracked:**
- `handovers/2026-04-12-claude-rework-loop.md` (this file)
- `logs/` (user-owned, untouched)
- `docs/MODEL_PROVIDER_SETUP.md`

**Recent commits (all P5):**
```
8d12850 fix(sandbox): set PYTHONPATH to workspace so src/ layout imports resolve
786113d feat: split model config per agent role (dev-jr → ollama, dev-sr → llama-server)
b6eb6bc feat(P5/slice-5): wire sandbox into dev agent + per-role model env vars
c7bd401 feat(P5/slice-4): add real reviewer agent with thinking-token handling
581cc2f feat(P5/slice-3): add sandbox-dispatcher + sandbox-runner with network isolation
```

The commit for the rework loop has NOT been made yet. Do that first.

---

## What was completed this session

### P5 Milestone: Dev Workflow + Sandbox — all 5 slices + rework loop

**Slice 1 — github-svc expansion** (`github-svc/app/main.py`)
- `POST /api/v1/branches` — creates branch off main via GitHub App JWT
- `POST /api/v1/commits` — commits files using Git Trees API
- `POST /api/v1/pulls` — opens PR

**Slice 2 — dev_agent** (`workers/app/agents/dev_agent.py`)
- Calls DEV_JR model (Ollama by default) to generate implementation files
- Runs sandbox before committing (non-fatal if unavailable)
- Pushes branch + commit + PR via github-svc (non-fatal if unconfigured)
- Produces `dev_output` and `sandbox_result` artifacts
- File contents embedded in `dev_output` so reviewer can read the code

**Slice 3 — sandbox** (`sandbox-runner/`, `sandbox-dispatcher/`)
- sandbox-dispatcher: FastAPI on port 8090, writes job JSON to shared volume, polls for result
- sandbox-runner: no network, polls jobs dir, executes in ephemeral tmpdir
- Command whitelist: `pytest`, `python`, `python3`
- PYTHONPATH set to workspace root so `from src.x import y` resolves

**Slice 4 — reviewer_agent** (`workers/app/agents/reviewer_agent.py`)
- Calls DEV_SR model (llama-server 35B) for substantive code review
- Reads `dev_output` and `sandbox_result` from prior_artifacts
- Produces `review_findings` artifact: `{verdict, findings, recommendation}`
- Valid verdicts: `approved` | `changes_requested` | `rejected`

**Slice 5 — sandbox wired into dev_agent**
- Dev agent posts to `CONTROL_API_URL/api/v1/sandbox/execute`
- control-api proxies to sandbox-dispatcher
- Sandbox result included in dev_output for reviewer context

**Rework loop** (`workers/app/tasks.py` — `_maybe_rework`)
- After dev-sr completes, checks verdict in `review_findings`
- If `changes_requested` and retries < `MAX_REWORK_RETRIES` (default 2):
  - Inserts new `dev-jr` + `dev-sr` step pair at end of run_steps
  - Dispatches new dev-jr step immediately
  - Returns early — run stays `running`
- Rework dev-jr automatically sees prior `review_findings` via existing `prior_artifacts` query (all artifacts for run, ordered by created_at)
- Retry cap: `DEV_REWORK_MAX_RETRIES` env var, default 2

---

## Key shared helpers (all in `pm_agent.py`, imported by other agents)

```python
_extract_response_content(body)  # strips <think>…</think>, falls back to reasoning_content
_parse_json(raw)                 # raw_decode scan — finds valid JSON even with preamble
_local_model_call_lock(provider) # fcntl.flock to serialize local model calls
_resolve_base_url()              # resolves PM base URL from provider/env
```

---

## Docker Compose env (workers service) — current production defaults

```yaml
PM_LLM_PROVIDER: llama_cpp
PM_BASE_URL: http://host.docker.internal:8080/v1
PM_MODEL: qwen3.5-35b-a3b-q4
DEV_JR_PROVIDER: ollama
DEV_JR_MODEL: qwen2.5-coder:7b
DEV_SR_PROVIDER: llama_cpp          # falls back to PM vars if unset
DEV_SR_BASE_URL: (empty — falls back to PM_BASE_URL)
DEV_SR_MODEL: (empty — falls back to PM_MODEL)
```

Inference backends running on host:
- llama-server (llama.cpp): port 8080, `Qwen3.5-35B-A3B-Q4_K_M.gguf`, ctx 16384
- Ollama: port 11434, `qwen2.5-coder:7b` pulled

---

## DB migrations applied

```
007_dev_output_artifact_type.sql    — adds 'dev_output' to artifact_type enum
008_sandbox_result_artifact_type.sql — adds 'sandbox_result' to artifact_type enum
```

`review_findings` was already in the original enum (005).

---

## Known issues / things to watch

1. **Qwen3 thinking tokens** — `/no_think` prefix on all user messages disables extended reasoning. If removed, model may exceed ctx-size 16384. Keep it.

2. **Empty `files: []` from model** — dev_agent raises RuntimeError if model returns no files. This surfaces as a step failure, not a silent bad artifact.

3. **Ollama for dev-jr** — `DEV_JR_BASE_URL` is empty in docker-compose, so `_resolve_dev_jr_url()` falls through to `OLLAMA_URL` (`http://host.docker.internal:11434`). This is intentional.

4. **Sandbox 503** — both dev_agent and control-api sandbox proxy return a `skipped` result rather than failing the step. Reviewer notes "not available" in that case.

5. **rework loop uses step.metadata** — new rework steps have `{"rework_retry": N}` in their metadata JSONB. This is informational; no code reads it back currently.

---

## What to do next

### Immediate
1. Commit the rework loop:
   ```bash
   cd /Users/klaiz/Documents/Github/ai-squad
   git add workers/app/tasks.py handovers/2026-04-12-claude-rework-loop.md
   git commit -m "feat(P5/rework): queue new dev-jr+dev-sr when reviewer requests changes (max 2 retries)"
   ```

2. Rebuild workers to pick up the change:
   ```bash
   docker compose -f infra/docker-compose.yml build workers
   docker compose -f infra/docker-compose.yml up -d workers
   ```

### P6 — QA + Judge + Approval Evidence

The milestone after P5. Expected slices:
- **qa_agent**: runs test suite, produces `test_results` artifact (pass/fail + coverage)
- **judge_agent**: evaluates all prior artifacts (spec, dev_output, review_findings, test_results) and produces `rubric_score` artifact with a structured recommendation
- **approval evidence**: wire judge output into the approval UI so human approval has machine-generated evidence attached
- **WORKFLOW_STEPS["dev_cycle"]** extension: add `qa` and `judge` steps after `dev-sr`

The admin-web approval UI already shows a stale-badge if the revision under review is outdated. Judge output should be attached as a linked artifact on the approval request so reviewers can see it.

### Test command for the full dev_cycle
```bash
docker cp control-api/tests/ squad-control-api:/app/tests/
docker compose -f infra/docker-compose.yml exec control-api pytest -q tests/test_reviewer_agent.py -v --tb=short
```

Expected: 3 artifacts produced — `dev_output`, `sandbox_result`, `review_findings`. Duration ~3-5 min depending on model speed.
