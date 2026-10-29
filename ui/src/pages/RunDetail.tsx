import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ActionButton, Badge, CodeBlock, Markdown, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useBusy } from "../lib/busy";
import { copy } from "../lib/copy";
import { presentText } from "../lib/errors";
import { formatNumber, formatWhen } from "../lib/format";
import { announceError, announceRun, notify } from "../lib/notify";

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
  summary: { delivery_warning?: string; llm_calls?: { model?: string; latency_ms?: number; prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }[]; cross_checks?: { name: string; ok: boolean; sql_value?: unknown; code_value?: unknown; error?: string }[] } | null;
  steps: Step[];
  artifacts: Artifact[];
  deliveries?: Delivery[];
};

type Delivery = {
  id: string;
  channel_name: string;
  recipients: { to?: string[]; cc?: string[] };
  subject: string;
  status: string;
  error: string | null;
  created_at: string;
};

const ACTIVE = new Set(["pending", "running"]);

const PIPELINE: [string, string][] = [
  ["introspect", "Schema"],
  ["plan", "Plan"],
  ["sql_guard", "SQL guard"],
  ["explain", "Cost"],
  ["sql_execute", "Data"],
  ["code_execute", "Code"],
  ["verify", "Cross-check"],
  ["report", "Report"],
  ["notify", "Notify"],
];

