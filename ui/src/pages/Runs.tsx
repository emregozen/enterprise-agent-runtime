import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, DataTable, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { formatWhen } from "../lib/format";

type Run = { id: string; agent_name: string; status: string; trigger: string; created_at: string; spec_version: number };

const STATUSES = ["", "running", "succeeded", "failed", "needs_review", "cancelled", "pending"];

export function Runs() {
  const [rows, setRows] = useState<Run[] | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [toast, setToast] = useState("");
  const [confirm, setConfirm] = useState(false);

  function load() {
    const params = new URLSearchParams({ limit: "100" });
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    api<Run[]>(`/api/runs?${params}`).then(setRows).catch((exc: ApiError) => setError(exc.message));
  }
  useEffect(load, [status, q]);

  async function call(path: string, method: string, message: string) {
    try {
      await api(path, { method });
      setToast(message);
      load();
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : "olmadı");
    }
  }

  const columns: ColumnDef<Run>[] = [
    { accessorKey: "agent_name", header: "Ajan", cell: ({ row }) => <Link to={`/runs/${row.original.id}`}>{row.original.agent_name}</Link> },
    { accessorKey: "status", header: "Durum", cell: ({ row }) => <Badge status={row.original.status} /> },
    { accessorKey: "trigger", header: "Tetik" },
    { accessorKey: "spec_version", header: "Sürüm" },
    { accessorKey: "created_at", header: "Zaman", cell: ({ getValue }) => formatWhen(String(getValue())) },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="row">
          {(row.original.status === "running" || row.original.status === "pending") && (
            <button className="btn-ghost" type="button" onClick={() => void call(`/api/runs/${row.original.id}/cancel`, "POST", "İptal edildi")}>İptal</button>
          )}
          <button className="btn-ghost" type="button" onClick={() => void call(`/api/runs/${row.original.id}/rerun`, "POST", "Yeniden istendi")}>Yeniden</button>
          <button className="btn-danger" type="button" onClick={() => void call(`/api/runs/${row.original.id}`, "DELETE", "Koşum silindi")}>Sil</button>
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
          <h1>Koşumlar</h1>
          <p>İptal ve başlamadan düşen koşumlar günlük kotaya yazılmaz.</p>
        </div>
        <button className="btn-danger" type="button" onClick={() => setConfirm(true)}>Eskileri sil</button>
      </div>
      <section className="card">
        <div className="row">
          <input className="search" aria-label="Ajan adına göre ara" value={q} placeholder="Ajan adı" onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") load(); }} />
          <select aria-label="Durum" value={status} onChange={(event) => setStatus(event.target.value)}>
            {STATUSES.map((item) => <option key={item} value={item}>{item || "Tümü"}</option>)}
          </select>
        </div>
        {rows.length === 0 ? <Empty title="Koşum yok" body="Bir ajanı şimdi çalıştırın." /> : <DataTable data={rows} columns={columns} />}
      </section>
      {confirm && (
        <Modal title="Eski koşumları sil" onClose={() => setConfirm(false)}>
          <p>30 günden eski, bitmiş koşumlar ve artefaktları silinir. Çalışan koşuma dokunulmaz.</p>
          <div className="row">
            <button className="btn-danger" type="button" onClick={() => { setConfirm(false); void api("/api/runs/bulk-delete", { method: "POST", body: JSON.stringify({ older_than_days: 30, statuses: ["succeeded", "failed", "cancelled", "needs_review"] }) }).then(() => { setToast("Eski koşumlar silindi"); load(); }).catch((exc: ApiError) => setToast(exc.message)); }}>Sil</button>
            <button className="btn-ghost" type="button" onClick={() => setConfirm(false)}>Vazgeç</button>
          </div>
        </Modal>
      )}
      {toast && <div className="toasts" role="status"><div className="toast">{toast}</div></div>}
    </>
  );
}
