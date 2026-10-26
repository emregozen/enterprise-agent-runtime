# Ajan Çalıştırıcı

Kurum içi ajanları doğal dille tarif edip sürümlü bir **AgentSpec** olarak saklayan ve her koşumu ayrı bir Kubernetes / OpenShift `batch/v1` Job’unda çalıştıran açık kaynak bir kanıttır. Ücretli ürün yoktur. OpenShift AI yoktur. Model çağrıları yalnızca OpenAI uyumlu bir HTTP API’ye gider.

Kimlik doğrulama, SSO ve çoklu kiracı bu turda yoktur.

## Ne değişti

Ajan, veri kaynağı ve model artık arayüzden yönetilir. Postgres veya Oracle bağlantısı, OpenAI uyumlu model adresi ve API anahtarı ekrandan yazılır; parola ve anahtar veritabanında şifreli durur, API bunları geri vermez. Ortam değişkeni ve Helm `llm.existingSecret` yalnızca ilk açılışta bir model tohumlar. Asıl kayıt veritabanındadır.

Ajan düzenlenince yeni bir sürüm oluşur. Eski sürümle farkı görülebilir. Ajan durdurulabilir, kopyalanabilir veya gizlenerek silinebilir; geçmiş koşumlar kalır. Koşum iptal, yeniden çalıştırma ve silme (artefaktıyla birlikte) arayüzdedir. İptal edilen ve hiç başlamadan düşen koşum günlük kotaya yazılmaz.

Rapor tablosundaki sapma yüzdeleri aynı biçimde yazılır (`0,00%` ve `300,00%`). Model çağrısı gecikme ve jeton sayısını günlüğe yazar. Akıl yürütme (`reasoning_effort`) isteğe bağlıdır ve varsayılan kapalıdır.

Arayüz sol menülü bir yönetim konsoludur. Açık ve koyu tema vardır. Yazı tipleri ve betikler imajın içindedir; çalışma anında dış ağdan font veya betik çekilmez. UI kabı statik dosyayı küçük bir Node süreciyle sunar.

Çıkış ağı sessizce açılmaz. Koşum podu DNS, kontrol düzlemi, Postgres ve chart’taki `extraEgress` listesi dışında çıkamaz. Ağ politikası DNS adı seçemediği için DeepSeek denemesinde `0.0.0.0/0:443` kullanılır ve özel aralıklar `except` ile kesilir. Kurumsal kurulumda bunun yerine EgressFirewall veya bir çıkış vekili gerekir.

## Ne yapar

1. Çalışan, veri kaynağını ve cümleyi seçer. Builder, şemayı okuyup bir AgentSpec taslağı üretir. Ham satır modele gitmez.
2. Taslak yayınlanır. Sürüm ve zamanlama Postgres’te durur.
3. Zamanlayıcı cron’u (`Europe/Istanbul`) ya da ajanın `schedule_next_run` isteğini politika sınırında işletir.
4. Her koşum bir Job’dur. Job bitince `ttlSecondsAfterFinished` ile silinir. Süre `activeDeadlineSeconds` ile sınırlıdır.
5. Podda iki kap vardır. Harness sırları taşır. Executor taşımaz; üretilen Python’u `python -I` ile çalıştırır.
6. Büyük okuma önce SQL’de toplanır. Gerekirse Arrow parçaları Parquet olur, DuckDB / Polars podun içinde hesaplar. Sayılar ayrı bir SQL ile karşılaştırılır. Tutmazsa koşum `needs_review` olur.
7. E-posta ve SMS, kontrol düzlemindeki araç vekilinden gider. Jeton poda konmaz. Adres boşsa çağrı taklit edilir ve denetlenir.

## Yerleşim

```
control_plane/     FastAPI, kayıt, zamanlayıcı, Job üretimi, araç vekili
harness/           plan, SQL, parquet, rapor
executor/          gizli bilgisiz kod yürütücü
sqlguard/          tek SELECT, izinli tablo, agrega veya LIMIT
datasources/       Postgres, Oracle, genel SQLAlchemy
shared/            AgentSpec, sahte LLM, OpenAI uyumlu istemci
ui/                Next.js arayüz
scripts/           satış verisi
deploy/helm/       OpenShift / CRC chart
deploy/openshift/  EgressFirewall örneği (chart uygulamaz)
tests/             birim ve uçtan uca
evals/             sahte builder kontrolü
docs/adr/          sapma gerekçeleri
```

## Mimari

