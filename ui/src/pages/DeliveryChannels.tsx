import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { EMPTY_SECRET_SOURCE, SecretSourceFields, secretSourceFromRow, type SecretSource } from "../components/SecretSourceFields";
import { Select } from "../components/Select";
import { ActionButton, Badge, ConfirmDialog, DataTable, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useBusy } from "../lib/busy";
import { copy } from "../lib/copy";
import { announceError, notify } from "../lib/notify";

type Channel = {
  id: string;
  name: string;
  kind: string;
  enabled: boolean;
  from_address: string;
  from_name: string;
  allow_domains: string[];
  max_attachment_bytes: number;
  credential_set: boolean;
  credential_hint: string;
  config: Record<string, unknown>;
  secret_backend?: string;
  k8s_secret_name?: string | null;
  k8s_secret_key?: string | null;
  secret_provider_id?: string | null;
  secret_path?: string;
  secret_ref?: { app_id?: string; safe?: string; object?: string; query?: string };
};

type SecretProvider = { id: string; name: string; kind: string; enabled: boolean };

const HTTP_TEMPLATE = `{
  "to": {{to}},
  "cc": {{cc}},
  "subject": "{{subject}}",
  "html": "{{html}}",
  "text": "{{text}}",
  "attachments": {{attachments}},
  "report_url": "{{report_url}}"
}`;

const EMPTY = {
  name: "",
  kind: "smtp" as "smtp" | "http",
  enabled: true,
  from_address: "",
  from_name: "",
  allow_domains: "",
  max_attachment_bytes: "2000000",
  password: "",
  host: "",
  port: "587",
  tls_mode: "starttls",
  username: "",
  url: "",
  method: "POST",
  headers: "{}",
  auth: "bearer",
  header_name: "",
  success_codes: "200, 201, 202",
  timeout_seconds: "20",
  body_template: HTTP_TEMPLATE,
  ...EMPTY_SECRET_SOURCE,
};

type Form = typeof EMPTY;

