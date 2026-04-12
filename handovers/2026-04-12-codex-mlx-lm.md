# AI Squad — Codex Handover (LM Studio Debug + MLX-LM Next)

**From:** Codex (GPT-5)  
**For:** Claude Sonnet or another follow-on model  
**Date:** 2026-04-12  
**Repo:** `/Users/klaiz/Documents/Github/ai-squad`

## Read this first

- User preference remains the same:
  - no overengineering
  - real validation, not inferred correctness
  - short direct answers
  - sequential Docker rebuilds only: `build` first, then `up -d`
- User now wants to pivot from LM Studio debugging to trying `mlx-lm`.
- I am stopping before a commit. Nothing in this slice is committed yet.

## Current uncommitted repo state

Tracked modified:
- `workers/app/agents/pm_agent.py`
- `infra/docker-compose.yml`
- `control-api/tests/test_pm_agent.py`

Untracked:
- `docs/MODEL_PROVIDER_SETUP.md`
- `handovers/2026-04-12-codex-mlx-lm.md`
- `logs/` (user-owned, untouched)

## What changed in code

### `workers/app/agents/pm_agent.py`

This file now supports multiple providers:
- `lmstudio`
- `mlx_lm`
- `llama_cpp`
- `openai_compat`
- `ollama`

Important additions:
- `PM_LLM_PROVIDER`
- `PM_BASE_URL`
- `PM_API_KEY`
- `PM_REQUEST_TIMEOUT_SECONDS`
- `PM_SERIALIZE_LOCAL_CALLS`
- `PM_LOCAL_CALL_LOCK_PATH`

Important behavior:
- OpenAI-compatible providers all use `POST /v1/chat/completions`
- Ollama still uses `/api/chat`
- OpenAI-compatible HTTP failures now log and return the response body snippet
- local model calls are serialized with a file lock by default

### Why the lock was added

LM Studio failures were not random.

Root cause found in:
- `~/.lmstudio/server-logs/2026-04/2026-04-12.1.log`

The overlapping PM runs against `qwen/qwen3.5-9b` failed with:
- `Context size has been exceeded`
- KV/cache exhaustion while two requests overlapped

The worker-side mitigation is:
- serialize local model calls with `fcntl.flock`
- default lock path: `/tmp/ai-squad-pm-llm.lock`

I mechanically validated the lock in-container with two concurrent Python processes:
- worker 2 blocked until worker 1 released the lock

### `docs/MODEL_PROVIDER_SETUP.md`

Added/expanded:
- provider list
- example LM Studio / MLX LM / llama.cpp / Ollama envs
- new lock-related env vars
- note that local runtimes should keep `PM_SERIALIZE_LOCAL_CALLS=true`
- note documenting the LM Studio concurrency/context failure mode

### `infra/docker-compose.yml`

Current worker defaults are still set to LM Studio:
- `PM_LLM_PROVIDER=lmstudio`
- `PM_BASE_URL=http://host.docker.internal:1234/v1`
- `PM_MODEL=qwen/qwen3.5-9b`

I reverted away from the temporary `1235` test port before stopping.

### `control-api/tests/test_pm_agent.py`

This file was already generalized away from Ollama-specific wording:
- references “configured local model server” instead of only Ollama

## What was validated

### LM Studio via existing local API

When LM Studio’s OpenAI-compatible endpoint on `1234` was available, this passed:
- `docker cp control-api/tests/test_pm_agent.py squad-control-api:/app/tests/test_pm_agent.py`
- `docker compose -f infra/docker-compose.yml exec control-api pytest -q tests/test_pm_agent.py -v --tb=short`

Observed result:
- `2 passed, 2 skipped in 459.56s`

Artifact quality was acceptable:
- `spec`, `tasks`, and `decision_log` all wrote correctly
- `sanity_check.passed = true`

### Explicit LM Studio `1235` path

I tested a separate LM Studio port and got:
- `1 failed, 2 passed, 1 skipped in 326.41s`

Failure:
- worker saw `400 Bad Request` from `POST /v1/chat/completions`

Later correlated to LM Studio server log:
- `Context size has been exceeded`

### Lock validation

After adding serialization, I rebuilt workers and ran a direct concurrency check:

