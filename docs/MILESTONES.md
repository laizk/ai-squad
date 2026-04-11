# AI Squad — Implementation Phases
# Version: 0.2.0-architecture-refresh | Date: 2026-04-11

---

## Reading This Document

This roadmap uses **phases** for building the platform itself.

Project delivery inside the product still uses **milestones**.

Each phase includes:
1. purpose
2. deployable outcome
3. acceptance criteria
4. verification strategy
5. required evidence
6. shallow-implementation catchers

---

## Phase Summary

| Phase | Name | Must Be Useful On Its Own |
|---|---|---|
| P-1 | Skeleton | Repo boots with minimal API and UI |
| P0 | Schema + Health | Platform stores state and reports health truthfully |
| P1 | Versioned CRUD | Human can manage projects, team, milestones, tasks, revisions |
| P2 | Admin Core | Human can operate the system through UI with revision visibility |
| P3 | Orchestrator + Stub Agents | End-to-end workflow works without relying on model quality |
| P4 | Real PM Agent | Planning pipeline produces reviewable artifacts and issues |
| P5 | Dev Workflow + Sandbox | Safe implementation, review, test, and PR flow works |
| P6 | QA + Judge + Approval Evidence | Evidence-driven review gate works |
| P7 | GitHub Projects + Webhooks | External state sync becomes practical |
| P8 | UX + DevOps Optional Paths | Optional specialists work with skip logic |
| P9 | Prompt Evaluation | Prompt changes are measurable before adoption |
| P10 | Hardening | Retries, idempotency, violations, and failure modes are real |

---

## P-1 — Skeleton

### Purpose
Create the smallest possible working stack so later phases build on something deployable rather than on imagined structure.

### Deployable Outcome
`docker compose up` starts:
- postgres
- redis
- minimal control-api with `/health`
- minimal admin-web home page

### Acceptance Criteria
- `docker compose up -d` succeeds without missing build context or Dockerfile failures
- `GET /api/v1/health` returns 200 from control-api
- admin-web root loads without JavaScript or console errors
- stopping and restarting the stack preserves postgres data volume behavior

### Verification
- smoke test that creates no domain data but proves service connectivity
- manual browser load of admin-web

### Required Evidence
- compose status output
- control-api health response
- screenshot of admin-web shell

### Shallow Catchers
- empty directories with no Dockerfiles do not count
- green container health without successful HTTP checks does not count

---

## P0 — Schema + Health

### Purpose
Introduce the real schema, seed data, restricted app role, and health reporting that reflects actual dependencies.

### Deployable Outcome
The stack has a real database schema, seed policies, and truthful health endpoints.

### Acceptance Criteria
- all baseline tables, enums, and triggers are created by migrations
- application connects as restricted `squad_app`, not the schema owner
- health endpoint reports dependency state accurately for postgres, redis, and ollama
- revision rows reject direct `UPDATE` and `DELETE`
- seed data for default roles and GitHub policies exists

### Verification
- integration tests against real postgres
- direct SQL attempt to mutate `revisions`
- health degradation tests by temporarily stopping dependencies

### Required Evidence
- migration output
- role and privilege inspection output
- failing SQL mutation proof for revisions

### Shallow Catchers
- table count alone is insufficient
- a health endpoint that returns hardcoded `"ok"` fails this phase

---

## P1 — Versioned CRUD

### Purpose
Make the platform useful as a structured project tracker even before any agents exist.

### Deployable Outcome
A human can create and manage:
- projects
- team members
- project assignments
- milestones
- tasks
- revisions

### Acceptance Criteria
- every versioned write appends a revision with structured reason
- project assignment overrides do not mutate the global team member record
- approvals are bound to revision numbers
- stale approvals are flagged after later edits
- point-in-time reconstruction works for at least project, milestone, and task graph state

### Verification
- API integration tests for create, update, disable, and reconstruct-at-time
- stale approval invalidation test

### Required Evidence
- revision history response examples
- reconstruction test output
- stale approval example

### Shallow Catchers
- revision creation without correct read-path behavior fails
- storing a free-form reason string without structure fails

---

## P2 — Admin Core

### Purpose
Give the human a viable UI for operation and review before any AI output is trusted.

### Deployable Outcome
Admin-web supports list/detail/edit flows, revision history, notifications, and approval evidence inspection.

### Acceptance Criteria
- all P1 entities have list and detail views
- revision timeline shows meaningful diffs, not generic “updated” rows
- approval screen requires evidence and comment before approval
- stale approvals are visible in the UI
- system page shows health plus current or recent model activity

### Verification
- Playwright flows for create, edit, review, and approve paths
- manual walk-through of revision diff and stale approval indicators

### Required Evidence
- screen capture of key flows
- Playwright results

### Shallow Catchers
- UI shells with missing mutation flows fail
- approve buttons enabled before evidence is linked fail

---

## P3 — Orchestrator + Stub Agents

### Purpose
Prove end-to-end workflow mechanics before model quality becomes a confounding variable.

### Deployable Outcome
Long-lived workers, Redis queues, run creation, run-step sequencing, pause-for-human, and artifact persistence all work using deterministic stub agents.

### Acceptance Criteria
- run plan is visible, including skipped optional steps
- stub agent artifacts validate against output contracts
- step ordering, pause, resume, reject, and request-changes flows work
- duplicate trigger requests with the same idempotency key do not create duplicate runs

### Verification
- integration tests with stub PM and stub reviewer outputs
- duplicate-trigger test
- failure and retry test with deterministic stub failure

### Required Evidence
- completed stub run record
- paused-for-human state example
- idempotency test result

