import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { Select } from "../components/Select";
import { ActionButton, ConfirmDialog, DataTable, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { useBusy } from "../lib/busy";
import { copy } from "../lib/copy";
import { announceError, notify } from "../lib/notify";

type Provider = {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  account: string;
  auth_method: string;
  ca_bundle: string;
  config: { login?: string; service_id?: string; app_id?: string };
  credential_secret_name: string;
  credential_secret_key: string;
  tls_cert_key: string;
  tls_key_key: string;
  credential_namespace: string;
  enabled: boolean;
};

const EMPTY = {
  name: "",
  kind: "conjur",
  base_url: "http://conjur.conjur-test.svc:80",
  account: "agentrt",
  auth_method: "api-key",
  login: "host/agent-runtime/control",
  service_id: "",
  app_id: "",
  ca_bundle: "",
  credential_secret_name: "conjur-host",
  credential_secret_key: "api_key",
  tls_cert_key: "",
  tls_key_key: "",
  credential_namespace: "",
  enabled: true,
};

export function SecretProviders() {
  const [rows, setRows] = useState<Provider[] | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState<typeof EMPTY | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Provider | null>(null);
  const { run, pending } = useBusy();

  function load() {
    api<Provider[]>("/api/secret-providers").then(setRows).catch((exc: ApiError) => setError(exc.message));
  }
  useEffect(load, []);

  async function save() {
    if (!form) return;
    const payload = {
      name: form.name,
      kind: form.kind,
      base_url: form.base_url,
      account: form.account,
      auth_method: form.auth_method,
      ca_bundle: form.ca_bundle,
      config: { login: form.login, service_id: form.service_id, app_id: form.app_id },
      credential_secret_name: form.credential_secret_name,
      credential_secret_key: form.credential_secret_key,
      tls_cert_key: form.tls_cert_key,
      tls_key_key: form.tls_key_key,
      credential_namespace: form.credential_namespace,
      enabled: form.enabled,
    };
    try {
      if (editing) await api(`/api/secret-providers/${editing}`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("/api/secret-providers", { method: "POST", body: JSON.stringify(payload) });
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
        const result = await api<{ ok: boolean; checked: string }>(`/api/secret-providers/${id}/test`, { method: "POST", body: "{}" });
        notify({
          tone: result.ok ? "success" : "warning",
          title: result.ok ? copy.providerResponded(result.checked) : copy.providerSilent,
        });
      } catch (exc) {
        announceError(exc, copy.providerUnreachable);
      }
    });
  }

  function remove(row: Provider) {
    void run(`delete:${row.id}`, async () => {
      try {
        await api(`/api/secret-providers/${row.id}`, { method: "DELETE" });
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
    { accessorKey: "kind", header: "Kind" },
    { accessorKey: "base_url", header: "Address" },
    { accessorKey: "auth_method", header: "Auth" },
    { id: "cred", header: "Credential Secret", cell: ({ row }) => row.original.credential_secret_name || "—" },
    { id: "on", header: "Status", cell: ({ row }) => row.original.enabled ? <span className="badge ok">On</span> : <span className="badge warn">Off</span> },
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

  function open(row: Provider) {
    setEditing(row.id);
    setForm({
      name: row.name,
      kind: row.kind,
      base_url: row.base_url,
      account: row.account,
      auth_method: row.auth_method,
      login: row.config?.login || "",
      service_id: row.config?.service_id || "",
      app_id: row.config?.app_id || "",
      ca_bundle: row.ca_bundle || "",
      credential_secret_name: row.credential_secret_name,
      credential_secret_key: row.credential_secret_key,
      tls_cert_key: row.tls_cert_key,
      tls_key_key: row.tls_key_key,
      credential_namespace: row.credential_namespace,
      enabled: row.enabled,
    });
  }

  if (error) return <div className="card">{error}</div>;
  if (!rows) return <SkeletonRows />;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Vaults</p>
          <h1>Secret sources</h1>
          <p>Conjur and CyberArk CCP addresses live here. API keys and client certificates are not stored in plaintext. The control plane reads them from a Kubernetes Secret in its own namespace.</p>
        </div>
        <button className="btn" type="button" onClick={() => { setEditing(null); setForm(EMPTY); }}>New source</button>
      </div>
      <section className="card">
        {rows.length === 0 ? <Empty title="No sources" body="Add a Conjur or CCP record. The OpenBao/Vault kind is reserved and does not read secrets yet." action={<button className="btn" type="button" onClick={() => { setEditing(null); setForm(EMPTY); }}>New source</button>} /> : <DataTable data={rows} columns={columns} />}
      </section>
      {form && (
        <Modal title={editing ? "Edit source" : "New secret source"} onClose={() => setForm(null)}>
          <div className="grid-2">
            <label className="field">Name<input value={form.name} disabled={Boolean(editing)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label className="field">Kind
              <Select
                ariaLabel="Kind"
                value={form.kind}
                onChange={(kind) => setForm({ ...form, kind, auth_method: kind === "ccp" ? "mtls" : kind === "conjur" ? "api-key" : "token" })}
                options={[
                  { value: "conjur", label: "CyberArk Conjur", description: "Variable path" },
                  { value: "ccp", label: "CyberArk CCP", description: "Safe and object" },
                  { value: "vault", label: "OpenBao / Vault", description: "Reserved; does not read secrets yet" },
                ]}
              />
            </label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>Address<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} /></label>
            <label className="field">Auth method
              <Select
                ariaLabel="Auth method"
                value={form.auth_method}
                onChange={(auth_method) => setForm({ ...form, auth_method })}
                options={form.kind === "ccp"
                  ? [
                    { value: "mtls", label: "Client certificate (mTLS)", description: "Certificate from the provider Secret" },
                    { value: "allowed-machines", label: "Allowed machines" },
                  ]
                  : [
                    { value: "api-key", label: "API key", description: "Proof-of-concept path" },
                    { value: "authn-k8s", label: "authn-k8s", description: "Service account" },
                    { value: "authn-jwt", label: "authn-jwt", description: "Service account" },
                    { value: "token", label: "token" },
                  ]}
              />
            </label>
            <label className="field">Account<input value={form.account} placeholder="Conjur account" onChange={(event) => setForm({ ...form, account: event.target.value })} /></label>
            <label className="field">Host login<input autoComplete="off" placeholder="host/agent-runtime/control" value={form.login} onChange={(event) => setForm({ ...form, login: event.target.value })} /></label>
            <label className="field">Authenticator<input autoComplete="off" placeholder="authn-k8s service id" value={form.service_id} onChange={(event) => setForm({ ...form, service_id: event.target.value })} /></label>
            <label className="field">Default AppID<input autoComplete="off" value={form.app_id} onChange={(event) => setForm({ ...form, app_id: event.target.value })} /></label>
            <label className="field">Secret name<input autoComplete="off" value={form.credential_secret_name} onChange={(event) => setForm({ ...form, credential_secret_name: event.target.value })} /></label>
            <label className="field">Secret key<input autoComplete="off" placeholder="api_key" value={form.credential_secret_key} onChange={(event) => setForm({ ...form, credential_secret_key: event.target.value })} /></label>
            <label className="field">Certificate key<input autoComplete="off" placeholder="tls.crt" value={form.tls_cert_key} onChange={(event) => setForm({ ...form, tls_cert_key: event.target.value })} /></label>
            <label className="field">Private key name<input autoComplete="off" placeholder="tls.key" value={form.tls_key_key} onChange={(event) => setForm({ ...form, tls_key_key: event.target.value })} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>CA bundle
              <textarea rows={4} value={form.ca_bundle} placeholder="Public CA only. Do not paste a private key." onChange={(event) => setForm({ ...form, ca_bundle: event.target.value })} />
            </label>
            <label className="field"><span>Enabled</span><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /></label>
          </div>
          <p>API keys and client certificates are not entered on this form. The control plane reads the Secret from its own namespace. authn-k8s and authn-jwt are used when the service-account token file is mounted. The proof-of-concept path is an API key. An OpenBao/Vault record does not return a secret.</p>
          <div className="row" style={{ marginTop: 12 }}>
            <ActionButton busy={pending("save")} onClick={() => void run("save", save)}>{copy.save}</ActionButton>
            <button className="btn-ghost" type="button" onClick={() => setForm(null)}>{copy.cancel}</button>
          </div>
        </Modal>
      )}
      {pendingDelete && (
        <ConfirmDialog
          title={copy.confirmDeleteTitle}
          body={copy.confirmDeleteSecret(pendingDelete.name)}
          busy={pending(`delete:${pendingDelete.id}`)}
          onConfirm={() => remove(pendingDelete)}
          onClose={() => setPendingDelete(null)}
        />
      )}
    </>
  );
}
