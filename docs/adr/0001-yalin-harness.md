# 0001. LangGraph yerine yalın durum makinesi

Koşum podundaki harness, planla, SQL’i süz, parquet’e çek, kodu yürütücüde çalıştır, sayıyı SQL ile karşılaştır ve gerekirse bir tur onar. Bu döngü düz bir durum makinesidir. LangGraph ek bir çalışma zamanı ve sürüm yüzeyi getirirdi; PoC’nin doğrulaması SQL ve yürütücüdedir, graf çerçevesinde değil.

İz, OpenTelemetry OTLP uç noktası ve JSON günlükle Postgres’teki `audit_events` tablosuna yazılır. Langfuse bu turda yok.
