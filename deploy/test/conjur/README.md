# Conjur denemesi

Bu dizin CRC üzerinde CyberArk Conjur Open Source kurar. Üretim chart'ına girmez. Ayrıntılı adımlar `OPENSHIFT-LOCAL-CHECKLIST.md` bölüm 10'dadır.

İmaj `cyberark/conjur:1.24.0` çok mimarilidir. `1.27` yalnız amd64'tür; arm64 CRC'de açılmaz. Sunucu 80 portunu dinlediği için `anyuid` yalnız `conjur-test/conjur` hesabına verilir.

Veritabanı, `agent-runtime` içindeki mevcut Postgres'te ayrı bir `conjur` veritabanıdır. İkinci bir Postgres pod'u açılmaz. İstek 50m CPU ve 384Mi bellektir.

Parolalar ve API anahtarı dosyadan okunur. Komut satırına yazılmaz, betik onları basmaz.
