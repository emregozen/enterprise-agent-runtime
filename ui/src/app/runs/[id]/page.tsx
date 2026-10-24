"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Markdown } from "@/components/markdown";
import { Badge, Button, Card, statusTone } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { RunDetail } from "@/lib/types";
import { STATUS_LABEL, formatAmount, formatWhen } from "@/lib/utils";

export default function RunPage() {
  const params = useParams<{ id: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [logs, setLogs] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      try {
        const row = await api<RunDetail>(`/api/runs/${params.id}`);
        const logRow = await api<{ text: string }>(`/api/runs/${params.id}/logs`);
        if (stop) return;
        setRun(row);
        setLogs(logRow.text || "");
        setError(null);
        setLoading(false);
        if (row.status === "pending" || row.status === "running") {
          timer = setTimeout(() => void tick(), 2000);
        }
      } catch (exc) {
        if (stop) return;
        setError(exc instanceof ApiError ? exc.message : "Koşum okunamadı.");
        setLoading(false);
      }
    }

    void tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [params.id]);

  if (loading) return <div className="h-48 animate-pulse rounded-lg bg-sand" />;
  if (!run) {
    return (
      <Card>
        <p className="text-sm">{error || "Koşum yok."}</p>
        <Button asChild className="mt-3" variant="outline">
          <Link href="/">Panoya dön</Link>
        </Button>
      </Card>
    );
  }

  const live = run.status === "pending" || run.status === "running";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href={`/agents/${run.agent_id}`} className="text-xs uppercase tracking-[0.16em] text-pine">
            {run.agent_name}
          </Link>
          <h1 className="mt-1 font-serif text-3xl tracking-tight">Koşum</h1>
          <p className="mt-2 text-sm text-muted">
            {run.trigger}
            {run.dry_run ? " · deneme" : ""} · sürüm {run.spec_version} · {formatWhen(run.created_at)}
          </p>
        </div>
        <Badge tone={statusTone(run.status)}>{STATUS_LABEL[run.status] || run.status}</Badge>
      </div>

      {error && (
        <Card className="border-bad/30 bg-bad-bg">
          <p className="text-sm text-bad">{error}</p>
        </Card>
      )}

      {live && <p className="text-sm text-muted">Koşum sürüyor. Sayfa iki saniyede bir yenileniyor.</p>}

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <p className="text-xs text-muted">Toplam</p>
          <p className="mt-1 font-serif text-2xl">{formatAmount(run.grand_total)}</p>
        </Card>
        <Card>
          <p className="text-xs text-muted">Sapma</p>
          <p className="mt-1 text-sm leading-6">{run.anomaly_regions.length ? run.anomaly_regions.join(", ") : "yok"}</p>
        </Card>
        <Card>
          <p className="text-xs text-muted">Job</p>
          <p className="mt-1 break-all font-mono text-xs">{run.job_name || "henüz yok"}</p>
          <p className="mt-1 text-xs text-muted">bitti {formatWhen(run.finished_at)}</p>
        </Card>
      </div>

      {run.needs_review_reason && (
        <Card className="border-warn/40 bg-warn-bg">
          <p className="text-sm font-medium text-warn">İnceleme gerekli</p>
          <p className="mt-1 text-sm leading-6 text-warn">{run.needs_review_reason}</p>
        </Card>
      )}
      {run.error && (
        <Card className="border-bad/30 bg-bad-bg">
          <p className="text-sm text-bad">{run.error}</p>
        </Card>
      )}

      <section className="space-y-3">
        <h2 className="font-serif text-2xl">Rapor</h2>
        <Card>
          {run.report_markdown ? (
            <Markdown source={run.report_markdown} />
          ) : (
            <p className="text-sm text-muted">{live ? "Rapor koşum bitince burada görünecek." : "Bu koşum rapor yazmadı."}</p>
          )}
        </Card>
      </section>

      <section className="space-y-3">
        <h2 className="font-serif text-2xl">Adımlar</h2>
        {run.steps.length === 0 && <Card><p className="text-sm text-muted">Henüz adım yok.</p></Card>}
        <ol className="space-y-2">
          {run.steps.map((step) => (
            <li key={step.ordinal}>
              <Card>
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium">
                    {step.ordinal}. {step.name}
                  </p>
                  <Badge tone={statusTone(step.status)}>{STATUS_LABEL[step.status] || step.status}</Badge>
                </div>
                {Object.keys(step.detail || {}).length > 0 && (
                  <pre className="mt-2 overflow-x-auto text-xs leading-5 text-muted">{JSON.stringify(step.detail, null, 2)}</pre>
                )}
              </Card>
            </li>
          ))}
        </ol>
      </section>

      <section className="space-y-3">
        <h2 className="font-serif text-2xl">Araç çağrıları</h2>
        {run.tool_calls.length === 0 && (
          <Card>
            <p className="text-sm text-muted">E-posta ve SMS, kimlik bilgisi podda olmadan kontrol düzlemi vekili üzerinden gider. Bu koşumda çağrı yok.</p>
          </Card>
        )}
        {run.tool_calls.map((call, index) => (
          <Card key={`${call.tool}-${index}`}>
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium">{call.tool}</p>
              <Badge tone={statusTone(call.status)}>{call.status}</Badge>
            </div>
            <p className="mt-1 text-xs text-muted">{formatWhen(call.created_at)}</p>
            <pre className="mt-2 overflow-x-auto text-xs leading-5">{JSON.stringify({ request: call.request, response: call.response }, null, 2)}</pre>
          </Card>
        ))}
      </section>

      <section className="space-y-3">
        <h2 className="font-serif text-2xl">Çıktılar</h2>
        {run.artifacts.length === 0 && <Card><p className="text-sm text-muted">Henüz artefakt yok.</p></Card>}
        <div className="grid gap-3 sm:grid-cols-2">
          {run.artifacts.map((artifact) => (
            <Card key={artifact.id}>
              <a className="font-medium text-pine hover:underline" href={`/backend/api/runs/${run.id}/artifacts/${artifact.id}`}>
                {artifact.name}
              </a>
              <p className="mt-1 text-xs text-muted">
                {artifact.media_type} · {artifact.size_bytes} bayt
              </p>
              <p className="mt-1 break-all font-mono text-[11px] text-muted">{artifact.sha256}</p>
            </Card>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-serif text-2xl">Günlük</h2>
        <Card>
          <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap text-xs leading-5">{logs || (live ? "Günlük bekleniyor…" : "Günlük boş.")}</pre>
        </Card>
      </section>
    </div>
  );
}
