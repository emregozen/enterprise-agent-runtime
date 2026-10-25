import { formatDuration, formatNumber, statusLabel } from "./format";

describe("format", () => {
  it("labels run statuses in Turkish", () => {
    expect(statusLabel("needs_review")).toBe("İnceleme");
    expect(statusLabel("succeeded")).toBe("Başarılı");
  });

  it("formats numbers and durations", () => {
    expect(formatNumber(10160)).toBe("10.160");
    expect(formatNumber(null)).toBe("—");
    expect(formatDuration(33)).toBe("33 sn");
    expect(formatDuration(90)).toBe("1 dk 30 sn");
  });
});
