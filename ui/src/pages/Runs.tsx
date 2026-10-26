import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, DataTable, Empty, Modal, SkeletonRows, Toast, ViewToggle } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { copy } from "../lib/copy";
import { statusLabel, formatWhen } from "../lib/format";

type Run = { id: string; agent_name: string; status: string; trigger: string; created_at: string; spec_version: number };

const STATUSES = ["", "running", "succeeded", "failed", "needs_review", "cancelled", "pending"];

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
  const [toast, setToast] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [view, setView] = useState("board");

  function load(nextStatus = status, nextQuery = q) {
    const params = new URLSearchParams({ limit: "100" });
    if (nextStatus) params.set("status", nextStatus);
    if (nextQuery) params.set("q", nextQuery);
    api<Run[]>(`/api/runs?${params}`).then(setRows).catch((exc: ApiError) => setError(exc.message));
  }
  useEffect(() => { load(status, q); }, [status, q]);

  async function call(path: string, method: string, message: string) {
    try {
      await api(path, { method });
      setToast(message);
      load();
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : copy.couldNotComplete);
    }
  }

  const columns: ColumnDef<Run>[] = [
    { accessorKey: "agent_name", header: "Agent", cell: ({ row }) => <Link to={`/runs/${row.original.id}`}>{row.original.agent_name}</Link> },
    { accessorKey: "status", header: "Status", cell: ({ row }) => <Badge status={row.original.status} /> },
    { accessorKey: "trigger", header: "Trigger" },
    { accessorKey: "spec_version", header: "Version" },
    { accessorKey: "created_at", header: "When", cell: ({ getValue }) => formatWhen(String(getValue())) },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="row">
          {(row.original.status === "running" || row.original.status === "pending") && (
            <button className="btn-ghost" type="button" onClick={() => void call(`/api/runs/${row.original.id}/cancel`, "POST", "Cancelled")}>Cancel</button>
          )}
          <button className="btn-ghost" type="button" onClick={() => void call(`/api/runs/${row.original.id}/rerun`, "POST", "Rerun requested")}>Rerun</button>
          <button className="btn-danger" type="button" onClick={() => void call(`/api/runs/${row.original.id}`, "DELETE", "Run deleted")}>Delete</button>
        </span>
      ),
    },
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
          <button className="btn-danger" type="button" onClick={() => setConfirm(true)}>Delete old runs</button>
        </div>
      </div>
      <section className="card">
        <div className="row">
          <input className="search" aria-label="Search by agent name" value={q} placeholder="Agent name" onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") load(status, event.currentTarget.value); }} />
          <div className="pills" role="group" aria-label="Status">
            {STATUSES.map((item) => (
              <button key={item || "all"} type="button" className={status === item ? "on" : ""} aria-pressed={status === item} onClick={() => setStatus(item)}>{item ? statusLabel(item) : "All"}</button>
            ))}
          </div>
        </div>
        {rows.length === 0 ? <Empty title="No runs" body="Run an agent to see it here." /> : view === "table" ? <DataTable data={rows} columns={columns} /> : (
          <div className="board">
            {BOARD.filter((column) => !status || column.statuses.includes(status)).map((column) => {
              const items = rows.filter((row) => column.statuses.includes(row.status));
              return (
                <section className={`board-col ${column.tone}`} key={column.key}>
                  <h2>{column.title} · {items.length}</h2>
                  {items.length === 0 && <p className="lede">None</p>}
                  {items.map((run) => (
                    <article className="board-card" key={run.id}>
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <Link to={`/runs/${run.id}`}>{run.agent_name}</Link>
                        <Badge status={run.status} />
                      </div>
                      <p>{run.trigger} · v{run.spec_version} · {formatWhen(run.created_at)}</p>
                      <span className="row">
                        {(run.status === "running" || run.status === "pending") && (
                          <button className="btn-ghost" type="button" onClick={() => void call(`/api/runs/${run.id}/cancel`, "POST", "Cancelled")}>Cancel</button>
                        )}
                        <button className="btn-ghost" type="button" onClick={() => void call(`/api/runs/${run.id}/rerun`, "POST", "Rerun requested")}>Rerun</button>
                        <button className="btn-danger" type="button" onClick={() => void call(`/api/runs/${run.id}`, "DELETE", "Run deleted")}>Delete</button>
                      </span>
                    </article>
                  ))}
                </section>
              );
            })}
          </div>
        )}
      </section>
      {confirm && (
        <Modal title="Delete old runs" onClose={() => setConfirm(false)}>
          <p>Finished runs older than 30 days, and their artifacts, are deleted. A running run is left alone.</p>
          <div className="row">
            <button className="btn-danger" type="button" onClick={() => { setConfirm(false); void api("/api/runs/bulk-delete", { method: "POST", body: JSON.stringify({ older_than_days: 30, statuses: ["succeeded", "failed", "cancelled", "needs_review"] }) }).then(() => { setToast("Old runs deleted"); load(); }).catch((exc: ApiError) => setToast(exc.message)); }}>Delete</button>
            <button className="btn-ghost" type="button" onClick={() => setConfirm(false)}>Cancel</button>
          </div>
        </Modal>
      )}
      <Toast message={toast} />
    </>
  );
}
