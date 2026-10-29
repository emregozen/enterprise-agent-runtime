import { type ColumnDef } from "@tanstack/react-table";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Select } from "../components/Select";
import { ActionButton, Badge, ConfirmDialog, DataTable, Empty, SkeletonRows, ViewToggle } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useBusy } from "../lib/busy";
import { copy } from "../lib/copy";
import { statusLabel, formatWhen } from "../lib/format";
import { announceError, announceRun, notify } from "../lib/notify";

type Run = { id: string; agent_name: string; status: string; trigger: string; created_at: string; spec_version: number };

const STATUS_OPTIONS = [
  { value: "", label: "All", description: "Every status" },
  { value: "running", label: "Running", description: "In progress now" },
  { value: "pending", label: "Pending", description: "Waiting to start" },
  { value: "needs_review", label: "Needs review", description: "A person should look" },
  { value: "failed", label: "Failed", description: "Stopped with an error" },
  { value: "succeeded", label: "Succeeded", description: "Finished cleanly" },
  { value: "cancelled", label: "Cancelled", description: "Stopped before the end" },
];

const BOARD = [
  { key: "running", title: "Running", tone: "info", statuses: ["running", "pending"] },
  { key: "needs_review", title: "Needs review", tone: "warn", statuses: ["needs_review"] },
  { key: "failed", title: "Failed", tone: "bad", statuses: ["failed"] },
  { key: "succeeded", title: "Succeeded", tone: "ok", statuses: ["succeeded"] },
  { key: "cancelled", title: "Cancelled", tone: "", statuses: ["cancelled"] },
];

