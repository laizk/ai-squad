# AI Squad — Tool-Agnostic Base Operating Specification
# Version: 0.2.0-architecture-refresh | Date: 2026-04-11
#
# This document is the source of truth for platform behavior.
# Tool-specific layers such as CLAUDE.md and AGENTS.md may add invocation guidance,
# but they must not contradict this base spec.

---

## 1. Platform Identity

AI Squad is a local, human-supervised software delivery platform that uses multiple specialized AI team members to produce auditable project work.

It is not a chatbot shell. It is a workflow system with:
- versioned project memory
- typed artifacts as the primary record of work
- human approval at delivery boundaries
- visible external execution trail in GitHub
- local-first execution on a single developer machine

---

## 2. Architectural Layers

The platform has three distinct layers. These must not be conflated.

### Layer A — Human Interface
How a human operates the system.

Examples:
- admin-web
- Claude Code
- Codex CLI
- curl or direct REST clients

This layer is pluggable. It does not define how unattended agents run.

### Layer B — Platform Runtime
How the platform stores state, schedules work, enforces permissions, and records evidence.

Core components:
- control-api
- PostgreSQL
- Redis
- github-svc
- sandbox-dispatcher
- sandbox-runner
- long-lived workers

### Layer C — Model Runtime
How prompts are executed against models.

Default V1:
- OpenAI-compatible SDK against Ollama

This layer is replaceable, but it is not provider-portable without code changes.

---

## 3. Core Operating Principles

### P1 — Local-first, human-supervised
The platform is optimized for single-operator local use first. Every meaningful delivery boundary requires explicit human review.

### P2 — Artifact-first workflow
Artifacts are the primary outputs of agent work. Free-form model conversation is not the system of record.

### P3 — Sequential by default
Workflow steps execute in a defined order by default. Optional steps may be skipped, but concurrency is introduced only where explicitly designed.

### P4 — Long-lived workers, not per-task agent containers
Agent logic runs in long-lived worker processes. The platform does not rely on cold-starting a new container for every step.

### P5 — Model-family scheduling
Workers are routed by model family to reduce Ollama reload thrash. Team member model choice is separate from queue topology, but queue topology must respect memory constraints.

### P6 — Central control plane
All authoritative state lives behind control-api and PostgreSQL. Agents do not write directly to the database and do not hold privileged GitHub credentials.

### P7 — Append-only history is enforced by discipline plus privilege
Revision history is append-only by application behavior, a database trigger, and a restricted application role with no DDL privileges. The trigger is defense in depth, not a magic guarantee.

### P8 — Structured reasons for all writes
Versioned writes require a structured reason:
- `category`
- `detail`
- optional references to related entities or comments

### P9 — Approval is evidence-based
Approval is bound to a specific entity revision and must include linked evidence. Approvals become stale if the approved entity changes later.

### P10 — GitHub is a visible trail, not the source of truth
GitHub shows externally visible execution: issues, branches, PRs, comments, checks, and milestone/project status. Internal prompts, full decision logs, and sensitive safety data stay inside the platform.

### P11 — Sandbox claims must match real isolation
The platform must not claim subprocess isolation it cannot provide. V1 sandbox isolation must rely on architecture that is viable on Docker Desktop for macOS.

### P12 — Failure handling is first-class
Runs and steps must support idempotency, retry, cancellation, stale approval detection, and explicit failure states. Happy path alone is not acceptable.

---

## 4. Runtime Model

### 4.1 Worker topology

V1 runtime uses long-lived workers grouped by model family:
- `workers.coder` for implementation-heavy roles
- `workers.prose` for PM, QA, judge, and similar roles
- `workers.housekeeping` for sync, cleanup, notifications, and retry dispatch

Each worker:
- polls Redis for assigned work
- loads role config from control-api
- writes artifacts and decisions back through control-api
- never holds GitHub App credentials directly

### 4.2 Optional workflow steps

The default role order remains:
1. PM
2. UX
3. Jr Dev
4. Sr Reviewer
5. QA
6. DevOps
7. Judge
8. Human Gate

But UX and DevOps are optional. The run plan must explicitly represent skipped steps instead of pretending the full chain always runs.