Command used:
```bash
docker compose -f infra/docker-compose.yml exec workers python -c "import multiprocessing as mp, time; from app.agents.pm_agent import _local_model_call_lock; start=time.time();
def worker(i):
    t0=time.time()-start
    with _local_model_call_lock('lmstudio'):
        t1=time.time()-start
        print(f'worker={i} requested={t0:.2f} acquired={t1:.2f}', flush=True)
        time.sleep(1.2)
        t2=time.time()-start
        print(f'worker={i} released={t2:.2f}', flush=True)
procs=[mp.Process(target=worker,args=(i,)) for i in (1,2)]
[p.start() for p in procs]
[p.join() for p in procs]"
```

Observed:
- worker 2 acquired only after worker 1 released

## What is currently blocked

True cold-start LM Studio headless mode is still not reliable on this machine.

Observed:
- `lms daemon up` times out
- `lms daemon status` stays `LM Studio is not running`
- simple GUI relaunch attempts from terminal did not restore `localhost:1234`

So the next model-serving attempt should move to `mlx-lm` instead of spending more time on LM Studio in this session.

## MLX-LM current state

I installed `mlx-lm` on the host with:
```bash
python3 -m pip install mlx-lm
```

Important install note:
- scripts were installed into `/Users/klaiz/Library/Python/3.11/bin`
- that directory is not on `PATH`

But the first import test did not succeed in the current default Python environment.

Checked locally:
```bash
python3 -c "import mlx_lm; print('mlx_lm_ok')"
```

Result:
- import failed
- root cause is not “mlx-lm missing” anymore
- root cause appears to be a mixed-architecture Python environment

Observed failure signature:
- NumPy C-extension import error
- incompatible architecture: active NumPy is `x86_64`, but `mlx-lm`/`mlx` expects `arm64`

Useful checks already done:
```bash
which -a python3
file /usr/local/bin/python3
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "import platform; print(platform.machine())"
```

Observed:
- `/usr/local/bin/python3` is universal, but the active environment is mixed and currently broken for MLX-LM
- `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` reports `arm64`

## Recommended next steps for Sonnet

1. Do not continue with the current `/usr/local/bin/python3` environment for MLX-LM.

2. Use a clean arm64 Python, most likely:
```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
```

3. Prefer creating a fresh venv with that interpreter and reinstalling there:
```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m venv <venv>
<venv>/bin/python -m pip install --upgrade pip
<venv>/bin/python -m pip install mlx-lm
```

4. Verify import and server help from that clean venv:
```bash
<venv>/bin/python -c "import mlx_lm; print('mlx_lm_ok')"
<venv>/bin/python -m mlx_lm.server --help
```

5. Start the MLX-LM OpenAI-compatible server on the host.
   - target repo config is already aligned to:
     - `PM_LLM_PROVIDER=mlx_lm`
     - `PM_BASE_URL=http://host.docker.internal:8080/v1`

6. Temporarily update worker env in `infra/docker-compose.yml` to:
   - `PM_LLM_PROVIDER: ${PM_LLM_PROVIDER:-mlx_lm}`
   - `PM_BASE_URL: ${PM_BASE_URL:-http://host.docker.internal:8080/v1}`
   - choose a real installed MLX model identifier

7. Rebuild and restart workers sequentially:
```bash
docker compose -f infra/docker-compose.yml build workers
docker compose -f infra/docker-compose.yml up -d workers
```

8. Copy the PM test file into the control-api container and rerun:
```bash
docker cp control-api/tests/test_pm_agent.py squad-control-api:/app/tests/test_pm_agent.py
docker compose -f infra/docker-compose.yml exec control-api pytest -q tests/test_pm_agent.py -v --tb=short
```

9. Inspect the latest artifacts from `/api/v1/runs` if tests pass.

10. Only commit after:
   - MLX-LM run actually passes
   - artifacts look acceptable
   - worker config is in a clean, intentional state

## Practical recommendation

Because the worker now serializes local calls, MLX-LM has a better chance of behaving reliably than the earlier LM Studio overlap tests. Keep the lock enabled unless there is clear evidence that the chosen local server handles concurrent PM generations safely on this machine.
