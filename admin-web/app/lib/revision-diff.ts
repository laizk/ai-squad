import type { Revision } from "./api";

type DiffLine = {
  key: string;
  label: string;
  before: string | null;
  after: string | null;
};

const hiddenKeys = new Set([
  "id",
  "project_id",
  "milestone_id",
  "team_member_id",
  "created_at",
  "updated_at",
  "disabled_at",
  "current_version"
]);

const labels: Record<string, string> = {
  name: "Name",
  display_name: "Display Name",
  description: "Description",
  status: "Status",
  role: "Role",
  model: "Model",
  provider: "Provider",
  provider_override: "Provider Override",
  model_override: "Model Override",
  is_active: "Active",
  is_enabled: "Enabled",
  disable_reason: "Disable Reason",
  github_org: "GitHub Org",
  github_repo: "GitHub Repo",
  github_project_id: "GitHub Project",
  title: "Title",
  due_date: "Due Date",
  priority: "Priority",
  assigned_role: "Assigned Role",
  skills: "Skills",
  acceptance_criteria: "Acceptance Criteria",
  metadata: "Metadata"
};

export function getRevisionDiffLines(revision: Revision): DiffLine[] {
  const before = revision.before_snapshot ?? {};
  const after = revision.after_snapshot ?? {};
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));

  return keys
    .filter((key) => !hiddenKeys.has(key))
    .filter((key) => !areEqual(before[key], after[key]))
    .map((key) => ({
      key,
      label: labels[key] ?? toTitleCase(key),
      before: key in before ? formatValue(key, before[key]) : null,
      after: key in after ? formatValue(key, after[key]) : null
    }));
}

function areEqual(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "empty";
  }

  if (typeof value === "boolean") {
    if (key === "is_active") {
      return value ? "active" : "inactive";
    }
    if (key === "is_enabled") {
      return value ? "enabled" : "disabled";
    }
    return value ? "true" : "false";
  }

  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number") {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value.length > 0 ? value.map((item) => formatValue(key, item)).join(" | ") : "empty";
  }

  return JSON.stringify(value);
}

function toTitleCase(key: string): string {
  return key
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
