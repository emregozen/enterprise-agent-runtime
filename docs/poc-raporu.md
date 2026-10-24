# PoC raporu

Tarih: 24 Ekim 2026. Sürüm 0.2.0.

## Çalışan ve test edilen

- `pytest`: 23 test geçti. SQL süzgeci, AgentSpec, cron politikası, Job belgesi (sırların executor kabında olmaması, restricted-v2 alanları), yürütücü ortam izolasyonu, araç vekili, Postgres salt okunur oturum ve Parquet dökümü, harness çapraz kontrolü, onarım turu, `needs_review`, builder, zamanlayıcının tek satır kilidi, denetim kaydının değiştirilememesi, yerel iki süreçlik uçtan uca koşum ve sahte Kubernetes API’sine Secret + Job gönderimi.
- `python evals/check_fake_builder.py`: iki soru, beklenen araç ve zamanlama.
- Yerel API `8841` ve arayüz `8842` ayakta. Sahte model. `sales` tablosunda 20 000 satır, `sales_ro` salt okunur.
- `gunluk-satis-ozeti` koşumu tamamlandı. Toplam 10.160,00. Tek sapma Doğu Anadolu. `send_email` vekili `ok` döndü. Artefaktlar: plan, SQL, parquet, çıktı, rapor, grafik.
- Arayüz tarayıcıda gezildi. Pano, tamamlanmış koşum, rapor, `report.md` indirme ve 390 piksel genişlik geçti. Yeni ajan taslağı, yayını ve koşumu da geçti: durum tamam, toplam 10.160,00, sapma Doğu Anadolu.

## Test edilmeyen

- Gerçek Kubernetes, kind, OpenShift ve CRC. Bu makinede docker, kind ve kubectl yok. Job üretimi sahte `create_from_dict` ile doğrulandı. Pod mantığı yerel iki süreçle çalıştı.
- İmaj derlemesi. Dockerfile’lar duruyor, build çalıştırılmadı.
- `helm template -f values-crc.yaml` 582 satır üretti (iki ad alanı, NetworkPolicy, Route, üç Deployment). Kümeye kurulmadı.
- Oracle konteyneri. Sürücü ve SQL süzgeci birim testinde. İmaj büyük olduğu için çekilmedi.
- SeaweedFS / S3. Yerel dosya deposu artefakt yüklemesiyle test edildi. S3 kod yolu duruyor.
- Gerçek bir OpenAI uyumlu model. `LLM_MODE=fake`.
- UBI9 taban imajı. Varsayılan `python:3.12-slim`.
- On milyon satırlık yükleme. Üretici `--rows 10000000` kabul eder; bu turda 20 000 yüklendi.
- Ağ politikasının kümede trafiği kestiği. YAML yazıldı, uygulanmadı.

## Yarın OpenShift Local

Komutların tamamı kök `README.md` içindeki “OpenShift Local” bölümündedir. Kısa dizi: `crc start`, `oc login -u kubeadmin`, imaj deposu route’unu aç, iki imajı `podman` ile bas, `helm upgrade --install agent-runtime deploy/helm/agent-runtime -f deploy/helm/agent-runtime/values-crc.yaml`. LLM ve dış veritabanı için `networkPolicy.extraEgress` doldurulmadan run podu oralara çıkamaz.
