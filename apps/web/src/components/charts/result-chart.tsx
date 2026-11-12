"use client";

import * as React from "react";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, Tooltip, XAxis, YAxis } from "recharts";

import { CHART, ChartLegend, ChartTooltipCard } from "@/components/charts/chart-tooltip";
import type { ChartType } from "@/lib/api/types";
import { formatCompact, formatNumber } from "@/lib/format";

const SERIES = [CHART.series1, CHART.series2, CHART.series3, CHART.series4];
const axisTick = { fill: CHART.axis, fontSize: 11 };

export interface ChartSpec {
  type: ChartType;
  x: string;
  y: string[];
}

/** Rows of a result as objects keyed by column, with the category as text. */
export function chartData(columns: string[], rows: unknown[][], spec: ChartSpec): Record<string, string | number>[] {
  const xi = columns.indexOf(spec.x);
  const yi = spec.y.map((y) => columns.indexOf(y));
  return rows.map((r) => {
    const out: Record<string, string | number> = { [spec.x]: String(r[xi] ?? "") };
    spec.y.forEach((y, i) => {
      const v = r[yi[i] ?? -1];
      out[y] = typeof v === "number" ? v : Number(v) || 0;
    });
    return out;
  });
}

/** The chart for a query result: bar, line or pie, in the theme's series colors. */
export function ResultChart({ columns, rows, spec, height = 300 }: { columns: string[]; rows: unknown[][]; spec: ChartSpec; height?: number }) {
  const data = React.useMemo(() => chartData(columns, rows, spec), [columns, rows, spec]);
  const label = `${spec.type} chart of ${spec.y.join(", ")} by ${spec.x}, ${data.length} points`;
  const tooltip = (
    <Tooltip
      isAnimationActive={false}
      cursor={spec.type === "bar" ? { fill: "var(--muted)", opacity: 0.6 } : { stroke: CHART.axis, strokeOpacity: 0.5 }}
      content={({ active, payload }) => {
        const p = payload?.[0]?.payload as Record<string, string | number> | undefined;
        if (!active || !p) return null;
        return (
          <ChartTooltipCard
            title={String(p[spec.x])}
            rows={spec.y.map((y, i) => ({ label: y, value: formatNumber(Number(p[y])), color: SERIES[i % SERIES.length] ?? CHART.series1 }))}
          />
        );
      }}
    />
  );
  if (spec.type === "pie") {
    const y = spec.y[0] ?? "";
    const total = data.reduce((a, d) => a + Number(d[y] ?? 0), 0);
    const colors = [CHART.series1, CHART.series3, CHART.series2, CHART.series4, "var(--info)", "var(--warning)", "var(--subtle)", "var(--faint)"];
    return (
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center">
        <div style={{ height, width: "100%", maxWidth: height }} role="img" aria-label={label} className="min-w-0">
          <PieChart responsive style={{ width: "100%", height: "100%" }}>
            {tooltip}
            <Pie data={data} dataKey={y} nameKey={spec.x} innerRadius="52%" outerRadius="86%" paddingAngle={1.5} stroke="var(--card)" strokeWidth={2} isAnimationActive={false}>
              {data.map((d, i) => (
                <Cell key={String(d[spec.x])} fill={colors[i % colors.length]} />
              ))}
            </Pie>
          </PieChart>
        </div>
        <ul className="w-full min-w-0 space-y-1.5 text-[12.5px]">
          {data.map((d, i) => (
            <li key={String(d[spec.x])} className="flex items-center justify-between gap-3">
              <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
                <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: colors[i % colors.length] }} aria-hidden />
                <span className="truncate">{String(d[spec.x])}</span>
              </span>
              <span className="tabular shrink-0 font-semibold">
                {formatNumber(Number(d[y]))}
                <span className="ml-1.5 font-normal text-subtle">{total ? `${Math.round((Number(d[y]) / total) * 100)}%` : ""}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  const legend = spec.y.length > 1 && <ChartLegend items={spec.y.map((y, i) => ({ label: y, color: SERIES[i % SERIES.length] ?? CHART.series1 }))} />;
  const axes = (
    <>
      <CartesianGrid vertical={false} stroke={CHART.grid} />
      <XAxis dataKey={spec.x} tickLine={false} axisLine={false} tick={axisTick} minTickGap={16} tickMargin={8} />
      <YAxis width={48} tickLine={false} axisLine={false} tick={axisTick} tickCount={5} tickFormatter={(v: number) => formatCompact(v)} />
      {tooltip}
    </>
  );
  return (
    <div className="space-y-3">
      {legend}
      <div style={{ height }} role="img" aria-label={label} className="w-full min-w-0">
        {spec.type === "line" ? (
          <LineChart responsive style={{ width: "100%", height: "100%" }} data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            {axes}
            {spec.y.map((y, i) => (
              <Line
                key={y}
                type="monotoneX"
                dataKey={y}
                stroke={SERIES[i % SERIES.length]}
                strokeWidth={2.2}
                dot={data.length <= 24 ? { r: 2.5, fill: SERIES[i % SERIES.length], strokeWidth: 0 } : false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        ) : (
          <BarChart responsive style={{ width: "100%", height: "100%" }} data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="20%">
            {axes}
            {spec.y.map((y, i) => (
              <Bar key={y} dataKey={y} fill={SERIES[i % SERIES.length]} radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false} />
            ))}
          </BarChart>
        )}
      </div>
    </div>
  );
}
