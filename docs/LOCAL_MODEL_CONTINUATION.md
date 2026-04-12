# AI Squad — Local Model Continuation Guide
# Version: 0.2.0-architecture-refresh | Date: 2026-04-12

---

## 1. Purpose

This document is for smaller local coding models such as Qwen 3.5, Gemma 4, or other non-frontier assistants that need to continue work after Codex or Claude.

It is not the architecture spec.  
It is a practical continuation playbook.

---

## 2. Read Order

Before changing code, read in this order:

1. `handovers/` newest file first
2. `CLAUDE.md`
3. `AGENTS.md`
4. `docs/MILESTONES.md`
5. `docs/API_DESIGN.md`
6. `docs/PLATFORM_SPEC.md` only if a design question is unclear

Then inspect the real repo state:

1. `git status --short`
2. changed files only
3. relevant router or page files

Do not start by “summarizing the whole codebase.”  
Read only what is needed for the current slice.

---

## 3. Operating Rules

Follow these rules strictly:

- Do not redesign the backend architecture.
- Do not invent new abstractions unless the current code is blocked without them.
- Do not treat a successful TypeScript build as proof the feature works.
- Do not assume the frontend contract matches the backend; read the router first.
- Do not overwrite unrelated dirty worktree changes.
- Do not edit `revisions` directly.
- Do not shorten `reason.detail` below 20 characters.
- Do not skip real HTTP verification after a Docker rebuild.

If the repo is dirty, work around existing changes instead of reverting them.

---

## 4. Known High-Value Facts

These details are easy for weaker models to miss:

- Admin web talks to control-api through `INTERNAL_API_URL`, not browser-side `localhost`.
- `admin-web/app/lib/api.ts` is server-only and is the canonical place for request helpers and shared frontend types.
- `reason.detail` is validated by the backend and must be at least 20 characters.
- Project-team deletion is soft-disable, not hard-delete.
- Revision history is append-only and enforced by the database.
- The Next standalone container must include copied static assets or CSS/JS 404s will happen.

Required Dockerfile behavior:

```dockerfile
RUN npm run build \
 && cp -r .next/static .next/standalone/.next/static \
 && cp -r public .next/standalone/public
```

Do not remove those copy steps.

---

## 5. Default Workflow

When asked to continue work:

1. Read the latest handover.
2. Inspect `git status --short`.
3. Identify the exact unfinished slice.
4. Read the backend route or model that defines the contract.
5. Patch the minimum files needed.
6. Rebuild only the affected service.
7. Validate the real HTTP path.
8. Only then describe the result.

If you are unsure whether the issue is in the UI or API, inspect the API router first.

---

## 6. Validation Standard

For `admin-web`, the minimum acceptable validation is:

1. `docker compose -f infra/docker-compose.yml build admin-web`
2. `docker compose -f infra/docker-compose.yml up -d admin-web`
3. fetch the affected page HTML
4. fetch the built CSS asset from `/_next/static/css/...`
5. if it is a mutation flow, call the real API and confirm the page reflects the new state

Do not stop at “build passed.”

If direct host `curl` is blocked, validate through the running container.

---

## 7. Small-Model Heuristics

To avoid getting lost:

- Prefer finishing one vertical slice over touching many files partially.
- Prefer copying an existing nearby pattern over inventing a new one.
- Prefer backend truth over assumptions from the UI.
- Prefer explicit strings and simple helpers over clever abstractions.
- Prefer adding one missing route or form over starting a broad refactor.

When reading a large file:

- find the exact component or action first
- read only the surrounding 100 to 200 lines
- patch that section

---

## 8. Current Project State

As of the latest frontier-model work:

- P1 is still partial overall, but core CRUD exists for projects, team members, assignments, milestones, tasks, and revisions.
- P2 now includes:
  - project list/detail
  - milestone and task forms
  - revision timeline
  - team-member list/detail
  - project assignment UI

Still missing or incomplete:

- meaningful revision diffs in the UI
- approval screen with evidence gating
- stale approval indicators
- system/health page
- Playwright coverage
- P3 worker orchestration

Unless the user explicitly redirects, stay in P2 breadth before jumping to P3.

---

## 9. Good Next Tasks

Safe next tasks for a smaller local model:

- add revision diff rendering to existing timeline entries
- add server-action error handling with inline validation feedback
- add a system page that shows current health dependencies
- add Playwright smoke coverage for project/team flows

Riskier tasks that need stronger discipline:

- approval entity flows
- stale approval invalidation logic
- orchestration and worker runtime work
- broad schema changes

---

## 10. Commit Discipline

When the slice is cohesive:

- make one bundled commit
- use a short subject line
- use the body to explain why the change matters
- do not include unrelated files like scratch notes or local tool folders

If validation required temporary smoke data, clean it back down when possible or state clearly what remains in the local database.

---

## 11. Failure Mode Checklist

Before saying “done,” check:

- Did you read the real backend route?
- Did you verify the page over HTTP?
- Did you verify the CSS asset path?
- Did you avoid touching unrelated dirty files?
- Did you keep `reason.detail` long enough?
- Did you preserve soft-delete and revision semantics?

If any answer is “no,” the task is not done.