export function RunDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState<Run | null>(null);
  const [logs, setLogs] = useState("");
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const { run: busyRun, pending } = useBusy();
  const { can } = useAuth();
  const inflightRef = useRef(false);

  const load = useCallback(() => {
    if (!id || inflightRef.current) return;
    inflightRef.current = true;
    Promise.all([
      api<Run>(`/api/runs/${id}`).then(setRun).catch((exc: ApiError) => setError(exc.message)),
      api<{ text: string }>(`/api/runs/${id}/logs`).then((body) => setLogs(body.text || "")).catch(() => setLogs("")),
    ]).finally(() => {
      inflightRef.current = false;
    });
  }, [id]);

  useEffect(() => {
    inflightRef.current = false;
    load();
  }, [load]);

  const isActive = Boolean(run && ACTIVE.has(run.status));

  useEffect(() => {
    if (!isActive) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      load();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [isActive, load]);

  function resend(logId: string) {
    void busyRun(`resend:${logId}`, async () => {
      try {
        await api(`/api/runs/${id}/deliveries/${logId}/resend`, { method: "POST" });
        notify({ tone: "success", title: copy.resent });
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function rerunCurrent() {
    if (!run) return;
    void busyRun("rerun", async () => {
      try {
        const created = await api<{ id: string; agent_name: string }>(`/api/runs/${run.id}/rerun`, { method: "POST" });
        announceRun(created, run.agent_name);
        navigate(`/runs/${created.id}`);
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function cancelCurrent() {
    if (!run) return;
    void busyRun("cancel", async () => {
      try {
        await api(`/api/runs/${run.id}/cancel`, { method: "POST" });
        notify({ tone: "info", title: copy.cancelledRun });
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  async function openArtifact(artifact: Artifact) {
    const response = await fetch(`/backend/api/runs/${id}/artifacts/${artifact.id}`);
    const text = await response.text();
    setPreview(text);
  }

  if (error) return <div className="card">{error}</div>;
  if (!run) return <SkeletonRows />;
  const byName = new Map(run.steps.map((step) => [step.name, step]));
  const currentStepKey = isActive ? PIPELINE.find(([key]) => !byName.has(key))?.[0] : undefined;
  const plan = run.steps.find((step) => step.name === "plan")?.detail || {};
  const sql = String(plan.sql || "");
  const codeStep = run.steps.find((step) => step.name === "code_execute");
  const reason = presentText(run.needs_review_reason || run.error || "");
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Run</p>
          <h1>{run.agent_name}</h1>
          <p><Link to={`/agents/${run.agent_id}`}>Back to agent</Link> · {formatWhen(run.created_at)} → {formatWhen(run.finished_at)}</p>
        </div>
        <div className="row">
          <Badge status={run.status} />
          {isActive && (
            <ActionButton
              className="btn-ghost"
              busy={pending("cancel")}
              disabled={!can("run:cancel")}
              title={!can("run:cancel") ? copy.permissionDeniedHint : undefined}
              onClick={cancelCurrent}
            >
              {copy.cancel}
            </ActionButton>
          )}
          <ActionButton
            className="btn-ghost"
            busy={pending("rerun")}
            disabled={!can("run:rerun")}
            title={!can("run:rerun") ? copy.permissionDeniedHint : undefined}
            onClick={rerunCurrent}
          >
            Rerun
          </ActionButton>
        </div>
      </div>
      {reason && <section className="card alert">{reason}</section>}
      {run.summary?.delivery_warning && (
        <section className="card notice">
          <strong>{copy.deliveryWarningTitle}</strong>
          <p>{presentText(run.summary.delivery_warning)}</p>
          <p>{copy.deliveryWarningBody}</p>
        </section>
      )}
      <section className="grid-2">
        <article className="card">
          <h2>Steps</h2>
          <div className="timeline">
            {PIPELINE.map(([key, label]) => {
              const step = byName.get(key);
              const tone = !step
                ? key === currentStepKey
                  ? "warn"
                  : ""
                : step.status === "succeeded"
                  ? "ok"
                  : step.status === "failed"
                    ? "bad"
                    : "warn";
              const gap = ACTIVE.has(run.status)
                ? <span className="badge">{copy.waiting}</span>
                : <span className="badge muted" title={copy.stepDidNotRun}>{copy.skipped}</span>;
              return (
                <div className={`item ${tone}`} key={key}>
                  <div className="rail" />
                  <div>
                    <strong>{label}</strong> {step ? <Badge status={step.status} /> : gap}
                    <div>{step ? formatWhen(step.created_at) : "—"}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </article>
        <article className="card">
          <h2>Report</h2>
          <div className="report-pane">
            {run.report_markdown ? <Markdown text={run.report_markdown} /> : <p>No report was written.</p>}
          </div>
        </article>
      </section>
      <section className="grid-2">
        <article className="card">
          <h2>Cross-check</h2>
          {(run.summary?.cross_checks || []).length === 0 && <p>No records.</p>}
          {(run.summary?.cross_checks || []).map((check) => (
            <p key={check.name}><Badge status={check.ok ? "succeeded" : "failed"} /> {check.name}: SQL {String(check.sql_value ?? "—")} / code {String(check.code_value ?? check.error ?? "—")}</p>
          ))}
        </article>
        <article className="card">
          <h2>Model calls</h2>
          {(run.summary?.llm_calls || []).length === 0 && <p>This run has no token record.</p>}
          {(run.summary?.llm_calls || []).map((call, index) => (
            <p key={index}>{call.model} · {call.latency_ms} ms · {formatNumber(call.prompt_tokens ?? 0)}+{formatNumber(call.completion_tokens ?? 0)} tokens</p>
          ))}
        </article>
      </section>
      <section className="grid-2">
        <article className="card"><h2>SQL</h2>{sql ? <CodeBlock code={sql} /> : <p>The plan step has no SQL.</p>}</article>
        <article className="card"><h2>Code</h2><CodeBlock code={JSON.stringify(codeStep?.detail || {}, null, 2)} /></article>
      </section>
      <section className="card">
        <h2>Artifacts</h2>
        {run.artifacts.length === 0 && <p>No artifacts.</p>}
        {run.artifacts.map((artifact) => (
          <p key={artifact.id}>
            <button className="btn-ghost" type="button" onClick={() => void openArtifact(artifact)}>{artifact.name}</button>
            <a href={`/backend/api/runs/${run.id}/artifacts/${artifact.id}`}> Download</a>
            <span> · {formatNumber(artifact.size_bytes)} bytes · {artifact.media_type}</span>
          </p>
        ))}
        {preview && <Markdown text={preview} />}
      </section>
      <section className="card">
        <h2>{copy.deliverySection}</h2>
        {(run.deliveries || []).length === 0 && <p>{copy.noDeliveries}</p>}
        {(run.deliveries || []).map((item) => (
          <p key={item.id}>
            <Badge status={item.status === "sent" ? "succeeded" : item.status === "skipped" ? "paused" : "failed"} />
            {" "}{item.channel_name || "—"} · {(item.recipients.to || []).join(", ") || "—"}
            {item.recipients.cc && item.recipients.cc.length > 0 ? ` · cc ${item.recipients.cc.join(", ")}` : ""}
            {" · "}{item.subject} · {formatWhen(item.created_at)}
            {item.error ? ` · ${presentText(item.error)}` : ""}
            <ActionButton
              className="btn-ghost"
              busy={pending(`resend:${item.id}`)}
              disabled={!can("delivery:resend")}
              title={!can("delivery:resend") ? copy.permissionDeniedHint : undefined}
              onClick={() => resend(item.id)}
            >
              {copy.resend}
            </ActionButton>
          </p>
        ))}
      </section>
      <section className="card">
        <h2>Logs</h2>
        <CodeBlock code={logs || "No logs."} />
      </section>
    </>
  );
}
