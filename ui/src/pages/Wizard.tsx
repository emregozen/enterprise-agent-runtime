import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DeliveryEditor, deliveryReady, draftsFromSpec, writeDelivery, type ChannelChoice, type DraftTarget } from "../components/DeliveryTargets";
import { ChartDataToggle, chartDataOf, withChartData } from "../components/ChartDataToggle";
import { Select } from "../components/Select";
import { api, ApiError } from "../lib/api";
import { copy } from "../lib/copy";
import { notify } from "../lib/notify";

type Source = { id: string; name: string; dialect: string };
type Model = { id: string; name: string; model: string; is_default: boolean };
type Spec = Record<string, unknown>;

const STEPS = ["Description", "Source and model", "Spec", "Schedule", "Delivery", "Review"];

function draftError(exc: unknown): string {
  if (exc instanceof ApiError) {
    if (exc.message && !/internal server error/i.test(exc.message)) return exc.message;
    if (exc.status === 502 || exc.status >= 500) {
      return "The data source is unreachable. It may be down, or the address is not responding.";
    }
    return exc.message || "Could not draft a spec";
  }
  return "Could not draft a spec";
}

export function Wizard() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const prefilledGoal = searchParams.get("goal");
  const prefilledSource = searchParams.get("datasource");
  const [step, setStep] = useState(0);
  const [description, setDescription] = useState(
    prefilledGoal || "Each weekday morning, summarize yesterday's sales by region, explain the outliers, and email finance@company.example.",
  );
  const [owner, setOwner] = useState("finance");
  const [chartData, setChartData] = useState(false);
  const [sources, setSources] = useState<Source[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [sourceId, setSourceId] = useState(prefilledSource || "");
  const [modelRef, setModelRef] = useState("");
  const [specText, setSpecText] = useState("");
  const [channels, setChannels] = useState<ChannelChoice[]>([]);
  const [targets, setTargets] = useState<DraftTarget[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Source[]>("/api/datasources").then((rows) => {
      setSources(rows);
      const matched = prefilledSource ? rows.find((row) => row.id === prefilledSource || row.name === prefilledSource) : undefined;
      const preferred = matched || rows.find((row) => row.dialect === "postgres") || rows[0];
      if (preferred) setSourceId(preferred.id);
    }).catch((exc: ApiError) => setError(exc.message));
    api<Model[]>("/api/llm/providers").then((rows) => {
      setModels(rows);
      const preferred = rows.find((row) => row.is_default) || rows[0];
      if (preferred) setModelRef(preferred.name);
    }).catch(() => setModels([]));
    api<ChannelChoice[]>("/api/delivery-channels").then(setChannels).catch(() => setChannels([]));
  }, []);

  async function generate() {
    setBusy(true);
    setError("");
    try {
      const draft = await api<{ spec: Spec }>("/api/builder/draft", {
        method: "POST",
        body: JSON.stringify({ description, owner, datasource_refs: [sourceId], model_ref: modelRef || null }),
      });
      const drafted = chartData ? withChartData(draft.spec, true) : draft.spec;
      setSpecText(JSON.stringify(drafted, null, 2));
      setTargets(draftsFromSpec(drafted));
      setStep(2);
    } catch (exc) {
      const message = draftError(exc);
      setError(message);
      notify({ tone: "error", title: message });
    } finally {
      setBusy(false);
    }
  }

  function spec(): Spec | null {
    try {
      return JSON.parse(specText) as Spec;
    } catch {
      setError("The spec is not valid JSON");
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

  function enterDelivery() {
    const body = spec();
    if (!body) return;
    setTargets(draftsFromSpec(body));
    setError("");
    setStep(4);
  }

  function enterReview() {
    const body = spec();
    if (!body) return;
    if (!deliveryReady(targets)) {
      setError(copy.deliveryNeedsRecipient);
      notify({ tone: "error", title: copy.deliveryNeedsRecipient });
      return;
    }
    setSpecText(JSON.stringify(writeDelivery(body, targets), null, 2));
    setError("");
    setStep(5);
  }

  async function publish() {
    const body = spec();
    if (!body) return;
    const ready = writeDelivery(body, targets);
    if (!deliveryReady(targets)) {
      setError(copy.deliveryNeedsRecipient);
      notify({ tone: "error", title: copy.deliveryNeedsRecipient });
      return;
    }
    setSpecText(JSON.stringify(ready, null, 2));
    setBusy(true);
    try {
      const created = await api<{ id: string }>("/api/agents", { method: "POST", body: JSON.stringify({ spec: ready, publish: true }) });
      const name = String((ready.metadata as { name?: string } | undefined)?.name || "agent");
      notify({
        tone: "success",
        title: copy.publishedAgent(name),
        actions: [{ label: copy.openAgent, href: `/agents/${created.id}` }],
      });
      navigate(`/agents/${created.id}`);
    } catch (exc) {
      const message = exc instanceof ApiError ? exc.message : "Could not publish";
      setError(message);
      notify({ tone: "error", title: message });
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
          <p className="eyebrow">Builder</p>
          <h1>New agent</h1>
          <p>A description, a data source, and a model produce a spec. Edit it before you publish. Turkish descriptions are accepted.</p>
        </div>
      </div>
      <div className="stepper" aria-label="Steps">
        {STEPS.map((label, index) => <span key={label} className={index === step ? "on" : ""}>{index + 1}. {label}</span>)}
      </div>
      <section className="card">
        {step === 0 && (
          <div className="grid-2">
            <label className="field">Owner<input value={owner} onChange={(event) => setOwner(event.target.value)} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>What should it do?<textarea rows={5} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
            <div style={{ gridColumn: "1 / -1" }}><ChartDataToggle checked={chartData} onChange={setChartData} /></div>
          </div>
        )}
        {step === 1 && (
          <div className="grid-2">
            <label className="field">Data source
              <Select
                ariaLabel="Data source"
                value={sourceId}
                onChange={setSourceId}
                placeholder="Select a source"
                options={sources.map((source) => ({ value: source.id, label: source.name, description: source.dialect }))}
              />
            </label>
            <label className="field">Model
              <Select
                ariaLabel="Model"
                value={modelRef}
                onChange={setModelRef}
                options={[
                  { value: "", label: "Environment default", description: "The seeded model" },
                  ...models.map((model) => ({ value: model.name, label: model.name, description: model.model })),
                ]}
              />
            </label>
            {sources.length === 0 && <p>Define a data source first.</p>}
          </div>
        )}
        {step === 2 && (
          <div>
            <ChartDataToggle
              checked={chartDataOf(parsed)}
              onChange={(value) => { const body = spec(); if (body) { setChartData(value); setSpecText(JSON.stringify(withChartData(body, value), null, 2)); setError(""); } }}
            />
            <label className="field">Generated spec
              <textarea rows={16} value={specText} onChange={(event) => setSpecText(event.target.value)} spellCheck={false} />
            </label>
          </div>
        )}
        {step === 3 && (
          <div>
            <div className="grid-2">
              <label className="field">Mode
                <Select
                  ariaLabel="Schedule mode"
                  value={schedule?.mode || "manual"}
                  onChange={(mode) => updateSchedule(mode, schedule?.cron || "30 8 * * 1-5")}
                  options={[
                    { value: "manual", label: "Manual", description: "Only when someone clicks Run" },
                    { value: "cron", label: "Scheduled", description: "A cron expression" },
                    { value: "hybrid", label: "Scheduled, plus its own decision", description: "Cron, and the agent may ask to run" },
                    { value: "self", label: "Its own decision", description: "No clock; the agent decides" },
                  ]}
                />
              </label>
              <label className="field">Cron<input value={schedule?.cron || ""} onChange={(event) => updateSchedule(schedule?.mode || "cron", event.target.value)} /></label>
            </div>
            {(!schedule?.mode || schedule.mode === "manual") && (
              <p>If the description names no time, the draft stays manual. Write the time yourself. The builder does not invent one.</p>
            )}
          </div>
        )}
        {step === 4 && (
          <DeliveryEditor channels={channels} targets={targets} onChange={setTargets} />
        )}
        {step === 5 && parsed && (
          <div>
            <p><b>{String((parsed.metadata as { name?: string })?.name || "")}</b></p>
            <p>{String((parsed.spec as { goal?: string })?.goal || "")}</p>
            <p>Model: {String((parsed.spec as { model?: { class?: string } })?.model?.class || "")}</p>
            <p>{targets.length === 0 ? copy.deliveryNone : targets.map((target) => `${target.toText} via ${target.channel || "—"}`).join(" · ")}</p>
          </div>
        )}
        {error && <p role="alert">{error}</p>}
        <div className="row" style={{ marginTop: 16 }}>
          {step > 0 && <button className="btn-ghost" type="button" onClick={() => {
            if (step === 4) {
              const body = spec();
              if (body) setSpecText(JSON.stringify(writeDelivery(body, targets), null, 2));
            }
            setStep(step - 1);
          }}>Back</button>}
          {step === 0 && <button className="btn" type="button" onClick={() => setStep(1)}>Continue</button>}
          {step === 1 && <button className="btn" type="button" disabled={busy || !sourceId} aria-busy={busy || undefined} onClick={() => void generate()}>{busy && <span className="spinner" aria-hidden />}{busy ? "Drafting…" : "Draft spec"}</button>}
          {step === 2 && <button className="btn" type="button" onClick={() => setStep(3)}>Schedule</button>}
          {step === 3 && <button className="btn" type="button" onClick={enterDelivery}>Delivery</button>}
          {step === 4 && <button className="btn" type="button" onClick={enterReview}>Review</button>}
          {step === 5 && <button className="btn" type="button" disabled={busy} aria-busy={busy || undefined} onClick={() => void publish()}>{busy && <span className="spinner" aria-hidden />}{busy ? "Publishing…" : "Publish"}</button>}
        </div>
      </section>
    </>
  );
}
