"use client";

import { BarChart3Icon, ChevronLeftIcon, ChevronRightIcon, DownloadIcon, LineChartIcon, PieChartIcon, Table2Icon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ResultChart } from "@/components/charts/result-chart";
import { Hint } from "@/components/hint";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { download } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { ChartType, Execution, RowsPage } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDuration, formatNumber, plural } from "@/lib/format";

import { useRows } from "../api";

const PAGE = 20;
const CHART_ICON: Record<ChartType, typeof BarChart3Icon> = { bar: BarChart3Icon, line: LineChartIcon, pie: PieChartIcon };
const CHART_LABEL: Record<ChartType, string> = { bar: "Bar", line: "Line", pie: "Pie" };

function cell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isInteger(v) ? formatNumber(v) : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/**
 * A query's result: the table (paged from the stored snapshot, so the database is never
 * queried again), and the chart SQLAgent suggested when the shape fits one, with the
 * types that also fit as a manual override.
 */
export function ResultView({ pid, execution, firstPage }: { pid: string; execution: Execution; firstPage?: RowsPage | null }) {
  const suggestion = execution.chart;
  const types: ChartType[] = suggestion ? [suggestion.type, ...(suggestion.alternatives ?? []).filter((t) => t !== suggestion.type)] : [];
  const [view, setView] = React.useState<"table" | ChartType>(suggestion ? suggestion.type : "table");
  const [offset, setOffset] = React.useState(0);
  const rows = useRows(pid, execution.id, offset, PAGE, firstPage && firstPage.limit === PAGE ? firstPage : null);
  // The chart draws every stored row (charts are only offered up to 50 categories).
  const all = useRows(pid, execution.id, 0, 1000);
  const columns = execution.columns.map((c) => c.name);
  const total = rows.data?.total ?? execution.row_count;
  const [exporting, setExporting] = React.useState(false);

  async function exportCsv() {
    setExporting(true);
    try {
      await download(`/api/v1/projects/${pid}/executions/${execution.id}/export.csv`, `sqlagent-${execution.id}.csv`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="min-w-0" data-qa="result">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Show the result as" className="inline-flex gap-0.5 rounded-lg bg-muted p-0.5">
          <ViewButton active={view === "table"} onClick={() => setView("table")} icon={Table2Icon} label="Table" />
          {types.map((t) => (
            <ViewButton key={t} active={view === t} onClick={() => setView(t)} icon={CHART_ICON[t]} label={CHART_LABEL[t]} />
          ))}
          {suggestion && <Hint term="chart" className="mx-1.5 self-center" />}
        </div>
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <span className="tabular">
            {plural(total, "row")} in {formatDuration(execution.duration_ms)}
            {execution.truncated && (
              <span className="ml-1.5 text-warning">
                (cut at the row limit) <Hint term="rowLimit" className="align-middle" />
              </span>
            )}
          </span>
          <Button variant="outline" size="xs" onClick={() => void exportCsv()} disabled={exporting || total === 0}>
            <DownloadIcon />
            CSV
          </Button>
        </div>
      </div>
      {view === "table" ? (
        <div className="overflow-hidden rounded-xl bg-muted/40">
          <div className="max-h-[420px] overflow-auto">
            <Table className="text-[12.5px]">
              <TableHeader>
                <TableRow>
                  {columns.map((c) => (
                    <TableHead key={c} className="whitespace-nowrap">
                      {c}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {(rows.data?.rows ?? []).map((r, i) => (
                  <TableRow key={offset + i}>
                    {r.map((v, j) => (
                      <TableCell
                        key={j}
                        className={cn("max-w-[280px] truncate whitespace-nowrap", execution.columns[j]?.kind === "number" && "tabular text-right")}
                        title={cell(v)}
                      >
                        {v === null ? <span className="text-faint">null</span> : cell(v)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
                {total === 0 && (
                  <TableRow>
                    <TableCell colSpan={Math.max(columns.length, 1)} className="py-6 text-center text-muted-foreground">
                      The query ran and matched no rows.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {total > PAGE && (
            <div className="flex items-center justify-between px-3 py-2 text-[12px] text-muted-foreground">
              <span className="tabular">
                {formatNumber(offset + 1)} to {formatNumber(Math.min(offset + PAGE, total))} of {formatNumber(total)}
              </span>
              <div className="flex gap-1">
                <Button variant="ghost" size="icon-xs" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>
                  <ChevronLeftIcon />
                </Button>
                <Button variant="ghost" size="icon-xs" aria-label="Next page" disabled={offset + PAGE >= total} onClick={() => setOffset((o) => o + PAGE)}>
                  <ChevronRightIcon />
                </Button>
              </div>
            </div>
          )}
        </div>
      ) : suggestion && all.data ? (
        <div className="rounded-xl bg-muted/30 p-3 sm:p-4">
          <ResultChart columns={columns} rows={all.data.rows} spec={{ type: view, x: suggestion.x, y: suggestion.y }} height={280} />
        </div>
      ) : (
        <div className="h-[280px] animate-pulse rounded-xl bg-muted/50" aria-busy aria-label="Loading the chart" />
      )}
    </div>
  );
}

function ViewButton({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: typeof Table2Icon; label: string }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring [&_svg]:size-3.5",
        active && "bg-card text-foreground shadow-[var(--elev-1)] dark:bg-accent",
      )}
    >
      <Icon aria-hidden />
      {label}
    </button>
  );
}
