import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { Select } from "../components/Select";
import { EMPTY_SECRET_SOURCE, SecretSourceFields, secretSourceFromRow, type SecretSource } from "../components/SecretSourceFields";
import { ActionButton, Badge, ConfirmDialog, DataTable, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useBusy } from "../lib/busy";
import { copy } from "../lib/copy";
import { announceError, notify } from "../lib/notify";

type Provider = {
  id: string;
  name: string;
  base_url: string;
  model: string;
  api_key_set: boolean;
  api_key_hint: string;
  temperature: number | null;
  reasoning_effort: string;
  is_default: boolean;
  enabled: boolean;
  secret_backend?: string;
  k8s_secret_name?: string | null;
  k8s_secret_key?: string | null;
  secret_provider_id?: string | null;
  secret_path?: string;
  secret_ref?: { app_id?: string; safe?: string; object?: string; query?: string };
};

type SecretProvider = { id: string; name: string; kind: string; enabled: boolean };

const EMPTY = {
  name: "",
  base_url: "https://api.deepseek.com",
  model: "deepseek-flash",
  api_key: "",
  temperature: "",
  reasoning_effort: "",
  is_default: false,
  ...EMPTY_SECRET_SOURCE,
};

export function Models() {
  const [rows, setRows] = useState<Provider[] | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState<typeof EMPTY | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [providers, setProviders] = useState<SecretProvider[]>([]);
  const [pendingDelete, setPendingDelete] = useState<Provider | null>(null);
  const { run, pending } = useBusy();
  const { can } = useAuth();

  function load() {
    api<Provider[]>("/api/llm/providers").then(setRows).catch((exc: ApiError) => setError(exc.message));
    api<SecretProvider[]>("/api/secret-providers").then(setProviders).catch(() => setProviders([]));
  }
  useEffect(load, []);

  async function save() {
    if (!form) return;
    const backend = form.secret_backend || "db";
    const payload = {
      name: form.name,
      base_url: form.base_url,
      model: form.model,
      api_key: backend === "db" ? form.api_key || null : null,
      temperature: form.temperature === "" ? null : Number(form.temperature),
      reasoning_effort: form.reasoning_effort,
      is_default: form.is_default,
      enabled: true,
      secret_backend: backend,
      k8s_secret_name: backend === "kubernetes" ? form.k8s_secret_name : null,
      k8s_secret_key: backend === "kubernetes" ? form.k8s_secret_key || "api_key" : null,
      secret_provider_id: backend === "conjur" || backend === "ccp" ? form.secret_provider_id || null : null,
      secret_path: backend === "conjur" ? form.secret_path : "",
      secret_ref: backend === "ccp"
        ? { app_id: form.ccp_app_id, safe: form.ccp_safe, object: form.ccp_object, query: form.ccp_query }
        : {},
    };
    try {
      if (editing) await api(`/api/llm/providers/${editing}`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("/api/llm/providers", { method: "POST", body: JSON.stringify(payload) });
      setForm(null);
      setEditing(null);
      notify({ tone: "success", title: copy.saved });
      load();
    } catch (exc) {
      announceError(exc, copy.couldNotSave);
    }
  }

  function test(id: string) {
    void run(`test:${id}`, async () => {
      try {
        const result = await api<{ ok: boolean; latency_ms: number; sample: string }>(`/api/llm/providers/${id}/test`, { method: "POST" });
        notify({ tone: "success", title: copy.modelReply(result.latency_ms, result.sample) });
      } catch (exc) {
        announceError(exc, copy.testDidNotFinish);
      }
    });
  }

  function remove(row: Provider) {
    void run(`delete:${row.id}`, async () => {
      try {
        await api(`/api/llm/providers/${row.id}`, { method: "DELETE" });
        notify({ tone: "success", title: copy.deletedSource(row.name) });
        setPendingDelete(null);
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  const columns: ColumnDef<Provider>[] = [
    { accessorKey: "name", header: "Name" },
    { accessorKey: "model", header: "Model" },
    { accessorKey: "base_url", header: "Address" },
    { id: "source", header: "Secret backend", cell: ({ row }) => sourceLabel(row.original.secret_backend) },
    { id: "key", header: "Key", cell: ({ row }) => row.original.api_key_set ? row.original.api_key_hint || "stored" : "—" },
    { accessorKey: "reasoning_effort", header: "Reasoning", cell: ({ getValue }) => String(getValue() || "off") },
    { id: "def", header: "Default", cell: ({ row }) => row.original.is_default ? <Badge status="published" /> : "—" },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="row">
          <ActionButton
            className="btn-ghost"
            busy={pending(`test:${row.original.id}`)}
            disabled={!can("llm_provider:test")}
            title={!can("llm_provider:test") ? copy.permissionDeniedHint : undefined}
            onClick={() => test(row.original.id)}
          >
            {copy.test}
          </ActionButton>
          <button
            className="btn-ghost"
            type="button"
            disabled={!can("llm_provider:write")}
            title={!can("llm_provider:write") ? copy.permissionDeniedHint : undefined}
            onClick={() => { setEditing(row.original.id); setForm({ ...EMPTY, name: row.original.name, base_url: row.original.base_url, model: row.original.model, api_key: "", temperature: row.original.temperature === null ? "" : String(row.original.temperature), reasoning_effort: row.original.reasoning_effort, is_default: row.original.is_default, ...secretSourceFromRow(row.original) }); }}
          >
            {copy.edit}
          </button>
          <button
            className="btn-danger"
            type="button"
            disabled={!can("llm_provider:delete")}
            title={!can("llm_provider:delete") ? copy.permissionDeniedHint : undefined}
            onClick={() => setPendingDelete(row.original)}
          >
            {copy.delete}
          </button>
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
          <p className="eyebrow">Models</p>
          <h1>LLM providers</h1>
          <p>OpenAI-compatible endpoints. The key can stay encrypted on the platform, or point at a Kubernetes Secret or a CyberArk record. Leave reasoning empty to turn it off.</p>
        </div>
        <button
          className="btn"
          type="button"
          disabled={!can("llm_provider:write")}
          title={!can("llm_provider:write") ? copy.permissionDeniedHint : undefined}
          onClick={() => { setEditing(null); setForm(EMPTY); }}
        >
          New model
        </button>
      </div>
      <section className="card">
        {rows.length === 0 ? <Empty title="No models" body="Add DeepSeek or another OpenAI-compatible endpoint. Simulated mode does not wait on this list." action={<button className="btn" type="button" onClick={() => { setEditing(null); setForm(EMPTY); }}>New model</button>} /> : <DataTable data={rows} columns={columns} />}
      </section>
      {form && (
        <Modal title={editing ? "Edit model" : "New model"} onClose={() => setForm(null)}>
          <div className="grid-2">
            <label className="field">Name<input value={form.name} disabled={Boolean(editing)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label className="field">Model<input value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>Address<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} /></label>
            <SecretSourceFields
              value={form}
              providers={providers}
              k8sKeyHint="api_key"
              onChange={(next: SecretSource) => setForm({ ...form, ...next, api_key: next.secret_backend === "db" ? form.api_key : "" })}
            />
            {form.secret_backend === "db" && (
              <label className="field">API key<input type="password" autoComplete="new-password" placeholder={editing ? "Leave blank to keep the current key" : ""} value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} /></label>
            )}
            <label className="field">Temperature<input value={form.temperature} placeholder="0" onChange={(event) => setForm({ ...form, temperature: event.target.value })} /></label>
            <label className="field">Reasoning
              <Select
                ariaLabel="Reasoning"
                value={form.reasoning_effort}
                onChange={(reasoning_effort) => setForm({ ...form, reasoning_effort })}
                options={[
                  { value: "", label: "Off", description: "No extra reasoning pass" },
                  { value: "low", label: "low" },
                  { value: "medium", label: "medium" },
                  { value: "high", label: "high" },
                ]}
              />
            </label>
            <label className="field"><span>Default</span><input type="checkbox" checked={form.is_default} onChange={(event) => setForm({ ...form, is_default: event.target.checked })} /></label>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <ActionButton busy={pending("save")} onClick={() => void run("save", save)}>{copy.save}</ActionButton>
            <button className="btn-ghost" type="button" onClick={() => setForm(null)}>{copy.cancel}</button>
          </div>
        </Modal>
      )}
      {pendingDelete && (
        <ConfirmDialog
          title={copy.confirmDeleteTitle}
          body={copy.confirmDeleteModel(pendingDelete.name)}
          busy={pending(`delete:${pendingDelete.id}`)}
          onConfirm={() => remove(pendingDelete)}
          onClose={() => setPendingDelete(null)}
        />
      )}
    </>
  );
}

function sourceLabel(backend: string | undefined) {
  if (backend === "kubernetes") return "Kubernetes";
  if (backend === "conjur") return "Conjur";
  if (backend === "ccp") return "CCP";
  return "Platform DB";
}
