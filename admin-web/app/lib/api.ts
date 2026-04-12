import "server-only";

function getApiUrl() {
  return (
    process.env["INTERNAL_API_URL"] ??
    process.env["NEXT_PUBLIC_API_URL"] ??
    "http://localhost:8000"
  );
}

type ReasonCategory =
  | "initial_creation"
  | "scope_change"
  | "prompt_tuning"
  | "fix"
  | "rollback"
  | "human_override"
  | "policy_change"
  | "retry"
  | "other";

type ApiRequestOptions = {
  method?: string;
  body?: unknown;
};

type ApiValidationDetail = {
  loc?: Array<string | number>;
  msg?: string;
};

async function parseJson(response: Response) {
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

function formatApiError(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object") {
    const detail = "detail" in payload ? payload.detail : null;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }

    if (Array.isArray(detail)) {
      const firstIssue = detail.find(
        (item): item is ApiValidationDetail =>
          Boolean(item) && typeof item === "object" && typeof item.msg === "string"
      );

      if (firstIssue?.msg) {
        const fieldPath = firstIssue.loc
          ?.filter((part) => part !== "body")
          .map((part) => String(part))
          .join(".");

        return fieldPath ? `${fieldPath}: ${firstIssue.msg}` : firstIssue.msg;
      }
    }

    const error = "error" in payload ? payload.error : null;
    if (typeof error === "string" && error.trim()) {
      return error;
    }
  }

  return fallback;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const response = await fetch(`${getApiUrl()}${path}`, {
    method: options.method ?? "GET",
    headers: {
      "Content-Type": "application/json"
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    cache: "no-store"
  });

  if (!response.ok) {
    const payload = await parseJson(response).catch(() => null);
    const detail = formatApiError(payload, response.statusText);
    throw new Error(detail);
  }

  return (await parseJson(response)) as T;
}

export function buildReason(category: ReasonCategory, detail: string, references: string[] = []) {
  return {
    category,
    detail,
    references
  };
}

export type Project = {
  id: string;
  name: string;
  description: string | null;
  status: "active" | "paused" | "archived";
  github_org: string | null;
  github_repo: string | null;
  github_project_id: string | null;
  current_version: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProjectListResponse = {
  total: number;
  page: number;
  per_page: number;
  items: Project[];
};

export type Milestone = {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  status: "planned" | "in_progress" | "review" | "pending_approval" | "approved" | "rejected";
  display_order: number;
  acceptance_criteria: string[];
  due_date: string | null;
  current_version: number;
  created_at: string;
  updated_at: string;
};

export type MilestoneListResponse = {
  total: number;
  items: Milestone[];
};

export type Task = {
  id: string;
  project_id: string;
  milestone_id: string;
  title: string;
  description: string | null;
  status:
    | "backlog"
    | "queued"
    | "in_progress"
    | "review"
    | "qa_check"
    | "judge_review"
    | "pending_human"
    | "done"
    | "rejected"
    | "rework";
  priority: "low" | "medium" | "high" | "critical";
  assigned_role: string | null;
  acceptance_criteria: string[];
  display_order: number;
  current_version: number;
  created_at: string;
  updated_at: string;
};

export type TaskListResponse = {
  total: number;
  items: Task[];
};

export type RevisionEntityType =
  | "project"
  | "team_member"
  | "project_assignment"
  | "milestone"
  | "task";

export type Revision = {
  revision_number: number;
  actor: string;
  change_summary: string;
  reason: {
    category: ReasonCategory;
    detail: string;
    references: string[];
  };
  before_snapshot: Record<string, unknown> | null;
  after_snapshot: Record<string, unknown>;
  created_at: string;
};

export type TeamMemberRole = "pm" | "ux" | "dev-jr" | "dev-sr" | "qa" | "devops" | "judge" | "custom";

export type ProviderType = "ollama" | "anthropic" | "openai" | "custom";

export type TeamMember = {
  id: string;
  name: string;
  role: TeamMemberRole;
  display_name: string;
  description: string | null;
  skills: string[];
  provider: ProviderType;
  model: string;
  is_active: boolean;
  current_version: number;
  created_at: string;
  updated_at: string;
};

export type TeamMemberListResponse = {
  total: number;
  page: number;
  per_page: number;
  items: TeamMember[];
};

export type ProjectAssignment = {
  id: string;
  project_id: string;
  team_member_id: string;
  is_enabled: boolean;
  provider_override: ProviderType | null;
  model_override: string | null;
  disabled_at: string | null;
  disable_reason: string | null;
  current_version: number;
  created_at: string;
  updated_at: string;
};

export type ProjectAssignmentListResponse = {
  total: number;
  items: ProjectAssignment[];
};

export type HealthResponse = {
  status: "ok" | "degraded";
  service: string;
  version: string;
  environment: string;
  phase: string;
  postgres: "ok" | "error";
  postgres_detail: string;
  redis: "ok" | "error";
  redis_detail: string;
};

export type RevisionListResponse = {
  entity_type: RevisionEntityType;
  entity_id: string;
  revisions: Revision[];
};

export type EvidenceType =
  | "artifact"
  | "test_result"
  | "screenshot"
  | "log"
  | "github_link"
  | "other";

export type ApprovalStatus = "approved" | "rejected" | "changes_requested";

export type ApprovalEvidence = {
  id: string;
  approval_id: string;
  evidence_type: EvidenceType;
  artifact_id: string | null;
  external_url: string | null;
  description: string;
  created_at: string;
};

export type Approval = {
  id: string;
  entity_type: RevisionEntityType;
  entity_id: string;
  approved_revision_number: number;
  status: ApprovalStatus;
  comment: string;
  override_used: boolean;
  override_reason: string | null;
  is_stale: boolean;
  stale_at: string | null;
  decided_by: string;
  decided_at: string;
  created_at: string;
  updated_at: string;
  evidence: ApprovalEvidence[];
};

export type ApprovalListResponse = {
  total: number;
  items: Approval[];
};

export type RunStatus = "created" | "running" | "paused" | "completed" | "failed" | "cancelled";

export type RunStepStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export type RunStep = {
  id: string;
  run_id: string;
  role: string;
  step_order: number;
  status: RunStepStatus;
  pause_after: boolean;
  output_artifact_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
};

export type Run = {
  id: string;
  project_id: string;
  task_id: string | null;
  status: RunStatus;
  workflow_type: string;
  trigger_actor: string;
  idempotency_key: string;
  steps: RunStep[];
  started_at: string | null;
  paused_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
};

export type RunListResponse = {
  total: number;
  items: Run[];
};

export type ArtifactType =
  | "spec" | "milestone_plan" | "tasks" | "acceptance_criteria"
  | "ui_notes" | "component_map" | "ux_risks"
  | "implementation_summary" | "code_diff"
  | "review_findings" | "refactor_summary"
  | "test_plan" | "test_results" | "bug_list"
  | "docker_changes" | "ci_changes" | "runbook"
  | "rubric_score" | "recommendation"
  | "decision_log" | "dev_output" | "sandbox_result"
  | "other";

export type Artifact = {
  id: string;
  project_id: string;
  run_id: string | null;
  run_step_id: string | null;
  role: string | null;
  artifact_type: ArtifactType;
  name: string;
  version: number;
  is_current: boolean;
  created_at: string;
};

export type ArtifactContent = {
  id: string;
  artifact_type: ArtifactType;
  name: string;
  body: string;
  created_at: string;
};
