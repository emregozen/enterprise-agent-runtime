import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, Empty, Modal, SkeletonRows, Toast, ViewToggle } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { copy } from "../lib/copy";
import { formatWhen } from "../lib/format";

type Agent = {
  id: string;
  name: string;
  owner: string;
  status: string;
  current_version: number | null;
  schedule: { paused: boolean; mode: string; cron: string | null; next_run_at: string | null } | null;
  updated_at: string;
};

export function Agents() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<Agent[] | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [pending, setPending] = useState<Agent | null>(null);
  const [toast, setToast] = useState("");
  const [view, setView] = useState("grid");

  function load() {
    api<Agent[]>("/api/agents").then(setRows).catch((exc: ApiError) => setError(exc.message));
  }
  useEffect(load, []);

  async function act(path: string, method: string, ok: string) {
    try {
      await api(path, { method });
      setToast(ok);
      load();
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : copy.couldNotComplete);
    }
  }

  if (error) return <div className="card">{error}</div>;
  if (!rows) return <SkeletonRows />;
  const filtered = rows.filter((row) => `${row.name} ${row.owner}`.toLocaleLowerCase("tr").includes(q.toLocaleLowerCase("tr")));
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Fleet</p>
          <h1>Agents</h1>
          <p>Published agents and their schedules. Deleting hides the record. Past runs stay.</p>
        </div>
        <div className="row">
          <ViewToggle value={view} onChange={setView} options={[{ id: "grid", label: "Cards" }, { id: "list", label: "List" }]} />
          <button className="btn" type="button" onClick={() => navigate("/agents/new")}>New agent</button>
        </div>
      </div>
      <section className="card">
        <input className="search" aria-label="Search agents" placeholder="Name or owner" value={q} onChange={(event) => setQ(event.target.value)} />
      </section>
      {filtered.length === 0 ? (
        <Empty title="No agents" body="Describe a job in the builder and publish a spec." action={<button className="btn" type="button" onClick={() => navigate("/agents/new")}>New agent</button>} />
      ) : view === "list" ? (
        <section className="list">
          {filtered.map((agent) => (
            <article className="card list-row" key={agent.id}>
              <div>
                <h2><Link to={`/agents/${agent.id}`}>{agent.name}</Link></h2>
                <p className="lede" style={{ margin: 0 }}>{agent.owner}</p>
              </div>
              <Badge status={agent.schedule?.paused ? "paused" : agent.status} />
              <p className="lede" style={{ margin: 0 }}>{agent.schedule?.cron || agent.schedule?.mode || "—"} · {formatWhen(agent.schedule?.next_run_at)}</p>
              <AgentActions onRun={() => act(`/api/agents/${agent.id}/runs`, "POST", "Run requested")} onCopy={() => act(`/api/agents/${agent.id}/duplicate`, "POST", "Duplicated")} onDelete={() => setPending(agent)} />
            </article>
          ))}
        </section>
      ) : (
        <section className="agent-grid">
          {filtered.map((agent) => (
            <article className="agent-card" key={agent.id}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2><Link to={`/agents/${agent.id}`}>{agent.name}</Link></h2>
                <Badge status={agent.schedule?.paused ? "paused" : agent.status} />
              </div>
              <p className="lede" style={{ margin: 0 }}>{agent.owner}</p>
              <dl className="agent-meta">
                <div><dt>Version</dt><dd>{agent.current_version ?? "—"}</dd></div>
                <div><dt>Schedule</dt><dd>{agent.schedule?.cron || agent.schedule?.mode || "—"}</dd></div>
                <div><dt>Next run</dt><dd>{formatWhen(agent.schedule?.next_run_at)}</dd></div>
                <div><dt>Updated</dt><dd>{formatWhen(agent.updated_at)}</dd></div>
              </dl>
              <AgentActions onRun={() => act(`/api/agents/${agent.id}/runs`, "POST", "Run requested")} onCopy={() => act(`/api/agents/${agent.id}/duplicate`, "POST", "Duplicated")} onDelete={() => setPending(agent)} />
            </article>
          ))}
        </section>
      )}
      {pending && (
        <Modal title="Delete agent" onClose={() => setPending(null)}>
          <p><b>{pending.name}</b> will be hidden and its schedule will stop. Runs and artifacts remain.</p>
          <div className="row">
            <button className="btn-danger" type="button" onClick={() => { const id = pending.id; setPending(null); void act(`/api/agents/${id}`, "DELETE", "Agent deleted"); }}>Delete</button>
            <button className="btn-ghost" type="button" onClick={() => setPending(null)}>Cancel</button>
          </div>
        </Modal>
      )}
      <Toast message={toast} />
    </>
  );
}

function AgentActions({ onRun, onCopy, onDelete }: { onRun: () => void; onCopy: () => void; onDelete: () => void }) {
  return (
    <div className="row">
      <button className="btn" type="button" onClick={() => void onRun()}>Run</button>
      <button className="btn-ghost" type="button" onClick={() => void onCopy()}>Duplicate</button>
      <button className="btn-danger" type="button" onClick={onDelete}>Delete</button>
    </div>
  );
}
