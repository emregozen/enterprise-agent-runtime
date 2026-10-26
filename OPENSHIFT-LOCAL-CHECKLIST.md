# OpenShift Local kontrol listesi

Yarın CRC üzerinde kurulumu bu sırayla doğrulayın. Komutlar `kubeadmin` içindir. Her adımın altında beklenen çıktı vardır. Metin birebir aynı olmak zorunda değil; kalın duran parçalar görünmeli.

Ayrıntılı kurulum kök `README.md` içindedir. Bu dosya yalnızca doğrulamadır.

## 0. Kurulu kümeyi yükseltme

`6adb025` chart’ı yayın ad alanı `agent-runtime`i bir Namespace kaynağı olarak release’e yazıyordu. `be4709e` ve sonrası bu kaynağı chart’tan çıkardı; yoksa `helm install --create-namespace` sahiplik yüzünden duruyordu. Chart’tan çıkan kaynak `helm upgrade` sırasında silinir. Bu, ad alanının kendisini siler: Secret’lar, BuildConfig’ler, ImageStream’ler ve Helm release geçmişi birlikte gider. “İmajı deriyip helm upgrade yeter” bu eski kurulum için yanlıştır.

Yükseltmeden önce, ad alanı hâlâ duruyorsa:

```bash
oc annotate ns agent-runtime helm.sh/resource-policy=keep --overwrite
oc get secret agent-runtime-master-key -n agent-runtime -o yaml > /tmp/agent-runtime-master-key.yaml
```

`keep` Helm’in ad alanını silmesini durdurur. Master key yedeği, ad alanı yine de giderse şifreli parolaların okunabilmesi içindir. Secret üzerindeki `helm.sh/resource-policy: keep` Helm uninstall’da Secret’ı bırakır; ad alanı silinirse Kubernetes Secret’ı yine de siler.

Sonra imajları ve chart’ı yükseltin:

```bash
oc get ns agent-runtime >/dev/null 2>&1 || oc new-project agent-runtime
oc get ns agent-runs >/dev/null 2>&1 || oc create namespace agent-runs
# Anahtar dosyası repoda yoktur. DeepSeek anahtarı her iki ad alanında da llm-deepseek / api_key olmalıdır.
# oc -n agent-runtime create secret generic llm-deepseek --from-file=api_key=./api_key
# oc -n agent-runs create secret generic llm-deepseek --from-file=api_key=./api_key
oc start-build agent-runtime-py312 --from-dir=. --follow -n agent-runtime
oc start-build agent-runtime-ui --from-dir=ui --follow -n agent-runtime
helm upgrade --install agent-runtime deploy/helm/agent-runtime \
  --namespace agent-runtime --create-namespace \
  -f deploy/helm/agent-runtime/values-crc.yaml \
  -f deploy/helm/agent-runtime/values-crc-small.yaml \
  -f deploy/helm/agent-runtime/values-crc-deepseek.yaml
# Etiket aynı kaldıysa Helm pod şablonunu değiştirmez ve eski imaj çalışmaya devam eder.
# values-crc imageTriggers açar: derleme ImageStream etiketine yeni bir özet yazınca
# control-plane ve ui kendiliğinden yenilenir. Tetikleyici yoksa derleme adını verin
# veya podları elle çevirin:
# helm upgrade ... --set imageBuildId="$(oc get builds -n agent-runtime -o jsonpath='{.items[-1:].metadata.name}')"
# oc rollout restart deploy/control-plane deploy/ui -n agent-runtime
oc get secret agent-runtime-master-key -n agent-runtime
oc get deploy control-plane -n agent-runtime -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="LLM_K8S_SECRET_NAME")].value}{"\n"}'
```

Ad alanı yükseltmede silindiyse toparlama (CRC’de kullanılan yol):

