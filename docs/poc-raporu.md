# PoC raporu

Tarih: 24 Ekim 2026. Sürüm 0.2.0.

## Çalışan ve test edilen

- `pytest`: 32 test geçti. PVC deposu, saklama temizliği ve akışlı yükleme API’si eklendi. SeaweedFS S3 turu ile OpenAI istemci sözleşmesi duruyor.
- 10 milyon satış satırı 42 saniyede yüklendi. Tablo 1,1 GB.
- Tam tablo SQL pushdown: 735 ms.
- Günlük pencere pushdown: 0,19 ms, 56 satır.
- 10 milyon satır Parquet: 13,9 s, 116 MB, okuyucu tepe belleği 114 MB. Parti boyu 10 000 bırakıldı; 2 000 ve 50 000 daha yavaştı.
- Executor içinde DuckDB: 0,24 s, tepe bellek 81 MB. SQL ile satır sayısı ve toplam tuttu.
- Seed ajan `gunluk-satis-ozeti`: 0,76 s, `succeeded`, toplam 10.160,00, tek sapma Doğu Anadolu, executor tepe belleği 107 MB.
- Varsayılan artefakt deposu PVC kod yoludur. Yerelde `var/artifacts`. Yükleme ham gövde olarak akar, indirme aynı baytları döner. 14 günden eski dosya silinir; çalışan koşumun dosyası durur. Helm şablonu PVC’yi yalnızca kontrol düzlemine bağlar. `replicas=2` pvc modunda reddedilir.
- SeaweedFS 3.80, `127.0.0.1:8833`. `ARTIFACT_STORE=s3` ile artefakt `s3://agent-artifacts/...` adresine yazıldı ve geri okundu. Bu, PVC varsayılanının yanındaki seçenektir.
- OpenAI istemcisi yerel bir Chat Completions sunucusuna model, bearer ve `response_format` geri çekilmesini gönderdi. Ağırlık indirilmedi.

Sayılar `docs/benchmarks/10m.md` içindedir.

## Test edilmeyen

- Gerçek Kubernetes, kind, OpenShift ve CRC. Docker, kind ve kubectl yok. Job belgesi sahte API ile doğrulandı. Yarınki adımlar `OPENSHIFT-LOCAL-CHECKLIST.md` dosyasındadır.
- İmaj derlemesi.
- Oracle. `127.0.0.1:1521` bağlantıyı reddetti. Docker olmadığı için Oracle Free kalkmadı. Sürücü ve SQL süzgeci birim testinde duruyor.
- Gerçek bir model ağırlığı. Ollama ve llama-server kurulu değil.
- UBI9 taban imajı.
- Ağ politikasının kümede trafiği kestiği.
