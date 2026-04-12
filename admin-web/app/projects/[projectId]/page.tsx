import Link from "next/link";
import { notFound } from "next/navigation";
import { revalidatePath } from "next/cache";

import { ActionForm } from "../../components/action-form";
import {
  apiRequest,
  buildReason,
  type Approval,
  type ApprovalListResponse,
  type Artifact,
  type ArtifactContent,
  type Milestone,
  type MilestoneListResponse,
  type Project,
  type ProjectAssignment,
  type ProjectAssignmentListResponse,
  type Revision,
  type RevisionEntityType,
  type RevisionListResponse,
  type RunListResponse,
  type Task,
  type TaskListResponse,
  type TeamMember,
  type TeamMemberListResponse
} from "../../lib/api";
import { formError, formErrorFromUnknown, formSuccess, type FormState } from "../../lib/form-state";
import { getRevisionDiffLines } from "../../lib/revision-diff";

type TimelineEntry = {
  entityType: RevisionEntityType;
  entityId: string;
  entityLabel: string;
  revision: Revision;
};

type MachineEvidence = {
  runId: string;
  judgeArtifact: Artifact | null;
  qaArtifact: Artifact | null;
  judgeSummary: string | null;
  judgeScore: number | null;
  qaStatus: string | null;
  qaSummary: string | null;
};

const milestoneStatuses = [
  "planned",
  "in_progress",
  "review",
  "pending_approval",
  "approved",
  "rejected"
] as const;

const taskStatuses = [
  "backlog",
  "queued",
  "in_progress",
  "review",
  "qa_check",
  "judge_review",
  "pending_human",
  "done",
  "rejected",
  "rework"
] as const;

const taskPriorities = ["low", "medium", "high", "critical"] as const;

const teamRoles = ["pm", "ux", "dev-jr", "dev-sr", "qa", "devops", "judge", "custom"] as const;

async function fetchProject(projectId: string) {
  try {
    const project = await apiRequest<Project>(`/api/v1/projects/${projectId}`);
    const milestones = await apiRequest<MilestoneListResponse>(`/api/v1/projects/${projectId}/milestones`);
    const tasksByMilestone = await Promise.all(
      milestones.items.map(async (milestone) => {
        const tasks = await apiRequest<TaskListResponse>(`/api/v1/milestones/${milestone.id}/tasks`);
        return [milestone.id, tasks.items] as const;
      })
    );
    const tasksByMilestoneMap = Object.fromEntries(tasksByMilestone) as Record<string, Task[]>;
    const assignments = await apiRequest<ProjectAssignmentListResponse>(`/api/v1/projects/${projectId}/team`);
    const teamMembers = await apiRequest<TeamMemberListResponse>("/api/v1/team-members");
    const [timeline, approvals, machineEvidence] = await Promise.all([
      fetchTimeline(
        project,
        milestones.items,
        tasksByMilestoneMap,
        assignments.items,
        teamMembers.items
      ),
      apiRequest<ApprovalListResponse>(`/api/v1/entities/project/${projectId}/approvals`).catch(() => ({ total: 0, items: [] as Approval[] })),
      fetchLatestMachineEvidence(projectId)
    ]);

    return {
      project,
      milestones: milestones.items,
      tasksByMilestone: tasksByMilestoneMap,
      timeline,
      assignments: assignments.items,
      teamMembers: teamMembers.items,
      approvals: approvals.items,
      machineEvidence
    };
  } catch (error) {
    if (error instanceof Error && error.message === "Project not found") {
      notFound();
    }
    throw error;
  }
}

async function fetchTimeline(
  project: Project,
  milestones: Milestone[],
  tasksByMilestone: Record<string, Task[]>,
  assignments: ProjectAssignment[],
  teamMembers: TeamMember[]
): Promise<TimelineEntry[]> {
  const allTasks: Task[] = Object.values(tasksByMilestone).flat();
  const memberNames = new Map(teamMembers.map((member) => [member.id, member.display_name]));

  const requests: Promise<TimelineEntry[]>[] = [
    apiRequest<RevisionListResponse>(`/api/v1/revisions/project/${project.id}`)
      .then((response) => response.revisions.map((revision) => ({
        entityType: "project" as const,
        entityId: project.id,
        entityLabel: project.name,
        revision
      })))
      .catch(() => []),
    ...milestones.map((milestone) =>
      apiRequest<RevisionListResponse>(`/api/v1/revisions/milestone/${milestone.id}`)
        .then((response) => response.revisions.map((revision) => ({
          entityType: "milestone" as const,
          entityId: milestone.id,
          entityLabel: milestone.title,
          revision
        })))
        .catch(() => [])
    ),
    ...allTasks.map((task) =>
      apiRequest<RevisionListResponse>(`/api/v1/revisions/task/${task.id}`)
        .then((response) => response.revisions.map((revision) => ({
          entityType: "task" as const,
          entityId: task.id,
          entityLabel: task.title,
          revision
        })))
        .catch(() => [])
    ),
    ...assignments.map((assignment) =>
      apiRequest<RevisionListResponse>(`/api/v1/revisions/project_assignment/${assignment.id}`)
        .then((response) => response.revisions.map((revision) => ({
          entityType: "project_assignment" as const,
          entityId: assignment.id,
          entityLabel: memberNames.get(assignment.team_member_id) ?? "Assigned team member",
          revision
        })))
        .catch(() => [])
    )
  ];

  const batches = await Promise.all(requests);
  return batches
    .flat()
    .sort((a, b) => b.revision.created_at.localeCompare(a.revision.created_at));
}

