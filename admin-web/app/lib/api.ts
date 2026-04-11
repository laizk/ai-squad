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

async function parseJson(response: Response) {
  const text = await response.text();
  return text ? JSON.parse(text) : null;
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
    const detail = payload?.detail ?? payload?.error ?? response.statusText;
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
