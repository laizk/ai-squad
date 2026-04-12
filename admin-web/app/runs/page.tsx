import Link from "next/link";
import { revalidatePath } from "next/cache";

import { ActionForm } from "../components/action-form";
import {
  apiRequest,
  type Project,
  type ProjectListResponse,
  type Run,
  type RunListResponse
} from "../lib/api";
import { formError, formErrorFromUnknown, formSuccess, type FormState } from "../lib/form-state";

const workflowTypes = ["pm_planning", "dev_cycle", "full_sequential"] as const;

async function fetchRunsData() {
  const [runsResp, projectsResp] = await Promise.all([
    apiRequest<RunListResponse>("/api/v1/runs?per_page=100"),
    apiRequest<ProjectListResponse>("/api/v1/projects?per_page=200")
  ]);
  const projectMap = new Map(projectsResp.items.map((p) => [p.id, p.name]));
  return { runs: runsResp.items, total: runsResp.total, projectMap, projects: projectsResp.items };
}

async function createRunAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";

  const projectId = String(formData.get("project_id") ?? "").trim();
  const workflowType = String(formData.get("workflow_type") ?? "");
  const idempotencyKey = String(formData.get("idempotency_key") ?? "").trim();

  if (!projectId) return formError("Project is required.");
  if (!workflowTypes.includes(workflowType as (typeof workflowTypes)[number])) {
    return formError("Workflow type is invalid.");
  }
  if (!idempotencyKey) return formError("Idempotency key is required.");

  try {
    await apiRequest("/api/v1/runs", {
      method: "POST",
      body: { project_id: projectId, workflow_type: workflowType, idempotency_key: idempotencyKey }
    });
  } catch (error) {
    return formErrorFromUnknown(error, "Run creation failed.");
  }

  revalidatePath("/runs");
  return formSuccess("Run triggered.");
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

function RunRow({ run, projectName }: { run: Run; projectName: string }) {
  const active = run.steps.filter((s) => s.status !== "skipped");
  const done = active.filter((s) => s.status === "completed").length;

  return (
    <li className="list-card">
      <div className="list-card-top">
        <div>
          <h3>
            <Link href={`/runs/${run.id}`} className="text-link">
              {run.workflow_type}
            </Link>
          </h3>
          <p className="list-card-meta">
            <span>{projectName}</span>
            <span>{formatTimestamp(run.created_at)}</span>
            <span>
              {done}/{active.length} steps
            </span>
          </p>
        </div>
        <span className={`status-chip status-${run.status}`}>{run.status}</span>
      </div>
      {run.error_message ? (
        <p className="run-error">{run.error_message}</p>
      ) : null}
    </li>
  );
}

export default async function RunsPage() {
  const { runs, total, projectMap, projects } = await fetchRunsData();

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">Orchestration</p>
        <div className="hero-topline">
          <div>
            <h1>Workflow runs</h1>
            <p className="lede">
              Trigger and monitor agent workflow runs. Each run sequences stub agents
              through the defined workflow and pauses for human review where configured.
            </p>
          </div>
        </div>
        <div className="hero-meta">
          <span>{total} total runs</span>
          <Link href="/" className="text-link">Back to projects</Link>
        </div>
      </section>

      <section className="grid grid-wide">
        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Runs</p>
              <h2>All runs</h2>
            </div>
            <p className="meta">{total} total</p>
          </div>

          {runs.length === 0 ? (
            <p className="empty-state">No runs yet. Trigger one below.</p>
          ) : (
            <ul className="stack-list">
              {runs.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  projectName={projectMap.get(run.project_id) ?? run.project_id}
                />
              ))}
            </ul>
          )}
        </article>

        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Trigger</p>
              <h2>New run</h2>
            </div>
          </div>

          <ActionForm action={createRunAction} className="form-stack" resetOnSuccess>
            <label className="field">
              <span>Project</span>
              <select name="project_id" required defaultValue="">
                <option value="" disabled>Select project</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Workflow type</span>
              <select name="workflow_type" defaultValue="pm_planning">
                {workflowTypes.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Idempotency key</span>
              <input
                name="idempotency_key"
                type="text"
                required
                placeholder="e.g. proj-abc-pm-run-1"
              />
            </label>

            <button type="submit" className="button-primary">Trigger run</button>
          </ActionForm>
        </article>
      </section>
    </main>
  );
}
