# AI Squad — Human Interface Layer
# Version: 0.2.0-architecture-refresh | Date: 2026-04-11
#
# This file describes how a human operates AI Squad from a terminal-oriented tool.
# It derives from docs/BASE_OPERATING_SPEC.md and docs/PLATFORM_SPEC.md.
# It does not define how unattended agents run internally.

---

## 1. Purpose

Use this layer when a human is driving the platform through Claude Code, Codex CLI, Cursor, or direct shell/API calls.

The human interface layer is pluggable. The authoritative behavior still lives in control-api and the platform docs.

---

## 2. Cross-Model Continuity

When work is handed between Codex, Claude, Cursor, or smaller local models such as Qwen or Gemma, all models should use the same continuation and validation discipline from `docs/LOCAL_MODEL_CONTINUATION.md`.

Treat that file as the shared reference for:
- read order
- validation standard
- frontend and backend design guardrails
- continuation after partial handovers or dirty worktrees

---

## 3. Human Operator Rules

- Operate the platform through `control-api` and `admin-web`.
- Do not bypass revisioned mutation paths with manual SQL edits.
- Do not treat GitHub as the source of truth for internal state.
- Review evidence before approval; approval is not a convenience click.
- Use project milestones for delivery work and platform phases for building AI Squad itself.

---

## 4. Local Stack Expectations

The platform target stack is:
- postgres
- redis
- ollama
- control-api
- admin-web
- workers
- github-svc
- sandbox-dispatcher
- sandbox-runner

Early phases may ship a smaller subset. The implementation roadmap in `docs/MILESTONES.md` defines what must exist at each stage.

---

## 5. Recommended Human Workflows

### Project setup
1. Create project
2. Add milestone(s)
3. Assign team members
4. Override models only where needed

### Review workflow
1. Inspect generated artifacts
2. Inspect sandbox/test evidence
3. Inspect GitHub trail
4. Approve, reject, or request changes with a real comment

### Prompt or team-member update
1. Edit prompt or model assignment
2. provide a structured reason
3. inspect revision diff
4. run prompt evaluation when available

---

## 6. What Humans Should Not Do

- do not edit `revisions` directly
- do not give workers direct GitHub credentials
- do not approve stale revisions without explicit override rationale
- do not trust a passing schema check as proof of useful output
- do not assume local webhook features work without relay setup

---

## 7. Approval Standard

Approval is valid only when:
- the entity revision under review is current
- required evidence is linked
- the comment explains why approval is warranted
- any override is explicit and justified

If a later edit occurs, previous approval becomes stale and must be revisited.

---

## 8. Human Verification Checklist

For any serious workflow output, ask:
- Does this artifact reflect the actual brief or task?
- Is the GitHub output readable and appropriately bounded?
- Did sandbox execution really happen?
- Are review findings substantive rather than generic?
- Would I reject this if I had to defend the approval later?

---

## 9. GitHub Usage Guidance

GitHub is for visibility, not for dumping every internal detail.

Expect to see:
- issues
- branches
- commits
- pull requests
- review summaries
- checks

Do not expect to see:
- full prompts
- full internal decision logs
- all raw test output
- internal safety diagnostics

---

## 10. Terminal-Friendly Commands

Examples of the kind of operations the human interface layer should support:

```bash
# health
curl http://localhost:8000/api/v1/health

# create project
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Example Project",
    "description": "Local-first AI delivery test",
    "reason": {
      "category": "initial_creation",
      "detail": "Creating the initial project container for platform validation."
    }
  }'

# trigger run
curl -X POST http://localhost:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "PROJECT_ID",
    "task_id": "TASK_ID",
    "workflow_type": "sequential",
    "reason": {
      "category": "initial_creation",
      "detail": "Starting the first workflow run for this task."
    }
  }'
```

---

## 11. Relationship To AGENTS.md

`CLAUDE.md` is about human operation.  
`AGENTS.md` is about unattended worker behavior.

They are complementary, not interchangeable.
