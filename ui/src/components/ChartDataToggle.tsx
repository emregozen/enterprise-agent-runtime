import { BarChart3 } from "lucide-react";

export function chartDataOf(spec: Record<string, unknown> | null | undefined): boolean {
  const output = ((spec?.spec as Record<string, unknown> | undefined)?.output ?? {}) as { chartData?: unknown };
  return output.chartData === true;
}

export function withChartData(spec: Record<string, unknown>, enabled: boolean): Record<string, unknown> {
  const next = structuredClone(spec);
  const inner = ((next.spec as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
  const output = ((inner.output as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>;
  output.chartData = enabled;
  inner.output = output;
  next.spec = inner;
  return next;
}

/** Opt-in: ask the agent for a chart-ready markdown table so boards can draw it. */
export function ChartDataToggle({ checked, onChange, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className="chart-toggle">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
      <span>
        <strong><BarChart3 size={14} aria-hidden /> Generate chart data</strong>
        <small>
          Adds an instruction to the agent: besides its analysis, the report must include a markdown table of labels and plain numbers.
          Boards then draw that table as a chart. Your own description is not changed.
        </small>
      </span>
    </label>
  );
}
