"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, Button, Card, statusTone } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Agent, DataSource, Health, Run } from "@/lib/types";
import { STATUS_LABEL, formatAmount, formatWhen } from "@/lib/utils";

export default function HomePage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [sources, setSources] = useState<DataSource[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [healthRow, sourceRows, agentRows, runRows] = await Promise.all([
        api<Health>("/api/health"),
        api<DataSource[]>("/api/datasources"),
        api<Agent[]>("/api/agents"),
        api<Run[]>("/api/runs?limit=8"),
      ]);
      setHealth(healthRow);
      setSources(sourceRows);
      setAgents(agentRows);
      setRuns(runRows);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Kontrol düzlemine ulaşılamadı.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-muted">Kontrol düzlemi</p>
          <h1 className="mt-1 font-serif text-3xl tracking-tight sm:text-4xl">Bugün hangi ajanlar çalışacak</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
            Ekip bir ajanı cümleyle ve veri kaynağıyla tarif eder. Platform bunu sürümlü bir AgentSpec yapar,
            zamanı gelince ya da ajan kendi sonraki koşumunu isteyince tek bir Kubernetes Job açar.
          </p>
        </div>
        <Button asChild>
          <Link href="/agents/new">Ajan tarif et</Link>
        </Button>
      </div>

      {error && (
        <Card className="border-bad/30 bg-bad-bg">
          <p className="text-sm text-bad">{error}</p>
          <Button className="mt-3" variant="outline" size="sm" onClick={() => void load()}>
            Yeniden dene
          </Button>
        </Card>
      )}

      {loading && !error && (
        <div className="grid gap-3 sm:grid-cols-3">
          {[0, 1, 2].map((item) => (
            <div key={item} className="h-24 animate-pulse rounded-lg bg-sand" />
          ))}
        </div>
      )}

      {health && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Card>
            <p className="text-xs text-muted">Model</p>
            <p className="mt-1 font-serif text-2xl">{health.llm_mode === "fake" ? "Sahte LLM" : "OpenAI uyumlu"}</p>
            <p className="text-xs text-muted">{health.llm_mode}</p>
          </Card>
          <Card>
            <p className="text-xs text-muted">Koşum</p>
            <p className="mt-1 font-serif text-2xl">{health.run_backend === "local" ? "Yerel süreç" : "Kubernetes Job"}</p>
            <p className="text-xs text-muted">{health.run_backend}</p>
          </Card>
          <Card>
            <p className="text-xs text-muted">Kayıt</p>
            <p className="mt-1 font-serif text-2xl">
              {agents.length} ajan · {sources.length} kaynak
            </p>
            <p className="text-xs text-muted">Son koşum {runs[0] ? formatWhen(runs[0].created_at) : "yok"}</p>
          </Card>
        </div>
      )}

      <section className="space-y-3">
        <h2 className="font-serif text-2xl">Veri kaynakları</h2>
        {sources.length === 0 && !loading && (
          <Card>
            <p className="text-sm leading-6">
              Henüz kaynak yok. Kontrol düzlemi <code>SALES_DATABASE_URL</code> görürse{" "}
              <strong>postgres-sales</strong> kaydını açılışta ekler. Bağlantı dizesi koşum podundaki yürütücüye
              yazılmaz; yalnızca harness ortamına gider.
            </p>
          </Card>
        )}
        <div className="grid gap-3 md:grid-cols-2">
          {sources.map((source) => (
            <Card key={source.id}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-medium">{source.name}</h3>
                  <p className="mt-1 text-sm leading-6 text-muted">{source.description || "Açıklama yok."}</p>
                </div>
                <Badge tone={source.configured ? "ok" : "warn"}>{source.configured ? "bağlı" : "dsn yok"}</Badge>
              </div>
              <p className="mt-3 text-xs text-muted">
                {source.dialect} · {source.sensitivity} · tablolar: {source.allow_tables.join(", ")} · {source.dsn_env}
              </p>
            </Card>
          ))}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="space-y-3">
          <h2 className="font-serif text-2xl">Ajanlar</h2>
          {agents.length === 0 && !loading && (
            <Card>
              <p className="text-sm leading-6">Yayınlanmış ajan yok. Günlük satış özetini bir cümleyle tarif ederek başlayın.</p>
            </Card>
          )}
          <div className="space-y-3">
            {agents.map((agent) => (
              <Link key={agent.id} href={`/agents/${agent.id}`} className="block">
                <Card className="hover:border-pine/40">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="font-medium">{agent.name}</h3>
                      <p className="mt-1 line-clamp-2 text-sm leading-6 text-muted">{agent.goal}</p>
                    </div>
                    <Badge tone={statusTone(agent.schedule?.paused ? "paused" : agent.status)}>
                      {agent.schedule?.paused ? "durduruldu" : STATUS_LABEL[agent.status] || agent.status}
                    </Badge>
                  </div>
                  <p className="mt-3 text-xs text-muted">
                    {agent.owner} · sürüm {agent.current_version ?? "—"} · sonraki{" "}
                    {formatWhen(agent.schedule?.next_run_at)}
                  </p>
                </Card>
              </Link>
            ))}
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="font-serif text-2xl">Son koşumlar</h2>
          {runs.length === 0 && !loading && (
            <Card>
              <p className="text-sm leading-6">Henüz koşum yok. Bir ajanı panodan açıp şimdi çalıştırabilirsiniz.</p>
            </Card>
          )}
          <div className="space-y-3">
            {runs.map((run) => (
              <Link key={run.id} href={`/runs/${run.id}`} className="block">
                <Card className="hover:border-pine/40">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="font-medium">{run.agent_name}</h3>
                      <p className="mt-1 text-xs text-muted">
                        {run.trigger}
                        {run.dry_run ? " · deneme" : ""} · {formatWhen(run.created_at)}
                      </p>
                    </div>
                    <Badge tone={statusTone(run.status)}>{STATUS_LABEL[run.status] || run.status}</Badge>
                  </div>
                  <p className="mt-3 text-sm">
                    Toplam {formatAmount(run.grand_total)}
                    {run.anomaly_regions.length > 0 ? ` · sapma: ${run.anomaly_regions.join(", ")}` : ""}
                  </p>
                </Card>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
