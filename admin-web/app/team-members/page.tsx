import Link from "next/link";
import { revalidatePath } from "next/cache";

import { apiRequest, buildReason, type TeamMember, type TeamMemberListResponse } from "../lib/api";

const teamRoles = ["pm", "ux", "dev-jr", "dev-sr", "qa", "devops", "judge", "custom"] as const;
const providers = ["ollama", "anthropic", "openai", "custom"] as const;

async function fetchTeamMembers() {
  return apiRequest<TeamMemberListResponse>("/api/v1/team-members");
}

async function createTeamMemberAction(formData: FormData) {
  "use server";

  const name = String(formData.get("name") ?? "").trim();
  const displayName = String(formData.get("display_name") ?? "").trim();
  const role = String(formData.get("role") ?? "");
  const description = String(formData.get("description") ?? "").trim();
  const skillsText = String(formData.get("skills") ?? "").trim();
  const provider = String(formData.get("provider") ?? "ollama");
  const model = String(formData.get("model") ?? "").trim();
  const isActive = formData.get("is_active") === "on";

  if (!name || !displayName || !role || !model) {
    throw new Error("Name, display name, role, and model are required");
  }

  const skills = skillsText
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  await apiRequest("/api/v1/team-members", {
    method: "POST",
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
        "initial_creation",
        "Creating a team member from the admin web so project staffing is visible and assignable inside the planning surface."
      )
    }
  });

  revalidatePath("/team-members");
}

export default async function TeamMembersPage() {
  const response = await fetchTeamMembers();
  const members = response.items;
  const activeMembers = members.filter((member) => member.is_active);

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">Team directory</p>
        <div className="hero-topline">
          <div>
            <h1>AI team members</h1>
            <p className="lede">
              Register the agents and operators available for project work, then assign them from each project detail view.
            </p>
          </div>
          <span className="status-chip status-active">{activeMembers.length} active</span>
        </div>

        <div className="hero-meta">
          <span>{members.length} total team members</span>
          <Link href="/" className="text-link">
            Back to projects
          </Link>
        </div>
      </section>

      <section className="grid grid-wide">
        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Create</p>
              <h2>Add team member</h2>
            </div>
          </div>

          <form action={createTeamMemberAction} className="form-stack">
            <div className="form-grid">
              <label className="field">
                <span>Name</span>
                <input name="name" type="text" placeholder="jane-doe" required />
              </label>

              <label className="field">
                <span>Display name</span>
                <input name="display_name" type="text" placeholder="Jane Doe" required />
              </label>
            </div>

            <div className="form-grid form-grid-3">
              <label className="field">
                <span>Role</span>
                <select name="role" required defaultValue="dev-sr">
                  {teamRoles.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Provider</span>
                <select name="provider" defaultValue="ollama">
                  {providers.map((provider) => (
                    <option key={provider} value={provider}>
                      {provider}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Model</span>
                <input name="model" type="text" placeholder="qwen3.5:35b-a3b" required />
              </label>
            </div>

            <label className="field">
              <span>Description</span>
              <textarea
                name="description"
                rows={4}
                placeholder="What role does this team member play in delivery and review?"
              />
            </label>

            <label className="field">
              <span>Skills</span>
              <input
                name="skills"
                type="text"
                placeholder="planning, react, testing, architecture"
              />
            </label>

            <label className="field field-inline">
              <span>Active now</span>
              <input name="is_active" type="checkbox" defaultChecked />
            </label>

            <button type="submit" className="button-primary">
              Create team member
            </button>
          </form>
        </article>

        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Roster</p>
              <h2>Available operators</h2>
            </div>
            <p className="meta">{members.length} registered</p>
          </div>

          {members.length === 0 ? (
            <p className="empty-state">No team members yet. Add the first role from this page.</p>
          ) : (
            <div className="stack-list">
              {members.map((member) => (
                <TeamMemberListCard key={member.id} member={member} />
              ))}
            </div>
          )}
        </article>
      </section>
    </main>
  );
}

function TeamMemberListCard({ member }: { member: TeamMember }) {
  return (
    <Link href={`/team-members/${member.id}`} className="list-card">
      <div className="list-card-top">
        <div>
          <h3>{member.display_name}</h3>
          <p>{member.description ?? "No description yet."}</p>
        </div>
        <span className={`status-chip ${member.is_active ? "status-active" : "status-archived"}`}>
          {member.is_active ? "active" : "inactive"}
        </span>
      </div>

      <div className="list-card-meta">
        <span>{member.role}</span>
        <span>{member.provider}</span>
        <span>{member.model}</span>
        <span>v{member.current_version}</span>
      </div>

      {member.skills.length > 0 ? (
        <ul className="criteria-list">
          {member.skills.map((skill) => (
            <li key={skill}>{skill}</li>
          ))}
        </ul>
      ) : null}
    </Link>
  );
}
