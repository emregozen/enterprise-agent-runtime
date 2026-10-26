import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { presentText } from "../lib/errors";
import { SkeletonRows } from "../components/ui";

type Settings = {
  llm_mode: string;
  artifact_store: string;
  run_backend: string;
  encryption_configured: boolean;
  egress: { mode: string; note: string };
};

export function SettingsPage() {
  const [data, setData] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Settings>("/api/settings").then(setData).catch((exc: ApiError) => setError(exc.message));
  }, []);
  if (error) return <div className="card">{error}</div>;
  if (!data) return <SkeletonRows />;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Platform</p>
          <h1>Settings</h1>
          <p>Sources and models come from this console. Environment variables are only the first-boot seed.</p>
        </div>
      </div>
      <section className="grid-3">
        <article className="card kpi"><div className="label">Model mode</div><div className="value">{data.llm_mode}</div></article>
        <article className="card kpi"><div className="label">Artifacts</div><div className="value">{data.artifact_store}</div></article>
        <article className="card kpi"><div className="label">Encryption</div><div className="value">{data.encryption_configured ? "Key present" : "Development"}</div></article>
      </section>
      <section className="card">
        <h2>Egress</h2>
        <p>{presentText(data.egress.note)}</p>
        <p>A run pod is not open to the internet. A new address is added only through Helm <code>networkPolicy.extraEgress</code>. Private ranges can be kept out with <code>except</code>. In production, prefer an EgressFirewall by DNS name or an egress proxy.</p>
      </section>
      <section className="card">
        <h2>Secrets</h2>
        <p>There are three places a secret can live. Platform DB stores the value with Fernet. The key is the <code>agent-runtime-master-key</code> Secret. A Kubernetes Secret reference is mounted into the run pod when the reference is a full URL. For Conjur and CCP, the database stores only the path. The control plane reads the value when a run starts and places it in that run's Secret. Provider credentials are also not plaintext. They come from a Secret in the control-plane namespace. See <Link to="/secrets">Secret sources</Link>. The API never returns these values. The run Secret is deleted with the Job. The executor container does not receive the secret.</p>
      </section>
    </>
  );
}
