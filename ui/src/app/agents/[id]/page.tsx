"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge, Button, Card, statusTone } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Agent, Run } from "@/lib/types";
import { STATUS_LABEL, formatWhen } from "@/lib/utils";

export default function AgentPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [agentRow, runRows] = await Promise.all([
        api<Agent>(`/api/agents/${params.id}`),
        api<Run[]>(`/api/runs?agent_id=${params.id}&limit=20`),
      ]);
      setAgent(agentRow);
      setRuns(runRows);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Ajan okunamadı.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [params.id]);

  async function run(dryRun: boolean) {
    setBusy(dryRun ? "dry" : "run");
    setError(null);
    try {
      const created = await api<Run>(`/api/agents/${params.id}/runs`, {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun }),
      });
      router.push(`/runs/${created.id}`);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Koşum başlatılamadı.");
      setBusy(null);
    }
  }

  async function pause(paused: boolean) {
    setBusy("pause");
    setError(null);
    try {
      await api(`/api/agents/${params.id}/pause`, {
        method: "POST",
        body: JSON.stringify({ paused }),
      });
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Zamanlama güncellenemedi.");
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <div className="h-40 animate-pulse rounded-lg bg-sand" />;
  if (!agent) {
    return (
      <Card>
        <p className="text-sm">{error || "Ajan yok."}</p>
        <Button asChild className="mt-3" variant="outline">
          <Link href="/">Panoya dön</Link>
        </Button>
      </Card>
    );
  }

  const schedule = agent.schedule;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-muted">{agent.owner}</p>
          <h1 className="mt-1 font-serif text-3xl tracking-tight">{agent.name}</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6">{agent.goal}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void run(false)} disabled={busy !== null}>
            {busy === "run" ? "Başlatılıyor…" : "Şimdi çalıştır"}
          </Button>
          <Button variant="outline" onClick={() => void run(true)} disabled={busy !== null}>
            Deneme koşumu
          </Button>
          {schedule && (
            <Button variant="secondary" onClick={() => void pause(!schedule.paused)} disabled={busy !== null}>
              {schedule.paused ? "Zamanlamayı aç" : "Zamanlamayı durdur"}
            </Button>
          )}
        </div>
      </div>

      {error && (
        <Card className="border-bad/30 bg-bad-bg">
          <p className="text-sm text-bad">{error}</p>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <p className="text-xs text-muted">Sürüm</p>
          <p className="mt-1 font-serif text-2xl">{agent.current_version ?? "—"}</p>
          <p className="text-xs text-muted">{STATUS_LABEL[agent.status] || agent.status}</p>
        </Card>
        <Card>
          <p className="text-xs text-muted">Zamanlama</p>
          <p className="mt-1 font-serif text-2xl">{schedule?.mode || "yok"}</p>
          <p className="text-xs text-muted">{schedule?.cron || "cron yok"} · {schedule?.time_zone || ""}</p>
        </Card>
        <Card>
          <p className="text-xs text-muted">Sonraki koşum</p>
          <p className="mt-1 font-serif text-2xl">{schedule?.paused ? "durdu" : formatWhen(schedule?.next_run_at)}</p>
          <p className="text-xs text-muted">
            pencere {schedule?.window || "—"} · günde en çok {schedule?.max_runs_per_day ?? "—"}
          </p>
        </Card>
      </div>

      <section className="space-y-3">
        <h2 className="font-serif text-2xl">Koşumlar</h2>
        {runs.length === 0 && <Card><p className="text-sm">Bu ajan henüz çalışmadı.</p></Card>}
        <div className="space-y-2">
          {runs.map((run) => (
            <Link key={run.id} href={`/runs/${run.id}`} className="block">
              <Card className="flex flex-wrap items-center justify-between gap-3 hover:border-pine/40">
                <div>
                  <p className="text-sm font-medium">
                    {run.trigger}
                    {run.dry_run ? " · deneme" : ""} · sürüm {run.spec_version}
                  </p>
                  <p className="text-xs text-muted">{formatWhen(run.created_at)} · {run.job_name || "job yok"}</p>
                </div>
                <Badge tone={statusTone(run.status)}>{STATUS_LABEL[run.status] || run.status}</Badge>
              </Card>
            </Link>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-serif text-2xl">Sürümler</h2>
        <div className="space-y-2">
          {(agent.versions || []).map((version) => (
            <Card key={version.version}>
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium">Sürüm {version.version}</p>
                <Badge tone={statusTone(version.status)}>{STATUS_LABEL[version.status] || version.status}</Badge>
              </div>
              <p className="mt-1 text-xs text-muted">{formatWhen(version.created_at)}</p>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
