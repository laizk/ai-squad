# AI Squad — Control API Design
# Version: 0.2.0-architecture-refresh | Date: 2026-04-11
# Base URL: http://localhost:8000/api/v1

---

## Design Conventions

- All resources return JSON
- All timestamps are ISO 8601 UTC (`2026-04-11T12:00:00Z`)
- All IDs are UUIDs
- Pagination: `?page=1&per_page=50` (max 200); response includes `total`, `page`, `per_page`, `items`
- Mutations require a structured `reason` object — returns 422 if missing or malformed
- Errors: `{"error": "string", "detail": "string", "field_errors": [...]}`
- All writes return the updated resource (not 204)

---

## Health

### GET /health

Returns status of all dependencies.

**Response 200:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "postgres": "ok",
  "redis": "ok",
  "ollama": "ok",
  "ollama_models": ["qwen2.5-coder:14b", "mistral-nemo:12b"]
}
```

If any dependency is down: `{"status": "degraded", "postgres": "error", ...}`

---

## Projects

### POST /projects

Create a project.

**Request:**
```json
{
  "name": "Todo App",
  "description": "A simple todo application with authentication",
  "github_org": "my-org",
  "github_repo": "todo-app",
  "reason": {
    "category": "initial_creation",
    "detail": "Creating the initial project record for this product."
  }
}
```

**Response 201:**
```json
{
  "id": "uuid",
  "name": "Todo App",
  "description": "...",
  "status": "active",
  "github_org": "my-org",
  "github_repo": "todo-app",
  "github_project_id": null,
  "current_version": 1,
  "metadata": {},
  "created_at": "2026-04-11T12:00:00Z",
  "updated_at": "2026-04-11T12:00:00Z"
}
```

### GET /projects

List projects. Supports `?status=active` filter.

### GET /projects/{id}

Get project by ID.

### PATCH /projects/{id}

Update project fields. `reason` required.

**Request:**
```json
{
  "description": "Updated description",
  "reason": {
    "category": "scope_change",
    "detail": "Updating project scope after the planning session clarified delivery boundaries."
  }
}
```

---

## Team Members

### POST /team-members

Create a new team member.

**Request:**
```json
{
  "name": "specialist-fe",
  "role": "custom",
  "display_name": "Frontend Specialist",
  "description": "Expert in React and TypeScript frontend development",
  "skills": ["react", "typescript", "tailwind", "accessibility"],
  "provider": "ollama",
  "model": "qwen2.5-coder:14b",
  "system_prompt": "You are a frontend specialist...",
  "output_contract": {...},
  "github_role": "dev-jr",
  "permissions": {
    "can_create_issues": false,
    "can_create_prs": true,
    "can_merge_prs": false,
    "can_push_main": false,
    "allowed_branches": ["feature/*"],
    "can_write_workflows": false
  },
  "reason": {
    "category": "initial_creation",
    "detail": "Onboarding a frontend specialist for UI-heavy work on this project."
  }
}
```

**Response 201:** team member object with `current_version: 1`

### GET /team-members

List all team members. Supports `?role=dev-jr&is_active=true`.

### GET /team-members/{id}

Get team member by ID including current prompt.

### PATCH /team-members/{id}

Update team member. `reason` required.  
Changing `system_prompt` or `model` creates a revision.

### GET /team-members/{id}/revisions

List all revisions for a team member, ordered by `revision_number`.

**Response 200:**
```json
{
  "entity_type": "team_member",
  "entity_id": "uuid",
  "revisions": [
    {
      "revision_number": 1,
      "actor": "human:klaiz",
      "change_summary": "Initial onboarding",
      "reason": {
        "category": "initial_creation",
        "detail": "Onboarding frontend specialist for UI-heavy work."
      },
      "before_snapshot": null,
      "after_snapshot": {...},
      "created_at": "..."
    },
    {
      "revision_number": 2,
      "actor": "human:klaiz",
      "change_summary": "Updated system prompt to improve code quality focus",
      "reason": {
        "category": "prompt_tuning",
        "detail": "Tightened instructions after the prior output quality was below the expected standard."
      },
      "before_snapshot": {"system_prompt": "old prompt..."},
      "after_snapshot": {"system_prompt": "new prompt..."},
      "created_at": "..."
    }
  ]
}
```

---

## Project Team Management

### POST /projects/{id}/team

Add a team member to a project.

**Request:**
```json
{
  "team_member_id": "uuid",
  "model_override": "llama3.2:3b",
  "provider_override": null,
  "reason": {
    "category": "initial_creation",
    "detail": "Adding the PM team member for the initial planning phase of this project."
  }
}
```

**Response 201:** project_team_member object

### DELETE /projects/{id}/team/{member_id}

Remove member from project (soft: sets `disabled_at`, preserves history).

**Request:**
```json
{
  "reason": {
    "category": "scope_change",
    "detail": "Removing this assignment because the role is no longer needed in the current project phase."
  }
}
```

### PATCH /projects/{id}/team/{member_id}

Enable/disable or change model override.

**Request:**
```json
{
  "is_enabled": false,
  "disable_reason": "Taking a different approach to UX",
  "reason": {
    "category": "scope_change",
    "detail": "Disabling the UX assignment for the current sprint while using the existing design direction."
  }
}
```

### PATCH /projects/{id}/team/{member_id}/model

Change model or provider override for this project.

**Request:**
```json
{
  "model_override": "mistral-nemo:12b",
  "provider_override": "ollama",
  "reason": {
    "category": "fix",
    "detail": "Switching to a smaller model after validating that output quality remains acceptable for this project."
  }
}
```

---

## Milestones

### POST /projects/{id}/milestones

**Request:**
```json
{
  "title": "M1: User Authentication",
  "description": "Implement login, register, and session management",
  "acceptance_criteria": [
    "User can register with email and password",
    "User can log in and receive a session token",
    "Invalid credentials return a 401"
  ],
  "display_order": 1,
  "due_date": "2026-05-01",
  "reason": {
    "category": "initial_creation",
    "detail": "Creating the first project milestone from the approved PM planning output."
  }
}
```

### GET /projects/{id}/milestones

List milestones for project, ordered by `display_order`.

### GET /milestones/{id}

Get milestone detail including tasks, artifacts, and linked GitHub data.

### PATCH /milestones/{id}

Update milestone. Creates revision. `reason` required.

### GET /milestones/{id}/revisions

Revision history for a milestone.

---

## Tasks

### POST /milestones/{id}/tasks

**Request:**
```json
{
  "title": "Implement /auth/register endpoint",
  "description": "Create POST /auth/register that accepts email+password, validates, hashes, stores user",
  "assigned_role": "dev-jr",
  "priority": "high",
  "acceptance_criteria": [
    "Returns 201 with user ID on success",
    "Returns 422 on invalid email format",
    "Password is bcrypt-hashed before storage"
  ],
  "display_order": 1,
  "reason": {
    "category": "initial_creation",
    "detail": "Creating this task from the approved PM planning output."
  }
}
```

### GET /milestones/{id}/tasks

List tasks for milestone.

### PATCH /tasks/{id}

Update task status, description, or assignment. `reason` required.

### GET /tasks/{id}/revisions

Task revision history.

---

## Runs

### POST /runs

Trigger a workflow run. This is the main entry point for agent work.

**Request:**
```json
{
  "project_id": "uuid",
  "task_id": "uuid",
  "workflow_type": "full_sequential",
  "roles_to_run": ["pm", "dev-jr", "dev-sr", "qa", "judge"],
  "input": {
    "brief": "User story or task description override (optional)"
  },
  "reason": {
    "category": "initial_creation",
    "detail": "Starting the workflow run for the auth register implementation task."
  }
}
```

**`workflow_type` options:**
- `full_sequential` — all enabled agents in order
- `pm_planning` — PM only
- `dev_cycle` — dev-jr + dev-sr + sandbox
- `qa_only` — QA + sandbox
- `judge_only` — judge scoring only
- `custom` — specify `roles_to_run` explicitly

**Response 201:**
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "task_id": "uuid",
  "status": "created",
  "workflow_type": "full_sequential",
  "trigger_actor": "human:klaiz",
  "steps": [
    {"role": "pm", "step_order": 1, "status": "pending"},
    {"role": "dev-jr", "step_order": 2, "status": "pending"},
    ...
  ],
  "created_at": "..."
}
```

