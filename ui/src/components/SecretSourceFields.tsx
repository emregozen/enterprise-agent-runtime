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
      <label className="field">Secret backend
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
          <label className="field">What the reference holds
            <select value={value.secret_form || "password"} onChange={(event) => onChange({ ...value, secret_form: event.target.value })}>
              <option value="password">Password</option>
              <option value="url">Full connection URL</option>
            </select>
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>
            {value.secret_form === "url"
              ? "The variable or Secret is the full connection string. Host and user may stay empty."
              : "Host, port, database, and user stay on this form. The reference is only the password."}
          </p>
        </>
      )}
      {value.secret_backend === "kubernetes" && (
        <>
          <label className="field">Secret name
            <input autoComplete="off" value={value.k8s_secret_name} onChange={(event) => onChange({ ...value, k8s_secret_name: event.target.value })} />
          </label>
          <label className="field">Secret key
            <input autoComplete="off" placeholder={k8sKeyHint} value={value.k8s_secret_key} onChange={(event) => onChange({ ...value, k8s_secret_key: event.target.value })} />
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>The value is not typed here. In password form the control plane reads the Secret and builds the URL. In full-URL form the run pod reads it with secretKeyRef.</p>
        </>
      )}
      {value.secret_backend === "conjur" && (
        <>
          <label className="field">Conjur source
            <select value={value.secret_provider_id} onChange={(event) => onChange({ ...value, secret_provider_id: event.target.value })}>
              <option value="">Select</option>
              {choices.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <label className="field">Variable path
            <input autoComplete="off" placeholder="agent-runtime/postgres-sales/password" value={value.secret_path} onChange={(event) => onChange({ ...value, secret_path: event.target.value })} />
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>Only this path is stored. The value is read from Conjur when a run starts.</p>
        </>
      )}
      {value.secret_backend === "ccp" && (
        <>
          <label className="field">CCP source
            <select value={value.secret_provider_id} onChange={(event) => onChange({ ...value, secret_provider_id: event.target.value })}>
              <option value="">Select</option>
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
            <input autoComplete="off" placeholder="Leave empty to use Safe and Object" value={value.ccp_query} onChange={(event) => onChange({ ...value, ccp_query: event.target.value })} />
          </label>
          <p className="field" style={{ gridColumn: "1 / -1" }}>CCP returns the vault value. In password form that value is the password. In full-URL form it is the connection string. The client certificate stays in the provider's Kubernetes Secret.</p>
        </>
      )}
    </>
  );
}