1. `oc new-project agent-runtime` ile ad alanını yeniden açın. BuildConfig ve ImageStream gittiği için imaj derlemesini yukarıdan tekrarlayın. Master key yedeği varsa `oc apply -f /tmp/agent-runtime-master-key.yaml` ile geri koyun. Yedek yoksa veritabanındaki parolalar ve API anahtarları çözülemez; arayüzden yeniden yazılır.
2. Disk `Retain` kaldıysa PV durur, PVC gitmiştir. PV `Released` ise aynı ada yeni PVC bağlanmadan önce claim silinir: `oc patch pv <pv> --type=json -p '[{"op":"remove","path":"/spec/claimRef"}]'`. Chart’ın PVC adları `postgres-data` ve `artifacts`tır. Aynı adla yeniden oluşunca disk yeniden bağlanır.
3. Postgres verisi eski projenin UID’sine aittir. Yeni projenin UID aralığı farklıdır. restricted-v2 kök init kabına ve `chown` yetkisine izin vermez. `fsGroup` dizini grup yazılır yapar ama Postgres sahip UID’si süreç UID’si değilse açılmaz. Pod kabul edilmeden önce eski aralığı yazın (eski değer `oc get ns` çıktısında veya silindiyse `ls -nd` ile diskteki sahip UID’nin düştüğü aralıktır):

```bash
oc annotate ns agent-runtime openshift.io/sa.scc.uid-range='<eski-aralık>' --overwrite
oc delete pod -n agent-runtime -l app=postgres --force --grace-period=0
```

Aralık, pod içeri alınırken okunur. Çalışan pod eski UID ile kalır; annotation’dan sonra podu silin.

Beklenen: master-key Secret’ı `key` alanını taşır. Son satır `llm-deepseek` olur. Kontrol düzlemi ilk açılışta bu Secret’ı veritabanına bir model olarak tohumlar; anahtarın kendisini satıra kopyalamaz, koşum aynı Secret adını kullanır. Arayüz kabı statik dosyayı küçük bir süreçle sunar. İstek `values-crc-small.yaml` içindeki düşük değerdir.

DeepSeek dosyasını eklemezseniz model kipi `fake` kalır. Çıkış kuralı `values-crc-deepseek.yaml` içindedir: genel `443`, özel aralıklar hariç. Üretimde bu kuralı EgressFirewall veya çıkış vekiliyle değiştirin.

## 1. Küme ayakta

```bash
crc status
```

Beklenen:

```text
CRC VM:          Running
OpenShift:       Running
```

```bash
eval "$(crc oc-env)"
eval "$(crc podman-env)"
oc login -u kubeadmin https://api.crc.testing:6443
oc whoami
```

Beklenen: `kubeadmin`. Parola `crc console --credentials` çıktısındadır.

## 2. İmaj deposu

```bash
oc patch configs.imageregistry.operator.openshift.io/cluster \
  --type merge -p '{"spec":{"defaultRoute":true}}'
oc get route default-route -n openshift-image-registry
```

Beklenen: `default-route` satırında bir host, çoğu kurulumda `default-route-openshift-image-registry.apps-crc.testing`.

```bash
HOST="$(oc get route default-route -n openshift-image-registry --template='{{ .spec.host }}')"
podman login --tls-verify=false -u kubeadmin -p "$(oc whoami -t)" "$HOST"
```

Beklenen son satır: `Login Succeeded`.

## 3. İmajlar

Derlemeden ve imaj itmeden önce eski build ve imaj katmanlarını silin. CRC düğümü imaj diski yaklaşık %15’in altına düşünce `disk-pressure` taint’i alır (`NoSchedule`). Kontrol düzlemi `Recreate` olduğu için bu sırada pod da kalkmaz; bir denemede düğüm yaklaşık beş dakika (10:32–10:37) ayakta değildi. `crc config set disk-size` yeni bir sanal makine ister, çalışan diski büyütmez.

```bash
oc adm prune builds --keep-complete=1 --keep-failed=1 -n agent-runtime --confirm
oc adm prune images --keep-tag-revisions=1 --confirm
```

`oc adm prune images` kümedeki kullanılmayan imaj katmanlarını siler. Başka projelerin etiketlenmemiş imajlarına da dokunabilir; yalnızca bu deneme kümesinde çalıştırın.

`podman` bu makinede varsa depo kökünden dış depoya itin:

```bash
podman build -f deploy/docker/Dockerfile.runtime -t agent-runtime-py312:0.2.0 .
podman build -f ui/Dockerfile -t agent-runtime-ui:0.2.0 \
  --build-arg CONTROL_PLANE_URL=http://control-plane.agent-runtime.svc:8841 ui
podman tag agent-runtime-py312:0.2.0 "$HOST/agent-runtime/agent-runtime-py312:0.2.0"
podman tag agent-runtime-ui:0.2.0 "$HOST/agent-runtime/agent-runtime-ui:0.2.0"
podman push --tls-verify=false "$HOST/agent-runtime/agent-runtime-py312:0.2.0"
podman push --tls-verify=false "$HOST/agent-runtime/agent-runtime-ui:0.2.0"
```

Beklenen: her `push` satırı `Copying blob` ile biter ve `Storing signatures` veya benzeri bir başarı satırı yazar. `unauthorized` görürseniz `podman login` adımını tekrarlayın.

`podman` yoksa imaj kümenin içinde derlenir. Önce yayın ad alanını açın. Helm aynı ad alanını sonra `--create-namespace` ile kullanır; chart bu ad alanını kendisi yazmaz.

```bash
oc get ns agent-runtime >/dev/null 2>&1 || oc new-project agent-runtime
oc new-build --name agent-runtime-py312 --strategy=docker --binary \
  --to=agent-runtime-py312:0.2.0 -n agent-runtime \
  --dockerfile="$(cat deploy/docker/Dockerfile.runtime)"
oc start-build agent-runtime-py312 --from-dir=. --follow -n agent-runtime
oc new-build --name agent-runtime-ui --strategy=docker --binary \
  --to=agent-runtime-ui:0.2.0 -n agent-runtime \
  --build-arg CONTROL_PLANE_URL=http://control-plane.agent-runtime.svc:8841 \
  --dockerfile="$(cat ui/Dockerfile)"
oc start-build agent-runtime-ui --from-dir=ui --follow -n agent-runtime
```

Beklenen: her `start-build` satırı `Push successful` veya `Build ... status: Complete` ile biter.

```bash
oc get builds -n agent-runtime
oc get imagestream -n agent-runtime
```

```text
NAME                  TYPE      FROM      STATUS
agent-runtime-py312   Docker    Binary    Complete
agent-runtime-ui      Docker    Binary    Complete
```

ImageStream etiketlerinde `0.2.0` görünür. `oc new-build` ikinci kez `already exists` derse build’i silmeden yalnızca `oc start-build` satırlarını çalıştırın.

```bash
oc get imagestream -n agent-runtime
```

`agent-runtime` ad alanı henüz yoksa bu komut boş döner. Helm kurulumundan sonra:

```text
NAME                   IMAGE REPOSITORY                                                          TAGS
agent-runtime-py312    .../agent-runtime/agent-runtime-py312                                     0.2.0
agent-runtime-ui       .../agent-runtime/agent-runtime-ui                                        0.2.0
```

ImageStream adı, push edilen depo adıyla birebir olmayabilir. Asıl kontrol podun `ImagePullBackOff` yazmamasıdır.

## 4. Chart

```bash
helm upgrade --install agent-runtime deploy/helm/agent-runtime \
  --namespace agent-runtime --create-namespace \
  -f deploy/helm/agent-runtime/values-crc.yaml
```

Dar sanal makinede aynı komuta `-f deploy/helm/agent-runtime/values-crc-small.yaml` ekleyin. Kontrol düzlemi isteği 50m / 256Mi, arayüz 20m / 96Mi, Postgres 50m / 256Mi, koşum isteği 50m / 128Mi ve geçici disk 1Gi olur.

Postgres kabında `/dev/shm` bir `emptyDir` bellek diski olarak bağlanır (`postgres.shmSize`, varsayılan `256Mi`). Varsayılan 64MiB paylaşılan bellek paralel `VACUUM`’u düşürür. Bu disk, kabın bellek limitinden yer yer; limiti `shmSize` altına indirmeyin.

Beklenen: `STATUS: deployed` ve `agent-runtime` adında bir Route. `Namespace "agent-runtime" exists and cannot be imported` görürseniz chart sürümü eskidir; güncel chart yayın ad alanını yazmaz.

```bash
oc get deploy control-plane -n agent-runtime -o jsonpath='{.spec.strategy.type}{"\n"}'
oc get secret agent-runtime-env -n agent-runtime -o jsonpath='{.data.SALES_DATABASE_URL}' | base64 -d; echo
oc get ns agent-runs --no-headers
```