### GET /runs/{id}

Get run detail with current status and step statuses.

### GET /runs/{id}/steps

List all run steps with timing, model used, and artifact references.

### POST /runs/{id}/pause

Pause a running workflow after the current step completes.

### POST /runs/{id}/resume

Resume a paused workflow.

### POST /runs/{id}/cancel

Cancel a run. Steps already completed are preserved.

**Request:**
```json
{
  "reason": {
    "category": "scope_change",
    "detail": "Cancelling this run because the human reviewer decided to reroute to a different implementation approach."
  }
}
```

### GET /runs/{id}/steps/{step_id}/logs

Get the decision log and model call details for a specific run step.

---

## Artifacts

### GET /artifacts/{id}

Get artifact metadata.

**Response:**
```json
{
  "id": "uuid",
  "artifact_type": "spec",
  "name": "spec_v1.md",
  "storage_path": "proj-abc/m1/t3/run-xyz/pm/spec_v1.md",
  "content_hash": "sha256:...",
  "version": 1,
  "is_current": true,
  "superseded_by": null,
  "created_by_role": "pm",
  "created_at": "..."
}
```

### GET /artifacts/{id}/content

Return the raw content of the artifact. Content-Type set based on file type.

### GET /artifacts/{id}/versions

List all versions of this artifact (same task + artifact_type).

