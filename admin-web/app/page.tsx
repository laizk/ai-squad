import Link from "next/link";
import { revalidatePath } from "next/cache";

import { apiRequest, buildReason, type ProjectListResponse } from "./lib/api";

const phase = process.env.NEXT_PUBLIC_APP_PHASE ?? "P0";

async function createProjectAction(formData: FormData) {
  "use server";

  const name = String(formData.get("name") ?? "").trim();
  const description = String(formData.get("description") ?? "").trim();
  const githubOrg = String(formData.get("github_org") ?? "").trim();
  const githubRepo = String(formData.get("github_repo") ?? "").trim();

  if (!name) {
    throw new Error("Project name is required");
  }

  await apiRequest("/api/v1/projects", {
    method: "POST",
    body: {
      name,
      description: description || null,
      github_org: githubOrg || null,
      github_repo: githubRepo || null,
      reason: buildReason(
        "initial_creation",
        "Creating a project from the admin web so the planning graph can be reviewed and edited in the UI."
      )
    }
  });

  revalidatePath("/");
}

export default async function HomePage() {
  const projects = await apiRequest<ProjectListResponse>("/api/v1/projects");

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">AI Squad</p>
        <h1>Phase {phase} planning desk</h1>
        <p className="lede">
          The admin web now reads the live control API and exposes the first reviewable planning surface:
          projects, milestones, and tasks with append-only revisions behind them.
        </p>

        <div className="hero-meta">
          <span>Phase {phase}</span>
          <Link href="/team-members" className="text-link">
            Manage team members
          </Link>
        </div>
      </section>

      <section className="grid grid-wide">
        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Projects</p>
              <h2>Active workspace</h2>
            </div>
            <p className="meta">{projects.total} total</p>
          </div>

          {projects.items.length === 0 ? (
            <p className="empty-state">No projects yet. Create the first project from this page.</p>
          ) : (
            <div className="stack-list">
              {projects.items.map((project) => (
                <Link key={project.id} href={`/projects/${project.id}`} className="list-card">
                  <div className="list-card-top">
                    <h3>{project.name}</h3>
                    <span className={`status-chip status-${project.status}`}>{project.status}</span>
                  </div>
                  <p>{project.description ?? "No description yet."}</p>
                  <div className="list-card-meta">
                    <span>v{project.current_version}</span>
                    <span>
                      {project.github_org && project.github_repo
                        ? `${project.github_org}/${project.github_repo}`
                        : "No GitHub repo linked"}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </article>

        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Create</p>
              <h2>New project</h2>
            </div>
          </div>

          <form action={createProjectAction} className="form-stack">
            <label className="field">
              <span>Name</span>
              <input name="name" type="text" placeholder="Planning workspace" required />
            </label>

            <label className="field">
              <span>Description</span>
              <textarea
                name="description"
                rows={4}
                placeholder="What is the product, and what should this team deliver?"
              />
            </label>

            <div className="form-grid">
              <label className="field">
                <span>GitHub org</span>
                <input name="github_org" type="text" placeholder="my-org" />
              </label>

              <label className="field">
                <span>GitHub repo</span>
                <input name="github_repo" type="text" placeholder="my-repo" />
              </label>
            </div>

            <button type="submit" className="button-primary">
              Create project
            </button>
          </form>
        </article>
      </section>
    </main>
  );
}
