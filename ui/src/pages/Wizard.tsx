import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";

type Source = { id: string; name: string; dialect: string };
type Model = { id: string; name: string; model: string; is_default: boolean };
type Spec = Record<string, unknown>;

const STEPS = ["Açıklama", "Kaynak ve model", "Spec", "Zamanlama", "Onay"];

function draftError(exc: unknown): string {
  if (exc instanceof ApiError) {
    if (exc.message && !/internal server error/i.test(exc.message)) return exc.message;
    if (exc.status === 502 || exc.status >= 500) {
      return "Veri kaynağına ulaşılamadı. Kaynak kapalı olabilir veya adres yanıt vermiyor.";
    }
    return exc.message || "taslak olmadı";
  }
  return "taslak olmadı";
}

export function Wizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [description, setDescription] = useState("Hafta içi her sabah dünkü satışları bölge bazında özetle, sapmaları açıkla ve finans@sirket.local adresine e-posta gönder.");
  const [owner, setOwner] = useState("finans");
  const [sources, setSources] = useState<Source[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [modelRef, setModelRef] = useState("");
  const [specText, setSpecText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Source[]>("/api/datasources").then((rows) => {
      setSources(rows);
      const preferred = rows.find((row) => row.dialect === "postgres") || rows[0];
      if (preferred) setSourceId(preferred.id);
    }).catch((exc: ApiError) => setError(exc.message));
    api<Model[]>("/api/llm/providers").then((rows) => {
      setModels(rows);
      const preferred = rows.find((row) => row.is_default) || rows[0];
      if (preferred) setModelRef(preferred.name);
    }).catch(() => setModels([]));
  }, []);

  async function generate() {
    setBusy(true);
    setError("");
    try {
      const draft = await api<{ spec: Spec }>("/api/builder/draft", {
        method: "POST",
        body: JSON.stringify({ description, owner, datasource_refs: [sourceId], model_ref: modelRef || null }),
      });
      setSpecText(JSON.stringify(draft.spec, null, 2));
      setStep(2);
    } catch (exc) {
      setError(draftError(exc));
    } finally {
      setBusy(false);
    }
  }

  function spec(): Spec | null {
    try {
      return JSON.parse(specText) as Spec;
    } catch {
      setError("Spec JSON değil");
      return null;
    }
  }

  function updateSchedule(mode: string, cron: string) {
    const body = spec();
    if (!body) return;
    const inner = (body.spec as Record<string, unknown>) || {};
    const schedule = { ...((inner.schedule as Record<string, unknown>) || {}), mode, cron: cron || null };
    inner.schedule = schedule;
    body.spec = inner;
    setSpecText(JSON.stringify(body, null, 2));
    setError("");
  }

  async function publish() {
    const body = spec();
    if (!body) return;
    setBusy(true);
    try {
      const created = await api<{ id: string }>("/api/agents", { method: "POST", body: JSON.stringify({ spec: body, publish: true }) });
      navigate(`/agents/${created.id}`);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "yayınlanamadı");
    } finally {
      setBusy(false);
    }
  }

  const parsed = (() => { try { return JSON.parse(specText) as Spec; } catch { return null; } })();
  const schedule = (parsed?.spec as { schedule?: { mode?: string; cron?: string } } | undefined)?.schedule;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Yeni ajan</h1>
          <p>Açıklama, veri kaynağı ve modelden bir spec üretilir. Yayınlamadan önce düzenleyebilirsiniz.</p>
        </div>
      </div>
      <div className="stepper" aria-label="Adımlar">
        {STEPS.map((label, index) => <span key={label} className={index === step ? "on" : ""}>{index + 1}. {label}</span>)}
      </div>
      <section className="card">
        {step === 0 && (
          <div className="grid-2">
            <label className="field">Sahip<input value={owner} onChange={(event) => setOwner(event.target.value)} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>Ne yapmalı?<textarea rows={5} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          </div>
        )}
        {step === 1 && (
          <div className="grid-2">
            <label className="field">Veri kaynağı
              <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
                {sources.map((source) => <option key={source.id} value={source.id}>{source.name} · {source.dialect}</option>)}
              </select>
            </label>
            <label className="field">Model
              <select value={modelRef} onChange={(event) => setModelRef(event.target.value)}>
                <option value="">Ortam varsayılanı</option>
                {models.map((model) => <option key={model.id} value={model.name}>{model.name} · {model.model}</option>)}
              </select>
            </label>
            {sources.length === 0 && <p>Önce bir veri kaynağı tanımlayın.</p>}
          </div>
        )}
        {step === 2 && (
          <label className="field">Üretilen spec
            <textarea rows={16} value={specText} onChange={(event) => setSpecText(event.target.value)} spellCheck={false} />
          </label>
        )}
        {step === 3 && (
          <div>
            <div className="grid-2">
              <label className="field">Mod
                <select value={schedule?.mode || "manual"} onChange={(event) => updateSchedule(event.target.value, schedule?.cron || "30 8 * * 1-5")}>
                  <option value="manual">Elle</option>
                  <option value="cron">Zamanlı</option>
                  <option value="hybrid">Zamanlı + kendi kararı</option>
                  <option value="self">Kendi kararı</option>
                </select>
              </label>
              <label className="field">Cron<input value={schedule?.cron || ""} onChange={(event) => updateSchedule(schedule?.mode || "cron", event.target.value)} /></label>
            </div>
            {(!schedule?.mode || schedule.mode === "manual") && (
              <p>Açıklamada saat yoksa taslak elle kalır. Zamanı siz yazın; sihirbaz saat uydurmaz.</p>
            )}
          </div>
        )}
        {step === 4 && parsed && (
          <div>
            <p><b>{String((parsed.metadata as { name?: string })?.name || "")}</b></p>
            <p>{String((parsed.spec as { goal?: string })?.goal || "")}</p>
            <p>Model: {String((parsed.spec as { model?: { class?: string } })?.model?.class || "")}</p>
          </div>
        )}
        {error && <p role="alert">{error}</p>}
        <div className="row" style={{ marginTop: 16 }}>
          {step > 0 && <button className="btn-ghost" type="button" onClick={() => setStep(step - 1)}>Geri</button>}
          {step === 0 && <button className="btn" type="button" onClick={() => setStep(1)}>Devam</button>}
          {step === 1 && <button className="btn" type="button" disabled={busy || !sourceId} onClick={() => void generate()}>{busy ? "Üretiliyor…" : "Spec üret"}</button>}
          {step === 2 && <button className="btn" type="button" onClick={() => setStep(3)}>Zamanlama</button>}
          {step === 3 && <button className="btn" type="button" onClick={() => setStep(4)}>Önizleme</button>}
          {step === 4 && <button className="btn" type="button" disabled={busy} onClick={() => void publish()}>{busy ? "Yayınlanıyor…" : "Yayınla"}</button>}
        </div>
      </section>
    </>
  );
}
