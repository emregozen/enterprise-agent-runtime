import { type ColumnDef } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { DataTable, Empty, Modal, SkeletonRows } from "../components/ui";
import { api, ApiError } from "../lib/api";

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
  const [toast, setToast] = useState("");

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
      config: {
        login: form.login,
        service_id: form.service_id,
        app_id: form.app_id,
      },
      credential_secret_name: form.credential_secret_name,
      credential_secret_key: form.credential_secret_key || "api_key",
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
      setToast("Kaydedildi");
      load();
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : "kaydedilemedi");
    }
  }

  async function test(id: string) {
    try {
      const result = await api<{ ok: boolean; checked: string }>(`/api/secret-providers/${id}/test`, { method: "POST", body: "{}" });
      setToast(result.ok ? `Sağlayıcı yanıt verdi (${result.checked})` : "Sağlayıcı yanıt vermedi");
    } catch (exc) {
      setToast(exc instanceof ApiError ? exc.message : "sağlayıcıya ulaşılamadı");
    }
  }

  const columns: ColumnDef<Provider>[] = [
    { accessorKey: "name", header: "Ad" },
    { accessorKey: "kind", header: "Tür" },
    { accessorKey: "base_url", header: "Adres" },
    { accessorKey: "auth_method", header: "Kimlik" },
    { id: "cred", header: "Kimlik Secret'ı", cell: ({ row }) => row.original.credential_secret_name || "—" },
    { id: "on", header: "Durum", cell: ({ row }) => row.original.enabled ? <span className="badge ok">Açık</span> : <span className="badge warn">Kapalı</span> },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <span className="row">
          <button className="btn-ghost" type="button" onClick={() => void test(row.original.id)}>Dene</button>
          <button className="btn-ghost" type="button" onClick={() => open(row.original)}>Düzenle</button>
          <button className="btn-danger" type="button" onClick={() => void api(`/api/secret-providers/${row.original.id}`, { method: "DELETE" }).then(() => { setToast("Silindi"); load(); }).catch((exc: ApiError) => setToast(exc.message))}>Sil</button>
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
          <h1>Gizli Bilgi Kaynakları</h1>
          <p>Conjur ve CyberArk CCP adresleri burada durur. API anahtarı ve istemci sertifikası düz metin kaydedilmez; kontrol düzlemi onları kendi ad alanındaki bir Kubernetes Secret'tan okur.</p>
        </div>
        <button className="btn" type="button" onClick={() => { setEditing(null); setForm(EMPTY); }}>Yeni kaynak</button>
      </div>
      <section className="card">
        {rows.length === 0 ? <Empty title="Kaynak yok" body="Bir Conjur veya CCP kaydı ekleyin. OpenBao/Vault türü durur, sır okumaz." /> : <DataTable data={rows} columns={columns} />}
      </section>
      {form && (
        <Modal title={editing ? "Kaynağı düzenle" : "Yeni gizli bilgi kaynağı"} onClose={() => setForm(null)}>
          <div className="grid-2">
            <label className="field">Ad<input value={form.name} disabled={Boolean(editing)} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
            <label className="field">Tür
              <select value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value, auth_method: event.target.value === "ccp" ? "mtls" : event.target.value === "conjur" ? "api-key" : "token" })}>
                <option value="conjur">CyberArk Conjur</option>
                <option value="ccp">CyberArk CCP</option>
                <option value="vault">OpenBao / Vault (henüz yok)</option>
              </select>
            </label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>Adres<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} /></label>
            <label className="field">Kimlik yöntemi
              <select value={form.auth_method} onChange={(event) => setForm({ ...form, auth_method: event.target.value })}>
                {form.kind === "ccp" ? (
                  <>
                    <option value="mtls">İstemci sertifikası (mTLS)</option>
                    <option value="allowed-machines">İzinli makine</option>
                  </>
                ) : (
                  <>
                    <option value="api-key">API anahtarı</option>
                    <option value="authn-k8s">authn-k8s (servis hesabı)</option>
                    <option value="authn-jwt">authn-jwt (servis hesabı)</option>
                    <option value="token">token</option>
                  </>
                )}
              </select>
            </label>
            <label className="field">Hesap<input value={form.account} placeholder="Conjur hesap adı" onChange={(event) => setForm({ ...form, account: event.target.value })} /></label>
            <label className="field">Host kimliği<input autoComplete="off" placeholder="host/agent-runtime/control" value={form.login} onChange={(event) => setForm({ ...form, login: event.target.value })} /></label>
            <label className="field">Kimlik doğrulayıcı<input autoComplete="off" placeholder="authn-k8s servis adı" value={form.service_id} onChange={(event) => setForm({ ...form, service_id: event.target.value })} /></label>
            <label className="field">Varsayılan AppID<input autoComplete="off" value={form.app_id} onChange={(event) => setForm({ ...form, app_id: event.target.value })} /></label>
            <label className="field">Secret adı<input autoComplete="off" value={form.credential_secret_name} onChange={(event) => setForm({ ...form, credential_secret_name: event.target.value })} /></label>
            <label className="field">Secret anahtarı<input autoComplete="off" placeholder="api_key" value={form.credential_secret_key} onChange={(event) => setForm({ ...form, credential_secret_key: event.target.value })} /></label>
            <label className="field">Sertifika anahtarı<input autoComplete="off" placeholder="tls.crt" value={form.tls_cert_key} onChange={(event) => setForm({ ...form, tls_cert_key: event.target.value })} /></label>
            <label className="field">Özel anahtar adı<input autoComplete="off" placeholder="tls.key" value={form.tls_key_key} onChange={(event) => setForm({ ...form, tls_key_key: event.target.value })} /></label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>CA paketi
              <textarea rows={4} value={form.ca_bundle} placeholder="Genel CA. Özel anahtar yazılmaz." onChange={(event) => setForm({ ...form, ca_bundle: event.target.value })} />
            </label>
            <label className="field"><span>Açık</span><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /></label>
          </div>
          <p>API anahtarı ve istemci sertifikası bu forma yazılmaz. Kontrol düzlemi Secret'ı kendi ad alanından okur. authn-k8s ve authn-jwt, servis hesabı token dosyası bağlıysa kullanılır; PoC yolu API anahtarıdır. OpenBao/Vault kaydı sır döndürmez.</p>
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
