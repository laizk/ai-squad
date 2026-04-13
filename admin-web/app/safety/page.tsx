import Link from "next/link";
import { revalidatePath } from "next/cache";

import { ActionForm } from "../components/action-form";
import { apiRequest } from "../lib/api";
import { formError, formErrorFromUnknown, formSuccess, type FormState } from "../lib/form-state";

type ViolationSeverity = "warning" | "critical";

type SafetyViolation = {
  id: string;
  run_id: string | null;
  step_id: string | null;
  role: string | null;
  violation_type: string;
  severity: ViolationSeverity;
  detail: string;
  resolved: boolean;
  resolved_at: string | null;
  created_at: string;
};

type SafetyViolationListResponse = {
  total: number;
  items: SafetyViolation[];
};

async function fetchViolations(unresolvedOnly: boolean) {
  const qs = unresolvedOnly ? "?unresolved_only=true&per_page=100" : "?per_page=100";
  return apiRequest<SafetyViolationListResponse>(`/api/v1/safety-violations${qs}`);
}

async function resolveViolationAction(
  _state: FormState,
  formData: FormData
): Promise<FormState> {
  "use server";
  const id = String(formData.get("violation_id") ?? "").trim();
  if (!id) return formError("Missing violation ID.");

  try {
    await apiRequest(`/api/v1/safety-violations/${id}/resolve`, { method: "POST" });
  } catch (error) {
    return formErrorFromUnknown(error, "Resolve failed.");
  }
  revalidatePath("/safety");
  return formSuccess("Violation resolved.");
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

function ViolationRow({ violation }: { violation: SafetyViolation }) {
  return (
    <li className="list-card">
      <div className="list-card-top">
        <div>
          <h3>
            <span className={`status-chip status-${violation.severity}`}>
              {violation.severity}
            </span>{" "}
            {violation.violation_type}
          </h3>
          <p className="list-card-meta">
            {violation.role && <span>role: {violation.role}</span>}
            {violation.run_id && (
              <span>
                run:{" "}
                <Link href={`/runs/${violation.run_id}`} className="text-link">
                  {violation.run_id.slice(0, 8)}…
                </Link>
              </span>
            )}
            <span>{formatTimestamp(violation.created_at)}</span>
            {violation.resolved && (
              <span>resolved {formatTimestamp(violation.resolved_at)}</span>
            )}
          </p>
          <p style={{ marginTop: "0.5rem", fontSize: "0.85rem", opacity: 0.85 }}>
            {violation.detail.slice(0, 400)}
            {violation.detail.length > 400 ? "…" : ""}
          </p>
        </div>
        <span className={`status-chip status-${violation.resolved ? "completed" : "failed"}`}>
          {violation.resolved ? "resolved" : "open"}
        </span>
      </div>
      {!violation.resolved && (
        <div className="list-card-actions" style={{ marginTop: "0.75rem" }}>
          <ActionForm action={resolveViolationAction} className="inline-form">
            <input type="hidden" name="violation_id" value={violation.id} />
            <button type="submit" className="button-secondary">Resolve</button>
          </ActionForm>
        </div>
      )}
    </li>
  );
}

export default async function SafetyPage({
  searchParams
}: {
  searchParams: Promise<{ unresolved?: string }>;
}) {
  const params = await searchParams;
  const unresolvedOnly = params.unresolved === "true";
  const data = await fetchViolations(unresolvedOnly);

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">Safety</p>
        <div className="hero-topline">
          <div>
            <h1>Safety violations</h1>
            <p className="lede">
              Agent and infrastructure safety events recorded during workflow execution.
              Review and resolve violations before approving related runs.
            </p>
          </div>
          <span className={`status-chip status-${data.total === 0 ? "completed" : "failed"}`}>
            {data.total} total
          </span>
        </div>

        <div className="hero-meta">
          <Link
            href="/safety"
            className={`text-link${!unresolvedOnly ? " text-link-active" : ""}`}
          >
            All
          </Link>
          <Link
            href="/safety?unresolved=true"
            className={`text-link${unresolvedOnly ? " text-link-active" : ""}`}
          >
            Unresolved only
          </Link>
          <Link href="/" className="text-link">
            Back to projects
          </Link>
        </div>
      </section>

      {data.items.length === 0 ? (
        <section>
          <p style={{ opacity: 0.6 }}>
            {unresolvedOnly ? "No unresolved safety violations." : "No safety violations recorded."}
          </p>
        </section>
      ) : (
        <section>
          <ul className="list-stack">
            {data.items.map((v) => (
              <ViolationRow key={v.id} violation={v} />
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
