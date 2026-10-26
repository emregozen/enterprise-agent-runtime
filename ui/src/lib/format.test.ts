import { formatDuration, formatNumber, formatPercent, statusLabel } from "./format";

describe("format", () => {
  it("labels run statuses in English", () => {
    expect(statusLabel("needs_review")).toBe("Needs review");
    expect(statusLabel("succeeded")).toBe("Succeeded");
  });

  it("formats numbers and durations in en-US", () => {
    expect(formatNumber(10160)).toBe("10,160");
    expect(formatNumber(null)).toBe("—");
    expect(formatDuration(33)).toBe("33s");
    expect(formatDuration(90)).toBe("1m 30s");
    expect(formatPercent(92.5)).toBe("92.5%");
  });
});
