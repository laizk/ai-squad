import Link from "next/link";
import { notFound } from "next/navigation";
import { revalidatePath } from "next/cache";

import { ActionForm } from "../../components/action-form";
import {
  apiRequest,
  type Artifact,
  type ArtifactContent,
  type Project,
  type Run,
  type RunStep
} from "../../lib/api";
import { formErrorFromUnknown, formSuccess, type FormState } from "../../lib/form-state";

async function fetchRunDetail(runId: string) {
  try {
    const run = await apiRequest<Run>(`/api/v1/runs/${runId}`);
    const project = await apiRequest<Project>(`/api/v1/projects/${run.project_id}`);
    const artifacts = await apiRequest<Artifact[]>(`/api/v1/runs/${runId}/artifacts`).catch(
      () => [] as Artifact[]
    );
    return { run, project, artifacts };
  } catch (error) {
    if (error instanceof Error && error.message === "Run not found") {
      notFound();
    }
    throw error;
  }
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

function stepDuration(step: RunStep): string {
  if (!step.started_at || !step.completed_at) return "—";
  const ms = new Date(step.completed_at).getTime() - new Date(step.started_at).getTime();
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

async function pauseRunAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";
  const runId = String(formData.get("run_id") ?? "");
  try {
    await apiRequest(`/api/v1/runs/${runId}/pause`, { method: "POST" });
  } catch (error) {
    return formErrorFromUnknown(error, "Pause failed.");
  }
  revalidatePath(`/runs/${runId}`);
  return formSuccess("Run paused.");
}

async function resumeRunAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";
  const runId = String(formData.get("run_id") ?? "");
  try {
    await apiRequest(`/api/v1/runs/${runId}/resume`, { method: "POST" });
  } catch (error) {
    return formErrorFromUnknown(error, "Resume failed.");
  }
  revalidatePath(`/runs/${runId}`);
  return formSuccess("Run resumed.");
}

async function cancelRunAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";
  const runId = String(formData.get("run_id") ?? "");
  try {
    await apiRequest(`/api/v1/runs/${runId}/cancel`, { method: "POST" });
  } catch (error) {
    return formErrorFromUnknown(error, "Cancel failed.");
  }
  revalidatePath(`/runs/${runId}`);
  return formSuccess("Run cancelled.");
}

async function rejectRunAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";
  const runId = String(formData.get("run_id") ?? "");
  try {
    await apiRequest(`/api/v1/runs/${runId}/reject`, { method: "POST" });
  } catch (error) {
    return formErrorFromUnknown(error, "Reject failed.");
  }
  revalidatePath(`/runs/${runId}`);
  return formSuccess("Run rejected.");
}

async function requestChangesAction(_state: FormState, formData: FormData): Promise<FormState> {
  "use server";
  const runId = String(formData.get("run_id") ?? "");
  try {
    await apiRequest(`/api/v1/runs/${runId}/request-changes`, { method: "POST" });
  } catch (error) {
    return formErrorFromUnknown(error, "Request changes failed.");
  }
  revalidatePath(`/runs/${runId}`);
  return formSuccess("Changes requested — step re-queued.");
}