Beklenen:

```text
Recreate
postgresql+psycopg://sales_ro:sales_ro@postgres.agent-runtime.svc.cluster.local:5432/sales
agent-runs   Active
```

```bash
oc get pods -n agent-runtime
oc get route agent-runtime -n agent-runtime
oc get pvc -n agent-runtime
oc get pvc artifacts -n agent-runtime -o jsonpath='{.status.phase} {.spec.accessModes[0]} {.spec.resources.requests.storage}{"\n"}'
oc get deploy control-plane -n agent-runtime -o jsonpath='{.spec.replicas}{"\n"}'
oc get deploy control-plane -n agent-runtime -o jsonpath='{range .spec.template.spec.containers[0].volumeMounts[*]}{.name}={.mountPath}{"\n"}{end}'
oc set env deploy/control-plane -n agent-runtime --list | grep '^ARTIFACT_'
```

Birkaç dakika içinde:

```text
NAME                             READY   STATUS    RESTARTS
control-plane-xxxxxxxxxx-xxxxx   1/1     Running   0
postgres-xxxxxxxxxx-xxxxx        1/1     Running   0
ui-xxxxxxxxxx-xxxxx              1/1     Running   0
```

PVC ve bağlama:

```text
Bound ReadWriteOnce 5Gi
1
tmp=/tmp
artifacts=/var/artifacts
ARTIFACT_STORE=pvc
ARTIFACT_DIR=/var/artifacts
ARTIFACT_RETENTION_DAYS=14
ARTIFACT_MAX_BYTES=20000000
```

`artifacts` claim'i `Pending` kalırsa `oc get sc` ile varsayılan sınıfı görün ve kurulumu `--set artifacts.storageClass=SINIF` ile tekrarlayın. Kontrol düzlemi tek replikadır. Bu disk `ReadWriteOnce` olduğu için ikinci replika bağlanamaz. Chart, `artifacts.store=pvc` iken `controlPlane.replicas` 1'den büyükse kurulumu reddeder.

Postgres ilk açılışta `Running` olup `READY 0/1` kalabilir. `oc logs deploy/postgres -n agent-runtime` içinde `database system is ready` geçmeli. Kontrol düzlemi hazır olunca:

```bash
oc logs deploy/control-plane -n agent-runtime | tail -30
```

Beklenen: `sales rows available` ve `Uvicorn running`. `SEED_SALES_ROWS` varsayılanı 20000'dir. On milyon satır için kurulumu `--set seedSalesRows=10000000` ile tekrarlayın; yükleme dakikalar sürebilir.

```bash
oc get networkpolicy -n agent-runtime
oc get networkpolicy -n agent-runs
oc get rolebinding agent-runs-image-puller -n agent-runtime
oc get sa agent-run -n agent-runs -o jsonpath='{.automountServiceAccountToken}{"\n"}'
```

Beklenen:

- `agent-runtime` içinde `control-plane-ingress`
- `agent-runs` içinde `agent-run-egress`
- RoleBinding `system:image-puller`
- Hizmet hesabı jetonu: `false`

## 5. Arayüz ve sağlık

```bash
ROUTE="$(oc get route agent-runtime -n agent-runtime -o jsonpath='{.spec.host}')"
curl -sk "https://${ROUTE}/backend/api/health"
```

Beklenen gövde:

```json
{"ok":true,"llm_mode":"fake","run_backend":"kubernetes","artifact_store":"pvc"}
```

Tarayıcıda `https://${ROUTE}` açılır. Pano, `postgres-sales` ve `gunluk-satis-ozeti` görünür. Sertifika uyarısı CRC'nin varsayılan sertifikasındandır.

## 6. Koşum Job'u

Arayüzden **Şimdi çalıştır** ya da:

```bash
AGENT="$(oc rsh -n agent-runtime deploy/control-plane python -c 'import urllib.request,json; print(json.load(urllib.request.urlopen("http://127.0.0.1:8841/api/agents"))[0]["id"])')"
```

Podun içinden çağırmak yerine, port yönlendirme daha sadedir:

```bash
oc port-forward -n agent-runtime svc/control-plane 8841:8841
```

Başka bir uçbirimde:

```bash
AGENT="$(curl -sf http://127.0.0.1:8841/api/agents | python3 -c 'import json,sys; print(next(a["id"] for a in json.load(sys.stdin) if a["name"]=="gunluk-satis-ozeti"))')"
curl -sf -X POST "http://127.0.0.1:8841/api/agents/${AGENT}/runs" \
  -H 'content-type: application/json' -d '{"dry_run":false}'
oc get jobs,pods -n agent-runs
```

Beklenen: `run-` ile başlayan bir Job ve `1/1` ya da bitmiş bir pod. Pod adı `run-` önekini taşır. İki kap vardır: `harness` ve `executor`.

```bash
JOB="$(oc get jobs -n agent-runs -o jsonpath='{.items[-1:].metadata.name}')"
oc get job "$JOB" -n agent-runs -o jsonpath='backoff={.spec.backoffLimit} deadline={.spec.activeDeadlineSeconds} ttl={.spec.ttlSecondsAfterFinished}{"\n"}'
oc get pod -n agent-runs -l job-name="$JOB" -o jsonpath='{.items[0].spec.automountServiceAccountToken}{"\n"}'
oc get pod -n agent-runs -l job-name="$JOB" -o jsonpath='{range .items[0].spec.containers[*]}{.name} ro={.securityContext.readOnlyRootFilesystem} priv={.securityContext.allowPrivilegeEscalation}{"\n"}{end}'
```

Beklenen:

```text
backoff=0 deadline=900 ttl=600
false
harness ro=true priv=false
executor ro=true priv=false
```

Executor ortamında `SALES_DATABASE_URL` ve `RUN_TOKEN` olmamalı:

```bash
oc set env pod/"$(oc get pod -n agent-runs -l job-name="$JOB" -o jsonpath='{.items[0].metadata.name}')" -n agent-runs --containers=executor --list | grep -E 'SALES_DATABASE_URL|RUN_TOKEN|LLM_API_KEY' || echo "executor ortamında sır yok"
```

Beklenen son satır: `executor ortamında sır yok`.

Run podu artefakt PVC'sini bağlamaz. Yalnızca iki geçici disk vardır. İki kabın geçici disk isteği 1Gi'dir:

```bash
POD="$(oc get pod -n agent-runs -l job-name="$JOB" -o jsonpath='{.items[0].metadata.name}')"
oc get pod "$POD" -n agent-runs -o jsonpath='{range .spec.volumes[*]}{.name}={.emptyDir.sizeLimit}{"\n"}{end}'
oc get pod "$POD" -n agent-runs -o jsonpath='{range .spec.containers[*]}{.name} eph={.resources.requests.ephemeral-storage}{"\n"}{end}'
oc get pod "$POD" -n agent-runs -o json | python3 -c 'import json,sys; vols=json.load(sys.stdin)["spec"]["volumes"]; assert all("persistentVolumeClaim" not in v for v in vols); print("run podunda PVC yok")'
```

Beklenen:

```text
work=20Gi
tmp=2Gi
harness eph=1Gi
executor eph=1Gi
run podunda PVC yok
```

Koşum bitince API durumu `succeeded` olur. Sahte modelle toplam ve Doğu Anadolu sapması gelir. `needs_review` görürseniz `oc logs job/"$JOB" -n agent-runs -c harness` çıktısını saklayın.

Rapor kontrol düzleminden iner.

```bash
RUN="$(curl -sf http://127.0.0.1:8841/api/agents/"$AGENT"/runs | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
ART="$(curl -sf http://127.0.0.1:8841/api/runs/"$RUN" | python3 -c 'import json,sys; arts=json.load(sys.stdin)["artifacts"]; print(next(a["id"] for a in arts if a["name"]=="report.md"))')"
curl -sfD - "http://127.0.0.1:8841/api/runs/${RUN}/artifacts/${ART}" -o /tmp/report.md
```

Beklenen başlıklarda `HTTP/1.1 200` ve `content-disposition` içinde `report.md`. Gövde metninde `Doğu Anadolu` geçer. `/tmp/report.md` boş değildir.

Dosya kontrol düzlemi podunun PVC'sindedir:

```bash
oc exec -n agent-runtime deploy/control-plane -- ls /var/artifacts/runs/gunluk-satis-ozeti
```

