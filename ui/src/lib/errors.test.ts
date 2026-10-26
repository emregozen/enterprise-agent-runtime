import { presentText } from "./errors";

const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

describe("presentText", () => {
  it("turns control-plane errors into English", () => {
    const samples = [
      "silinmiş ajan çalıştırılamaz",
      "postgres-sales veri kaynağına ulaşılamadı. Kaynak kapalı olabilir veya adres yanıt vermiyor.",
      "parola biçiminde sunucu ve kullanıcı gerekli",
      "Conjur sunucusuna ulaşılamadı. Adres, sertifika ve ağ politikasını kontrol edin.",
      "günlük koşum limiti doldu",
      "taslak üretilemedi: timeout",
      "OpenBao ve HashiCorp Vault henüz bağlı değil. Sağlayıcı kaydı durur; KV okuma sonraki sürümde eklenecek.",
      "plan doğrulanamadı",
      "satır sayısı çapraz kontrolü tutmadı",
      "SQL çapraz kontrolü tutmadı: row_count",
    ];
    for (const sample of samples) {
      const shown = presentText(sample);
      expect(shown).not.toBe(sample);
      expect(shown).not.toMatch(TURKISH);
    }
    expect(presentText("postgres-sales veri kaynağına ulaşılamadı. Kaynak kapalı olabilir veya adres yanıt vermiyor.")).toContain("postgres-sales");
    expect(presentText("host-api-key is fine")).toBe("host-api-key is fine");
  });
});
