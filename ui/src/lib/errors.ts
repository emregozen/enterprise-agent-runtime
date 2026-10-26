/**
 * English presentation for control-plane messages.
 * The API still speaks Turkish for operators and tests. The UI is English-only.
 * A future locale can replace this map; `en` is the only shipped language.
 */

const EXACT: Record<string, string> = {
  "ajan yok": "Agent not found",
  "koşum yok": "Run not found",
  "run token gerekli": "A run token is required",
  "run token geçersiz": "The run token is invalid",
  "bu ada sahip bir veri kaynağı var": "A data source with this name already exists",
  "veri kaynağı yok": "Data source not found",
  "yayınlanmış zamanlama yok": "There is no published schedule",
  "artefakt yok": "Artifact not found",
  "artefakt dosyası yok": "Artifact file not found",
  "Content-Length sayı olmalı": "Content-Length must be a number",
  "at ISO zaman olmalı": "The time must be an ISO timestamp",
  "at zaman dilimi içermeli": "The time must include a timezone",
  "bu ada sahip bir model var": "A model with this name already exists",
  "model yok": "Model not found",
  "bu ada sahip bir gizli bilgi kaynağı var": "A secret source with this name already exists",
  "gizli bilgi kaynağı yok": "Secret source not found",
  "bu kaynak bir veri kaynağı veya model tarafından kullanılıyor": "This source is used by a data source or a model",
  "silinmiş ajan düzenlenemez": "A deleted agent cannot be edited",
  "silinmiş ajan çalıştırılamaz": "A deleted agent cannot be run",
  "dialect postgres, oracle veya ansi olmalı": "Dialect must be postgres, oracle, or ansi",
  "sensitivity internal veya restricted olmalı": "Sensitivity must be internal or restricted",
  "en az bir tablo gerekli": "At least one table is required",
  "parola kaynağı platform, kubernetes, conjur veya ccp olmalı": "The secret backend must be platform, kubernetes, conjur, or ccp",
  "Kubernetes Secret adı gerekli": "A Kubernetes Secret name is required",
  "Conjur değişken yolu gerekli": "A Conjur variable path is required",
  "CCP AppID gerekli": "A CCP AppID is required",
  "CCP Object veya Query gerekli": "A CCP Object or Query is required",
  "gizli bilgi kaynağı seçilmedi": "No secret source is selected",
  "seçilen kaynak bu parola türü ile uyuşmuyor": "The selected source does not match this secret type",
  "gizli bilgi kaynağı kapalı": "The secret source is disabled",
  "bağlantı bilgisi yok": "Connection details are missing",
  "biçim parola ya da tam adres olmalı": "The form must be password or full URL",
  "parola biçiminde sunucu ve kullanıcı gerekli": "Password form requires a host and a username",
  "parola biçiminde sunucu ve kullanıcı gerekli. Tam bağlantı adresi kasadaysa biçimi tam adres yapın.":
    "Password form requires a host and a username. If the vault holds the full URL, choose the full URL form.",
  "bu tür için deneme bağlantısı yok": "There is no connection test for this type",
  "sürüm yok": "Version not found",
  "kopyalanacak spec yok": "There is no spec to copy",
  "yalnızca bekleyen veya çalışan koşum iptal edilir": "Only a pending or running run can be cancelled",
  "en az 1 gün": "At least 1 day is required",
  "silinecek durum seçilmedi": "Choose at least one status to delete",
  "API anahtarı yok": "API key is missing",
  "tür conjur, ccp veya vault olmalı": "Kind must be conjur, ccp, or vault",
  "özel anahtar CA alanına yazılmaz; Kubernetes Secret kullanın": "Do not paste a private key into the CA field. Use a Kubernetes Secret.",
  "sağlayıcı sırrı kayda yazılmaz; Kubernetes Secret kullanın": "Provider secrets are not stored on the record. Use a Kubernetes Secret.",
  "Conjur kimliği api-key, authn-k8s veya authn-jwt olmalı": "Conjur auth must be api-key, authn-k8s, or authn-jwt",
  "Conjur hesap adı gerekli": "A Conjur account name is required",
  "Conjur host kimliği (login) gerekli": "A Conjur host login is required",
  "Conjur API anahtarı için Kubernetes Secret adı gerekli": "A Kubernetes Secret name is required for the Conjur API key",
  "CCP kimliği mtls veya allowed-machines olmalı": "CCP auth must be mtls or allowed-machines",
  "CCP sertifikası için Kubernetes Secret adı gerekli": "A Kubernetes Secret name is required for the CCP certificate",
  "CCP sertifika ve anahtar adları gerekli": "CCP certificate and key names are required",
  "adres gerekli": "An address is required",
  "kısıtlı veri kaynağı yalnızca local model sınıfıyla kullanılır": "A restricted data source can only be used with the local model class",
  "ajan adı üretilemedi": "Could not generate an agent name",
  "ajan henüz yayınlanmadı": "The agent is not published yet",
  "yayınlanacak spec yok": "There is no spec to publish",
  "bu ajanın çalışan bir koşumu var": "This agent already has a running run",
  "günlük koşum limiti doldu": "The daily run limit is reached",
  "bu ajan kendi zamanını kuramaz": "This agent cannot set its own schedule",
  "deneme koşusu zamanlama kuramaz": "A dry run cannot set a schedule",
  "zamanlama reddedildi": "The schedule was rejected",
  "geçersiz koşum durumu": "Invalid run status",
  "artefakt özeti uyuşmuyor": "The artifact checksum does not match",
  "Kubernetes Secret adı veya ad alanı boş": "Kubernetes Secret name or namespace is empty",
  "Kubernetes istemcisi yok; Secret okunamadı": "The Kubernetes client is unavailable, so the Secret could not be read",
  "Kubernetes Secret adı yok": "Kubernetes Secret name is missing",
  "Kubernetes Secret anahtarı yok": "Kubernetes Secret key is missing",
  "Kubernetes Secret okunamadı": "The Kubernetes Secret could not be read",
  "gizli bilgi kaynağı yok veya kapalı": "The secret source is missing or disabled",
  "bilinmeyen gizli bilgi kaynağı türü": "Unknown secret source kind",
  "sağlayıcı boş değer döndürdü": "The provider returned an empty value",
  "Conjur değişken yolu yok": "The Conjur variable path is missing",
  "Conjur hesap adı yok": "The Conjur account name is missing",
  "Conjur host kimliği yok. Sağlayıcı kaydında login yazın (örnek: host/agent-runtime/control).":
    "The Conjur host login is missing. Set login on the provider (for example host/agent-runtime/control).",
  "Conjur API anahtarı boş. Anahtar Kubernetes Secret içinden okunur, düz metin kaydedilmez.":
    "The Conjur API key is empty. It is read from a Kubernetes Secret and is never stored in plaintext.",
  "Conjur kimlik yöntemi api-key, authn-k8s veya authn-jwt olmalı. PoC yolu API anahtarıdır.":
    "Conjur auth must be api-key, authn-k8s, or authn-jwt. The proof-of-concept path is an API key.",
  "Conjur sunucusuna ulaşılamadı. Adres, sertifika ve ağ politikasını kontrol edin.":
    "The Conjur server is unreachable. Check the address, certificate, and network policy.",
  "Conjur kimlik doğrulaması reddedildi. API anahtarı veya host kimliği yanlış.":
    "Conjur authentication was rejected. The API key or host login is wrong.",
  "Conjur token boş döndü": "Conjur returned an empty token",
  "servis hesabı token dosyası boş": "The service-account token file is empty",
  "authn-k8s / authn-jwt için kontrol düzleminin servis hesabı token dosyası yok. PoC API anahtarı kullanır; bu yöntem token dosyası bağlanınca açılır.":
    "The control plane has no service-account token file for authn-k8s / authn-jwt. The proof of concept uses an API key; this method turns on when the token file is mounted.",
  "Conjur API anahtarı Kubernetes Secret içinde yok. Düz metin anahtar kaydedilmez.":
    "The Conjur API key is not in the Kubernetes Secret. A plaintext key is not stored.",
  "CyberArk CCP AppID yok. Sağlayıcıda veya hesap başvurusunda AppID yazın.":
    "The CyberArk CCP AppID is missing. Set it on the provider or on the account reference.",
  "CyberArk CCP için Object veya Query gerekli.": "CyberArk CCP needs an Object or a Query.",
  "CyberArk CCP sunucusuna ulaşılamadı. Adres, istemci sertifikası ve izinli makine listesini kontrol edin.":
    "The CyberArk CCP server is unreachable. Check the address, client certificate, and allowed-machines list.",
  "CyberArk CCP yanıtı okunamadı.": "The CyberArk CCP response could not be read.",
  "CyberArk CCP yanıtı beklenen hesap nesnesi değil.": "The CyberArk CCP response was not an account object.",
  "CyberArk CCP hesap içeriği boş döndü.": "CyberArk CCP returned an empty account value.",
  "CCP istemci sertifikası Kubernetes Secret içinde yok. Sertifika düz metin kaydedilmez.":
    "The CCP client certificate is not in the Kubernetes Secret. Certificates are not stored in plaintext.",
  "CCP kimlik yöntemi mtls veya allowed-machines olmalı.": "CCP auth must be mtls or allowed-machines.",
  "OpenBao ve HashiCorp Vault henüz bağlı değil. Sağlayıcı kaydı durur; KV okuma sonraki sürümde eklenecek.":
    "OpenBao and HashiCorp Vault are not connected yet. The provider record is kept; KV reads come in a later release.",
  "Kubernetes API'ye ulaşılamadı. Kontrol düzlemi küme içinden Secret okuyamıyor.":
    "The Kubernetes API is unreachable. The control plane cannot read Secrets from inside the cluster.",
  "PoC: koşum podları yalnızca DNS, kontrol düzlemi, Postgres ve Helm extraEgress kurallarına çıkar. Ağ politikası DNS adını seçemez. Kurumsal kurulumda EgressFirewall veya bir çıkış vekili kullanın. Örnek: deploy/openshift/egressfirewall.example.yaml.":
    "Proof of concept: run pods may leave only for DNS, the control plane, Postgres, and Helm extraEgress rules. NetworkPolicy cannot select a DNS name. In production use an EgressFirewall or an egress proxy. Example: deploy/openshift/egressfirewall.example.yaml.",
  "istek başarısız": "Request failed",
  "Fark yok.": "No difference.",
};

