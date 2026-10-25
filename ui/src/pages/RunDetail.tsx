import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, CodeBlock, Markdown } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { formatWhen } from "../lib/format";

type Step = { ordinal: number; name: string; status: string; detail: Record<string, unknown>; created_at: string };
type Artifact = { id: string; name: string; media_type: string; size_bytes: number };
type Run = {
  id: string;
  agent_id: string;
  agent_name: string;
  status: string;
  error: string | null;
  needs_review_reason: string | null;
  report_markdown: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  spec: { spec?: { goal?: string } };
  summary: { llm_calls?: { model?: string; latency_ms?: number; prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }[]; cross_checks?: { name: string; ok: boolean; sql_value?: unknown; code_value?: unknown; error?: string }[] };
  steps: Step[];
  artifacts: Artifact[];
};

const PIPELINE: [string, string][] = [
  ["introspect", "Şema"],
  ["plan", "Plan"],
  ["sql_guard", "SQL koruması"],
  ["explain", "Maliyet"],
  ["sql_execute", "Veri"],
  ["code_execute", "Kod"],
  ["verify", "Çapraz kontrol"],
  ["report", "Rapor"],
  ["notify", "Bildirim"],
];

export function RunDetail() {
  const { id = "" } = useParams();
  const [run, setRun] = useState<Run | null>(null);
  const [logs, setLogs] = useState("");
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Run>(`/api/runs/${id}`).then(setRun).catch((exc: ApiError) => setError(exc.message));
    api<{ text: string }>(`/api/runs/${id}/logs`).then((body) => setLogs(body.text || "")).catch(() => setLogs(""));
  }, [id]);

  async function openArtifact(artifact: Artifact) {
    const response = await fetch(`/backend/api/runs/${id}/artifacts/${artifact.id}`);
    const text = await response.text();
    setPreview(text);
  }

  if (error) return <div className="card">{error}</div>;
  if (!run) return <div className="card">Yükleniyor…</div>;
  const byName = new Map(run.steps.map((step) => [step.name, step]));
  const plan = run.steps.find((step) => step.name === "plan")?.detail || {};
  const sql = String(plan.sql || "");
  const codeStep = run.steps.find((step) => step.name === "code_execute");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{run.agent_name}</h1>
          <p><Link to={`/agents/${run.agent_id}`}>Ajana dön</Link> · {formatWhen(run.created_at)} → {formatWhen(run.finished_at)}</p>
        </div>
        <Badge status={run.status} />
      </div>
      {(run.error || run.needs_review_reason) && <section className="card">{run.needs_review_reason || run.error}</section>}
      <section className="grid-2">
        <article className="card">
          <h2>Adımlar</h2>
          <div className="timeline">
            {PIPELINE.map(([key, label]) => {
              const step = byName.get(key);
              const tone = !step ? "" : step.status === "succeeded" ? "ok" : step.status === "failed" ? "bad" : "warn";
              return (
                <div className={`item ${tone}`} key={key}>
                  <div className="rail" />
                  <div>
                    <strong>{label}</strong> {step ? <Badge status={step.status} /> : <span className="badge">bekliyor</span>}
                    <div>{step ? formatWhen(step.created_at) : "—"}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </article>
        <article className="card">
          <h2>Çapraz kontrol</h2>
          {(run.summary.cross_checks || []).length === 0 && <p>Kayıt yok.</p>}
          {(run.summary.cross_checks || []).map((check) => (
            <p key={check.name}><Badge status={check.ok ? "succeeded" : "failed"} /> {check.name}: SQL {String(check.sql_value ?? "—")} / kod {String(check.code_value ?? check.error ?? "—")}</p>
          ))}
          <h2>Model çağrıları</h2>
          {(run.summary.llm_calls || []).length === 0 && <p>Bu koşumda jeton kaydı yok.</p>}
          {(run.summary.llm_calls || []).map((call, index) => (
            <p key={index}>{call.model} · {call.latency_ms} ms · {call.prompt_tokens ?? 0}+{call.completion_tokens ?? 0} jeton</p>
          ))}
        </article>
      </section>
      <section className="grid-2">
        <article className="card"><h2>SQL</h2>{sql ? <CodeBlock code={sql} /> : <p>Plan SQL'i adımda yok.</p>}</article>
        <article className="card"><h2>Kod</h2><CodeBlock code={JSON.stringify(codeStep?.detail || {}, null, 2)} /></article>
      </section>
      <section className="card">
        <h2>Rapor</h2>
        {run.report_markdown ? <Markdown text={run.report_markdown} /> : <p>Rapor yazılmadı.</p>}
      </section>
      <section className="card">
        <h2>Artefaktlar</h2>
        {run.artifacts.map((artifact) => (
          <p key={artifact.id}>
            <button className="btn-ghost" type="button" onClick={() => void openArtifact(artifact)}>{artifact.name}</button>
            <a href={`/backend/api/runs/${run.id}/artifacts/${artifact.id}`}> indir</a>
            <span> · {artifact.size_bytes} bayt</span>
          </p>
        ))}
        {preview && <Markdown text={preview} />}
      </section>
      <section className="card">
        <h2>Günlük</h2>
        <CodeBlock code={logs || "Günlük yok."} />
      </section>
    </>
  );
}
