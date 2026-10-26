import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, DataTable, Empty, Modal, SkeletonRows, Toast } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { copy } from "../lib/copy";
import { statusLabel, formatWhen } from "../lib/format";

type Run = { id: string; agent_name: string; status: string; trigger: string; created_at: string; spec_version: number };

const STATUSES = ["", "running", "succeeded", "failed", "needs_review", "cancelled", "pending"];

export function Runs() {
  const [rows, setRows] = useState<Run[] | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [toast, setToast] = useState("");
  const [confirm, setConfirm] = useState(false);

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
        <button className="btn-danger" type="button" onClick={() => setConfirm(true)}>Delete old runs</button>
      </div>
      <section className="card">
        <div className="row">
          <input className="search" aria-label="Search by agent name" value={q} placeholder="Agent name" onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") load(status, event.currentTarget.value); }} />
          <select className="top-select" aria-label="Status" value={status} onChange={(event) => setStatus(event.target.value)}>
            {STATUSES.map((item) => <option key={item || "all"} value={item}>{item ? statusLabel(item) : "All"}</option>)}
          </select>
        </div>
        {rows.length === 0 ? <Empty title="No runs" body="Run an agent to see it here." /> : <DataTable data={rows} columns={columns} />}
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
