"use client";

import * as React from "react";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { CHART, ChartLegend, ChartTooltipCard } from "@/components/charts/chart-tooltip";
import type { UsageDay } from "@/lib/api/types";
import { formatCompact, formatNumber, shortDay } from "@/lib/format";

interface Row {
  x: string;
  answered: number;
  refused: number;
  other: number;
  questions: number;
  rows: number;
}

/** One bar per day for the last `days` days, with empty days filled in. */
export function dayRows(days: UsageDay[], span = 14, today: Date = new Date()): Row[] {
  const byDay = new Map(days.map((d) => [d.day, d]));
  const out: Row[] = [];
  for (let i = span - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    const u = byDay.get(key);
    const answered = u?.answered ?? 0;
    const refused = u?.refused ?? 0;
    const questions = u?.questions ?? 0;
    out.push({ x: shortDay(key), answered, refused, other: Math.max(0, questions - answered - refused), questions, rows: u?.rows_returned ?? 0 });
  }
  return out;
}

const axisTick = { fill: CHART.axis, fontSize: 11 };

/** Questions per day, stacked: answered, refused by the guard, and the rest. */
export function QuestionsByDayChart({ days, height = 220 }: { days: UsageDay[]; height?: number }) {
  const data = React.useMemo(() => dayRows(days), [days]);
  const total = data.reduce((a, r) => a + r.questions, 0);
  return (
    <div className="space-y-3">
      <ChartLegend
        items={[
          { label: "Answered", color: CHART.series1 },
          { label: "Refused by the guard", color: CHART.series4 },
          { label: "Other", color: CHART.grid },
        ]}
      />
      <div style={{ height }} role="img" aria-label={`Questions per day: ${formatNumber(total)} in ${data.length} days`} className="w-full min-w-0">
        <BarChart responsive style={{ width: "100%", height: "100%" }} data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="22%">
          <CartesianGrid vertical={false} stroke={CHART.grid} />
          <XAxis dataKey="x" tickLine={false} axisLine={false} tick={axisTick} minTickGap={20} tickMargin={8} />
          <YAxis width={32} tickLine={false} axisLine={false} tick={axisTick} allowDecimals={false} tickCount={4} tickFormatter={(v: number) => formatCompact(v)} />
          <Tooltip
            cursor={{ fill: "var(--muted)", opacity: 0.6 }}
            isAnimationActive={false}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as Row | undefined;
              if (!active || !p) return null;
              return (
                <ChartTooltipCard
                  title={p.x}
                  rows={[
                    { label: "Answered", value: formatNumber(p.answered), color: CHART.series1 },
                    { label: "Refused", value: formatNumber(p.refused), color: CHART.series4 },
                    { label: "Other", value: formatNumber(p.other), color: CHART.grid },
                  ]}
                  footer={`${formatNumber(p.rows)} rows returned`}
                />
              );
            }}
          />
          <Bar dataKey="answered" stackId="q" fill={CHART.series1} maxBarSize={36} isAnimationActive={false} />
          <Bar dataKey="refused" stackId="q" fill={CHART.series4} maxBarSize={36} isAnimationActive={false} />
          <Bar dataKey="other" stackId="q" fill={CHART.grid} radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false} />
        </BarChart>
      </div>
    </div>
  );
}
