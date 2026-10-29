/** Detect markdown tables in a report and decide which of them can be drawn as a chart. */

export type ParsedNumber = { value: number; percent: boolean };

export type Metric = { index: number; name: string; values: (number | null)[]; percent: boolean };

export type ChartTableModel = {
  headers: string[];
  labels: string[];
  raw: string[][];
  metrics: Metric[];
  /** Labels look like dates or months: a line reads better than bars. */
  temporal: boolean;
};

export type ReportSegment = { kind: "text"; text: string } | { kind: "table"; block: string; chart: ChartTableModel };

const CURRENCY = /(?:₺|\$|€|£|\bTRY\b|\bTL\b|\bUSD\b|\bEUR\b)/gi;
const NUMBER_SHAPE = /^[+-]?\d[\d.,\u00a0\u202f ]*$/;
const TEMPORAL = /^(\d{4}-\d{2}(-\d{2})?|\d{4}\/\d{2}(\/\d{2})?|\d{2}[./]\d{2}[./]\d{4}|\d{4}-?Q[1-4]|Q[1-4] ?\d{4})$/i;
const MONTHS = /^(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?( \d{4})?$/i;

export const MAX_ROWS = 30;
export const MAX_METRICS = 8;

/** Parse a table cell such as `1.163.555.575,28`, `164,898,011.85 TL`, `+6,7%` or `-0,26%`. */
export function parseCell(raw: string): ParsedNumber | null {
  let text = raw.replace(/\*\*|__|`/g, "").replace(CURRENCY, "").replace(/\u2212/g, "-").trim();
  let percent = false;
  if (text.endsWith("%")) {
    percent = true;
    text = text.slice(0, -1).trim();
  }
  if (!NUMBER_SHAPE.test(text)) return null;
  const sign = text.startsWith("-") ? -1 : 1;
  const digits = text.replace(/^[+-]/, "").replace(/[\u00a0\u202f ]/g, "");
  const dots = (digits.match(/\./g) || []).length;
  const commas = (digits.match(/,/g) || []).length;
  let normalized: string;
  if (dots && commas) {
    const decimal = digits.lastIndexOf(",") > digits.lastIndexOf(".") ? "," : ".";
    const thousands = decimal === "," ? "." : ",";
    normalized = digits.split(thousands).join("").replace(decimal, ".");
  } else if (commas) {
    // `1,234,567` is thousands; a single comma is a decimal mark (Turkish reports).
    normalized = commas > 1 ? digits.replace(/,/g, "") : digits.replace(",", ".");
  } else if (dots) {
    // `164.421.795` and `117.416` are Turkish thousands groups; `5.5` is a decimal.
    const grouped = dots > 1 || /^\d{1,3}\.\d{3}$/.test(digits);
    normalized = grouped ? digits.replace(/\./g, "") : digits;
  } else {
    normalized = digits;
  }
  const value = Number(normalized) * sign;
  return Number.isFinite(value) ? { value, percent } : null;
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

const isSeparator = (line: string) => /^\|?[\s:|-]+\|?$/.test(line.trim()) && line.includes("-");

/** Return the table rows of a markdown block, or null when the block is not a table. */
export function parseTable(block: string): { headers: string[]; rows: string[][] } | null {
  const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length < 3 || !lines.every((line) => line.startsWith("|"))) return null;
  const body = lines.filter((line) => !isSeparator(line));
  if (body.length < 3) return null;
  const headers = splitRow(body[0]);
  const rows = body.slice(1).map((line) => {
    const cells = splitRow(line);
    while (cells.length < headers.length) cells.push("");
    return cells.slice(0, headers.length);
  });
  return { headers, rows };
}

/** Build a chart model for a table, or null when it is not worth charting. */
export function chartModel(block: string): ChartTableModel | null {
  const table = parseTable(block);
  if (!table || table.headers.length < 2) return null;
  const { headers, rows } = table;
  if (rows.length < 2 || rows.length > MAX_ROWS) return null;
  const labels = rows.map((row) => row[0].replace(/\*\*|__/g, ""));
  if (labels.some((label) => label === "") || new Set(labels).size !== labels.length) return null;
  const temporal = labels.every((label) => TEMPORAL.test(label) || MONTHS.test(label));
  if (!temporal && labels.every((label) => parseCell(label) !== null)) return null;
  const metrics: Metric[] = [];
  for (let col = 1; col < headers.length && metrics.length < MAX_METRICS; col += 1) {
    const cells = rows.map((row) => row[col]);
    const filled = cells.filter((cell) => cell !== "" && cell !== "-" && cell !== "—");
    if (filled.length < 2) continue;
    const parsed = cells.map((cell) => (filled.includes(cell) ? parseCell(cell) : null));
    if (parsed.some((item, i) => item === null && filled.includes(cells[i]))) continue;
    metrics.push({
      index: col,
      name: headers[col].replace(/\*\*|__/g, "") || `Column ${col}`,
      values: parsed.map((item) => (item ? item.value : null)),
      percent: parsed.some((item) => item?.percent) || /%/.test(headers[col]),
    });
  }
  if (metrics.length === 0) return null;
  return { headers, labels, raw: rows, metrics, temporal };
}

/** Split a report into text runs and tables; chartable tables keep their raw block for the table view. */
export function segmentReport(markdown: string): ReportSegment[] {
  const segments: ReportSegment[] = [];
  let text: string[] = [];
  const flush = () => {
    if (text.length) segments.push({ kind: "text", text: text.join("\n\n") });
    text = [];
  };
  for (const block of markdown.split(/\n{2,}/)) {
    const chart = block.trim().startsWith("|") ? chartModel(block) : null;
    if (chart) {
      flush();
      segments.push({ kind: "table", block, chart });
    } else if (block.trim()) {
      text.push(block);
    }
  }
  flush();
  return segments;
}