function StepRow({ step, artifacts }: { step: RunStep; artifacts: Artifact[] }) {
  const stepArtifacts = artifacts.filter((a) => a.run_step_id === step.id);

  return (
    <li className={`step-row step-${step.status}`}>
      <div className="step-head">
        <div className="step-order">{step.step_order}</div>
        <div className="step-body">
          <div className="step-title">
            <span className="step-role">{step.role}</span>
            <span className={`status-chip status-${step.status}`}>{step.status}</span>
            {step.pause_after && step.status !== "skipped" ? (
              <span className="pause-badge">pause after</span>
            ) : null}
          </div>
          <div className="step-meta">
            <span>Started {formatTimestamp(step.started_at)}</span>
            <span>Completed {formatTimestamp(step.completed_at)}</span>
            <span>Duration {stepDuration(step)}</span>
          </div>
          {step.error_message ? (
            <p className="step-error">{step.error_message}</p>
          ) : null}
          {stepArtifacts.length > 0 ? (
            <ul className="step-artifacts">
              {stepArtifacts.map((a) => (
                <li key={a.id}>
                  <Link href={`/artifacts/${a.id}`} className="text-link">
                    {a.name}
                  </Link>
                  <span className="artifact-type-chip">{a.artifact_type}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </li>
  );
}

export default async function RunDetailPage({
  params
}: {
  params: { runId: string };
}) {
  const { run, project, artifacts } = await fetchRunDetail(params.runId);
  const canPause = run.status === "running";
  const canResume = run.status === "paused";
  const canReject = run.status === "paused";
  const canRequestChanges = run.status === "paused";
  const canCancel = !["completed", "failed", "cancelled"].includes(run.status);

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">Run detail</p>
        <div className="hero-topline">
          <div>
            <h1>{run.workflow_type}</h1>
            <p className="lede">
              <Link href={`/projects/${project.id}`} className="text-link">{project.name}</Link>
            </p>
          </div>
          <span className={`status-chip status-${run.status}`}>{run.status}</span>
        </div>
        <div className="hero-meta">
          <span>{run.trigger_actor}</span>
          <span>Started {formatTimestamp(run.started_at)}</span>
          {run.paused_at ? <span>Paused {formatTimestamp(run.paused_at)}</span> : null}
          {run.completed_at ? <span>Finished {formatTimestamp(run.completed_at)}</span> : null}
          <Link href="/runs" className="text-link">Back to runs</Link>
        </div>
      </section>

      {run.error_message ? (
        <article className="card">
          <p className="run-error-block">{run.error_message}</p>
        </article>
      ) : null}

      {/* run controls */}
      {(canPause || canResume || canReject || canRequestChanges || canCancel) ? (
        <article className="card">
          <div className="section-head tight">
            <div>
              <p className="eyebrow">Controls</p>
              <h2>Run actions</h2>
            </div>
          </div>
          <div className="run-controls">
            {canResume ? (
              <ActionForm action={resumeRunAction} className="inline-form">
                <input type="hidden" name="run_id" value={run.id} />
                <button type="submit" className="button-primary">Resume run</button>
              </ActionForm>
            ) : null}
            {canRequestChanges ? (
              <ActionForm action={requestChangesAction} className="inline-form">
                <input type="hidden" name="run_id" value={run.id} />
                <button type="submit" className="button-secondary">Request changes</button>
              </ActionForm>
            ) : null}
            {canReject ? (
              <ActionForm action={rejectRunAction} className="inline-form">
                <input type="hidden" name="run_id" value={run.id} />
                <button type="submit" className="button-danger">Reject run</button>
              </ActionForm>
            ) : null}
            {canPause ? (
              <ActionForm action={pauseRunAction} className="inline-form">
                <input type="hidden" name="run_id" value={run.id} />
                <button type="submit" className="button-secondary">Pause run</button>
              </ActionForm>
            ) : null}
            {canCancel ? (
              <ActionForm action={cancelRunAction} className="inline-form">
                <input type="hidden" name="run_id" value={run.id} />
                <button type="submit" className="button-secondary">Cancel run</button>
              </ActionForm>
            ) : null}
          </div>
        </article>
      ) : null}

      <article className="card">
        <div className="section-head">
          <div>
            <p className="eyebrow">Steps</p>
            <h2>Run plan</h2>
          </div>
          <p className="meta">{run.steps.length} steps</p>
        </div>

        <ol className="step-list">
          {run.steps.map((step) => (
            <StepRow key={step.id} step={step} artifacts={artifacts} />
          ))}
        </ol>
      </article>

      {artifacts.length > 0 ? (
        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Output</p>
              <h2>Artifacts</h2>
            </div>
            <p className="meta">{artifacts.length} artifacts</p>
          </div>
          <ul className="artifact-list">
            {artifacts.map((a) => (
              <li key={a.id} className="artifact-item">
                <div className="artifact-head">
                  <span className="artifact-type-chip">{a.artifact_type}</span>
                  <span className="artifact-role">{a.role ?? "—"}</span>
                </div>
                <Link href={`/artifacts/${a.id}`} className="text-link artifact-name">
                  {a.name}
                </Link>
                <span className="artifact-meta">{formatTimestamp(a.created_at)}</span>
              </li>
            ))}
          </ul>
        </article>
      ) : null}
    </main>
  );
}
