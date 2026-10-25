# 0002. Artefaktlar kontrol düzleminin diskindedir

İlk fazda rapor dosyası OpenShift PersistentVolume üzerindedir. Disk `ReadWriteOnce`dır ve yalnızca kontrol düzlemi poduna bağlanır. Koşum podu bu diski görmez. Harness dosyayı, koşum jetonuyla, iç API’ye parça parça yazar. Düzlem boyutu sınırlar, özeti kontrol eder ve dosyayı PVC’ye koyar.

`ARTIFACT_STORE=s3` seçilince aynı akış S3 uyumlu depoya gider. Anahtar yine poda konmaz. S3, birden fazla kontrol düzlemi replikası gerektiğinde kullanılır. PVC ile replika sayısı 1 kalır.

Yirmi megabaytın üstü reddedilir. `ARTIFACT_RETENTION_DAYS` süresini aşan dosyalar zamanlayıcı döngüsünde silinir.

Doğrudan poddan diske yazmak daha az kopya demektir. Bu turda kimlik bilgisinin ve kalıcı diskin poddan uzak durması önde gelir.
