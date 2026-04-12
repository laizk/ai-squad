# AI Squad — Model Provider Setup

This repo can route the PM agent to different local model servers through worker env vars.

## Shared env vars

- `PM_LLM_PROVIDER`
- `PM_BASE_URL`
- `PM_API_KEY`
- `PM_MODEL`
- `PM_REQUEST_TIMEOUT_SECONDS`
- `PM_SERIALIZE_LOCAL_CALLS`
- `PM_LOCAL_CALL_LOCK_PATH`

## Supported provider values

- `lmstudio`
- `mlx_lm`
- `llama_cpp`
- `openai_compat`
- `ollama`

## Recommended default

For Apple Silicon local serving, prefer LM Studio in headless mode.

LM Studio official docs:
- headless service via `llmster`: https://lmstudio.ai/docs/developer/core/headless
- OpenAI-compatible API on port `1234` by default: https://lmstudio.ai/docs/developer/openai-compat

## Example settings

### LM Studio

```env
PM_LLM_PROVIDER=lmstudio
PM_BASE_URL=http://host.docker.internal:1234/v1
PM_API_KEY=
PM_MODEL=qwen2.5-coder:7b
PM_SERIALIZE_LOCAL_CALLS=true
```

Start LM Studio server:

```bash
lms daemon up
lms server start --port 1234
```

### MLX LM

Official note: the `mlx-lm` HTTP server is intended to be similar to the OpenAI chat API, but is not recommended for production.
Source: https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md

```env
PM_LLM_PROVIDER=mlx_lm
PM_BASE_URL=http://host.docker.internal:8080/v1
PM_MODEL=mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
```

### llama.cpp

```env
PM_LLM_PROVIDER=llama_cpp
PM_BASE_URL=http://host.docker.internal:8080/v1
PM_MODEL=/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
```

### Ollama

```env
PM_LLM_PROVIDER=ollama
OLLAMA_URL=http://host.docker.internal:11434
PM_MODEL=qwen2.5-coder:7b
```

## Notes

- `lmstudio`, `mlx_lm`, and `llama_cpp` all use the same OpenAI-compatible `POST /v1/chat/completions` path in the worker.
- `ollama` keeps its dedicated `/api/chat` path.
- `PM_API_KEY` is optional and only sent for OpenAI-compatible providers.
- `PM_SERIALIZE_LOCAL_CALLS=true` is the safe default for local runtimes. It serializes PM model calls across worker processes with a file lock to avoid LM Studio/llama.cpp/MLX/Ollama concurrency failures on a single machine.
- `PM_LOCAL_CALL_LOCK_PATH` defaults to `/tmp/ai-squad-pm-llm.lock`.
- During LM Studio testing with `qwen/qwen3.5-9b`, overlapping PM runs produced `400 Bad Request` responses backed by `Context size has been exceeded` in LM Studio server logs. The lock is intended to avoid that failure mode.
