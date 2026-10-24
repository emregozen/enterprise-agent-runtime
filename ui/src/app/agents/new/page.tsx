"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge, Button, Card, Input, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Agent, DataSource, Draft } from "@/lib/types";

const EXAMPLE =
  "Dünkü satışları bölge bazında özetle, toplam tutarı hesapla, yüzde 10'dan büyük sapmaları açıkla ve finans@sirket.local adresine e-posta gönder.";

export default function NewAgentPage() {
  const router = useRouter();
  const [sources, setSources] = useState<DataSource[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [owner, setOwner] = useState("finans-ekibi");
  const [description, setDescription] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [specText, setSpecText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadingSources, setLoadingSources] = useState(true);
  const [drafting, setDrafting] = useState(false);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    api<DataSource[]>("/api/datasources")
      .then((rows) => {
        setSources(rows);
        if (rows[0]) setSelected([rows[0].name]);
      })
      .catch((exc: unknown) => setError(exc instanceof ApiError ? exc.message : "Kaynaklar okunamadı."))
      .finally(() => setLoadingSources(false));
  }, []);

  function toggle(name: string) {
    setSelected((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  }

  async function buildDraft() {
    setDrafting(true);
    setError(null);
    try {
      const result = await api<Draft>("/api/builder/draft", {
        method: "POST",
        body: JSON.stringify({ description, owner, datasource_refs: selected }),
      });
      setDraft(result);
      setSpecText(JSON.stringify(result.spec, null, 2));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "Taslak üretilemedi.");
    } finally {
      setDrafting(false);
    }
  }

  async function publish() {
    setPublishing(true);
    setError(null);
    try {
      const spec = JSON.parse(specText) as Record<string, unknown>;
      const agent = await api<Agent>("/api/agents", {
        method: "POST",
        body: JSON.stringify({ spec, publish: true }),
      });
      router.push(`/agents/${agent.id}`);
    } catch (exc) {
      if (exc instanceof SyntaxError) setError("Spec JSON olarak okunamadı.");
      else setError(exc instanceof ApiError ? exc.message : "Ajan yayınlanamadı.");
      setPublishing(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-muted">Builder</p>
        <h1 className="mt-1 font-serif text-3xl tracking-tight">Ajanı cümleyle tarif edin</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
          Model ham satır görmez. Taslak, seçtiğiniz kaynağın şemasından ve cümlenizden bir AgentSpec üretir.
          Teknik ekip JSON’u gözden geçirip yayınlar.
        </p>
      </div>

      {error && (
        <Card className="border-bad/30 bg-bad-bg">
          <p className="text-sm text-bad">{error}</p>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <Card className="space-y-4">
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Ne yapsın</span>
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Dünkü satışları bölge bazında özetle…"
            />
          </label>
          <button type="button" className="text-sm text-pine underline-offset-2 hover:underline" onClick={() => setDescription(EXAMPLE)}>
            Günlük satış örneğini doldur
          </button>
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Sahip ekip</span>
            <Input value={owner} onChange={(event) => setOwner(event.target.value)} />
          </label>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Veri kaynakları</legend>
            {loadingSources && <p className="text-sm text-muted">Kaynaklar yükleniyor…</p>}
            {!loadingSources && sources.length === 0 && (
              <p className="text-sm leading-6 text-muted">
                Kayıtlı kaynak yok. Kontrol düzlemini <code>SALES_DATABASE_URL</code> ile başlatın ya da{" "}
                <code>POST /api/datasources</code> ile bir tane ekleyin.
              </p>
            )}
            {sources.map((source) => (
              <label key={source.id} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selected.includes(source.name)}
                  onChange={() => toggle(source.name)}
                />
                <span>
                  <span className="font-medium">{source.name}</span>
                  <span className="block text-xs text-muted">
                    {source.dialect} · {source.allow_tables.join(", ")} · {source.configured ? "dsn hazır" : "dsn eksik"}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          <Button onClick={() => void buildDraft()} disabled={drafting || description.trim().length < 8 || selected.length === 0}>
            {drafting ? "Taslak üretiliyor…" : "Taslak üret"}
          </Button>
        </Card>

        <Card className="space-y-4">
          {!draft && <p className="text-sm leading-6 text-muted">Taslak burada görünecek. Yayınlamadan önce araçları, zamanlamayı ve doğrulamayı kontrol edin.</p>}
          {draft && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-serif text-2xl">{draft.summary.name}</h2>
                <Badge>sürüm {draft.summary.version}</Badge>
                <Badge tone="ok">{draft.summary.model}</Badge>
              </div>
              <p className="text-sm leading-6">{draft.summary.goal}</p>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className="text-xs text-muted">Kaynaklar</dt>
                  <dd>{draft.summary.datasources.join(", ") || "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Araçlar</dt>
                  <dd>{draft.summary.tools.join(", ") || "yok"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Zamanlama</dt>
                  <dd>{String((draft.summary.schedule as { mode?: string } | null)?.mode || "manual")}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Çapraz kontrol</dt>
                  <dd>{draft.summary.verification?.crossCheckSql ? "SQL ile" : "kapalı"}</dd>
                </div>
              </dl>
              <label className="block space-y-1.5">
                <span className="text-sm font-medium">AgentSpec</span>
                <Textarea className="min-h-80 font-mono text-xs leading-5" value={specText} onChange={(event) => setSpecText(event.target.value)} />
              </label>
              <Button onClick={() => void publish()} disabled={publishing}>
                {publishing ? "Yayınlanıyor…" : "Yayınla"}
              </Button>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