export function DeliveryChannels() {
  const [rows, setRows] = useState<Channel[] | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState<Form | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [providers, setProviders] = useState<SecretProvider[]>([]);
  const [pendingDelete, setPendingDelete] = useState<Channel | null>(null);
  const { run, pending } = useBusy();

  function load() {
    api<Channel[]>("/api/delivery-channels").then(setRows).catch((exc: ApiError) => setError(exc.message));
    api<SecretProvider[]>("/api/secret-providers").then(setProviders).catch(() => setProviders([]));
  }
  useEffect(load, []);

  function open(row?: Channel) {
    if (!row) {
      setEditing(null);
      setForm({ ...EMPTY });
      return;
    }
    const config = row.config || {};
    setEditing(row.id);
    setForm({
      ...EMPTY,
      ...secretSourceFromRow(row),
      name: row.name,
      kind: row.kind === "http" ? "http" : "smtp",
      enabled: row.enabled,
      from_address: row.from_address,
      from_name: row.from_name,
      allow_domains: (row.allow_domains || []).join(", "),
      max_attachment_bytes: String(row.max_attachment_bytes),
      password: "",
      host: String(config.host || ""),
      port: String(config.port || (config.tls_mode === "ssl" ? 465 : 587)),
      tls_mode: String(config.tls_mode || "starttls"),
      username: String(config.username || ""),
      url: String(config.url || ""),
      method: String(config.method || "POST"),
      headers: JSON.stringify(config.headers || {}, null, 2),
      auth: String(config.auth || "none"),
      header_name: String(config.header_name || ""),
      success_codes: Array.isArray(config.success_codes) ? (config.success_codes as number[]).join(", ") : "200, 201, 202",
      timeout_seconds: String(config.timeout_seconds || 20),
      body_template: String(config.body_template || HTTP_TEMPLATE),
    });
  }

  async function save() {
    if (!form) return;
    const backend = form.secret_backend || "db";
    const needsSecret = form.kind === "smtp" || form.auth !== "none";
    const payload = {
      name: form.name,
      kind: form.kind,
      enabled: form.enabled,
      from_address: form.from_address,
      from_name: form.from_name,
      allow_domains: form.allow_domains.split(",").map((item) => item.trim()).filter(Boolean),
      max_attachment_bytes: Number(form.max_attachment_bytes),
      password: needsSecret && backend === "db" ? form.password || null : null,
      secret_backend: needsSecret ? backend : "db",
      k8s_secret_name: needsSecret && backend === "kubernetes" ? form.k8s_secret_name : null,
      k8s_secret_key: needsSecret && backend === "kubernetes" ? form.k8s_secret_key || "password" : null,
      secret_provider_id: needsSecret && (backend === "conjur" || backend === "ccp") ? form.secret_provider_id || null : null,
      secret_path: needsSecret && backend === "conjur" ? form.secret_path : "",
      secret_ref: needsSecret && backend === "ccp"
        ? { app_id: form.ccp_app_id, safe: form.ccp_safe, object: form.ccp_object, query: form.ccp_query }
        : {},
      config: form.kind === "smtp"
        ? {
            host: form.host,
            port: Number(form.port),
            tls_mode: form.tls_mode,
            username: form.username,
            timeout_seconds: Number(form.timeout_seconds),
          }
        : {
            url: form.url,
            method: form.method,
            headers: form.headers,
            auth: form.auth,
            username: form.username,
            header_name: form.header_name,
            success_codes: form.success_codes,
            timeout_seconds: Number(form.timeout_seconds),
            body_template: form.body_template,
          },
    };
    try {
      if (editing) await api(`/api/delivery-channels/${editing}`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("/api/delivery-channels", { method: "POST", body: JSON.stringify(payload) });
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
        const result = await api<{ ok: boolean; latency_ms: number }>(`/api/delivery-channels/${id}/test`, { method: "POST" });
        notify({ tone: "success", title: copy.deliveryTestSent(result.latency_ms) });
      } catch (exc) {
        announceError(exc, copy.testDidNotFinish);
      }
    });
  }

  function remove(row: Channel) {
    void run(`delete:${row.id}`, async () => {
      try {
        await api(`/api/delivery-channels/${row.id}`, { method: "DELETE" });
        notify({ tone: "success", title: copy.deletedSource(row.name) });
        setPendingDelete(null);
        load();
      } catch (exc) {
        announceError(exc);
      }
    });
  }

  const columns: ColumnDef<Channel>[] = [
    { accessorKey: "name", header: copy.name },
    { id: "kind", header: copy.type, cell: ({ row }) => row.original.kind === "http" ? copy.httpApi : copy.smtp },
    { accessorKey: "from_address", header: copy.fromAddress },
    { id: "domains", header: copy.allowDomains, cell: ({ row }) => (row.original.allow_domains || []).join(", ") || "—" },
    { id: "state", header: copy.status, cell: ({ row }) => <Badge status={row.original.enabled ? "published" : "paused"} /> },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="row">
          <ActionButton className="btn-ghost" busy={pending(`test:${row.original.id}`)} onClick={() => test(row.original.id)}>{copy.test}</ActionButton>
          <button className="btn-ghost" type="button" onClick={() => open(row.original)}>{copy.edit}</button>
          <button className="btn-danger" type="button" onClick={() => setPendingDelete(row.original)}>{copy.delete}</button>
        </span>
      ),
    },
  ];

  if (error) return <div className="card">{error}</div>;
  if (!rows) return <SkeletonRows />;
  const needsSecret = Boolean(form && (form.kind === "smtp" || form.auth !== "none"));
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{copy.navConfigure}</p>
          <h1>{copy.deliveryTitle}</h1>
          <p>{copy.deliveryLead}</p>
        </div>
        <button className="btn" type="button" onClick={() => open()}>{copy.newChannel}</button>
      </div>
      <section className="card">
        {rows.length === 0
          ? <Empty title={copy.noChannels} body={copy.noChannelsBody} action={<button className="btn" type="button" onClick={() => open()}>{copy.newChannel}</button>} />
          : <DataTable data={rows} columns={columns} />}
      </section>
      {form && (
        <Modal title={editing ? copy.editChannel : copy.newChannel} onClose={() => setForm(null)}>
          <div className="grid-2">
            <label className="field">{copy.name}<input value={form.name} disabled={Boolean(editing)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label className="field">{copy.channelType}
              <Select
                ariaLabel={copy.channelType}
                value={form.kind}
                onChange={(kind) => setForm({ ...form, kind: kind === "http" ? "http" : "smtp" })}
                options={[
                  { value: "smtp", label: copy.smtp, description: "Host, port, and TLS" },
                  { value: "http", label: copy.httpApi, description: "JSON body to your email API" },
                ]}
              />
            </label>
            <label className="field">{copy.fromAddress}<input value={form.from_address} onChange={(event) => setForm({ ...form, from_address: event.target.value })} /></label>
            <label className="field">{copy.fromName}<input value={form.from_name} onChange={(event) => setForm({ ...form, from_name: event.target.value })} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>{copy.allowDomains}
              <input value={form.allow_domains} placeholder="company.example, *.company.example" onChange={(event) => setForm({ ...form, allow_domains: event.target.value })} />
            </label>
            <p style={{ gridColumn: "1 / -1" }}>{copy.allowDomainsHint}</p>
            <label className="field">{copy.maxAttachment}<input value={form.max_attachment_bytes} onChange={(event) => setForm({ ...form, max_attachment_bytes: event.target.value })} /></label>
            <label className="field"><span>{copy.enabled}</span><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /></label>
            {form.kind === "smtp" && (
              <>
                <label className="field">{copy.host}<input value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} /></label>
                <label className="field">{copy.port}<input value={form.port} onChange={(event) => setForm({ ...form, port: event.target.value })} /></label>
                <label className="field">{copy.tlsMode}
                  <Select
                    ariaLabel={copy.tlsMode}
                    value={form.tls_mode}
                    onChange={(tls_mode) => setForm({ ...form, tls_mode })}
                    options={[
                      { value: "none", label: "none" },
                      { value: "starttls", label: "STARTTLS" },
                      { value: "ssl", label: "SSL" },
                    ]}
                  />
                </label>
                <label className="field">{copy.username}<input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
              </>
            )}
            {form.kind === "http" && (
              <>
                <label className="field" style={{ gridColumn: "1 / -1" }}>{copy.url}<input value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} /></label>
                <label className="field">{copy.method}
                  <Select
                    ariaLabel={copy.method}
                    value={form.method}
                    onChange={(method) => setForm({ ...form, method })}
                    options={[
                      { value: "POST", label: "POST" },
                      { value: "PUT", label: "PUT" },
                      { value: "PATCH", label: "PATCH" },
                    ]}
                  />
                </label>
                <label className="field">{copy.auth}
                  <Select
                    ariaLabel={copy.auth}
                    value={form.auth}
                    onChange={(auth) => setForm({ ...form, auth })}
                    options={[
                      { value: "none", label: "none" },
                      { value: "bearer", label: "bearer" },
                      { value: "basic", label: "basic" },
                      { value: "header", label: "custom header" },
                    ]}
                  />
                </label>
                {form.auth === "basic" && (
                  <label className="field">{copy.username}<input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
                )}
                {form.auth === "header" && (
                  <label className="field">{copy.headerName}<input value={form.header_name} onChange={(event) => setForm({ ...form, header_name: event.target.value })} /></label>
                )}
                <label className="field">{copy.successCodes}<input value={form.success_codes} onChange={(event) => setForm({ ...form, success_codes: event.target.value })} /></label>
                <label className="field" style={{ gridColumn: "1 / -1" }}>{copy.headers}
                  <textarea rows={4} value={form.headers} spellCheck={false} onChange={(event) => setForm({ ...form, headers: event.target.value })} />
                </label>
                <label className="field" style={{ gridColumn: "1 / -1" }}>{copy.bodyTemplate}
                  <textarea rows={8} value={form.body_template} spellCheck={false} onChange={(event) => setForm({ ...form, body_template: event.target.value })} />
                </label>
                <p style={{ gridColumn: "1 / -1" }}>{copy.bodyTemplateHint}</p>
              </>
            )}
            <label className="field">{copy.timeoutSeconds}<input value={form.timeout_seconds} onChange={(event) => setForm({ ...form, timeout_seconds: event.target.value })} /></label>
            {needsSecret && (
              <SecretSourceFields
                value={form}
                providers={providers}
                k8sKeyHint="password"
                onChange={(next: SecretSource) => setForm({ ...form, ...next, password: next.secret_backend === "db" ? form.password : "" })}
              />
            )}
            {needsSecret && form.secret_backend === "db" && (
              <label className="field">{copy.password}
                <input type="password" autoComplete="new-password" placeholder={editing ? copy.passwordKeep : ""} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />
              </label>
            )}
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
          body={copy.confirmDeleteChannel(pendingDelete.name)}
          busy={pending(`delete:${pendingDelete.id}`)}
          onConfirm={() => remove(pendingDelete)}
          onClose={() => setPendingDelete(null)}
        />
      )}
    </>
  );
}
