# AI Squad — Platform Specification
**Version**: 0.2.0-architecture-refresh  
**Date**: 2026-04-11  
**Status**: Revised design baseline

---

## A. Executive Summary

AI Squad is a local, human-supervised software delivery platform that runs a structured AI team against real project work. It is designed for milestone-based delivery, durable project memory, visible GitHub execution, and human verification before trust.

This revision makes five material changes to the original baseline:
- replaces the conflicting per-task container story with long-lived workers
- reframes platform milestones as implementation phases
- corrects overclaimed guarantees around append-only history and sandbox isolation
- formalizes evidence-based approvals and stale approval invalidation
- separates human-interface portability from agent-runtime portability

---

## B. Product Framing

The platform acts like a supervised delivery organization:

```
Human operator
  -> defines project scope and team composition
  -> reviews artifacts and evidence
  -> approves, rejects, or requests changes

Platform runtime
  -> stores state
  -> routes work
  -> enforces policy
  -> records decisions

AI team members
  -> produce typed artifacts
  -> hand off work in a defined sequence
  -> never self-certify completion
```

The external visible trail lives in GitHub. The authoritative internal trail lives in PostgreSQL and artifact storage.

---

## C. V1 Scope

V1 is successful if it can do all of the following on a single local machine:
- define a project and assign a team
- produce a milestone plan and task breakdown
- execute a safe implementation step via sandboxed code execution
- create a bounded GitHub trail of issues, branches, PRs, comments, and checks
- preserve revision history without silent overwrite
- force a human to inspect evidence before approval

V1 explicitly does not attempt:
- fully autonomous delivery
- horizontal scale
- cloud-first multi-tenant deployment
- provider-neutral runtime abstractions

---

## D. Revised Architecture

### D.1 System diagram

```
┌──────────────────────────────────────────────────────────────┐
│ Human operator                                               │
│ - admin-web                                                  │
│ - CLI clients such as Claude Code / Codex / curl             │
└──────────────────────────────┬───────────────────────────────┘
                               │
                     ┌─────────▼─────────┐
                     │     admin-web     │
                     └─────────┬─────────┘
                               │ REST
┌──────────────────────────────▼───────────────────────────────┐
│ control-api                                                   │
│ - authoritative state                                         │
│ - permission gate                                             │
│ - workflow orchestration                                      │
│ - approval and evidence logic                                 │
└───────┬────────────┬──────────────┬──────────────┬────────────┘
        │            │              │              │
   postgres        redis        github-svc   sandbox-dispatcher
        │            │              │              │
        │      ┌─────▼─────┐        │        shared volume
        │      │ workers   │        │              │
        │      │ coder     │        │         ┌────▼────┐
        │      │ prose     │        │         │sandbox  │
        │      │ housekeep │        │         │runner   │
        │      └─────┬─────┘        │         │network  │
        │            │              │         │none     │
        │         ollama            │         └─────────┘
        └──────────────────────────────────────────────────────
```

### D.2 Why this architecture

#### Long-lived workers
The original spec mixed Celery and ephemeral task containers. That creates duplicate scheduling paths and unclear ownership. V1 uses long-lived workers only.

#### Model-family queues
Workers are grouped by model family to reduce Ollama reload churn. The scheduler can still select a specific model per step, but the queue topology is designed around actual memory limits.

#### Separate github-svc
The GitHub App key is isolated from workers. This makes the permission boundary real instead of policy-only.

#### Realistic sandbox isolation
The platform does not pretend a Python child process can drop network access on macOS Docker. V1 sandbox isolation is implemented with a network-isolated runner and file-based job dispatch.

---

## E. Core Design Corrections

### E.1 History model

The original append-only story was directionally right but overstated. Revised stance:
- control-api never mutates revision rows
- PostgreSQL trigger blocks ordinary `UPDATE` and `DELETE`
- app role has no DDL privileges
- audits treat the trigger as defense in depth, not as an absolute guarantee

### E.2 Approval model

Approvals are now tied to specific revisions and can become stale. Approval without evidence is not allowed unless a project-level override says otherwise.

### E.3 Evidence model

Evidence is a first-class table, not a loose array of artifact IDs. An approval may include artifacts, logs, screenshots, external links, or test records.

