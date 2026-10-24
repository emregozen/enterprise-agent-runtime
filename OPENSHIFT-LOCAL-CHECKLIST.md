# OpenShift Local kontrol listesi

Yarın CRC üzerinde kurulumu bu sırayla doğrulayın. Komutlar `kubeadmin` içindir. Her adımın altında beklenen çıktı vardır. Metin birebir aynı olmak zorunda değil; kalın duran parçalar görünmeli.

Ayrıntılı kurulum kök `README.md` içindedir. Bu dosya yalnızca doğrulamadır.

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

Depo kökünden:

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

Beklenen: `STATUS: deployed` ve `agent-runtime` adında bir Route.

```bash
oc get pods -n agent-runtime
oc get route agent-runtime -n agent-runtime
oc get pvc -n agent-runtime
```

Birkaç dakika içinde:

```text
NAME                             READY   STATUS    RESTARTS
control-plane-xxxxxxxxxx-xxxxx   1/1     Running   0
postgres-xxxxxxxxxx-xxxxx        1/1     Running   0
ui-xxxxxxxxxx-xxxxx              1/1     Running   0
```

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
{"ok":true,"llm_mode":"fake","run_backend":"kubernetes"}
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

Koşum bitince API durumu `succeeded` olur. Sahte modelle toplam ve Doğu Anadolu sapması gelir. `needs_review` görürseniz `oc logs job/"$JOB" -n agent-runs -c harness` çıktısını saklayın.

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
