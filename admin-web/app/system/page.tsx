import Link from "next/link";

import { apiRequest, type HealthResponse } from "../lib/api";

const plannedServices = [
  "postgres",
  "redis",
  "ollama",
  "control-api",
  "admin-web",
  "workers",
  "github-svc",
  "sandbox-dispatcher",
  "sandbox-runner"
] as const;

async function fetchHealth() {
  return apiRequest<HealthResponse>("/api/v1/health");
}

export default async function SystemPage() {
  const health = await fetchHealth();

  const dependencyCards = [
    {
      name: "Postgres",
      state: health.postgres,
      detail: health.postgres_detail || "No detail returned by health endpoint."
    },
    {
      name: "Redis",
      state: health.redis,
      detail: health.redis_detail || "No detail returned by health endpoint."
    }
  ];

  const liveServices = new Set(["postgres", "redis", "control-api", "admin-web"]);

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">System</p>
        <div className="hero-topline">
          <div>
            <h1>Local stack health</h1>
            <p className="lede">
              This page reports the real control-api health response and the current platform shape. It should stay honest
              about what exists now versus what is only planned for later phases.
            </p>
          </div>
          <span className={`status-chip status-${health.status}`}>{health.status}</span>
        </div>

        <div className="hero-meta">
          <span>{health.service}</span>
          <span>{health.environment}</span>
          <span>Phase {health.phase}</span>
          <span>{health.version}</span>
          <Link href="/" className="text-link">
            Back to projects
          </Link>
        </div>
      </section>

      <section className="grid grid-wide">
        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Dependencies</p>
              <h2>Live health checks</h2>
            </div>
            <p className="meta">{dependencyCards.length} reported</p>
          </div>

          <div className="stack-list">
            {dependencyCards.map((dependency) => (
              <div key={dependency.name} className="list-card">
                <div className="list-card-top">
                  <h3>{dependency.name}</h3>
                  <span className={`status-chip status-${dependency.state}`}>{dependency.state}</span>
                </div>
                <p>{dependency.detail}</p>
              </div>
            ))}
          </div>
        </article>

        <article className="card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Model Activity</p>
              <h2>Current truth</h2>
            </div>
          </div>

          <div className="stack-list">
            <div className="list-card">
              <div className="list-card-top">
                <h3>Workers</h3>
                <span className="status-chip status-other">not started</span>
              </div>
              <p>No worker orchestration is running yet, so there is no current or recent model activity feed to display.</p>
            </div>

            <div className="list-card">
              <div className="list-card-top">
                <h3>Ollama</h3>
                <span className="status-chip status-other">not wired</span>
              </div>
              <p>Health currently reports Postgres and Redis only. Ollama and runtime telemetry belong to later phases.</p>
            </div>
          </div>
        </article>
      </section>

      <article className="card">
        <div className="section-head">
          <div>
            <p className="eyebrow">Roadmap Fit</p>
            <h2>Expected local services</h2>
          </div>
          <p className="meta">{plannedServices.length} planned</p>
        </div>

        <div className="stack-list">
          {plannedServices.map((serviceName) => (
            <div key={serviceName} className="list-card">
              <div className="list-card-top">
                <h3>{serviceName}</h3>
                <span className={`status-chip ${liveServices.has(serviceName) ? "status-active" : "status-other"}`}>
                  {liveServices.has(serviceName) ? "present" : "planned"}
                </span>
              </div>
              <p>
                {liveServices.has(serviceName)
                  ? "This service is part of the current local stack."
                  : "This service is part of the platform target but is not shipped in the current phase."}
              </p>
            </div>
          ))}
        </div>
      </article>
    </main>
  );
}