### E.4 Retry and idempotency

Runs and run steps now carry retry and idempotency fields. Duplicate trigger attempts should return the existing run rather than create a second one.

### E.5 Portability

Claude Code and Codex are human-interface variants for this repo, not interchangeable unattended runtimes. The internal agent runtime remains an OpenAI-compatible SDK against Ollama unless explicitly changed.

---

## F. GitHub Operating Model

### F.1 What GitHub is for

GitHub contains the externally visible delivery trail:
- project or milestone issues
- task issues
- feature and fix branches
- commits
- pull requests
- bounded comments and checks

### F.2 What stays internal

The following stay inside the platform:
- prompts and prompt revisions
- full decision logs
- internal scoring detail
- safety violation internals
- raw model transcripts

### F.3 Practical constraints

The platform must control GitHub noise:
- max issues per run
- max comments per run
- summary comments when limits are reached
- no raw LLM dumps

### F.4 Branch protection compatibility

Agents do not merge to `main`. Staging may be agent-assisted. Promotion to `main` is a separate human action.

### F.5 Local webhook development

Webhook-based sync in local development uses a relay such as `smee.io`. The platform must also support manual replay for testing.

---

## G. Team, Roles, and Model Selection

Three concepts are distinct:

### G.1 Role
The type of work: PM, UX, Jr Dev, Sr Reviewer, QA, DevOps, Judge, or custom specialist.

### G.2 Team member
A concrete reusable persona with:
- name
- role
- specialty
- prompt
- output contract
- default provider and model
- GitHub policy binding

Multiple team members may share the same role.

### G.3 Assignment
A project-level binding of a team member, optionally with provider or model overrides and enabled/disabled state.

### G.4 Model precedence
Actual model resolution order:
1. run-step override
2. project assignment override
3. team member default

The resolved model is written to the run step.

---

## H. Memory and Revision Strategy

### H.1 Content storage
Small snapshots can be stored inline. Large prompt and document bodies are deduplicated in `content_blobs` and referenced by hash.

### H.2 Point-in-time reconstruction
Project memory requires graph reconstruction, not just single-entity history. The platform must provide project-as-of queries spanning projects, milestones, tasks, assignments, and approvals.

### H.3 Structured reason
Every write reason includes:
- category
- detail
- optional references

This replaces the weak `reason >= 10 chars` approach.

---

## I. Run and Step Model

Each run has:
- workflow type
- idempotency key
- trigger actor
- attempt number
- cancellation policy

Each step has:
- role
- assigned team member
- actual model and provider used
- status
- attempt number
- max attempts
- retry schedule
- bounded decision metadata

Optional roles are explicitly marked `skipped`.

---

## J. Safety Model

### J.1 Sandbox
- only sandbox-runner executes code
- only whitelisted commands run
- timeouts and violations are recorded
- network egress is blocked by topology, not wishful subprocess control

### J.2 GitHub
- no direct agent GitHub access
- no push to protected branches
- no force push
- workflow file writes only for roles explicitly allowed

### J.3 Secrets
Secret scanning is advisory but blocking. A flagged write goes to human review rather than silently proceeding or pretending the scanner is perfect.

---

## K. Admin UX Requirements

The admin UI must support:
- project and milestone management
- revision timelines with useful diffs
- run timelines and step detail
- approval evidence inspection
- stale approval visibility
- safety violation visibility
- team member prompt and model history
- notification triage
- system status including model activity

The approval screen should show evidence before actions. Default posture is skeptical review, not optimistic approval.

---

## L. Phase Roadmap

Implementation phases are defined in [docs/MILESTONES.md](/Users/klaiz/Documents/Github/ai-squad/docs/MILESTONES.md), which now uses `P-1`, `P0`, `P1`, ... instead of overloading the word milestone.

The important sequencing changes are:
- add a scaffold phase before infrastructure claims
- add a stub-agent phase before real LLM quality matters
- add prompt evaluation before hardening is declared complete

---

## M. Non-Goals For This Revision

This revision does not try to:
- finalize every prompt
- lock a perfect schema for future cloud deployment
- overengineer distributed scheduling
- claim tamper-proof guarantees stronger than the host can actually support

It is a realism pass so the next implementation work starts from constraints that are true.