```
tarayıcı → UI :8842 → kontrol düzlemi :8841 → Postgres
                              │
                              ├─ zamanlayıcı (advisory lock)
                              ├─ araç vekili (e-posta, SMS, genel HTTP)
                              └─ Kubernetes API
                                    │
                                    ▼
                         Job (her koşumda yeni)
                         ├─ harness  (RUN_TOKEN, DSN, LLM)
                         └─ executor (sır yok, 127.0.0.1:7070)
                              paylaşılan emptyDir /work
                              artefakt PVC'si yok
```

Run podu restricted-v2 ile uyumludur: kök değil, `runAsUser` yok (platform UID verir), yetki yükseltme yok, kök dosya sistemi salt okunur, tüm yetkiler düşürülür, `automountServiceAccountToken: false`, `enableServiceLinks: false`. NetworkPolicy çıkışı DNS, kontrol düzlemi ve Postgres ile sınırlar. LLM ve dış veritabanı için `networkPolicy.extraEgress` doldurulur. Artefakt yüklemesi bu listenin içindeki kontrol düzlemi çıkışını (`:8841`) kullanır. Yeni bir kapı açılmaz.

## Neden bu bileşenler?

Satış tablosu on milyon satıra çıkabilir. Modele bu tablonun ham hali gitmez; modele yalnızca hesaplanmış kısa özet gider.

Önce soru veritabanına sorulur: dünün tutarı bölge bölge nedir? Postgres indeksi sekiz günlük pencereyi onlarca satıra indirir. Toplama verinin yanında biter. Buna SQL pushdown denir. On milyon satırlık denemede tam tablo toplamı 735 ms, günlük pencere 0,2 ms sürdü.

Kodun kendisi hesaplayacaksa satırlar parça parça okunur ve Parquet dosyasına yazılır. Parquet sayıları sütun sütun tutar, bu yüzden aynı veri Python listesinde olduğundan çok daha az yer kaplar. On milyon satır yaklaşık 116 MB dosya oldu. Okuyan sürecin tepe belleği 114 MB idi. Parça boyu 10 000 satırdır; 2 000 ve 50 000 de denendi, 10 000 daha hızlı kaldı.

DuckDB bu dosyanın üstünde, koşum podunun içinde çalışır. Ayrı bir hesap sunucusu kurulmaz. Pod, toplamı bir de SQL ile sayar. İki sonuç uyuşursa rapora güvenilir. Uyuşmazsa koşum `needs_review` olur ve e-posta gitmez.

Pod raporu geçici `/work` alanında üretir ve koşum jetonuyla kontrol düzlemine akıtır. Düzlem boyutu sınırlar ve kalıcı kopyayı kendi diskine yazar. OpenShift’te bu disk bir PersistentVolume’dur. Yalnızca kontrol düzlemi podu onu görür. `ReadWriteOnce` olduğu için kontrol düzlemi tek replika kalır. Birden fazla replika gerekiyorsa `ARTIFACT_STORE=s3` seçilir.

SeaweedFS, S3 yolunu bu makinede denemek için kurulan yerel bir deneme tezgahıdır. Kurumun nesne deposu ayrıdır. İlk fazın varsayılanı PVC’dir.

## Sapmalar

Referans yerleşime göre bilinçli farklar `docs/adr/` altındadır.

| Konu | Bu PoC |
| --- | --- |
| Orkestrasyon | LangGraph yok. Yalın döngü. |
| İz | Langfuse yok. JSON günlük, OTLP uç noktası, Postgres denetim kaydı. |
| Model ağ geçidi | LiteLLM süreci yok. İstemci `base_url` / `model` / `api_key` kullanır. `LLM_MODEL_CLASSES` sınıf adını eşler. |
| Çekme | ADBC ve ConnectorX yok. psycopg sunucu imleci, Oracle `fetch_df_batches`, diğerleri SQLAlchemy. |
| Grafik | matplotlib yok. Rapor SVG’si standart kütüphane. |
| İmaj | Varsayılan taban `python:3.12-slim`. İç ayna için imajı yeniden etiketleyin. `BASE_IMAGE` ile kök yetkili bir Python 3.12 tabanı verilebilir. UBI9 python-312 sanal ortam beklediği için varsayılan değildir. |
| Artefakt | Kalıcı kopya kontrol düzleminin PVC’sindedir. Pod dosyayı iç API’ye akıtır. S3 seçenek olarak durur. |
| Yerel Kubernetes | Docker ve kind bu ortamda yok. Yerel arka uç iki süreçtir. Job belgesi sahte API ile test edilir. |
| Kaynak isteği | Referanstaki 1 CPU / 2Gi yerine kap başına 500m / 1Gi. OpenShift Local’da iki kap sığsın diye. Spec JSON’dan yükseltilir. |
| Şema | Açılışta `create_all` ve denetim tetikleyicisi. Ayrı bir Alembic revizyonu üretilmedi. |