### 4.3 Model selection

Model selection exists at three scopes:
- team member default
- project assignment override
- run-step override

The actual model used for a step must be recorded on the step itself.

---

## 5. Sandbox Model

### 5.1 V1 implementation

V1 sandbox uses:
- `sandbox-dispatcher` on the main platform network
- `sandbox-runner` with `network_mode: none`
- shared job/result volume between the two services

Execution requests are written as job files. Results are written back as result files. This is slower than an in-process call, but it is materially closer to the isolation the platform claims.

### 5.2 Rules

- Only sandbox-runner executes repo code
- Only whitelisted commands are allowed
- Workspace access is limited to the target mount
- Timeouts and blocked actions generate safety violations
- Network egress from sandboxed execution is not permitted

---

## 6. GitHub Boundary

### 6.1 Service split

GitHub App credentials live only in `github-svc`.

Flow:
1. worker asks control-api for a GitHub action
2. control-api validates the action against role policy and run context
3. control-api calls github-svc
4. github-svc performs the GitHub API operation

### 6.2 Enforcement reality

GitHub does not enforce per-role permissions for this platform. The enforcement boundary is entirely internal:
- agents never receive the GitHub App private key
- agents never receive raw installation tokens
- control-api checks role policy before every GitHub write

### 6.3 Noise control

GitHub writes are rate-limited per run. Raw LLM dumps are never posted to GitHub. Summaries must be concise and human-readable.

---

## 7. Memory, Revisions, and Approvals

### 7.1 Versioned entities

The following are versioned:
- projects
- team members
- project assignments
- milestones
- tasks
- artifacts
- role policies
- prompts and prompt-linked settings

### 7.2 Revision requirements

Each revision stores:
- entity type
- entity id
- revision number
- actor
- structured reason
- change summary
- before snapshot or reference
- after snapshot or reference
- created timestamp

### 7.3 Large content

Large prompt or document bodies are stored in deduplicated content blobs and referenced by hash from revisions and artifacts.

### 7.4 Point-in-time reconstruction

Point-in-time reconstruction is a project-graph concern, not a single-row concern. The platform must support as-of reconstruction across projects, milestones, tasks, assignments, and approvals.

### 7.5 Approval semantics

Approvals must record:
- entity type and id
- approved revision number
- decision
- comment
- override flag and override reason when applicable
- linked evidence rows

If a later revision is created for that entity, prior approvals are marked stale.

---

## 8. Run Semantics

### 8.1 Idempotency and retries

Runs require an idempotency key. The orchestrator must avoid creating duplicate runs for the same trigger context.

Run steps support:
- attempt number
- max attempts
- next retry time
- terminal failure state when retries are exhausted

### 8.2 Cancellation

Cancellation is explicit and audited. The platform must record what was preserved, archived, or abandoned after cancellation.

### 8.3 Decision logs

Decision logs exist for auditability, but they are bounded records. They store summarized input/output plus targeted deep context where needed. They must not become an unbounded prompt dump table.

---

## 9. Portability Rules

Portability applies cleanly to the human interface layer and partially to the model runtime.

Portable without redesign:
- admin-web vs CLI vs scripted API usage
- Claude-specific instructions vs Codex-specific instructions for humans

Not portable without implementation changes:
- model provider adapters
- runtime SDK behavior
- tool-call orchestration specifics

The platform may be provider-adaptable. It is not provider-neutral by default.

---

## 10. Monitoring and Verification

Minimum required observability:
- health by dependency
- queue depth by worker family
- run counts and failure counts
- average step latency by role
- safety violation counts
- currently warm model or recent model activity

Human approval screens must surface evidence before action. The system should bias toward rejection until evidence is reviewed.

---

## 11. Definition Of Done

A work item is done only when:
1. acceptance criteria are met
2. required artifacts exist and validate
3. required sandbox execution succeeded or a human explicitly overrode the failure
4. reviewer and judge outputs are recorded when applicable
5. human approval is recorded against the current revision with linked evidence
6. GitHub trail has been updated to reflect the result

No item is done based solely on agent self-report.
