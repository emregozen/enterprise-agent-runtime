import { describe, expect, it } from "vitest";
import { chartModel, parseCell, segmentReport } from "./tables";

describe("parseCell", () => {
  it("reads Turkish and English number formats", () => {
    expect(parseCell("1.163.555.575,28")?.value).toBeCloseTo(1163555575.28);
    expect(parseCell("164.421.795")?.value).toBe(164421795);
    expect(parseCell("117.416")?.value).toBe(117416);
    expect(parseCell("117416")?.value).toBe(117416);
    expect(parseCell("164,898,011.85 TL")?.value).toBeCloseTo(164898011.85);
    expect(parseCell("5.5")?.value).toBe(5.5);
  });
  it("reads signed percentages", () => {
    expect(parseCell("+6,7%")).toEqual({ value: 6.7, percent: true });
    expect(parseCell("-0,26%")).toEqual({ value: -0.26, percent: true });
  });
  it("rejects text", () => {
    expect(parseCell("Ürün-14 (4.240.965,99 TL)")).toBeNull();
    expect(parseCell("Akdeniz")).toBeNull();
  });
});

const REGION = `| Bölge | Tutar | Sapma | Adet |
| --- | --- | --- | --- |
| Akdeniz | 164.898.011,85 | 0,28% | 117416 |
| Ege | 164.270.194,20 | -0,26% | 117416 |
| Marmara | 164.421.795 | 0,26% | 117416 |`;

const TOP = `| Bölge | 1. Ürün | 2. Ürün |
| --- | --- | --- |
| Akdeniz | Ürün-14 (4.240.965,99 TL) | Ürün-05 (4.229.150,20 TL) |
| Ege | Ürün-04 (4.194.949,06 TL) | Ürün-25 (4.182.871,30 TL) |`;

describe("chartModel", () => {
  it("finds numeric metrics next to a label column", () => {
    const model = chartModel(REGION);
    expect(model?.labels).toEqual(["Akdeniz", "Ege", "Marmara"]);
    expect(model?.metrics.map((m) => m.name)).toEqual(["Tutar", "Sapma", "Adet"]);
    expect(model?.metrics[1].percent).toBe(true);
  });
  it("skips tables with text cells", () => {
    expect(chartModel(TOP)).toBeNull();
  });
  it("detects date labels", () => {
    const model = chartModel("| Gün | Adet |\n| --- | --- |\n| 2026-10-01 | 5 |\n| 2026-10-02 | 7 |");
    expect(model?.temporal).toBe(true);
  });
});

describe("segmentReport", () => {
  it("keeps text and unchartable tables as text, chartable tables as tables", () => {
    const parts = segmentReport(`# Rapor\n\n${REGION}\n\nÖzet\n\n${TOP}`);
    expect(parts.map((p) => p.kind)).toEqual(["text", "table", "text"]);
  });
  it("returns only text when nothing can be charted", () => {
    expect(segmentReport("Merhaba\n\nDünya").map((p) => p.kind)).toEqual(["text"]);
  });
});