Beklenen: koşum kimliğiyle bir dizin. Run podunda bakılacak yer geçici `/work` diskidir. Kalıcı kopya kontrol düzleminde durur.

Job bittikten yaklaşık on dakika sonra `ttlSecondsAfterFinished` podu siler. Bu bir hata değildir.

## 7. Çıkış politikası

Run podu varsayılan olarak yalnızca DNS, kontrol düzlemi `:8841` ve Postgres `:5432` adreslerine çıkar. LLM kümenin dışındaysa koşum model adımında zaman aşımına düşer. Bunu açmak için:

```bash
helm upgrade agent-runtime deploy/helm/agent-runtime \
  --namespace agent-runtime \
  -f deploy/helm/agent-runtime/values-crc.yaml \
  --set-json 'networkPolicy.extraEgress=[{"name":"llm","cidr":"10.20.0.0/24","port":443}]'
```

CIDR'yi kendi ağ geçidinizle değiştirin. `deploy/openshift/egressfirewall.example.yaml` chart tarafından uygulanmaz.

## 8. Bozulduğunda bakılacak yer

| Belirti | Bakılacak komut |
| --- | --- |
| `ImagePullBackOff` | `oc describe pod -n agent-runs -l app=agent-run` ve image-puller RoleBinding |
| `CrashLoopBackOff` kontrol düzlemi | `oc logs deploy/control-plane -n agent-runtime` — Postgres hazır değilse pod kendini yeniden dener |
| Postgres `CreateContainerConfigError` | Secret `agent-runtime-env` içinde `POSTGRESQL_PASSWORD` var mı |
| Koşum `failed` ve logda `SQL reddedildi` | AgentSpec tabloları `allowTables` ile uyuşmuyor |
| Arayüz açılıyor, veri gelmiyor | UI podunda `CONTROL_PLANE_URL=http://control-plane.agent-runtime.svc:8841` |
| PVC `Pending` | `oc describe pvc artifacts -n agent-runtime`. Varsayılan sınıf yoksa `artifacts.storageClass` verin |
| Koşum `succeeded`, indirme 404 | `oc exec -n agent-runtime deploy/control-plane -- ls /var/artifacts`. `ARTIFACT_STORE=pvc` ve disk bağlı mı |

## 9. Oracle Free denemesi

`deploy/test/oracle` yalnızca CRC üzerindeki geçici Oracle Database Free içindir. Üretim chart’ına girmez. `anyuid` bağları yalnız `oracle-test` ad alanındaki `oracle` ServiceAccount’una verilir; restricted-v2’nin rastgele UID’si imajın `/opt/oracle` dizinine yazamaz. Veritabanının PVC’si yoktur. Deneme bitince deployment’ı sıfıra indirin, gerekirse imajı silin.

Parolaları depoya koymayın. Üç parolayı yerel dosyalara yazın (`sys`, `owner`, `ro`) ve Secret’ı dosyadan üretin:

```bash
oc apply -f deploy/test/oracle/namespace.yaml
oc -n oracle-test create secret generic oracle-creds \
  --from-file=sys=./sys --from-file=owner=./owner --from-file=ro=./ro
oc apply -f deploy/test/oracle/scc.yaml
oc apply -f deploy/test/oracle/namespace.yaml
```

İkinci `namespace.yaml` uygulaması Secret’tan sonra Deployment’ın parola dosyalarını görmesi içindir. Pod hazır olunca, `agent-runs` varsa çıkış politikasını açın ve salt okunur kullanıcıyı kurun. `load-sales.sql` bu depoda yoktur; satır yüklemek için onu betiğin yanına koyun. Betik parolayı yazdırmaz.

```bash
oc -n oracle-test rollout status deploy/oracle-free
oc apply -f deploy/test/oracle/networkpolicy.yaml
bash deploy/test/oracle/reload.sh
```

Beklenen: `sales_ro` kullanıcısı `FREEPDB1` içinde `sales` eşanlamlısını görür, `CREATE SESSION` ve `SELECT` dışında yetkisi yoktur. Koşum podu `oracle.oracle-test.svc:1521` adresine çıkar.

Deneme bitince:

```bash
oc -n oracle-test scale deploy/oracle-free --replicas=0
oc -n agent-runs delete networkpolicy agent-run-egress-oracle-test
```
