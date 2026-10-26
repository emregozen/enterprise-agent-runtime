type Provider = { id: string; name: string; kind: string; enabled: boolean };

export type SecretSource = {
  secret_backend: string;
  k8s_secret_name: string;
  k8s_secret_key: string;
  secret_provider_id: string;
  secret_path: string;
  ccp_app_id: string;
  ccp_safe: string;
  ccp_object: string;
  ccp_query: string;
};

export const EMPTY_SECRET_SOURCE: SecretSource = {
  secret_backend: "db",
  k8s_secret_name: "",
  k8s_secret_key: "",
  secret_provider_id: "",
  secret_path: "",
  ccp_app_id: "",
  ccp_safe: "",
  ccp_object: "",
  ccp_query: "",
};

const BACKENDS = [
  { id: "db", label: "Platform DB" },
  { id: "kubernetes", label: "Kubernetes Secret" },
  { id: "conjur", label: "CyberArk Conjur" },
  { id: "ccp", label: "CyberArk CCP" },
];

export function secretSourceFromRow(row: {
  secret_backend?: string;
  k8s_secret_name?: string | null;
  k8s_secret_key?: string | null;
  secret_provider_id?: string | null;
  secret_path?: string;
  secret_ref?: { app_id?: string; safe?: string; object?: string; query?: string };
}): SecretSource {
  const ref = row.secret_ref || {};
  return {
    secret_backend: row.secret_backend || "db",
    k8s_secret_name: row.k8s_secret_name || "",
    k8s_secret_key: row.k8s_secret_key || "",
    secret_provider_id: row.secret_provider_id || "",
    secret_path: row.secret_path || "",
    ccp_app_id: ref.app_id || "",
    ccp_safe: ref.safe || "",
    ccp_object: ref.object || "",
    ccp_query: ref.query || "",
  };
}

export function SecretSourceFields({
  value,
  providers,
  k8sKeyHint,
  onChange,
}: {
  value: SecretSource;
  providers: Provider[];
  k8sKeyHint: string;
  onChange: (next: SecretSource) => void;
}) {
  const kind = value.secret_backend === "ccp" ? "ccp" : "conjur";
  const choices = providers.filter((item) => item.kind === kind && item.enabled);
  return (
    <>
      <label className="field">Parola kaynağı
        <select
          value={value.secret_backend}
          onChange={(event) => onChange({ ...value, secret_backend: event.target.value })}
        >
          {BACKENDS.map((item) => (
            <option key={item.id} value={item.id}>{item.label}</option>
          ))}
        </select>
      </label>
      {value.secret_backend === "kubernetes" && (
        <>
          <label className="field">Secret adı
            <input autoComplete="off" value={value.k8s_secret_name} onChange={(event) => onChange({ ...value, k8s_secret_name: event.target.value })} />
          </label>
          <label className="field">Secret anahtarı
            <input autoComplete="off" placeholder={k8sKeyHint} value={value.k8s_secret_key} onChange={(event) => onChange({ ...value, k8s_secret_key: event.target.value })} />
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>Değer yazılmaz. Secret koşum ad alanındadır; deneme bağlantısı onu oradan okur.</p>
        </>
      )}
      {value.secret_backend === "conjur" && (
        <>
          <label className="field">Conjur kaynağı
            <select value={value.secret_provider_id} onChange={(event) => onChange({ ...value, secret_provider_id: event.target.value })}>
              <option value="">Seçin</option>
              {choices.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <label className="field">Değişken yolu
            <input autoComplete="off" placeholder="agent-runtime/postgres-sales/password" value={value.secret_path} onChange={(event) => onChange({ ...value, secret_path: event.target.value })} />
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>Veritabanında yalnızca bu yol durur. Parola, koşum başlarken Conjur'dan okunur.</p>
        </>
      )}
      {value.secret_backend === "ccp" && (
        <>
          <label className="field">CCP kaynağı
            <select value={value.secret_provider_id} onChange={(event) => onChange({ ...value, secret_provider_id: event.target.value })}>
              <option value="">Seçin</option>
              {choices.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <label className="field">AppID
            <input autoComplete="off" value={value.ccp_app_id} onChange={(event) => onChange({ ...value, ccp_app_id: event.target.value })} />
          </label>
          <label className="field">Safe
            <input autoComplete="off" value={value.ccp_safe} onChange={(event) => onChange({ ...value, ccp_safe: event.target.value })} />
          </label>
          <label className="field">Object
            <input autoComplete="off" value={value.ccp_object} onChange={(event) => onChange({ ...value, ccp_object: event.target.value })} />
          </label>
          <label className="field" style={{ gridColumn: "1 / -1" }}>Query
            <input autoComplete="off" placeholder="Boşsa Safe ve Object kullanılır" value={value.ccp_query} onChange={(event) => onChange({ ...value, ccp_query: event.target.value })} />
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>CCP parola döndürür. İstemci sertifikası sağlayıcı kaydındaki Kubernetes Secret'tadır, bu forma yazılmaz.</p>
        </>
      )}
    </>
  );
}
