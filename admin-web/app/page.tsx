const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const phase = process.env.NEXT_PUBLIC_APP_PHASE ?? "P-1";

const checklist = [
  "Postgres bootstrap marker exists and is queryable",
  "Redis responds to a real ping from control-api",
  "Control API reports dependency truth instead of a hardcoded ok",
  "Admin web stays minimal while the foundation layer becomes real"
];

export default function HomePage() {
  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">AI Squad</p>
        <h1>Phase {phase} foundation</h1>
        <p className="lede">
          The stack now checks real Postgres and Redis dependencies and carries
          a minimal schema marker, while the UI remains intentionally thin.
        </p>
      </section>

      <section className="grid">
        <article className="card">
          <h2>Control API</h2>
          <p>Expected health endpoint:</p>
          <code>{apiUrl}/api/v1/health</code>
        </article>

        <article className="card">
          <h2>Current intent</h2>
          <ul>
            {checklist.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
      </section>
    </main>
  );
}
