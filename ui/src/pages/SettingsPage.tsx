import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";

type Settings = {
  llm_mode: string;
  artifact_store: string;
  run_backend: string;
  encryption_configured: boolean;
  egress: { mode: string; note: string };
};

export function SettingsPage() {
  const [data, setData] = useState<Settings | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Settings>("/api/settings").then(setData).catch((exc: ApiError) => setError(exc.message));
  }, []);
  if (error) return <div className="card">{error}</div>;
  if (!data) return <div className="card">Yükleniyor…</div>;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ayarlar</h1>
          <p>Kaynaklar ve modeller arayüzden gelir. Ortam değişkenleri yalnızca ilk kurulum tohumudur.</p>
        </div>
      </div>
      <section className="grid-3">
        <article className="card kpi"><div className="label">Model kipi</div><div className="value">{data.llm_mode}</div></article>
        <article className="card kpi"><div className="label">Artefakt</div><div className="value">{data.artifact_store}</div></article>
        <article className="card kpi"><div className="label">Şifreleme</div><div className="value">{data.encryption_configured ? "Anahtar var" : "Geliştirme"}</div></article>
      </section>
      <section className="card">
        <h2>Çıkış ağı</h2>
        <p>{data.egress.note}</p>
        <p>Koşum podu herkese açık değildir. Helm <code>networkPolicy.extraEgress</code> dışında yeni bir adres eklenmez. Özel aralıklar <code>except</code> ile dışarıda bırakılabilir. Üretimde DNS adına göre EgressFirewall veya bir çıkış vekili kullanın.</p>
      </section>
      <section className="card">
        <h2>Gizliler</h2>
        <p>Üç parola kaynağı vardır. Platform DB değeri Fernet ile saklar; anahtar <code>agent-runtime-master-key</code> Secret'ındadır. Kubernetes Secret başvurusu koşum poduna bağlanır. Conjur ve CCP başvurusunda veritabanında yalnızca yol durur; kontrol düzlemi değeri koşum başlarken okur ve o koşumun Secret'ına koyar. Sağlayıcı kimliği de düz metin değildir, kontrol düzleminin ad alanındaki bir Secret'tan gelir. Ayrıntı <Link to="/secrets">Gizli Bilgi Kaynakları</Link> sayfasındadır. API bu değerleri geri vermez. Koşum Secret'ı Job ile silinir. Kod kabı sır almaz.</p>
      </section>
    </>
  );
}
