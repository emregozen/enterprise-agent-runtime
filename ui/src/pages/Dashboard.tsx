import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, DataTable, Empty, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { copy } from "../lib/copy";
import { presentText } from "../lib/errors";
import { dayLabel, formatDuration, formatNumber, formatPercent, formatWhen } from "../lib/format";

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

type Agent = { id: string; name: string; schedule: { paused: boolean; cron: string | null; next_run_at: string | null; mode: string } | null };

const columns: ColumnDef<Board["recent_runs"][number]>[] = [
  { accessorKey: "agent_name", header: "Agent" },
  { accessorKey: "status", header: "Status", cell: ({ row }) => <Badge status={row.original.status} /> },
  { accessorKey: "created_at", header: "When", cell: ({ getValue }) => formatWhen(String(getValue())) },
  { id: "open", header: "", cell: ({ row }) => <Link to={`/runs/${row.original.id}`}>{copy.open}</Link> },
];

export function Dashboard() {
  const [data, setData] = useState<Board | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Board>("/api/dashboard?days=14").then(setData).catch((exc: ApiError) => setError(exc.message));
    api<Agent[]>("/api/agents").then(setAgents).catch(() => setAgents([]));
  }, []);
  if (error) return <div className="card">Could not load the overview: {error}</div>;
  if (!data) return <SkeletonRows />;
  const chart = data.series.map((item) => ({ ...item, label: dayLabel(item.day) }));
  const upcoming = agents
    .filter((agent) => agent.schedule?.next_run_at && !agent.schedule.paused)
    .sort((left, right) => String(left.schedule?.next_run_at).localeCompare(String(right.schedule?.next_run_at)))
    .slice(0, 5);
  const today = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" }).format(new Date());
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Control room</p>
          <h1>Overview</h1>
          <p className="hero-date">{today}. Today's runs, the review queue, and model use.</p>
        </div>
        <Link className="btn" to="/agents/new">New agent</Link>
      </div>
      <section className="grid-6">
        <Kpi label="Published agents" value={formatNumber(data.active_agents)} />
        <Kpi label="Runs today" value={formatNumber(data.runs_today)} />
        <Kpi label="Success rate" value={formatPercent(data.success_rate)} />
        <Kpi label="Avg. duration" value={formatDuration(data.avg_duration_seconds)} />
        <Kpi label="Needs review" value={formatNumber(data.needs_review)} />
        <Kpi label="Tokens today" value={formatNumber(data.tokens_today)} />
      </section>
      <section className="grid-2">
        <article className="card">
          <h2>Runs by outcome</h2>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 480, height: 240 }}>
              <BarChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                <XAxis dataKey="label" stroke="var(--muted)" />
                <YAxis allowDecimals={false} stroke="var(--muted)" />
                <Tooltip />
                <Bar dataKey="succeeded" stackId="a" fill="#1d7a4d" name="Succeeded" isAnimationActive={false} />
                <Bar dataKey="failed" stackId="a" fill="#9d2c3a" name="Failed" isAnimationActive={false} />
                <Bar dataKey="needs_review" stackId="a" fill="#c48a2e" name="Needs review" isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>
        <article className="card">
          <h2>Duration trend</h2>
          <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 480, height: 240 }}>
              <LineChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                <XAxis dataKey="label" stroke="var(--muted)" />
                <YAxis stroke="var(--muted)" />
                <Tooltip />
                <Line type="monotone" dataKey="avg_duration" stroke="#c48a2e" name="Seconds" connectNulls strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </article>
      </section>
      <section className="grid-2">
        <article className="card">
          <h2>Recent runs</h2>
          {data.recent_runs.length === 0 ? <Empty title="No runs yet" body="Publish an agent and run it now." /> : <DataTable data={data.recent_runs} columns={columns} />}
        </article>
        <article className="card">
          <h2>Up next</h2>
          {upcoming.length === 0 && <Empty title="Nothing scheduled" body="Agents on a cron show their next run here." />}
          {upcoming.map((agent) => (
            <p key={agent.id}><Link to={`/agents/${agent.id}`}>{agent.name}</Link> · {agent.schedule?.cron || agent.schedule?.mode} · {formatWhen(agent.schedule?.next_run_at)}</p>
          ))}
          <h2>Alerts</h2>
          {data.alerts.length === 0 && <Empty title="No open alerts" body="Failed runs and reviews appear here." />}
          {data.alerts.map((alert) => (
            <p key={alert.id}><Badge status={alert.status} /> <Link to={`/runs/${alert.id}`}>{alert.agent_name}</Link> — {presentText(alert.reason) || "No detail"}</p>
          ))}
        </article>
      </section>
    </>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return <article className="card kpi"><div className="label">{label}</div><div className="value">{value}</div></article>;
}