### Shallow Catchers
- direct function calls that bypass queueing fail this phase
- “workflow works” claims without retry or resume proof fail

---

## P4 — Real PM Agent

### Purpose
Replace the PM stub with a real model-backed planning step that produces useful, reviewable work.

### Deployable Outcome
The PM can turn a brief into spec artifacts, milestone/task breakdown, and bounded GitHub issue creation.

### Acceptance Criteria
- PM outputs validate against the real contract
- PM output passes content sanity checks, not just schema checks
- GitHub issues are created with traceable links to internal tasks
- decision logs contain substantive rationale
- human can inspect artifacts before approval

### Verification
- contract tests plus real-run integration tests
- content sanity checks for task count, AC density, and rationale length
- GitHub test repo verification

### Required Evidence
- generated spec artifact
- task artifact
- linked GitHub issues
- decision log record

### Shallow Catchers
- fewer than 3 tasks for a non-trivial brief is suspicious
- repetitive placeholder acceptance criteria fail
- issue count matching task count is not enough by itself

---

## P5 — Dev Workflow + Sandbox

### Purpose
Prove safe implementation and review flow with real branch, commit, PR, and sandbox execution behavior.

### Deployable Outcome
Jr Dev, Sr Reviewer, sandbox execution, and PR creation work end-to-end without exposing privileged GitHub credentials to workers.

### Acceptance Criteria
- branch and commit conventions are enforced
- sandbox execution uses isolated runner topology, not a process-level fiction
- Jr Dev cannot push to protected branches or unauthorized paths
- SR rejection moves task into rework and supports retry
- PR includes bounded implementation and test summary

### Verification
- safety tests for protected branches, force push, workflow file writes, and network egress
- integration test from PM artifact to PR creation
- manual review of PR readability

### Required Evidence
- PR link
- blocked-action safety records
- sandbox execution report

### Shallow Catchers
- tiny diffs for large tasks are suspicious
- stub tests or zero-duration test runs fail
- a single “cannot push main” test is insufficient

---

## P6 — QA + Judge + Approval Evidence

### Purpose
Make the review gate evidence-based instead of relying on output shape or LLM self-certification.

### Deployable Outcome
QA produces test evidence, judge produces rubric and recommendation, and the human approval UI requires linked evidence.

### Acceptance Criteria
- QA artifacts validate and correspond to real sandbox execution
- judge output includes scores, reasons, and recommendation
- judge calibration against a human-scored fixture set clears the defined threshold
- approval records store evidence rows, override data, and approved revision number

### Verification
- sandbox-backed QA tests
- judge calibration run against known-good and known-bad fixtures
- UI tests for evidence gating and human override path

### Required Evidence
- QA test results
- judge calibration report
- approval record with evidence rows

### Shallow Catchers
- judge score threshold mapping alone does not pass this phase
- evidence panel that is informative but not required fails

---

## P7 — GitHub Projects + Webhooks

### Purpose
Connect internal workflow state to GitHub project management without making local development impossible.

### Deployable Outcome
Project board sync, webhook ingestion, replay, and reconciliation reports work against a test repository.

### Acceptance Criteria
- webhook ingestion works through a documented local relay path
- every webhook event is stored append-only for audit
- reconciler surfaces mismatches instead of auto-mutating internal truth
- board updates remain bounded and readable

### Verification
- local relay test
- webhook replay test
- reconciliation report generation test

### Required Evidence
- stored webhook event example
- reconciliation report
- board sync example

### Shallow Catchers
- GitHub sync that only works on a public URL is not sufficient
- auto-apply sync without review path fails

---

## P8 — UX + DevOps Optional Paths

### Purpose
Add optional specialists without breaking the core sequential workflow.

### Deployable Outcome
UX and DevOps steps can be included or skipped explicitly based on task needs.

### Acceptance Criteria
- optional steps are represented explicitly as executed or skipped
- UX artifacts and DevOps artifacts validate against contracts
- skip logic is visible in run plans and UI

### Verification
- runs with UX/DevOps enabled and disabled
- UI verification of skipped-step visibility

### Required Evidence
- run with optional steps
- run with skipped optional steps

### Shallow Catchers
- hidden branch logic that silently omits steps fails

---

## P9 — Prompt Evaluation

### Purpose
Make prompt and team-member evolution measurable instead of anecdotal.

### Deployable Outcome
Prompt revisions can be evaluated against a golden task set before adoption.

### Acceptance Criteria
- prompt eval runs store revision under test, output artifact, and scores
- side-by-side comparison between old and new prompt revision is visible
- human can reject a prompt revision after evaluation without losing prior prompt history

### Verification
- golden-task regression run
- prompt revision comparison test

### Required Evidence
- prompt evaluation report
- before/after prompt score comparison

### Shallow Catchers
- prompt edits without evaluation path fail
- prompt evaluation that only stores the latest result and overwrites prior results fails

---

## P10 — Hardening

### Purpose
Make the platform resilient enough that failure modes are legible and controlled.

### Deployable Outcome
Retries, idempotency, cancellation cleanup, safety violation UI, and chaos-style failure tests all exist.

### Acceptance Criteria
- retry backoff is implemented and visible
- duplicate triggers are deduplicated
- cancellation preserves audit trail according to policy
- safety violations are visible in admin-web
- chaos tests cover dependency loss and malformed model output

### Verification
- retry and backoff tests
- dependency-failure integration tests
- safety violation UI tests

### Required Evidence
- failed-and-retried run example
- cancellation audit example
- safety dashboard screenshot

### Shallow Catchers
- “hardening” without negative-path tests fails
- logging violations without a UI or review path fails
