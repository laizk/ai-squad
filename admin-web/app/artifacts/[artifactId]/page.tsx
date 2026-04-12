import Link from "next/link";
import { notFound } from "next/navigation";

import { apiRequest, type ArtifactContent } from "../../lib/api";

async function fetchArtifact(artifactId: string) {
  try {
    return await apiRequest<ArtifactContent>(`/api/v1/artifacts/${artifactId}/content`);
  } catch (error) {
    if (error instanceof Error && error.message === "Artifact not found") {
      notFound();
    }
    throw error;
  }
}

function formatBody(body: string): string {
  try {
    return JSON.stringify(JSON.parse(body), null, 2);
  } catch {
    return body;
  }
}

export default async function ArtifactPage({
  params
}: {
  params: { artifactId: string };
}) {
  const artifact = await fetchArtifact(params.artifactId);

  return (
    <main className="shell page-stack">
      <section className="hero">
        <p className="eyebrow">Artifact</p>
        <div className="hero-topline">
          <div>
            <h1>{artifact.name}</h1>
          </div>
          <span className="artifact-type-chip artifact-type-large">{artifact.artifact_type}</span>
        </div>
        <div className="hero-meta">
          <span>{artifact.id}</span>
          <Link href="/runs" className="text-link">Back to runs</Link>
        </div>
      </section>

      <article className="card">
        <div className="section-head">
          <div>
            <p className="eyebrow">Content</p>
            <h2>Artifact body</h2>
          </div>
        </div>
        <pre className="artifact-body">{formatBody(artifact.body)}</pre>
      </article>
    </main>
  );
}