export function Runs() {
  const [rows, setRows] = useState<Run[] | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [confirmOld, setConfirmOld] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Run | null>(null);
  const [view, setView] = useState("board");
  const { run, pending } = useBusy();
  const { can } = useAuth();
  const inflightRef = useRef(false);

  const load = useCallback((nextStatus = status, nextQuery = q) => {
    if (inflightRef.current) return;
    inflightRef.current = true;
    const params = new URLSearchParams({ limit: "100" });
    if (nextStatus) params.set("status", nextStatus);
    if (nextQuery) params.set("q", nextQuery);
    api<Run[]>(`/api/runs?${params}`)
      .then(setRows)
      .catch((exc: ApiError) => setError(exc.message))
      .finally(() => {
        inflightRef.current = false;
      });
  }, [status, q]);

  useEffect(() => {
    inflightRef.current = false;
    load(status, q);
  }, [status, q, load]);

  const hasActiveRuns = Boolean(rows?.some((item) => item.status === "running" || item.status === "pending"));

  useEffect(() => {
    const intervalMs = hasActiveRuns ? 2000 : 5000;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") return;
      load(status, q);
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [hasActiveRuns, status, q, load]);

  function rerun(item: Run) {
    void run(`rerun:${item.id}`, async () => {
      try {
        const created = await api<{ id: string; agent_name: string }>(`/api/runs/${item.id}/rerun`, { method: "POST" });
        announceRun(created, item.agent_name);
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function cancel(item: Run) {
    void run(`cancel:${item.id}`, async () => {
      try {
        await api(`/api/runs/${item.id}/cancel`, { method: "POST" });
        notify({ tone: "info", title: copy.cancelledRun });
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function remove(item: Run) {
    void run(`delete:${item.id}`, async () => {
      try {
        await api(`/api/runs/${item.id}`, { method: "DELETE" });
        notify({ tone: "success", title: copy.deletedRun });
        setPendingDelete(null);
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function removeOld() {
    void run("bulk", async () => {
      try {
        const result = await api<{ deleted: number }>("/api/runs/bulk-delete", {
          method: "POST",
          body: JSON.stringify({ older_than_days: 30, statuses: ["succeeded", "failed", "cancelled", "needs_review"] }),
        });
        notify({ tone: "success", title: copy.oldRunsDeleted(result.deleted) });
        setConfirmOld(false);
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  function actions(item: Run) {
    return (
      <span className="row">
        {(item.status === "running" || item.status === "pending") && (
          <ActionButton
            className="btn-ghost"
            busy={pending(`cancel:${item.id}`)}
            disabled={!can("run:cancel")}
            title={!can("run:cancel") ? copy.permissionDeniedHint : undefined}
            onClick={() => cancel(item)}
          >
            {copy.cancel}
          </ActionButton>
        )}
        <ActionButton
          className="btn-ghost"
          busy={pending(`rerun:${item.id}`)}
          disabled={!can("run:rerun")}
          title={!can("run:rerun") ? copy.permissionDeniedHint : undefined}
          onClick={() => rerun(item)}
        >
          Rerun
        </ActionButton>
        <button
          className="btn-danger"
          type="button"
          disabled={!can("run:delete")}
          title={!can("run:delete") ? copy.permissionDeniedHint : undefined}
          onClick={() => setPendingDelete(item)}
        >
          {copy.delete}
        </button>
      </span>
    );
  }

  const columns: ColumnDef<Run>[] = [
    { accessorKey: "agent_name", header: "Agent", cell: ({ row }) => <Link to={`/runs/${row.original.id}`}>{row.original.agent_name}</Link> },
    { accessorKey: "status", header: "Status", cell: ({ row }) => <Badge status={row.original.status} /> },
    { accessorKey: "trigger", header: "Trigger" },
    { accessorKey: "spec_version", header: "Version" },
    { accessorKey: "created_at", header: "When", cell: ({ getValue }) => formatWhen(String(getValue())) },
    { id: "actions", header: "", cell: ({ row }) => actions(row.original) },
  ];

  if (error) return <div className="card">{error}</div>;
  if (!rows) return <SkeletonRows />;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">History</p>
          <h1>Runs</h1>
          <p>Cancelled runs, and runs that fail before they start, do not count toward the daily limit.</p>
        </div>
        <div className="row">
          <ViewToggle value={view} onChange={setView} options={[{ id: "board", label: "Board" }, { id: "table", label: "Table" }]} />
          <button
            className="btn-danger"
            type="button"
            disabled={!can("run:delete")}
            title={!can("run:delete") ? copy.permissionDeniedHint : undefined}
            onClick={() => setConfirmOld(true)}
          >
            Delete old runs
          </button>
        </div>
      </div>
      <section className="card">
        <div className="row">
          <input className="search" aria-label="Search by agent name" value={q} placeholder="Agent name" onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") load(status, event.currentTarget.value); }} />
          <Select className="compact" ariaLabel={copy.status} value={status} onChange={setStatus} options={STATUS_OPTIONS.map((option) => ({ ...option, label: option.value ? statusLabel(option.value) : copy.all }))} />
        </div>
        {rows.length === 0 ? <Empty title="No runs" body="Run an agent to see it here." action={<Link className="btn" to="/agents">{copy.openAgents}</Link>} /> : view === "table" ? <DataTable data={rows} columns={columns} /> : (
          <div className="board">
            {BOARD.filter((column) => !status || column.statuses.includes(status)).map((column) => {
              const items = rows.filter((row) => column.statuses.includes(row.status));
              return (
                <section className={`board-col ${column.tone}`} key={column.key}>
                  <h2>{column.title} · {items.length}</h2>
                  {items.length === 0 && <p className="lede">None</p>}
                  {items.map((item) => (
                    <article className="board-card" key={item.id}>
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <Link to={`/runs/${item.id}`}>{item.agent_name}</Link>
                        <Badge status={item.status} />
                      </div>
                      <p>{item.trigger} · v{item.spec_version} · {formatWhen(item.created_at)}</p>
                      {actions(item)}
                    </article>
                  ))}
                </section>
              );
            })}
          </div>
        )}
      </section>
      {confirmOld && (
        <ConfirmDialog
          title="Delete old runs"
          body={copy.confirmDeleteOld}
          busy={pending("bulk")}
          onConfirm={removeOld}
          onClose={() => setConfirmOld(false)}
        />
      )}
      {pendingDelete && (
        <ConfirmDialog
          title={copy.confirmDeleteTitle}
          body={copy.confirmDeleteRun}
          busy={pending(`delete:${pendingDelete.id}`)}
          onConfirm={() => remove(pendingDelete)}
          onClose={() => setPendingDelete(null)}
        />
      )}
    </>
  );
}