async function fetchLatestMachineEvidence(projectId: string): Promise<MachineEvidence | null> {
  const runs = await apiRequest<RunListResponse>(`/api/v1/runs?project_id=${projectId}&per_page=20`).catch(
    () => ({ total: 0, items: [] })
  );

  for (const run of runs.items) {
    const artifacts = await apiRequest<Artifact[]>(`/api/v1/runs/${run.id}/artifacts`).catch(() => [] as Artifact[]);
    const judgeArtifact = [...artifacts].reverse().find((artifact) => artifact.artifact_type === "rubric_score") ?? null;
    const qaArtifact = [...artifacts].reverse().find((artifact) => artifact.artifact_type === "test_results") ?? null;

    if (!judgeArtifact && !qaArtifact) {
      continue;
    }

    const judgePayload = judgeArtifact
      ? parseArtifactBody<{ score?: number; recommendation?: string }>(await fetchArtifactBody(judgeArtifact.id))
      : null;
    const qaPayload = qaArtifact
      ? parseArtifactBody<{ status?: string; summary?: string }>(await fetchArtifactBody(qaArtifact.id))
      : null;

    return {
      runId: run.id,
      judgeArtifact,
      qaArtifact,
      judgeSummary: judgePayload?.recommendation ?? null,
      judgeScore: typeof judgePayload?.score === "number" ? judgePayload.score : null,
      qaStatus: qaPayload?.status ?? null,
      qaSummary: qaPayload?.summary ?? null
    };
  }

  return null;
}

async function fetchArtifactBody(artifactId: string): Promise<string> {
  const artifact = await apiRequest<ArtifactContent>(`/api/v1/artifacts/${artifactId}/content`);
  return artifact.body;
}

