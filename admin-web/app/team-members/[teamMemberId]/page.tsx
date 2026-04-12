import Link from "next/link";
import { notFound } from "next/navigation";
import { revalidatePath } from "next/cache";

import {
  apiRequest,
  buildReason,
  type Revision,
  type RevisionListResponse,
  type TeamMember
} from "../../lib/api";

const teamRoles = ["pm", "ux", "dev-jr", "dev-sr", "qa", "devops", "judge", "custom"] as const;
const providers = ["ollama", "anthropic", "openai", "custom"] as const;

async function fetchTeamMember(teamMemberId: string) {
  try {
    const [member, revisions] = await Promise.all([
      apiRequest<TeamMember>(`/api/v1/team-members/${teamMemberId}`),
      apiRequest<RevisionListResponse>(`/api/v1/revisions/team_member/${teamMemberId}`)
    ]);

    return {
      member,
      revisions: revisions.revisions.slice().reverse()
    };
  } catch (error) {
    if (error instanceof Error && error.message === "Team member not found") {
      notFound();
    }
    throw error;
  }
}

async function updateTeamMemberAction(formData: FormData) {
  "use server";

  const teamMemberId = String(formData.get("team_member_id") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  const displayName = String(formData.get("display_name") ?? "").trim();
  const role = String(formData.get("role") ?? "");
  const description = String(formData.get("description") ?? "").trim();
  const skillsText = String(formData.get("skills") ?? "").trim();
  const provider = String(formData.get("provider") ?? "ollama");
  const model = String(formData.get("model") ?? "").trim();
  const isActive = formData.get("is_active") === "on";

  if (!teamMemberId || !name || !displayName || !role || !model) {
    throw new Error("Team member update is missing required fields");
  }

  const skills = skillsText
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  await apiRequest(`/api/v1/team-members/${teamMemberId}`, {
    method: "PATCH",
    body: {
      name,
      display_name: displayName,
      role,
      description: description || null,
      skills,
      provider,
      model,
      is_active: isActive,
      reason: buildReason(
        "scope_change",
        "Updating a team member from the admin web so assignment defaults and role metadata stay aligned with current delivery needs."
      )
    }
  });

  revalidatePath("/team-members");
  revalidatePath(`/team-members/${teamMemberId}`);
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

export default async function TeamMemberDetailPage({
  params
}: {
  params: { teamMemberId: string };
}) {
  const { member, revisions } = await fetchTeamMember(params.teamMemberId);

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">Team member</p>
        <div className="hero-topline">
          <div>
            <h1>{member.display_name}</h1>
            <p className="lede">{member.description ?? "No description yet."}</p>
          </div>
          <span className={`status-chip ${member.is_active ? "status-active" : "status-archived"}`}>
            {member.is_active ? "active" : "inactive"}
          </span>
        </div>

        <div className="hero-meta">
          <span>{member.role}</span>
          <span>{member.provider}</span>
          <span>{member.model}</span>
          <span>Version {member.current_version}</span>
          <Link href="/team-members" className="text-link">
            Back to team
          </Link>
        </div>
      </section>

      <section className="grid grid-wide">
        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Profile</p>
              <h2>Edit defaults</h2>
            </div>
          </div>

          <form action={updateTeamMemberAction} className="form-stack">
            <input type="hidden" name="team_member_id" value={member.id} />

            <div className="form-grid">
              <label className="field">
                <span>Name</span>
                <input name="name" type="text" defaultValue={member.name} required />
              </label>

              <label className="field">
                <span>Display name</span>
                <input name="display_name" type="text" defaultValue={member.display_name} required />
              </label>
            </div>

            <div className="form-grid form-grid-3">
              <label className="field">
                <span>Role</span>
                <select name="role" defaultValue={member.role}>
                  {teamRoles.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Provider</span>
                <select name="provider" defaultValue={member.provider}>
                  {providers.map((provider) => (
                    <option key={provider} value={provider}>
                      {provider}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Model</span>
                <input name="model" type="text" defaultValue={member.model} required />
              </label>
            </div>

            <label className="field">
              <span>Description</span>
              <textarea name="description" rows={4} defaultValue={member.description ?? ""} />
            </label>

            <label className="field">
              <span>Skills</span>
              <input name="skills" type="text" defaultValue={member.skills.join(", ")} />
            </label>

            <label className="field field-inline">
              <span>Active now</span>
              <input name="is_active" type="checkbox" defaultChecked={member.is_active} />
            </label>

            <button type="submit" className="button-primary">
              Save team member
            </button>
          </form>
        </article>

        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Snapshot</p>
              <h2>Current state</h2>
            </div>
          </div>

          <div className="stack-list">
            <div className="list-card">
              <div className="list-card-top">
                <h3>Identity</h3>
                <span className="status-chip status-scope_change">current</span>
              </div>
              <div className="list-card-meta">
                <span>{member.name}</span>
                <span>{member.display_name}</span>
              </div>
            </div>

            <div className="list-card">
              <div className="list-card-top">
                <h3>Execution defaults</h3>
                <span className="status-chip status-fix">runtime</span>
              </div>
              <div className="list-card-meta">
                <span>{member.role}</span>
                <span>{member.provider}</span>
                <span>{member.model}</span>
              </div>
            </div>

            <div className="list-card">
              <div className="list-card-top">
                <h3>Skills</h3>
                <span className="status-chip status-other">{member.skills.length}</span>
              </div>
              {member.skills.length === 0 ? (
                <p className="empty-state">No skills captured yet.</p>
              ) : (
                <ul className="criteria-list">
                  {member.skills.map((skill) => (
                    <li key={skill}>{skill}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </article>
      </section>

      <article className="card">
        <div className="section-head">
          <div>
            <p className="eyebrow">Revisions</p>
            <h2>Audit history</h2>
          </div>
          <p className="meta">{revisions.length} recorded</p>
        </div>

        {revisions.length === 0 ? (
          <p className="empty-state">No revisions recorded for this team member yet.</p>
        ) : (
          <ol className="timeline">
            {revisions.map((revision) => (
              <TeamMemberRevisionRow key={revision.revision_number} revision={revision} />
            ))}
          </ol>
        )}
      </article>
    </main>
  );
}

function TeamMemberRevisionRow({ revision }: { revision: Revision }) {
  return (
    <li className="timeline-row">
      <div className="timeline-marker" aria-hidden="true" />
      <div className="timeline-body">
        <div className="timeline-head">
          <span className={`status-chip status-${revision.reason.category}`}>
            {revision.reason.category}
          </span>
          <span className="timeline-entity">team member</span>
          <span className="timeline-version">v{revision.revision_number}</span>
        </div>
        <p className="timeline-summary">{revision.change_summary}</p>
        <p className="timeline-reason">{revision.reason.detail}</p>
        <div className="timeline-meta">
          <span>{revision.actor}</span>
          <span>{formatTimestamp(revision.created_at)}</span>
        </div>
      </div>
    </li>
  );
}