const PATTERNS: Array<[RegExp, string]> = [
  [/^veri kaynağı yok: (.+)$/, "Data source not found: $1"],
  [/^(.+) için tablo izinli değil: (.+)$/, "Tables are not allowed for $1: $2"],
  [/^koşum başlatılamadı: (.+)$/, "The run could not start: $1"],
  [/^artefakt (\d+) bayt sınırını aşıyor$/, "The artifact exceeds the $1 byte limit"],
  [/^(.+) veri kaynağının adresi tanımlı değil$/, "$1 has no address configured"],
  [/^(.+) veri kaynağına ulaşılamadı\. Kaynak kapalı olabilir veya adres yanıt vermiyor\.$/, "$1 is unreachable. The source may be down, or the address is not responding."],
  [/^taslak üretilemedi: (.+)$/, "Could not draft a spec: $1"],
  [/^(.+) için Kubernetes Secret adı yok$/, "No Kubernetes Secret name for $1"],
  [/^(.+) kontrol düzlemi ortamında yok$/, "$1 is not set in the control-plane environment"],
  [/^bağlantı kurulamadı: (.+)$/, "Could not connect: $1"],
  [/^model yanıt vermedi: (.+)$/, "The model did not respond: $1"],
  [/^Kubernetes Secret bulunamadı: (.+)$/, "Kubernetes Secret not found: $1"],
  [/^Kubernetes Secret (.+) içinde '(.+)' anahtarı yok$/, "Kubernetes Secret $1 has no key '$2'"],
  [/^Kubernetes Secret okunamadı \((.+)\). Kontrol düzleminin bu ad alanındaki Secret'ları görme yetkisi olmayabilir\.$/, "Could not read the Kubernetes Secret ($1). The control plane may not be allowed to view Secrets in that namespace."],
  [/^Kubernetes Secret anahtarı metin değil: (.+)$/, "Kubernetes Secret key is not text: $1"],
  [/^Conjur değişkeni bulunamadı: (.+)$/, "Conjur variable not found: $1"],
  [/^Conjur değişkeni okunamadı \(HTTP (\d+)\)\. Host'un bu değişkeni okuma izni olmayabilir\.$/, "Could not read the Conjur variable (HTTP $1). The host may not be allowed to read it."],
  [/^Conjur kimlik doğrulaması başarısız \(HTTP (\d+)\)\.$/, "Conjur authentication failed (HTTP $1)."],
  [/^CyberArk CCP isteği reddedildi \(HTTP (\d+)\)\. AppID, Safe veya istemci sertifikası kabul edilmedi\.$/, "CyberArk CCP rejected the request (HTTP $1). The AppID, Safe, or client certificate was not accepted."],
];

export function presentText(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (!text) return "";
  if (EXACT[text]) return EXACT[text];
  for (const [pattern, replacement] of PATTERNS) {
    if (pattern.test(text)) return text.replace(pattern, replacement);
  }
  return text;
}
