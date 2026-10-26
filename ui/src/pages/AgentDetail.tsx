import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, CodeBlock, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { formatWhen } from "../lib/format";

type Version = { version: number; status: string; created_at: string; spec: Record<string, unknown> };
type Detail = {
  id: string;
  name: string;
  owner: string;
  status: string;
  description: string;
  current_version: number | null;
  schedule: { mode: string; cron: string | null; paused: boolean; time_zone: string; max_runs_per_day: number; window: string; next_run_at: string | null } | null;
  spec: Record<string, unknown> | null;
  versions: Version[];
};
type RunRow = { id: string; status: string; created_at: string; trigger: string };

export function AgentDetail() {
  const { id = "" } = useParams();
  const [agent, setAgent] = useState<Detail | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [tab, setTab] = useState("overview");
  const [diff, setDiff] = useState("");
  const [error, setError] = useState("");
  const [goal, setGoal] = useState("");

  function load() {
    api<Detail>(`/api/agents/${id}`).then((body) => { setAgent(body); setGoal(body.description); }).catch((exc: ApiError) => setError(exc.message));
    api<RunRow[]>(`/api/runs?agent_id=${id}&limit=20`).then(setRuns).catch(() => setRuns([]));
  }
  useEffect(load, [id]);

  async function saveGoal() {
    if (!agent?.spec) return;
    const spec = structuredClone(agent.spec) as { spec?: { goal?: string } };
    if (spec.spec) spec.spec.goal = goal;
    await api(`/api/agents/${id}`, { method: "PATCH", body: JSON.stringify({ spec, publish: true, description: goal }) });
    load();
  }

  async function showDiff(left: number, right: number) {
    const body = await api<{ diff: string }>(`/api/agents/${id}/diff?left=${left}&right=${right}`);
    setDiff(body.diff || "No difference.");
    setTab("versions");
  }

  if (error) return <div className="card">{error}</div>;
  if (!agent) return <SkeletonRows />;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{agent.owner}</p>
          <h1>{agent.name}</h1>
          <p>Version {agent.current_version ?? "—"} · next {formatWhen(agent.schedule?.next_run_at)}</p>
        </div>
        <div className="row">
          <Badge status={agent.schedule?.paused ? "paused" : agent.status} />
          <button className="btn" type="button" onClick={() => api(`/api/agents/${id}/runs`, { method: "POST", body: "{}" }).then(load)}>Run now</button>
          <button className="btn-ghost" type="button" onClick={() => api(`/api/agents/${id}/pause`, { method: "POST", body: JSON.stringify({ paused: !agent.schedule?.paused }) }).then(load)}>
            {agent.schedule?.paused ? "Resume" : "Pause"}
          </button>
        </div>
      </div>
      <div className="tabs">
        {[["overview", "Overview"], ["spec", "Spec"], ["versions", "Versions"], ["runs", "Runs"]].map(([key, label]) => (
          <button key={key} className={tab === key ? "on" : ""} type="button" onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "overview" && (
        <section className="grid-2">
          <article className="card goal-card">
            <h2>Goal</h2>
            <textarea rows={5} value={goal} onChange={(event) => setGoal(event.target.value)} aria-label="Goal" />
            <div className="goal-actions">
              <button className="btn" type="button" onClick={() => void saveGoal()}>Save as a new version</button>
            </div>
          </article>
          <article className="card">
            <h2>Schedule</h2>
            {agent.schedule ? (
              <dl className="agent-meta">
                <div><dt>Mode</dt><dd>{agent.schedule.mode}</dd></div>
                <div><dt>Cron</dt><dd>{agent.schedule.cron || "—"}</dd></div>
                <div><dt>Time zone</dt><dd>{agent.schedule.time_zone}</dd></div>
                <div><dt>Window</dt><dd>{agent.schedule.window}</dd></div>
                <div><dt>Daily cap</dt><dd>{agent.schedule.max_runs_per_day}</dd></div>
                <div><dt>Next</dt><dd>{formatWhen(agent.schedule.next_run_at)}</dd></div>
              </dl>
            ) : <p>No schedule.</p>}
          </article>
        </section>
      )}
      {tab === "spec" && <section className="card"><CodeBlock code={JSON.stringify(agent.spec, null, 2)} /></section>}
      {tab === "versions" && (
        <section className="card">
          {agent.versions.map((version) => (
            <p key={version.version}>
              v{version.version} <Badge status={version.status} /> {formatWhen(version.created_at)}
              {version.version > 1 && <button className="btn-ghost" type="button" onClick={() => void showDiff(version.version - 1, version.version)}>Diff</button>}
            </p>
          ))}
          {diff && <CodeBlock code={diff} />}
        </section>
      )}
      {tab === "runs" && (
        <section className="card">
          {runs.map((run) => (
            <p key={run.id}><Badge status={run.status} /> <Link to={`/runs/${run.id}`}>{formatWhen(run.created_at)}</Link> · {run.trigger}</p>
          ))}
          {runs.length === 0 && <p>This agent has no runs.</p>}
        </section>
      )}
    </>
  );
}
