# 0003. Zamanlayıcı Postgres kilidinde

Cron ve ajanın kendi istediği sonraki koşum aynı `schedules` tablosundadır. Bir tik `pg_try_advisory_xact_lock` ve `FOR UPDATE SKIP LOCKED` ile tek satır alır. Ayrı bir kuyruk ürünü yok.

Politika aynı gün penceresini, en kısa ve en uzun aralığı ve günlük üst sınırı uygular. Üst sınır bugünü doldurunca yarına izin verir.
