import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Badge, DataTable, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { formatWhen } from "../lib/format";

type Agent = {
  id: string;
  name: string;
  owner: string;
  status: string;
  current_version: number | null;
  schedule: { paused: boolean; mode: string; cron: string | null } | null;
  updated_at: string;
};

export function Agents() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<Agent[] | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [pending, setPending] = useState<Agent | null>(null);
  const [toast, setToast] = useState("");

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
      setToast(exc instanceof ApiError ? exc.message : "işlem olmadı");
    }
  }

  const columns: ColumnDef<Agent>[] = [
    { accessorKey: "name", header: "Ad", cell: ({ row }) => <Link to={`/agents/${row.original.id}`}>{row.original.name}</Link> },
    { accessorKey: "owner", header: "Sahip" },
    { accessorKey: "status", header: "Durum", cell: ({ row }) => <Badge status={row.original.schedule?.paused ? "paused" : row.original.status} /> },
    { accessorKey: "current_version", header: "Sürüm" },
    { id: "when", header: "Güncelleme", accessorFn: (row) => row.updated_at, cell: ({ getValue }) => formatWhen(String(getValue() || "")) },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="row">
          <button className="btn-ghost" type="button" onClick={() => act(`/api/agents/${row.original.id}/runs`, "POST", "Koşum istendi")}>Çalıştır</button>
          <button className="btn-ghost" type="button" onClick={() => act(`/api/agents/${row.original.id}/duplicate`, "POST", "Kopyalandı")}>Kopyala</button>
          <button className="btn-danger" type="button" onClick={() => setPending(row.original)}>Sil</button>
        </span>
      ),
    },
  ];

  if (error) return <div className="card">{error}</div>;
  if (!rows) return <SkeletonRows />;
  const filtered = rows.filter((row) => `${row.name} ${row.owner}`.toLocaleLowerCase("tr").includes(q.toLocaleLowerCase("tr")));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Agent'lar</h1>
          <p>Yayınlanan ajanlar ve zamanlamaları. Silmek kaydı gizler, geçmiş koşumlar durur.</p>
        </div>
        <button className="btn" type="button" onClick={() => navigate("/agents/new")}>Yeni ajan</button>
      </div>
      <section className="card">
        <input className="search" aria-label="Ajan ara" placeholder="Ad veya sahip" value={q} onChange={(event) => setQ(event.target.value)} />
        {filtered.length === 0 ? <Empty title="Ajan yok" body="Sihirbazla bir açıklama yazıp spec üretebilirsiniz." /> : <DataTable data={filtered} columns={columns} />}
      </section>
      {pending && (
        <Modal title="Ajanı sil" onClose={() => setPending(null)}>
          <p><b>{pending.name}</b> gizlenecek, zamanlaması duracak. Koşumlar ve artefaktlar kalır.</p>
          <div className="row">
            <button className="btn-danger" type="button" onClick={() => { setPending(null); void act(`/api/agents/${pending.id}`, "DELETE", "Ajan silindi"); }}>Sil</button>
            <button className="btn-ghost" type="button" onClick={() => setPending(null)}>Vazgeç</button>
          </div>
        </Modal>
      )}
      {toast && <div className="toasts" role="status"><div className="toast">{toast}</div></div>}
    </>
  );
}
