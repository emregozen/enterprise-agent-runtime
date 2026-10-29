import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { segmentReport, type ChartTableModel } from "../lib/tables";
import { Markdown, ViewToggle } from "./ui";

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const full = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 2 });

/** Markdown report where tables that make sense as a chart are drawn as one; everything else stays text. */
export function ReportView({ text }: { text: string }) {
  const segments = useMemo(() => segmentReport(text), [text]);
  return (
    <div className="report-view">
      {segments.map((segment, index) =>
        segment.kind === "text" ? <Markdown key={index} text={segment.text} /> : <ChartTable key={index} model={segment.chart} block={segment.block} />,
      )}
    </div>
  );
}

function ChartTable({ model, block }: { model: ChartTableModel; block: string }) {
  const [view, setView] = useState("chart");
  const [metricIndex, setMetricIndex] = useState(0);
  const metric = model.metrics[Math.min(metricIndex, model.metrics.length - 1)];
  const data = model.labels.map((label, i) => ({ label, value: metric.values[i], raw: model.raw[i][metric.index] }));
  const signed = data.some((d) => (d.value ?? 0) < 0);
  const horizontal = !model.temporal && (data.length >= 5 || data.some((d) => d.label.length > 12));
  const height = horizontal ? Math.max(200, data.length * 30 + 40) : 240;
  const longest = Math.min(160, Math.max(60, Math.max(...data.map((d) => d.label.length)) * 7));
  const tick = { fill: "var(--muted)", fontSize: 12 };
  const tooltip = (
    <Tooltip
      cursor={{ fill: "color-mix(in srgb, var(--ink) 6%, transparent)" }}
      contentStyle={{ background: "var(--surface-strong)", border: "1px solid var(--line)", borderRadius: 12, color: "var(--ink)" }}
      formatter={(_value, _name, item) => [(item.payload as { raw: string }).raw, metric.name]}
    />
  );
  const color = (value: number | null) => (signed ? ((value ?? 0) < 0 ? "var(--danger)" : "var(--ok)") : "var(--accent)");
  const axis = metric.percent ? (v: number) => `${full.format(v)}%` : (v: number) => compact.format(v);

  return (
    <figure className="chart-table">
      <div className="chart-table-bar">
        {model.metrics.length > 1 ? (
          <div className="pills" role="tablist" aria-label="Metric">
            {model.metrics.map((m, i) => (
              <button key={m.index} type="button" role="tab" aria-selected={m === metric} className={m === metric ? "on" : ""} onClick={() => setMetricIndex(i)}>{m.name}</button>
            ))}
          </div>
        ) : <strong className="chart-table-title">{metric.name}</strong>}
        <ViewToggle value={view} onChange={setView} options={[{ id: "chart", label: "Chart" }, { id: "table", label: "Table" }]} />
      </div>
      {view === "table" ? (
        <Markdown text={block} />
      ) : (
        <div style={{ height }} role="img" aria-label={`${metric.name} by ${model.headers[0]}`}>
          <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 480, height }}>
            {model.temporal ? (
              <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                <XAxis dataKey="label" tick={tick} stroke="var(--line)" />
                <YAxis tick={tick} stroke="var(--line)" tickFormatter={axis} width={56} />
                {tooltip}
                <Line type="monotone" dataKey="value" stroke="var(--accent)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} connectNulls />
              </LineChart>
            ) : horizontal ? (
              <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" horizontal={false} />
                <XAxis type="number" tick={tick} stroke="var(--line)" tickFormatter={axis} />
                <YAxis type="category" dataKey="label" tick={tick} stroke="var(--line)" width={longest} interval={0} />
                {tooltip}
                <Bar dataKey="value" radius={[0, 6, 6, 0]} isAnimationActive={false}>
                  {data.map((d, i) => <Cell key={i} fill={color(d.value)} />)}
                </Bar>
              </BarChart>
            ) : (
              <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
                <XAxis dataKey="label" tick={tick} stroke="var(--line)" interval={0} />
                <YAxis tick={tick} stroke="var(--line)" tickFormatter={axis} width={56} />
                {tooltip}
                <Bar dataKey="value" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                  {data.map((d, i) => <Cell key={i} fill={color(d.value)} />)}
                </Bar>
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}
