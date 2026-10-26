import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { EMPTY_SECRET_SOURCE, SecretSourceFields, secretSourceFromRow, type SecretSource } from "../components/SecretSourceFields";
import { Badge, DataTable, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";

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
  const [toast, setToast] = useState("");
  const [providers, setProviders] = useState<SecretProvider[]>([]);

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
      setToast("Kaydedildi");
      load();
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : "kaydedilemedi");
    }
  }

  async function test(id: string) {
    try {
      const result = await api<{ ok: boolean; latency_ms: number; sample: string }>(`/api/llm/providers/${id}/test`, { method: "POST" });
      setToast(`Yanıt ${result.latency_ms} ms: ${result.sample}`);
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : "deneme olmadı");
    }
  }

  const columns: ColumnDef<Provider>[] = [
    { accessorKey: "name", header: "Ad" },
    { accessorKey: "model", header: "Model" },
    { accessorKey: "base_url", header: "Adres" },
    { id: "source", header: "Parola kaynağı", cell: ({ row }) => sourceLabel(row.original.secret_backend) },
    { id: "key", header: "Anahtar", cell: ({ row }) => row.original.api_key_set ? row.original.api_key_hint || "kayıtlı" : "—" },
    { accessorKey: "reasoning_effort", header: "Akıl yürütme", cell: ({ getValue }) => String(getValue() || "kapalı") },
    { id: "def", header: "Varsayılan", cell: ({ row }) => row.original.is_default ? <Badge status="published" /> : "—" },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="row">
          <button className="btn-ghost" type="button" onClick={() => void test(row.original.id)}>Dene</button>
          <button className="btn-ghost" type="button" onClick={() => { setEditing(row.original.id); setForm({ ...EMPTY, name: row.original.name, base_url: row.original.base_url, model: row.original.model, api_key: "", temperature: row.original.temperature === null ? "" : String(row.original.temperature), reasoning_effort: row.original.reasoning_effort, is_default: row.original.is_default, ...secretSourceFromRow(row.original) }); }}>Düzenle</button>
          <button className="btn-danger" type="button" onClick={() => void api(`/api/llm/providers/${row.original.id}`, { method: "DELETE" }).then(() => { setToast("Silindi"); load(); })}>Sil</button>
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
          <h1>LLM Modelleri</h1>
          <p>OpenAI uyumlu adresler. Anahtar platformda şifreli durabilir veya bir Kubernetes Secret ya da CyberArk kaydına başvurur. Akıl yürütme boşsa kapalıdır.</p>
        </div>
        <button className="btn" type="button" onClick={() => { setEditing(null); setForm(EMPTY); }}>Yeni model</button>
      </div>
      <section className="card">
        {rows.length === 0 ? <Empty title="Model yok" body="DeepSeek veya başka bir OpenAI uyumlu uç ekleyin. Sahte modda koşumlar bu listeyi beklemez." /> : <DataTable data={rows} columns={columns} />}
      </section>
      {form && (
        <Modal title={editing ? "Modeli düzenle" : "Yeni model"} onClose={() => setForm(null)}>
          <div className="grid-2">
            <label className="field">Ad<input value={form.name} disabled={Boolean(editing)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label className="field">Model<input value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>Adres<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} /></label>
            <SecretSourceFields
              value={form}
              providers={providers}
              k8sKeyHint="api_key"
              onChange={(next: SecretSource) => setForm({ ...form, ...next, api_key: next.secret_backend === "db" ? form.api_key : "" })}
            />
            {form.secret_backend === "db" && (
              <label className="field">API anahtarı<input type="password" autoComplete="new-password" placeholder={editing ? "Boş bırakılırsa değişmez" : ""} value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} /></label>
            )}
            <label className="field">Sıcaklık<input value={form.temperature} placeholder="0" onChange={(event) => setForm({ ...form, temperature: event.target.value })} /></label>
            <label className="field">Akıl yürütme
              <select value={form.reasoning_effort} onChange={(event) => setForm({ ...form, reasoning_effort: event.target.value })}>
                <option value="">Kapalı</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </label>
            <label className="field"><span>Varsayılan</span><input type="checkbox" checked={form.is_default} onChange={(event) => setForm({ ...form, is_default: event.target.checked })} /></label>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" type="button" onClick={() => void save()}>Kaydet</button>
            <button className="btn-ghost" type="button" onClick={() => setForm(null)}>Vazgeç</button>
          </div>
        </Modal>
      )}
      {toast && <div className="toasts" role="status"><div className="toast">{toast}</div></div>}
    </>
  );
}

function sourceLabel(backend: string | undefined) {
  if (backend === "kubernetes") return "Kubernetes";
  if (backend === "conjur") return "Conjur";
  if (backend === "ccp") return "CCP";
  return "Platform DB";
}
