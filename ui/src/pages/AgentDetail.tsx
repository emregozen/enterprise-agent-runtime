import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { DeliveryEditor, draftsFromSpec, writeDelivery, type ChannelChoice, type DraftTarget } from "../components/DeliveryTargets";
import { ActionButton, Badge, CodeBlock, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useBusy } from "../lib/busy";
import { copy } from "../lib/copy";
import { formatWhen } from "../lib/format";
import { announceError, announceRun, notify } from "../lib/notify";

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
  const [channels, setChannels] = useState<ChannelChoice[]>([]);
  const [targets, setTargets] = useState<DraftTarget[]>([]);
  const { run, pending } = useBusy();

  function load() {
    api<Detail>(`/api/agents/${id}`).then((body) => {
      setAgent(body);
      setGoal(body.description);
      setTargets(draftsFromSpec(body.spec));
    }).catch((exc: ApiError) => setError(exc.message));
    api<RunRow[]>(`/api/runs?agent_id=${id}&limit=20`).then(setRuns).catch(() => setRuns([]));
    api<ChannelChoice[]>("/api/delivery-channels").then(setChannels).catch(() => setChannels([]));
  }
  useEffect(load, [id]);

  function saveGoal() {
    if (!agent?.spec) return;
    void run("save", async () => {
      try {
        const spec = structuredClone(agent.spec) as { spec?: { goal?: string } };
        if (spec.spec) spec.spec.goal = goal;
        await api(`/api/agents/${id}`, { method: "PATCH", body: JSON.stringify({ spec, publish: true, description: goal }) });
        notify({ tone: "success", title: copy.savedVersion });
        load();
      } catch (exc) {
        announceError(exc, copy.couldNotSave);
      }
    });
  }

  function saveDelivery() {
    if (!agent?.spec) return;
    void run("delivery", async () => {
      try {
        const spec = writeDelivery(agent.spec as Record<string, unknown>, targets);
        await api(`/api/agents/${id}`, { method: "PATCH", body: JSON.stringify({ spec, publish: true }) });
        notify({ tone: "success", title: copy.savedVersion });
        load();
      } catch (exc) {
        announceError(exc, copy.couldNotSave);
      }
    });
  }

  function startRun() {
    if (!agent) return;
    void run("run", async () => {
      try {
        const created = await api<{ id: string; agent_name: string }>(`/api/agents/${id}/runs`, { method: "POST", body: "{}" });
        announceRun(created, agent.name);
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function togglePause() {
    if (!agent) return;
    const paused = !agent.schedule?.paused;
    void run("pause", async () => {
      try {
        await api(`/api/agents/${id}/pause`, { method: "POST", body: JSON.stringify({ paused }) });
        notify({ tone: "info", title: paused ? copy.agentPaused : copy.agentResumed });
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  async function showDiff(left: number, right: number) {
    try {
      const body = await api<{ diff: string }>(`/api/agents/${id}/diff?left=${left}&right=${right}`);
      setDiff(body.diff || "No difference.");
      setTab("versions");
    } catch (exc) {
      announceError(exc);
    }
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
          <ActionButton busy={pending("run")} onClick={startRun}>Run now</ActionButton>
          <ActionButton className="btn-ghost" busy={pending("pause")} onClick={togglePause}>
            {agent.schedule?.paused ? "Resume" : "Pause"}
          </ActionButton>
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
              <ActionButton busy={pending("save")} onClick={saveGoal}>Save as a new version</ActionButton>
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
      {tab === "overview" && agent.spec && (
        <section className="card" style={{ marginTop: 16 }}>
          <h2>{copy.deliverySection}</h2>
          <DeliveryEditor channels={channels} targets={targets} onChange={setTargets} />
          <div className="goal-actions">
            <ActionButton busy={pending("delivery")} onClick={saveDelivery}>Save as a new version</ActionButton>
          </div>
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
          {runs.map((item) => (
            <p key={item.id}><Badge status={item.status} /> <Link to={`/runs/${item.id}`}>{formatWhen(item.created_at)}</Link> · {item.trigger}</p>
          ))}
          {runs.length === 0 && <p>This agent has no runs.</p>}
        </section>
      )}
    </>
  );
}
