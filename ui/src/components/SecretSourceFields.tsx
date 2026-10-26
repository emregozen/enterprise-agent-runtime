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
  secret_form: string;
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
  secret_form: "password",
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
  secret_form?: string;
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
    secret_form: row.secret_form === "url" ? "url" : "password",
  };
}

export function SecretSourceFields({
  value,
  providers,
  k8sKeyHint,
  showSecretForm = false,
  onChange,
}: {
  value: SecretSource;
  providers: Provider[];
  k8sKeyHint: string;
  showSecretForm?: boolean;
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
      {showSecretForm && value.secret_backend !== "db" && (
        <>
          <label className="field">Başvurunun içeriği
            <select value={value.secret_form || "password"} onChange={(event) => onChange({ ...value, secret_form: event.target.value })}>
              <option value="password">Parola</option>
              <option value="url">Tam bağlantı adresi</option>
            </select>
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>
            {value.secret_form === "url"
              ? "Değişken veya Secret tam bağlantı adresidir. Sunucu ve kullanıcı boş kalabilir."
              : "Sunucu, port, veritabanı ve kullanıcı bu formda kalır. Başvuru yalnız paroladır."}
          </p>
        </>
      )}
      {value.secret_backend === "kubernetes" && (
        <>
          <label className="field">Secret adı
            <input autoComplete="off" value={value.k8s_secret_name} onChange={(event) => onChange({ ...value, k8s_secret_name: event.target.value })} />
          </label>
          <label className="field">Secret anahtarı
            <input autoComplete="off" placeholder={k8sKeyHint} value={value.k8s_secret_key} onChange={(event) => onChange({ ...value, k8s_secret_key: event.target.value })} />
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>Değer yazılmaz. Parola biçiminde kontrol düzlemi Secret'tan parolayı okur ve bağlantı adresini kurar. Tam adres biçiminde koşum Secret'ı secretKeyRef ile okur.</p>
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
          <p className="field" style={{ gridColumn: "1 / -1" }}>Veritabanında yalnızca bu yol durur. Değer koşum başlarken Conjur'dan okunur.</p>
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
          <p className="field" style={{ gridColumn: "1 / -1" }}>CCP kasadaki değeri döndürür. Parola biçiminde bu değer paroladır; tam adres biçiminde bağlantı adresidir. İstemci sertifikası sağlayıcı kaydındaki Kubernetes Secret'tadır, bu forma yazılmaz.</p>
        </>
      )}
    </>
  );
}
