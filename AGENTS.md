# AI Squad — Agent Runtime Layer
# Version: 0.2.0-architecture-refresh | Date: 2026-04-11
#
# This file describes the unattended agent-runtime contract.
# It derives from docs/BASE_OPERATING_SPEC.md and docs/PLATFORM_SPEC.md.
# It does not define the human interface layer.

---

## 1. Purpose

This document exists for programmatic agent runtimes that execute workflow steps inside AI Squad.

It does not describe how a human operates the platform from a terminal. That belongs in `CLAUDE.md` or other human-interface guidance.

---

## 2. Runtime Assumptions

- Agents run as long-lived workers, not one container per task.
- Workers talk to `control-api`, not directly to PostgreSQL or GitHub.
- Workers use an OpenAI-compatible SDK against Ollama by default.
- The actual model used is resolved by control-api and recorded on the run step.
- GitHub App credentials are never available inside worker processes.

---

## 3. Core Tool Boundary

Agent runtimes must use control-api mediated actions for:
- fetching task context
- writing artifacts
- logging decisions
- requesting sandbox execution
- requesting GitHub actions
- pausing for human approval

Agents must not:
- call GitHub directly
- execute project code directly
- mutate revision history
- bypass artifact validation

---

## 4. Canonical Agent Tools

These tool definitions are the logical contract for the runtime layer.

### `get_task_context`
Fetch complete task, milestone, project, run-step, and prior artifact context.

### `write_artifact`
Write a typed artifact through control-api validation. The write includes a structured reason.

### `log_decision`
Write a bounded decision log entry after major reasoning steps.

### `request_sandbox_execution`
Ask control-api to dispatch sandboxed execution. Agents do not shell out locally.

### `request_github_action`
Request a policy-checked GitHub action such as creating an issue, branch, PR, comment, or check run.

### `submit_for_human_approval`
Pause the run or step with a summary and linked evidence references.

---

## 5. Required Agent Behavior

1. Read context from control-api at step start.
2. Resolve role configuration and output contract from control-api.
3. Produce typed output only.
4. Validate artifacts before treating the step as complete.
5. Log a decision summary with rationale.
6. Request sandbox execution when code needs to be built, linted, or tested.
7. Request GitHub actions only through control-api.
8. Pause for human review at defined workflow boundaries.

---

## 6. Failure Handling

Agents must handle:
- schema validation failures
- model malformed output
- sandbox denial or timeout
- GitHub permission denial
- transient control-api failures

They must not silently swallow these states. The step should fail, retry, or pause according to orchestrator policy.

---

## 7. Artifact Rules

Artifacts are the contract between steps.

Rules:
- artifacts are immutable
- new output means new artifact version or new artifact row
- artifact writes include structured reason
- partial invalid output is not accepted
- no free-form “done” message replaces an artifact

---

## 8. Decision Log Rules

Decision logs are required after major reasoning steps, but they are bounded.

They should contain:
- concise input summary
- concise output summary
- rationale of useful length
- references to relevant artifact or entity IDs

They should not become a raw transcript dump of full prompts and full responses by default.

---

## 9. Example Runtime Loop

```python
config = get_team_member_config(run_step_id)
context = get_task_context(task_id)

response = llm.generate(
    model=config.model,
    system=config.system_prompt,
    user=render_prompt(context),
)

validated = validate_output(response, config.output_contract)
artifact = write_artifact(
    run_step_id=run_step_id,
    artifact_type=validated.artifact_type,
    content=validated.content,
    reason={
        "category": "initial_creation",
        "detail": "Produced the planned output for this step from current task context."
    },
)

log_decision(
    run_step_id=run_step_id,
    decision_type="step_output",
    input_summary="Loaded task context and role configuration.",
    output_summary="Produced validated artifact for current step.",
    rationale="Selected the artifact shape required by the role contract and retained explicit assumptions."
)
```

---

## 10. Portability Boundary

This runtime layer is not the same thing as Claude Code or a terminal-based coding assistant.

Portable at this layer:
- swapping Ollama for another OpenAI-compatible backend with adapter work
- changing worker orchestration internals

Not portable by simple text substitution:
- moving from a human CLI tool to unattended workers
- changing tool-call semantics without implementation changes

---

## 11. Audit Expectations

An acceptable agent step leaves behind:
- run-step record
- validated artifacts
- decision log entry
- sandbox record when execution occurred
- GitHub action record when external state changed
- pause or completion state suitable for human review
