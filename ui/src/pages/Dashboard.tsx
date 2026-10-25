import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, DataTable, Empty, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { dayLabel, formatDuration, formatNumber, formatWhen } from "../lib/format";

type Board = {
  active_agents: number;
  runs_today: number;
  success_rate: number | null;
  avg_duration_seconds: number | null;
  needs_review: number;
  tokens_today: number;
  series: { day: string; succeeded: number; failed: number; needs_review: number; cancelled: number; avg_duration: number | null }[];
  recent_runs: { id: string; agent_name: string; status: string; created_at: string }[];
  alerts: { id: string; agent_name: string; status: string; reason: string; created_at: string }[];
};

const columns: ColumnDef<Board["recent_runs"][number]>[] = [
  { accessorKey: "agent_name", header: "Ajan" },
  { accessorKey: "status", header: "Durum", cell: ({ row }) => <Badge status={row.original.status} /> },
  { accessorKey: "created_at", header: "Zaman", cell: ({ getValue }) => formatWhen(String(getValue())) },
  { id: "open", header: "", cell: ({ row }) => <Link to={`/runs/${row.original.id}`}>Aç</Link> },
];

export function Dashboard() {
  const [data, setData] = useState<Board | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Board>("/api/dashboard?days=14").then(setData).catch((exc: ApiError) => setError(exc.message));
  }, []);
  if (error) return <div className="card">Pano alınamadı: {error}</div>;
  if (!data) return <SkeletonRows />;
  const chart = data.series.map((item) => ({ ...item, label: dayLabel(item.day) }));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Genel Bakış</h1>
          <p>Bugünün koşumları, inceleme kuyruğu ve model kullanımı.</p>
        </div>
        <Link className="btn" to="/agents/new">Yeni ajan</Link>
      </div>
      <section className="grid-6">
        <Kpi label="Yayındaki ajan" value={formatNumber(data.active_agents)} />
        <Kpi label="Bugünkü koşum" value={formatNumber(data.runs_today)} />
        <Kpi label="Başarı" value={data.success_rate === null ? "—" : `%${data.success_rate}`} />
        <Kpi label="Ort. süre" value={formatDuration(data.avg_duration_seconds)} />
        <Kpi label="İnceleme" value={formatNumber(data.needs_review)} />
        <Kpi label="Jeton (bugün)" value={formatNumber(data.tokens_today)} />
      </section>
      <section className="grid-2">
        <article className="card">
          <h2>Duruma göre koşum</h2>
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <BarChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                <XAxis dataKey="label" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="succeeded" stackId="a" fill="#1b7a48" name="Başarılı" />
                <Bar dataKey="failed" stackId="a" fill="#9d2d2d" name="Başarısız" />
                <Bar dataKey="needs_review" stackId="a" fill="#8a5a10" name="İnceleme" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>
        <article className="card">
          <h2>Süre eğilimi</h2>
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                <XAxis dataKey="label" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="avg_duration" stroke="#0c6e67" name="Saniye" connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </article>
      </section>
      <section className="grid-2">
        <article className="card">
          <h2>Son koşumlar</h2>
          {data.recent_runs.length === 0 ? <Empty title="Henüz koşum yok" body="Bir ajan yayınlayıp şimdi çalıştırın." /> : <DataTable data={data.recent_runs} columns={columns} />}
        </article>
        <article className="card">
          <h2>Uyarılar</h2>
          {data.alerts.length === 0 && <Empty title="Açık uyarı yok" body="Başarısız veya incelemeye düşen koşum burada görünür." />}
          {data.alerts.map((alert) => (
            <p key={alert.id}><Badge status={alert.status} /> <Link to={`/runs/${alert.id}`}>{alert.agent_name}</Link> — {alert.reason || "ayrıntı yok"}</p>
          ))}
        </article>
      </section>
    </>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return <article className="card kpi"><div className="label">{label}</div><div className="value">{value}</div></article>;
}
