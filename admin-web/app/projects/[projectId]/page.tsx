import Link from "next/link";
import { notFound } from "next/navigation";
import { revalidatePath } from "next/cache";

import {
  apiRequest,
  buildReason,
  type Milestone,
  type MilestoneListResponse,
  type Project,
  type Task,
  type TaskListResponse
} from "../../lib/api";

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

    return {
      project,
      milestones: milestones.items,
      tasksByMilestone: Object.fromEntries(tasksByMilestone) as Record<string, Task[]>
    };
  } catch (error) {
    if (error instanceof Error && error.message === "Project not found") {
      notFound();
    }
    throw error;
  }
}

async function createMilestoneAction(formData: FormData) {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  const dueDate = String(formData.get("due_date") ?? "").trim();
  const acceptanceCriteriaText = String(formData.get("acceptance_criteria") ?? "").trim();

  if (!projectId || !title) {
    throw new Error("Project and milestone title are required");
  }

  const acceptanceCriteria = acceptanceCriteriaText
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

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

  revalidatePath(`/projects/${projectId}`);
}

async function updateMilestoneStatusAction(formData: FormData) {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const milestoneId = String(formData.get("milestone_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  const status = String(formData.get("status") ?? "");

  if (!projectId || !milestoneId || !title || !milestoneStatuses.includes(status as (typeof milestoneStatuses)[number])) {
    throw new Error("Valid milestone update data is required");
  }

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

  revalidatePath(`/projects/${projectId}`);
}

async function createTaskAction(formData: FormData) {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const milestoneId = String(formData.get("milestone_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  const assignedRole = String(formData.get("assigned_role") ?? "").trim();
  const priority = String(formData.get("priority") ?? "medium");
  const acceptanceCriteriaText = String(formData.get("acceptance_criteria") ?? "").trim();

  if (!projectId || !milestoneId || !title) {
    throw new Error("Project, milestone, and task title are required");
  }

  if (!taskPriorities.includes(priority as (typeof taskPriorities)[number])) {
    throw new Error("Task priority is invalid");
  }
  if (assignedRole && !teamRoles.includes(assignedRole as (typeof teamRoles)[number])) {
    throw new Error("Assigned role is invalid");
  }

  const acceptanceCriteria = acceptanceCriteriaText
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

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

  revalidatePath(`/projects/${projectId}`);
}

async function updateTaskStatusAction(formData: FormData) {
  "use server";

  const projectId = String(formData.get("project_id") ?? "");
  const taskId = String(formData.get("task_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  const status = String(formData.get("status") ?? "");

  if (!projectId || !taskId || !title || !taskStatuses.includes(status as (typeof taskStatuses)[number])) {
    throw new Error("Valid task update data is required");
  }

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

  revalidatePath(`/projects/${projectId}`);
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

      <form action={updateTaskStatusAction} className="inline-form">
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
      </form>
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

      <form action={updateMilestoneStatusAction} className="inline-form">
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
      </form>

      <div className="task-stack">
        {tasks.length === 0 ? <p className="empty-state">No tasks yet for this milestone.</p> : null}
        {tasks.map((task) => (
          <TaskCard key={task.id} projectId={projectId} task={task} />
        ))}
      </div>

      <form action={createTaskAction} className="form-stack form-slab">
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
      </form>
    </article>
  );
}

export default async function ProjectDetailPage({
  params
}: {
  params: { projectId: string };
}) {
  const { project, milestones, tasksByMilestone } = await fetchProject(params.projectId);

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
          <Link href="/" className="text-link">
            Back to projects
          </Link>
        </div>
      </section>

      <section className="grid grid-wide">
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

        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Create</p>
              <h2>Add milestone</h2>
            </div>
          </div>

          <form action={createMilestoneAction} className="form-stack">
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
          </form>
        </article>
      </section>
    </main>
  );
}
