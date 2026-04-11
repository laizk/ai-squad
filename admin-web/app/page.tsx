const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const phase = process.env.NEXT_PUBLIC_APP_PHASE ?? "P-1";

const checklist = [
  "Postgres and Redis containers start cleanly",
  "Control API responds on /api/v1/health",
  "Admin web loads without client-side errors",
  "The repo now has a real scaffold to build on"
];

export default function HomePage() {
  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">AI Squad</p>
        <h1>Phase {phase} scaffold</h1>
        <p className="lede">
          This is the first deployable slice: a minimal control plane and a
          browser entry point, with no agent runtime or model dependency yet.
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