## Yerel çalıştırma

Python 3.12, Node 22 ve Postgres 16 gerekir. Bu depoda sanal ortam `.venv` içindedir.

```bash
sudo pg_ctlcluster 16 main start
sudo -u postgres psql -c "CREATE USER agentrt WITH SUPERUSER PASSWORD 'agentrt';" || true
sudo -u postgres psql -c "CREATE DATABASE agentrt OWNER agentrt;" || true

cd /yol/agent-runtime
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env

chmod +x scripts/local-up.sh
SEED_SALES_ROWS=20000 scripts/local-up.sh

set -a && source .env && set +a
.venv/bin/python -m control_plane
```

İkinci uçbirimde:

```bash
cd ui
npm ci
CONTROL_PLANE_URL=http://127.0.0.1:8841 npm run dev
```

Arayüz [http://127.0.0.1:8842](http://127.0.0.1:8842), API [http://127.0.0.1:8841/docs](http://127.0.0.1:8841/docs).

`LLM_MODE=fake` iken model ağa çıkmaz. Gerçek model için:

```bash
LLM_MODE=openai
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5-coder:7b
```

Kısıtlı veri (`sensitivity: restricted`) `cloud-` ile başlayan model sınıfına gidemez; koşum `needs_review` olur.

### Docker Compose

Docker varsa kontrol düzlemi, arayüz ve Postgres birlikte kalkar. Postgres konteyner içinde 5432, makinede **54329** portudur.

```bash
docker compose up --build
```

İsteğe bağlı profiller:

```bash
docker compose --profile oracle up    # gvenzl/oracle-free, büyük imaj
docker compose --profile s3 up        # SeaweedFS, S3 API makinede 8833
```

Oracle DSN örneği: `oracle://system:oracle@127.0.0.1:1521/FREEPDB1`. Kaynak `dialect: oracle` ile kaydedilir. Oracle sürücüsü ince moddadır; anlık istemci gerekmez. Bu imaj burada çekilmedi.

Varsayılan artefakt deposu `ARTIFACT_STORE=pvc`dir. Yerelde bu, `ARTIFACT_DIR` klasörüdür (bu makinede `var/artifacts`). OpenShift’te aynı yol kontrol düzleminin PVC’sine bağlanır (`/var/artifacts`).

S3 denemesi için `ARTIFACT_STORE=s3` ve `S3_ENDPOINT_URL=http://seaweedfs:8333`. Docker olmadan aynı yol, Apache-2.0 SeaweedFS 3.80 ikili dosyasıyla `127.0.0.1:8833` üzerinde denendi. Anahtar `agentrt` / `agentrt-secret`. `tests/test_s3_artifacts.py` nesneyi yazıp geri okur. Sunucu yoksa test atlanır. SeaweedFS, S3 seçeneğinin yerel provasıdır.

## Örnek satış verisi

Yapısal çekirdek, her bölge için dün ve önceki yedi günü doldurur. Doğu Anadolu’nun dünkü tutarı dört katıdır; sapma bu yüzden durur. Ek satırlar sekiz günlük pencerenin dışına yazılır.

```bash
.venv/bin/python scripts/generate_sales.py \
  --database-url postgresql://agentrt:agentrt@127.0.0.1:5432/sales \
  --rows 20000 --grant-read-only
```

On milyon satır aynı komutla `--rows 10000000`. Yükleme `COPY` kullanır. Koşum kullanıcısı `sales_ro` olur ve `default_transaction_read_only` alır. Kontrol düzlemi `SALES_DATABASE_URL` ile bu kullanıcıyı görür. Yönetici adresi `SALES_ADMIN_URL` yalnızca yükleme içindir ve Job’a konmaz.

Bu makinede 10 milyon satır 42 saniyede yüklendi. Tablo yaklaşık 1,1 GB. Ayrıntılı süreler `docs/benchmarks/10m.md` dosyasındadır. Özet:

| Yol | Sonuç |
| --- | --- |
| Tam tablo `SUM` / `GROUP BY` | 735 ms, plan düğümü Aggregate |
| Günlük pencere (indeks) | 0,2 ms, 56 satır |
| 10 milyon satırın Parquet’e alınması | 13,9 s, 116 MB dosya, okuyucu tepe belleği 114 MB, parti boyu 10 000 |
| Executor içinde DuckDB | 0,24 s, tepe bellek 81 MB, SQL toplamıyla uyumlu (10 000 000 satır) |
| Seed `gunluk-satis-ozeti` | 0,76 s, durum succeeded, toplam 10.160,00, tek sapma Doğu Anadolu, executor tepe belleği 107 MB |

300 bin satırda 2 000, 10 000 ve 50 000’lik partiler denendi. 10 000 en hızlısıydı ve 50 000’den daha az bellek kullandı. Varsayılan `ARROW_BATCH_ROWS` bu yüzden 10 000 kaldı.

## Test

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python evals/check_fake_builder.py
```

Uçtan uca test, örnek ajanı iki yerel süreç olarak API’ye karşı çalıştırır. Kubernetes testi `create_from_dict` işlevini değiştirir; Secret ve Job belgesini, executor ortamında sır olmadığını ve `backoffLimit: 0` olduğunu doğrular. Kind veya gerçek bir küme bu makinede yoktur.

## OpenShift Local

Yarınki doğrulama adımları ve beklenen çıktılar `OPENSHIFT-LOCAL-CHECKLIST.md` dosyasındadır. Kurulum `kubeadmin` ile yapılır. Geliştirici kullanıcısı ad alanları arasında RoleBinding yazamayabilir.

```bash
crc start
eval "$(crc oc-env)"
eval "$(crc podman-env)"
oc login -u kubeadmin https://api.crc.testing:6443
# parola: crc console --credentials

oc patch configs.imageregistry.operator.openshift.io/cluster \
  --type merge -p '{"spec":{"defaultRoute":true}}'
HOST="$(oc get route default-route -n openshift-image-registry --template='{{ .spec.host }}')"
podman login --tls-verify=false -u kubeadmin -p "$(oc whoami -t)" "$HOST"

podman build -f deploy/docker/Dockerfile.runtime -t agent-runtime-py312:0.2.0 .
podman tag agent-runtime-py312:0.2.0 "$HOST/agent-runtime/agent-runtime-py312:0.2.0"
podman push --tls-verify=false "$HOST/agent-runtime/agent-runtime-py312:0.2.0"

podman build -f ui/Dockerfile -t agent-runtime-ui:0.2.0 \
  --build-arg CONTROL_PLANE_URL=http://control-plane.agent-runtime.svc:8841 ui
podman tag agent-runtime-ui:0.2.0 "$HOST/agent-runtime/agent-runtime-ui:0.2.0"
podman push --tls-verify=false "$HOST/agent-runtime/agent-runtime-ui:0.2.0"

helm upgrade --install agent-runtime deploy/helm/agent-runtime \
  --namespace agent-runtime --create-namespace \
  -f deploy/helm/agent-runtime/values-crc.yaml
```

`podman` yoksa imajları kümede derleyin. Adım adım komutlar `OPENSHIFT-LOCAL-CHECKLIST.md` bölüm 3’tedir (`oc new-build --binary`, `oc start-build --from-dir`).

Dar bir CRC sanal makinesinde aynı kuruluma `values-crc-small.yaml` eklenir. İstekler düşer; koşumun geçici disk isteği 1Gi kalır.

```bash
helm upgrade --install agent-runtime deploy/helm/agent-runtime \
  --namespace agent-runtime --create-namespace \
  -f deploy/helm/agent-runtime/values-crc.yaml \
  -f deploy/helm/agent-runtime/values-crc-small.yaml

oc get route agent-runtime -n agent-runtime
oc get pods -n agent-runtime
oc get pods -n agent-runs
```

`--create-namespace` yayın ad alanı `agent-runtime`i açar. Chart bu ad alanını bir daha yazmaz; yazsaydı Helm sahiplik yüzünden kurulumu durdururdu. Eski chart (`6adb025`) ad alanını release’e koyuyordu. O kurulumdan yükseltmeden önce `oc annotate ns agent-runtime helm.sh/resource-policy=keep --overwrite` gerekir; yoksa `helm upgrade` ad alanını ve içindeki Secret, derleme ve release kaydını siler. Toparlama adımları `OPENSHIFT-LOCAL-CHECKLIST.md` bölüm 0’dadır. Chart yalnızca koşum ad alanı `agent-runs`i açar. Kontrol düzlemi Job ve Secret’ı oraya koyar. Postgres adresi `postgres.agent-runtime.svc.cluster.local` olur, böylece koşum ad alanından da çözülür. `ARTIFACT_STORE=pvc` iken kontrol düzlemi `Recreate` ile kalkar. Run podunun imajı çekebilmesi için `agent-runs` hizmet hesabına `system:image-puller` bağlanır (`grantImagePuller`).

LLM kümenin dışındaysa çıkış kapalıdır. `values-crc.yaml` içine ekleyip yeniden kurun:

```yaml
networkPolicy:
  extraEgress:
    - name: llm
      cidr: 10.20.0.0/24
      port: 443
    - name: oracle
      cidr: 10.20.1.0/24
      port: 1521
```

Küme dışına ikinci bir kapı olarak `deploy/openshift/egressfirewall.example.yaml` durur. Chart onu uygulamaz. CIDR’leri değiştirmeden uygulamayın.

Gerçek modele geçmek için:

```bash
helm upgrade agent-runtime deploy/helm/agent-runtime \
  --namespace agent-runtime \
  -f deploy/helm/agent-runtime/values-crc.yaml \
  --set llm.mode=openai \
  --set llm.baseUrl=http://llm-gateway.internal:8000/v1 \
  --set llm.model=qwen2.5-coder \
  --set llm.apiKey=degistirin
```

İmaj adresi chart’ta `image-registry.openshift-image-registry.svc:5000/agent-runtime` olur. Podlar bu iç adresten çeker. `podman push` dış route’a yapılır.

Satış tablosu açılışta `SEED_SALES_ROWS` kadar yüklenir (varsayılan 20 000). On milyon için `--set seedSalesRows=10000000`. Postgres kabında `readOnlyRootFilesystem` yoktur; SCL imajı veri dizinine yazar. Kontrol düzlemi ve arayüz salt okunur kök ile kalkar. Kontrol düzleminin yazdığı yerler `emptyDir /tmp` ve artefakt PVC’sidir. PVC `ReadWriteOnce`, varsayılan boy 5Gi, depolama sınıfı boşsa kümenin varsayılan sınıfı kullanılır (`artifacts.storageClass`). Yalnızca control-plane Deployment bu diski bağlar. `controlPlane.replicas` 1 kalır. Chart, pvc modunda replikayı 1’in üstüne çıkarırsa kurulumu durdurur. Ölçek için `artifacts.store=s3` ya da ReadWriteMany bir sınıf gerekir.

Eski raporlar `artifacts.retentionDays` (varsayılan 14) sonunda silinir. Zamanlayıcı bunu saatte bir yapar. `0` silmeyi kapatır. `SCHEDULER_ENABLED=false` ise temizlik döngüsü de durur.

Parolalar chart değerlerindeki geliştirme varsayılanlarıdır (`agentrt`, `agentrt-admin`, `sales_ro`). Kurumda değiştirin.

## Bilinen sınırlar

- Kimlik doğrulama yok. Arayüz ve `/api` ağda kim varsa açıktır. İç uçlar koşum jetonu ister.
- Executor ile harness aynı pod ağını paylaşır. Executor’un ortamında DSN ve jeton yoktur; yine de podun ağ arayüzünü görür.
- Oracle sürücüsü ve SQL süzgeci testlidir. Bu makinede 1521 portu kapalı; Oracle Free kurulmadı.
- S3 yolu SeaweedFS 3.80 ile denendi. Bu, PVC varsayılanının yanında duran seçenektir. MinIO’nun güncel ikili dosyası AIStor lisansına geçtiği için kullanılmadı.
- Gerçek bir OpenAI uyumlu modele ağırlık indirilmedi. `tests/test_openai_client.py` yerel bir Chat Completions sunucusuna model adını, bearer jetonunu ve `response_format` geri çekilmesini doğrular. `LLM_MODE=fake` demo varsayılanıdır.
- Gerçek bir kümede Job kalkmadı. Docker, kind ve kubectl bu makinede yok.
- İmajlar burada derlenmedi.
- Denetim kaydı güncellenemez ve silinemez. Başka tablolar normaldir.
- Araç vekili saatte `TOOL_RATE_LIMIT_PER_HOUR` çağrıyı geçerse reddeder. Alıcı listesi `EMAIL_RECIPIENT_ALLOWLIST` dışına çıkamaz.
- `needs_review` ve `dry_run` araç çağırmaz.
- Artefakt üst sınırı `ARTIFACT_MAX_BYTES` (varsayılan 20 MB). Saklama `ARTIFACT_RETENTION_DAYS` (varsayılan 14). PVC tek kontrol düzlemi replikasına bağlanır. Başlamadan düşen koşum (Job 502, `started_at` boş) günlük kotaya yazılmaz. Başlayıp sonra düşen koşum yazılır.
- Pencere aynı gün içindedir (`07:00-20:00`). Geceyi aşan aralık desteklenmez.