function parseArtifactBody<T>(body: string): T | null {
  try {
    return JSON.parse(body) as T;
  } catch {
    return null;
  }
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

function RevisionTimeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return <p className="empty-state">No revisions recorded for this project yet.</p>;
  }

  return (
    <ol className="timeline">
      {entries.map((entry) => {
        const key = `${entry.entityType}:${entry.entityId}:${entry.revision.revision_number}`;
        return (
          <li key={key} className="timeline-row">
            <div className="timeline-marker" aria-hidden="true" />
            <div className="timeline-body">
              <div className="timeline-head">
                <span className={`status-chip status-${entry.revision.reason.category}`}>
                  {entry.revision.reason.category}
                </span>
                <span className="timeline-entity">
                  {entry.entityType} · {entry.entityLabel}
                </span>
                <span className="timeline-version">v{entry.revision.revision_number}</span>
              </div>
              <p className="timeline-summary">{entry.revision.change_summary}</p>
              <p className="timeline-reason">{entry.revision.reason.detail}</p>
              <RevisionDiff revision={entry.revision} />
              {entry.revision.reason.references.length > 0 ? (
                <ul className="timeline-refs">
                  {entry.revision.reason.references.map((reference) => (
                    <li key={reference}>{reference}</li>
                  ))}
                </ul>
              ) : null}
              <div className="timeline-meta">
                <span>{entry.revision.actor}</span>
                <span>{formatTimestamp(entry.revision.created_at)}</span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function RevisionDiff({ revision }: { revision: Revision }) {
  const lines = getRevisionDiffLines(revision);

  if (lines.length === 0) {
    return null;
  }

  return (
    <dl className="timeline-diff">
      {lines.map((line) => (
        <div key={line.key} className="timeline-diff-row">
          <dt>{line.label}</dt>
          <dd>
            {line.before !== null ? <span className="timeline-diff-before">{line.before}</span> : null}
            {line.before !== null && line.after !== null ? (
              <span className="timeline-diff-arrow" aria-hidden="true">→</span>
            ) : null}
            {line.after !== null ? <span className="timeline-diff-after">{line.after}</span> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

async function createMilestoneAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  const dueDate = String(formData.get("due_date") ?? "").trim();
  const acceptanceCriteriaText = String(formData.get("acceptance_criteria") ?? "").trim();

  if (!projectId || !title) {
    return formError("Project and milestone title are required.");
  }

  const acceptanceCriteria = acceptanceCriteriaText
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

  try {
    await apiRequest(`/api/v1/projects/${projectId}/milestones`, {
      method: "POST",
      body: {
        title,
        description: description || null,
        status: "planned",
        display_order: 0,
        acceptance_criteria: acceptanceCriteria,
        due_date: dueDate || null,
        reason: buildReason(
          "initial_creation",
          "Creating a milestone from the admin web so the human operator can structure and review project delivery."
        )
      }
    });
  } catch (error) {
    return formErrorFromUnknown(error, "Milestone creation failed.");
  }

  revalidatePath(`/projects/${projectId}`);
  return formSuccess("Milestone added.");
}

async function updateMilestoneStatusAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const milestoneId = String(formData.get("milestone_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  const status = String(formData.get("status") ?? "");

  if (!projectId || !milestoneId || !title || !milestoneStatuses.includes(status as (typeof milestoneStatuses)[number])) {
    return formError("Valid milestone update data is required.");
  }

  try {
    await apiRequest(`/api/v1/milestones/${milestoneId}`, {
      method: "PATCH",
      body: {
        title,
        status,
        reason: buildReason(
          "scope_change",
          "Updating milestone review status from the admin web so human progress reflects the current planning state."
        )
      }
    });
  } catch (error) {
    return formErrorFromUnknown(error, "Milestone update failed.");
  }

  revalidatePath(`/projects/${projectId}`);
  return formSuccess("Milestone updated.");
}

async function createTaskAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const milestoneId = String(formData.get("milestone_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  const assignedRole = String(formData.get("assigned_role") ?? "").trim();
  const priority = String(formData.get("priority") ?? "medium");
  const acceptanceCriteriaText = String(formData.get("acceptance_criteria") ?? "").trim();

  if (!projectId || !milestoneId || !title) {
    return formError("Project, milestone, and task title are required.");
  }

  if (!taskPriorities.includes(priority as (typeof taskPriorities)[number])) {
    return formError("Task priority is invalid.");
  }
  if (assignedRole && !teamRoles.includes(assignedRole as (typeof teamRoles)[number])) {
    return formError("Assigned role is invalid.");
  }

  const acceptanceCriteria = acceptanceCriteriaText
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

  try {
    await apiRequest(`/api/v1/milestones/${milestoneId}/tasks`, {
      method: "POST",
      body: {
        title,
        description: description || null,
        priority,
        assigned_role: assignedRole || null,
        acceptance_criteria: acceptanceCriteria,
        reason: buildReason(
          "initial_creation",
          "Creating a task from the admin web so delivery work is visible under the milestone and can be reviewed."
        )
      }
    });
  } catch (error) {
    return formErrorFromUnknown(error, "Task creation failed.");
  }

  revalidatePath(`/projects/${projectId}`);
  return formSuccess("Task added.");
}

async function updateTaskStatusAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const taskId = String(formData.get("task_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  const status = String(formData.get("status") ?? "");

  if (!projectId || !taskId || !title || !taskStatuses.includes(status as (typeof taskStatuses)[number])) {
    return formError("Valid task update data is required.");
  }

  try {
    await apiRequest(`/api/v1/tasks/${taskId}`, {
      method: "PATCH",
      body: {
        title,
        status,
        reason: buildReason(
          "fix",
          "Updating task execution state from the admin web so the milestone view reflects the latest human-reviewed status."
        )
      }
    });
  } catch (error) {
    return formErrorFromUnknown(error, "Task update failed.");
  }

  revalidatePath(`/projects/${projectId}`);
  return formSuccess("Task updated.");
}

function TaskCard({ projectId, task }: { projectId: string; task: Task }) {
  return (
    <article className="task-card">
      <div className="task-head">
        <div>
          <h4>{task.title}</h4>
          <p>{task.description ?? "No task description yet."}</p>
        </div>
        <span className={`status-chip status-${task.status}`}>{task.status}</span>
      </div>

      <div className="inline-meta">
        <span>Priority {task.priority}</span>
        <span>{task.assigned_role ?? "Unassigned role"}</span>
        <span>v{task.current_version}</span>
      </div>

      {task.acceptance_criteria.length > 0 ? (
        <ul className="criteria-list">
          {task.acceptance_criteria.map((criterion) => (
            <li key={criterion}>{criterion}</li>
          ))}
        </ul>
      ) : null}

      <ActionForm action={updateTaskStatusAction} className="inline-form">
        <input type="hidden" name="project_id" value={projectId} />
        <input type="hidden" name="task_id" value={task.id} />
        <input type="hidden" name="title" value={task.title} />
        <label className="field field-inline">
          <span>Status</span>
          <select name="status" defaultValue={task.status}>
            {taskStatuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="button-secondary">
          Update task
        </button>
      </ActionForm>
    </article>
  );
}

function TeamAssignmentCard({
  projectId,
  assignments,
  teamMembers
}: {
  projectId: string;
  assignments: ProjectAssignment[];
  teamMembers: TeamMember[];
}) {
  const activeAssignments = assignments.filter((assignment) => assignment.is_enabled);
  const assignedMemberIds = new Set(assignments.map((assignment) => assignment.team_member_id));
  const assignableMembers = teamMembers.filter(
    (member) => member.is_active && !assignedMemberIds.has(member.id)
  );

  const getMemberName = (memberId: string) => {
    const member = teamMembers.find((m) => m.id === memberId);
    return member ? member.display_name : "Unknown member";
  };

  const getMemberRole = (memberId: string) => {
    const member = teamMembers.find((m) => m.id === memberId);
    return member ? member.role : "unknown";
  };

  return (
    <article className="card">
      <div className="section-head">
        <div>
          <p className="eyebrow">Team</p>
          <h2>Assigned team members</h2>
        </div>
        <p className="meta">{activeAssignments.length} active · {assignments.length} total</p>
      </div>

      {assignments.length === 0 ? (
        <p className="empty-state">No team members assigned yet.</p>
      ) : (
        <ul className="assignment-list">
          {assignments.map((assignment) => {
            return (
              <li key={assignment.id} className="assignment-item">
                <div className="assignment-head">
                  <div>
                    <strong>
                      <Link href={`/team-members/${assignment.team_member_id}`} className="text-link">
                        {getMemberName(assignment.team_member_id)}
                      </Link>
                    </strong>
                    <span className="assignment-role">
                      ({getMemberRole(assignment.team_member_id)})
                    </span>
                  </div>
                  <div className="assignment-meta">
                    <span className={`status-chip ${assignment.is_enabled ? "status-active" : "status-archived"}`}>
                      {assignment.is_enabled ? "enabled" : "disabled"}
                    </span>
                    {assignment.provider_override && (
                      <span className="assignment-provider">
                        {assignment.provider_override}
                      </span>
                    )}
                    {assignment.model_override && (
                      <span className="assignment-model">
                        {assignment.model_override}
                      </span>
                    )}
                    <span className="assignment-version">v{assignment.current_version}</span>
                  </div>
                </div>
                {assignment.disable_reason && (
                  <p className="assignment-disabled">
                    Disabled: {assignment.disable_reason}
                  </p>
                )}
                <ActionForm action={toggleAssignmentAction} className="inline-form">
                  <input type="hidden" name="project_id" value={projectId} />
                  <input type="hidden" name="team_member_id" value={assignment.team_member_id} />
                  <input type="hidden" name="is_enabled" value={assignment.is_enabled ? "false" : "true"} />
                  <button type="submit" className="button-secondary btn-sm">
                    {assignment.is_enabled ? "Disable assignment" : "Re-enable assignment"}
                  </button>
                </ActionForm>
              </li>
            );
          })}
        </ul>
      )}

      <ActionForm action={assignTeamMemberAction} className="form-stack form-slab" resetOnSuccess>
        <input type="hidden" name="project_id" value={projectId} />
        <div className="section-head tight">
          <div>
            <p className="eyebrow">Assign</p>
            <h3>Add member</h3>
          </div>
        </div>

        {assignableMembers.length === 0 ? (
          <p className="empty-state">All active team members are already assigned to this project.</p>
        ) : (
          <>
            <label className="field">
              <span>Team member</span>
              <select name="team_member_id" required defaultValue="">
                <option value="" disabled>
                  Select a team member
                </option>
                {assignableMembers.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.display_name} ({member.role})
                  </option>
                ))}
              </select>
            </label>

            <div className="form-grid">
              <label className="field">
                <span>Model override</span>
                <input
                  type="text"
                  name="model_override"
                  placeholder="Leave blank to use the team member default"
                />
              </label>

              <label className="field">
                <span>Provider override</span>
                <select name="provider_override" defaultValue="">
                  <option value="">Use team member default</option>
                  <option value="ollama">ollama</option>
                  <option value="anthropic">anthropic</option>
                  <option value="openai">openai</option>
                  <option value="custom">custom</option>
                </select>
              </label>
            </div>

            <button type="submit" className="button-primary">
              Assign to project
            </button>
          </>
        )}
      </ActionForm>
    </article>
  );
}

function MilestoneCard({
  projectId,
  milestone,
  tasks
}: {
  projectId: string;
  milestone: Milestone;
  tasks: Task[];
}) {
  return (
    <article className="milestone-card">
      <div className="milestone-head">
        <div>
          <div className="section-head tight">
            <div>
              <p className="eyebrow">Milestone</p>
              <h3>{milestone.title}</h3>
            </div>
            <span className={`status-chip status-${milestone.status}`}>{milestone.status}</span>
          </div>
          <p className="milestone-copy">{milestone.description ?? "No milestone description yet."}</p>
        </div>
      </div>

      <div className="inline-meta">
        <span>v{milestone.current_version}</span>
        <span>Due {milestone.due_date ?? "unscheduled"}</span>
        <span>{tasks.length} tasks</span>
      </div>

      {milestone.acceptance_criteria.length > 0 ? (
        <ul className="criteria-list">
          {milestone.acceptance_criteria.map((criterion) => (
            <li key={criterion}>{criterion}</li>
          ))}
        </ul>
      ) : null}

      <ActionForm action={updateMilestoneStatusAction} className="inline-form">
        <input type="hidden" name="project_id" value={projectId} />
        <input type="hidden" name="milestone_id" value={milestone.id} />
        <input type="hidden" name="title" value={milestone.title} />
        <label className="field field-inline">
          <span>Status</span>
          <select name="status" defaultValue={milestone.status}>
            {milestoneStatuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="button-secondary">
          Update milestone
        </button>
      </ActionForm>

      <div className="task-stack">
        {tasks.length === 0 ? <p className="empty-state">No tasks yet for this milestone.</p> : null}
        {tasks.map((task) => (
          <TaskCard key={task.id} projectId={projectId} task={task} />
        ))}
      </div>

      <ActionForm action={createTaskAction} className="form-stack form-slab" resetOnSuccess>
        <input type="hidden" name="project_id" value={projectId} />
        <input type="hidden" name="milestone_id" value={milestone.id} />
        <div className="section-head tight">
          <div>
            <p className="eyebrow">Task</p>
            <h4>Add task</h4>
          </div>
        </div>

        <label className="field">
          <span>Title</span>
          <input name="title" type="text" placeholder="Implement milestone slice" required />
        </label>

        <label className="field">
          <span>Description</span>
          <textarea
            name="description"
            rows={3}
            placeholder="What does this task need to deliver for the milestone to move forward?"
          />
        </label>

        <div className="form-grid form-grid-3">
          <label className="field">
            <span>Assigned role</span>
            <select name="assigned_role" defaultValue="dev-jr">
              <option value="">Unassigned</option>
              {teamRoles.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Priority</span>
            <select name="priority" defaultValue="medium">
              {taskPriorities.map((priority) => (
                <option key={priority} value={priority}>
                  {priority}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="field">
          <span>Acceptance criteria</span>
          <textarea
            name="acceptance_criteria"
            rows={3}
            placeholder={"One criterion per line\nVisible from the milestone page\nBacked by revision history"}
          />
        </label>

        <button type="submit" className="button-primary">
          Add task
        </button>
      </ActionForm>
    </article>
  );
}

async function assignTeamMemberAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const teamMemberId = String(formData.get("team_member_id") ?? "");
  const modelOverride = String(formData.get("model_override") ?? "").trim() || null;
  const providerOverride = String(formData.get("provider_override") ?? "").trim() || null;

  if (!projectId || !teamMemberId) {
    return formError("Project and team member are required.");
  }

  try {
    await apiRequest(`/api/v1/projects/${projectId}/team`, {
      method: "POST",
      body: {
        team_member_id: teamMemberId,
        model_override: modelOverride,
        provider_override: providerOverride,
        reason: buildReason(
          "initial_creation",
          "Assigning a team member to the project so they can begin work on defined tasks and milestones."
        )
      }
    });
  } catch (error) {
    return formErrorFromUnknown(error, "Project assignment failed.");
  }

  revalidatePath(`/projects/${projectId}`);
  return formSuccess("Team member assigned.");
}

async function toggleAssignmentAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const teamMemberId = String(formData.get("team_member_id") ?? "");
  const isEnabled = String(formData.get("is_enabled") ?? "") === "true";

  if (!projectId || !teamMemberId) {
    return formError("Project and team member are required.");
  }

  try {
    await apiRequest(`/api/v1/projects/${projectId}/team/${teamMemberId}`, {
      method: isEnabled ? "PATCH" : "DELETE",
      body: {
        ...(isEnabled
          ? {
              is_enabled: true,
              disable_reason: null
            }
          : {}),
        reason: buildReason(
          "scope_change",
          isEnabled
            ? "Re-enabling a project assignment so this team member can resume work under the current project plan."
            : "Disabling a project assignment so the current staffing plan matches the project scope."
        )
      }
    });
  } catch (error) {
    return formErrorFromUnknown(error, "Project assignment update failed.");
  }

  revalidatePath(`/projects/${projectId}`);
  return formSuccess(isEnabled ? "Assignment re-enabled." : "Assignment disabled.");
}

const approvalStatuses = ["approved", "rejected", "changes_requested"] as const;

const evidenceTypes = [
  "artifact",
  "test_result",
  "screenshot",
  "log",
  "github_link",
  "other"
] as const;

async function createApprovalAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const approvedRevisionNumber = parseInt(String(formData.get("approved_revision_number") ?? ""), 10);
  const status = String(formData.get("status") ?? "");
  const comment = String(formData.get("comment") ?? "").trim();
  const overrideUsed = formData.get("override_used") === "on";
  const overrideReason = String(formData.get("override_reason") ?? "").trim() || null;
  const evidenceType = String(formData.get("evidence_type") ?? "");
  const externalUrl = String(formData.get("external_url") ?? "").trim() || null;
  const evidenceDescription = String(formData.get("evidence_description") ?? "").trim();
  const artifactIds = formData.getAll("artifact_id").map((value) => String(value).trim()).filter(Boolean);
  const artifactEvidenceTypes = formData.getAll("artifact_evidence_type").map((value) => String(value).trim());
  const artifactDescriptions = formData.getAll("artifact_description").map((value) => String(value).trim());

  if (!projectId) {
    return formError("Project ID is missing.");
  }
  if (!approvalStatuses.includes(status as (typeof approvalStatuses)[number])) {
    return formError("A valid decision is required.");
  }
  if (comment.length < 10) {
    return formError("Comment must be at least 10 characters.");
  }
  if (!evidenceTypes.includes(evidenceType as (typeof evidenceTypes)[number])) {
    return formError("A valid evidence type is required.");
  }
  if (!evidenceDescription) {
    return formError("Evidence description is required.");
  }
  if (overrideUsed && !overrideReason) {
    return formError("Override reason is required when recording a human override.");
  }
  if (!overrideUsed && overrideReason !== null) {
    return formError("Select the override option before providing an override reason.");
  }
  if (artifactIds.length === 0 && !overrideUsed) {
    return formError("Machine evidence is required unless you record a human override.");
  }

  try {
    const machineEvidence = artifactIds.map((artifactId, index) => ({
      evidence_type: artifactEvidenceTypes[index] || "artifact",
      artifact_id: artifactId,
      description: artifactDescriptions[index] || "Attached machine-generated evidence from the latest workflow run."
    }));

    await apiRequest(`/api/v1/approvals`, {
      method: "POST",
      body: {
        entity_type: "project",
        entity_id: projectId,
        approved_revision_number: approvedRevisionNumber,
        status,
        comment,
        override_used: overrideUsed,
        override_reason: overrideReason,
        evidence: [
          ...machineEvidence,
          {
            evidence_type: evidenceType,
            external_url: externalUrl,
            description: evidenceDescription
          }
        ]
      }
    });
  } catch (error) {
    return formErrorFromUnknown(error, "Approval submission failed.");
  }

  revalidatePath(`/projects/${projectId}`);
  return formSuccess("Decision recorded.");
}

function ApprovalPanel({
  project,
  approvals,
  machineEvidence
}: {
  project: Project;
  approvals: Approval[];
  machineEvidence: MachineEvidence | null;
}) {
  return (
    <article className="card">
      <div className="section-head">
        <div>
          <p className="eyebrow">Review</p>
          <h2>Approval decisions</h2>
        </div>
        <p className="meta">{approvals.length} recorded</p>
      </div>

      {approvals.length === 0 ? (
        <p className="empty-state">No approval decisions yet for this project.</p>
      ) : (
        <ul className="approval-list">
          {approvals.map((approval) => (
            <li key={approval.id} className="approval-item">
              <div className="approval-head">
                <span className={`status-chip status-${approval.status}`}>{approval.status}</span>
                {approval.is_stale ? (
                  <span className="stale-badge">stale</span>
                ) : null}
                {approval.override_used ? (
                  <span className="override-badge">override</span>
                ) : null}
                <span className="approval-rev">revision {approval.approved_revision_number}</span>
              </div>
              <p className="approval-comment">{approval.comment}</p>
              {approval.override_used && approval.override_reason ? (
                <p className="meta">Override reason: {approval.override_reason}</p>
              ) : null}
              {approval.evidence.length > 0 ? (
                <ul className="evidence-list">
                  {approval.evidence.map((ev: Approval["evidence"][number]) => (
                    <li key={ev.id} className="evidence-item">
                      <span className="evidence-type">{ev.evidence_type}</span>
                      <span>{ev.description}</span>
                      {ev.artifact_id ? (
                        <Link href={`/artifacts/${ev.artifact_id}`} className="text-link">
                          artifact
                        </Link>
                      ) : null}
                      {ev.external_url ? (
                        <a href={ev.external_url} className="text-link" target="_blank" rel="noreferrer">
                          {ev.external_url}
                        </a>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              <div className="approval-meta">
                <span>{approval.decided_by}</span>
                <span>{formatTimestamp(approval.decided_at)}</span>
                {approval.is_stale && approval.stale_at ? (
                  <span className="stale-since">marked stale {formatTimestamp(approval.stale_at)}</span>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      <ActionForm action={createApprovalAction} className="form-stack form-slab" resetOnSuccess>
        <input type="hidden" name="project_id" value={project.id} />
        <input type="hidden" name="approved_revision_number" value={project.current_version} />

        <div className="section-head tight">
          <div>
            <p className="eyebrow">Approve / reject</p>
            <h3>Record decision for v{project.current_version}</h3>
          </div>
        </div>

        <div className="subtle-panel">
          <p className="eyebrow">Machine evidence</p>
          {machineEvidence ? (
            <>
              <p className="meta">
                Latest run: <Link href={`/runs/${machineEvidence.runId}`} className="text-link">{machineEvidence.runId.slice(0, 8)}</Link>
              </p>
              {machineEvidence.judgeArtifact ? (
                <>
                  <input type="hidden" name="artifact_id" value={machineEvidence.judgeArtifact.id} />
                  <input type="hidden" name="artifact_evidence_type" value="artifact" />
                  <input
                    type="hidden"
                    name="artifact_description"
                    value={`Judge rubric from run ${machineEvidence.runId.slice(0, 8)}${machineEvidence.judgeScore !== null ? ` with score ${machineEvidence.judgeScore}` : ""}.`}
                  />
                  <p>
                    Judge rubric: <Link href={`/artifacts/${machineEvidence.judgeArtifact.id}`} className="text-link">{machineEvidence.judgeArtifact.name}</Link>
                    {machineEvidence.judgeScore !== null ? ` (score ${machineEvidence.judgeScore})` : ""}
                  </p>
                  {machineEvidence.judgeSummary ? <p className="meta">{machineEvidence.judgeSummary}</p> : null}
                </>
              ) : (
                <p className="meta">No judge artifact found on recent runs.</p>
              )}
              {machineEvidence.qaArtifact ? (
                <>
                  <input type="hidden" name="artifact_id" value={machineEvidence.qaArtifact.id} />
                  <input type="hidden" name="artifact_evidence_type" value="test_result" />
                  <input
                    type="hidden"
                    name="artifact_description"
                    value={`QA test results from run ${machineEvidence.runId.slice(0, 8)}${machineEvidence.qaStatus ? ` with status ${machineEvidence.qaStatus}` : ""}.`}
                  />
                  <p>
                    QA results: <Link href={`/artifacts/${machineEvidence.qaArtifact.id}`} className="text-link">{machineEvidence.qaArtifact.name}</Link>
                    {machineEvidence.qaStatus ? ` (${machineEvidence.qaStatus})` : ""}
                  </p>
                  {machineEvidence.qaSummary ? <p className="meta">{machineEvidence.qaSummary}</p> : null}
                </>
              ) : (
                <p className="meta">No QA artifact found on recent runs.</p>
              )}
            </>
          ) : (
            <p className="meta">No recent judge or QA artifacts are available yet for this project.</p>
          )}
          <p className="meta">
            Project approvals require linked machine evidence from QA or judge. If that evidence is unavailable or invalid,
            record a human override with a reason before submitting.
          </p>
        </div>

        <label className="field">
          <span>Decision</span>
          <select name="status" required defaultValue="">
            <option value="" disabled>Select decision</option>
            {approvalStatuses.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Comment</span>
          <textarea
            name="comment"
            rows={3}
            required
            minLength={10}
            placeholder="Explain the decision — what was reviewed and why this outcome is warranted."
          />
        </label>

        <div className="section-head tight">
          <div>
            <p className="eyebrow">Evidence</p>
            <h4>Attach evidence (required)</h4>
          </div>
        </div>

        <div className="form-grid">
          <label className="field">
            <span>Type</span>
            <select name="evidence_type" required defaultValue="">
              <option value="" disabled>Select type</option>
              {evidenceTypes.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>External URL</span>
            <input
              type="url"
              name="external_url"
              placeholder="https://github.com/... (optional)"
            />
          </label>
        </div>

        <label className="field">
          <span>Evidence description</span>
          <textarea
            name="evidence_description"
            rows={2}
            required
            placeholder="Describe what this evidence shows and how it supports the decision."
          />
        </label>

        <label className="field-checkbox">
          <input type="checkbox" name="override_used" />
          <span>Record human override when machine evidence is missing or cannot be trusted.</span>
        </label>

        <label className="field">
          <span>Override reason</span>
          <textarea
            name="override_reason"
            rows={2}
            placeholder="Explain why this decision is proceeding without the expected machine evidence."
          />
        </label>

        <button type="submit" className="button-primary">
          Submit decision
        </button>
      </ActionForm>
    </article>
  );
}

export default async function ProjectDetailPage({
  params
}: {
  params: { projectId: string };
}) {
  const { project, milestones, tasksByMilestone, timeline, assignments, teamMembers, approvals, machineEvidence } = await fetchProject(params.projectId);

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">Project review</p>
        <div className="hero-topline">
          <div>
            <h1>{project.name}</h1>
            <p className="lede">{project.description ?? "No project description yet."}</p>
          </div>
          <span className={`status-chip status-${project.status}`}>{project.status}</span>
        </div>

        <div className="hero-meta">
          <span>Version {project.current_version}</span>
          <span>{project.github_org && project.github_repo ? `${project.github_org}/${project.github_repo}` : "No linked repository"}</span>
          <Link href="/system" className="text-link">
            System health
          </Link>
          <Link href="/" className="text-link">
            Back to projects
          </Link>
        </div>
      </section>

      <section className="grid grid-wide">
        <TeamAssignmentCard
          projectId={project.id}
          assignments={assignments}
          teamMembers={teamMembers}
        />

        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Milestones</p>
              <h2>Delivery map</h2>
            </div>
            <p className="meta">{milestones.length} total</p>
          </div>

          <div className="stack-list">
            {milestones.length === 0 ? <p className="empty-state">No milestones yet for this project.</p> : null}
            {milestones.map((milestone) => (
              <MilestoneCard
                key={milestone.id}
                projectId={project.id}
                milestone={milestone}
                tasks={tasksByMilestone[milestone.id] ?? []}
              />
            ))}
          </div>
        </article>
      </section>

      <article className="card">
        <div className="section-head">
          <div>
            <p className="eyebrow">Create</p>
            <h2>Add milestone</h2>
          </div>
        </div>

        <ActionForm action={createMilestoneAction} className="form-stack" resetOnSuccess>
          <input type="hidden" name="project_id" value={project.id} />

          <label className="field">
            <span>Title</span>
            <input name="title" type="text" placeholder="Planning approved" required />
          </label>

          <label className="field">
            <span>Description</span>
            <textarea
              name="description"
              rows={4}
              placeholder="What should this milestone prove or deliver?"
            />
          </label>

          <label className="field">
            <span>Due date</span>
            <input name="due_date" type="date" />
          </label>

          <label className="field">
            <span>Acceptance criteria</span>
            <textarea
              name="acceptance_criteria"
              rows={5}
              placeholder={"One criterion per line\nVisible in the review UI\nBacked by revision history"}
            />
          </label>

          <button type="submit" className="button-primary">
            Add milestone
          </button>
        </ActionForm>
      </article>

      <ApprovalPanel project={project} approvals={approvals} machineEvidence={machineEvidence} />

      <article className="card">
        <div className="section-head">
          <div>
            <p className="eyebrow">Revision history</p>
            <h2>Audit trail</h2>
          </div>
          <p className="meta">{timeline.length} entries</p>
        </div>

        <RevisionTimeline entries={timeline} />
      </article>
    </main>
  );
}