### GET /tasks/{id}/artifacts

List all artifacts for a task, grouped by artifact_type.

---

## Approvals

### POST /approvals

Create an approval decision bound to a specific revision.

**Request:**
```json
{
  "entity_type": "milestone",
  "entity_id": "uuid",
  "approved_revision_number": 3,
  "status": "approved",
  "comment": "PM output is solid. Tasks are well-scoped. GitHub Issues created correctly.",
  "override_used": false,
  "override_reason": null,
  "evidence": [
    {
      "evidence_type": "artifact",
      "artifact_id": "uuid1",
      "description": "Approved PM spec artifact"
    },
    {
      "evidence_type": "github_link",
      "external_url": "https://github.com/example/repo/issues/12",
      "description": "Representative GitHub issue created from the plan"
    }
  ]
}
```

**`status` options:** `approved`, `rejected`, `changes_requested`

**Response 200:** approval object with `decided_at` set.

### GET /approvals/{id}

Get approval detail.

### GET /entities/{entity_type}/{entity_id}/approvals

List approval history for an entity.

---

## Comments

### POST /comments

**Request:**
```json
{
  "entity_type": "milestone",
  "entity_id": "uuid",
  "body": "The acceptance criteria for this milestone need to be more specific.",
  "parent_id": null
}
```

### GET /entities/{entity_type}/{entity_id}/comments

List comments for an entity, threaded.

---

## Revisions

### GET /revisions/{entity_type}/{entity_id}

List all revisions for any entity. Returns ordered list by `revision_number`.

**Query params:**
- `?from_revision=2` — start from revision number
- `?to_revision=5` — end at revision number
- `?as_of=2026-04-01T00:00:00Z` — get snapshot at a point in time

---

## GitHub Sync

### GET /projects/{id}/github-sync

List all GitHub sync records for a project.

### POST /github-sync/force

Force re-sync of a specific entity to GitHub.

**Request:**
```json
{
  "entity_type": "task",
  "entity_id": "uuid",
  "reason": {
    "category": "fix",
    "detail": "Forcing re-sync because the GitHub issue was deleted and must be recreated from internal state."
  }
}
```

---

## Notifications

### GET /notifications

List notifications for the human operator.

**Query params:** `?is_read=false&page=1`

### POST /notifications/{id}/read

Mark a notification as read.

### POST /notifications/read-all

Mark all notifications as read.

---

## System / Admin

### GET /system/ollama/models

List currently available Ollama models and their status.

### POST /system/ollama/pull

Pull a model into Ollama.

**Request:**
```json
{"model": "llama3.2:3b"}
```

### GET /system/metrics

Return current system metrics snapshot.

```json
{
  "queue_depth": 3,
  "active_runs": 1,
  "last_24h_runs": 12,
  "avg_latency_ms_by_role": {
    "pm": 8200,
    "dev-jr": 45000,
    "dev-sr": 12000,
    "qa": 22000,
    "judge": 6000
  },
  "token_usage_last_24h": 125000,
  "safety_violations_last_24h": 0
}
```

---

## Error Responses

```json
// 400 Bad Request — invalid state transition
{
  "error": "InvalidStateTransition",
  "detail": "Cannot transition task from 'done' to 'in_progress'",
  "current_status": "done",
  "attempted_transition": "in_progress"
}

// 403 Forbidden — permission denied
{
  "error": "PermissionDenied",
  "detail": "Agent role 'dev-jr' is not permitted to push to branch 'main'",
  "role": "dev-jr",
  "resource": "branch:main",
  "action": "push"
}

// 422 Unprocessable Entity — validation failure
{
  "error": "ValidationError",
  "field_errors": [
    {"field": "reason", "message": "Field required"},
    {"field": "name", "message": "String must have at least 1 character"}
  ]
}

// 409 Conflict — revision conflict
{
  "error": "RevisionConflict",
  "detail": "Entity was modified since you last read it. Expected version 3, found 4.",
  "expected_version": 3,
  "current_version": 4
}
```
