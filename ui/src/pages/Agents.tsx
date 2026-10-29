import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ActionButton, Badge, ConfirmDialog, Empty, SkeletonRows, ViewToggle } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useBusy } from "../lib/busy";
import { copy } from "../lib/copy";
import { formatWhen } from "../lib/format";
import { announceError, announceRun, notify } from "../lib/notify";

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
  const [view, setView] = useState("grid");
  const { run, pending: isPending } = useBusy();
  const { can } = useAuth();

  function load() {
    api<Agent[]>("/api/agents").then(setRows).catch((exc: ApiError) => setError(exc.message));
  }
  useEffect(load, []);

  function startRun(agent: Agent) {
    void run(`run:${agent.id}`, async () => {
      try {
        const created = await api<{ id: string; agent_name: string }>(`/api/agents/${agent.id}/runs`, { method: "POST", body: "{}" });
        announceRun(created, agent.name);
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function duplicate(agent: Agent) {
    void run(`copy:${agent.id}`, async () => {
      try {
        const created = await api<{ id: string; name: string }>(`/api/agents/${agent.id}/duplicate`, { method: "POST" });
        notify({
          tone: "success",
          title: copy.duplicatedAgent(created.name || agent.name),
          actions: [{ label: copy.openCopy, href: `/agents/${created.id}` }],
        });
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function remove(agent: Agent) {
    void run(`delete:${agent.id}`, async () => {
      try {
        await api(`/api/agents/${agent.id}`, { method: "DELETE" });
        notify({ tone: "success", title: copy.deletedAgent(agent.name) });
        setPending(null);
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
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
          <button
            className="btn"
            type="button"
            disabled={!can("agent:write")}
            title={!can("agent:write") ? copy.permissionDeniedHint : undefined}
            onClick={() => navigate("/agents/new")}
          >
            New agent
          </button>
        </div>
      </div>
      <section className="card">
        <input className="search" aria-label="Search agents" placeholder="Name or owner" value={q} onChange={(event) => setQ(event.target.value)} />
      </section>
      {filtered.length === 0 ? (
        <Empty
          title={rows.length === 0 ? "No agents" : copy.noMatches}
          body={rows.length === 0 ? "Describe a job in the builder and publish a spec." : "Try another name or owner."}
          action={rows.length === 0 ? <button className="btn" type="button" onClick={() => navigate("/agents/new")}>New agent</button> : undefined}
        />
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
              <AgentActions agent={agent} pending={isPending} onRun={() => startRun(agent)} onCopy={() => duplicate(agent)} onDelete={() => setPending(agent)} />
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
              <AgentActions agent={agent} pending={isPending} onRun={() => startRun(agent)} onCopy={() => duplicate(agent)} onDelete={() => setPending(agent)} />
            </article>
          ))}
        </section>
      )}
      {pending && (
        <ConfirmDialog
          title={copy.confirmDeleteTitle}
          body={copy.confirmDeleteAgent(pending.name)}
          busy={isPending(`delete:${pending.id}`)}
          onConfirm={() => remove(pending)}
          onClose={() => setPending(null)}
        />
      )}
    </>
  );
}

function AgentActions({
  agent,
  pending,
  onRun,
  onCopy,
  onDelete,
}: {
  agent: Agent;
  pending: (id: string) => boolean;
  onRun: () => void;
  onCopy: () => void;
  onDelete: () => void;
}) {
  const { can } = useAuth();
  return (
    <div className="row">
      <ActionButton
        busy={pending(`run:${agent.id}`)}
        disabled={!can("agent:run")}
        title={!can("agent:run") ? copy.permissionDeniedHint : undefined}
        onClick={onRun}
      >
        {copy.run}
      </ActionButton>
      <ActionButton
        className="btn-ghost"
        busy={pending(`copy:${agent.id}`)}
        disabled={!can("agent:write")}
        title={!can("agent:write") ? copy.permissionDeniedHint : undefined}
        onClick={onCopy}
      >
        {copy.copy}
      </ActionButton>
      <button
        className="btn-danger"
        type="button"
        disabled={!can("agent:delete")}
        title={!can("agent:delete") ? copy.permissionDeniedHint : undefined}
        onClick={onDelete}
      >
        {copy.delete}
      </button>
    </div>
  );
}
