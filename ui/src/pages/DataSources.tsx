import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { EMPTY_SECRET_SOURCE, SecretSourceFields, secretSourceFromRow, type SecretSource } from "../components/SecretSourceFields";
import { DataTable, Empty, Modal, SkeletonRows, Toast } from "../components/ui";
import { api, ApiError } from "../lib/api";

type Source = {
  id: string;
  name: string;
  dialect: string;
  description: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  password_set: boolean;
  password_hint: string;
  allow_tables: string[];
  read_only: boolean;
  sensitivity: string;
  enabled: boolean;
  configured: boolean;
  secret_backend?: string;
  k8s_secret_name?: string | null;
  k8s_secret_key?: string | null;
  secret_provider_id?: string | null;
  secret_path?: string;
  secret_ref?: { app_id?: string; safe?: string; object?: string; query?: string };
  secret_form?: string;
};

type Provider = { id: string; name: string; kind: string; enabled: boolean };

const EMPTY = {
  name: "",
  dialect: "postgres",
  description: "",
  host: "127.0.0.1",
  port: 5432,
  database_name: "",
  username: "",
  password: "",
  allow_tables: "sales",
  read_only: true,
  sensitivity: "internal",
  ...EMPTY_SECRET_SOURCE,
};

export function DataSources() {
  const [rows, setRows] = useState<Source[] | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState<typeof EMPTY | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const [q, setQ] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);

  function load() {
    api<Source[]>("/api/datasources").then(setRows).catch((exc: ApiError) => setError(exc.message));
    api<Provider[]>("/api/secret-providers").then(setProviders).catch(() => setProviders([]));
  }
  useEffect(load, []);

  async function save() {
    if (!form) return;
    const backend = form.secret_backend || "db";
    const payload = {
      name: form.name,
      dialect: form.dialect,
      description: form.description,
      host: form.host,
      port: form.port,
      database_name: form.database_name,
      username: form.username,
      allow_tables: form.allow_tables.split(",").map((item) => item.trim()).filter(Boolean),
      read_only: form.read_only,
      sensitivity: form.sensitivity,
      password: backend === "db" ? form.password || null : null,
      secret_backend: backend,
      k8s_secret_name: backend === "kubernetes" ? form.k8s_secret_name : null,
      k8s_secret_key: backend === "kubernetes" ? form.k8s_secret_key || (form.secret_form === "url" ? "dsn" : "password") : null,
      secret_provider_id: backend === "conjur" || backend === "ccp" ? form.secret_provider_id || null : null,
      secret_path: backend === "conjur" ? form.secret_path : "",
      secret_ref: backend === "ccp"
        ? { app_id: form.ccp_app_id, safe: form.ccp_safe, object: form.ccp_object, query: form.ccp_query }
        : {},
      secret_form: backend === "db" ? "password" : form.secret_form || "password",
    };
    try {
      if (editing) await api(`/api/datasources/${editing}`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("/api/datasources", { method: "POST", body: JSON.stringify(payload) });
      setForm(null);
      setEditing(null);
      setToast("Saved");
      load();
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : "Could not save");
    }
  }

  async function test(id: string) {
    try {
      const result = await api<{ ok: boolean; latency_ms: number }>(`/api/datasources/${id}/test`, { method: "POST" });
      setToast(result.ok ? `Connected in ${result.latency_ms} ms` : "Connection failed");
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : "Connection failed");
    }
  }

  const columns: ColumnDef<Source>[] = [
    { accessorKey: "name", header: "Name" },
    { accessorKey: "dialect", header: "Type" },
    { id: "place", header: "Target", accessorFn: (row) => row.host ? `${row.host}:${row.port}/${row.database_name}` : "environment variable" },
    { accessorKey: "username", header: "User" },
    { id: "source", header: "Secret backend", cell: ({ row }) => sourceLabel(row.original.secret_backend) },
    { id: "secret", header: "Password", cell: ({ row }) => row.original.password_set ? row.original.password_hint : "—" },
    { id: "ro", header: "Access", cell: ({ row }) => row.original.read_only ? <span className="badge ok">Read only</span> : <span className="badge warn">Writable</span> },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="row">
          <button className="btn-ghost" type="button" onClick={() => void test(row.original.id)}>Test</button>
          <button className="btn-ghost" type="button" onClick={() => { setEditing(row.original.id); setForm({ ...EMPTY, ...row.original, ...secretSourceFromRow(row.original), allow_tables: row.original.allow_tables.join(", "), password: "" }); }}>Edit</button>
          <button className="btn-danger" type="button" onClick={() => void api(`/api/datasources/${row.original.id}`, { method: "DELETE" }).then(() => { setToast("Deleted"); load(); })}>Delete</button>
        </span>
      ),
    },
  ];

  if (error) return <div className="card">{error}</div>;
  if (!rows) return <SkeletonRows />;
  const filtered = rows.filter((row) => row.name.toLocaleLowerCase("tr").includes(q.toLocaleLowerCase("tr")));
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Connections</p>
          <h1>Data sources</h1>
          <p>Postgres and Oracle. A password can stay encrypted on the platform, or point at a Kubernetes Secret or a CyberArk record. By default the reference is only the password. Host and user stay on this form. The value is never returned.</p>
        </div>
        <button className="btn" type="button" onClick={() => { setEditing(null); setForm(EMPTY); }}>New source</button>
      </div>
      <section className="card">
        <input className="search" aria-label="Search sources" value={q} placeholder="Name" onChange={(event) => setQ(event.target.value)} />
        {filtered.length === 0 ? <Empty title="No sources" body="Add a Postgres or Oracle connection." /> : <DataTable data={filtered} columns={columns} />}
      </section>
      {form && (
        <Modal title={editing ? "Edit source" : "New source"} onClose={() => setForm(null)}>
          <div className="grid-2">
            <label className="field">Name<input value={form.name} disabled={Boolean(editing)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label className="field">Type
              <select value={form.dialect} onChange={(event) => setForm({ ...form, dialect: event.target.value, port: event.target.value === "oracle" ? 1521 : 5432 })}>
                <option value="postgres">Postgres</option>
                <option value="oracle">Oracle</option>
              </select>
            </label>
            <label className="field">Host<input value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} /></label>
            <label className="field">Port<input type="number" value={form.port} onChange={(event) => setForm({ ...form, port: Number(event.target.value) })} /></label>
            <label className="field">Database / service<input value={form.database_name} onChange={(event) => setForm({ ...form, database_name: event.target.value })} /></label>
            <label className="field">User<input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
            <SecretSourceFields
              value={form}
              providers={providers}
              k8sKeyHint={form.secret_form === "url" ? "dsn" : "password"}
              showSecretForm
              onChange={(next: SecretSource) => setForm({ ...form, ...next, password: next.secret_backend === "db" ? form.password : "" })}
            />
            {form.secret_backend === "db" && (
              <label className="field">Password<input type="password" autoComplete="new-password" placeholder={editing ? "Leave blank to keep the current password" : ""} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></label>
            )}
            <label className="field">Tables<input value={form.allow_tables} onChange={(event) => setForm({ ...form, allow_tables: event.target.value })} /></label>
            <label className="field">Sensitivity
              <select value={form.sensitivity} onChange={(event) => setForm({ ...form, sensitivity: event.target.value })}>
                <option value="internal">internal</option>
                <option value="restricted">restricted</option>
              </select>
            </label>
            <label className="field">Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
            <label className="field"><span>Read only</span><input type="checkbox" checked={form.read_only} onChange={(event) => setForm({ ...form, read_only: event.target.checked })} /></label>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" type="button" onClick={() => void save()}>Save</button>
            <button className="btn-ghost" type="button" onClick={() => setForm(null)}>Cancel</button>
          </div>
        </Modal>
      )}
      <Toast message={toast} />
    </>
  );
}

function sourceLabel(backend: string | undefined) {
  if (backend === "kubernetes") return "Kubernetes";
  if (backend === "conjur") return "Conjur";
  if (backend === "ccp") return "CCP";
  return "Platform DB";
}
