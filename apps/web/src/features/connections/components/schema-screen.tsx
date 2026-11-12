"use client";

import { ArrowLeftIcon, EyeIcon, KeyRoundIcon, LinkIcon, MessageSquareTextIcon, RefreshCwIcon, SearchIcon, TableIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { KindChip } from "@/components/status-chips";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCurrentProject } from "@/features/projects/api";
import { errorMessage } from "@/lib/api/errors";
import type { SchemaTable } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatCompact, formatDuration, formatRelative, plural } from "@/lib/format";

import { useConnection, useRefreshSchema, useSchema } from "../api";

function qualified(t: SchemaTable): string {
  return t.schema_name ? `${t.schema_name}.${t.name}` : t.name;
}

/** The schema explorer: every table SQLAgent discovered, with what the model is shown. */
export function SchemaScreen({ cid }: { cid: string }) {
  const { pid, canManage, canAsk } = useCurrentProject();
  const conn = useConnection(pid, cid);
  const schema = useSchema(pid, cid);
  const refresh = useRefreshSchema(pid, cid);
  const [filter, setFilter] = React.useState("");
  const [selected, setSelected] = React.useState<string | null>(null);
  const tables = schema.data?.tables ?? [];
  const f = filter.trim().toLowerCase();
  const shown = f ? tables.filter((t) => qualified(t).toLowerCase().includes(f) || (t.columns ?? []).some((c) => c.name.toLowerCase().includes(f))) : tables;
  const current = tables.find((t) => qualified(t) === selected) ?? shown[0];

  return (
    <>
      <PageHeader
        eyebrow={
          <Link href={`/projects/${pid}/connections`} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-muted-foreground hover:text-foreground">
            <ArrowLeftIcon className="size-3.5" />
            Connections
          </Link>
        }
        title={
          <span className="inline-flex flex-wrap items-center gap-2">
            {conn.data?.name ?? <Skeleton className="h-6 w-48" />}
            {conn.data && <KindChip kind={conn.data.kind} />}
          </span>
        }
        description={
          schema.data
            ? `${plural(schema.data.table_count, "table")} and ${plural(schema.data.column_count, "column")}, read ${formatRelative(schema.data.refreshed_at)} in ${formatDuration(schema.data.duration_ms)}. This is exactly what the model is shown.`
            : "Tables, columns, keys and indexes, read from the database itself."
        }
        actions={
          <>
            {canAsk && (
              <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/projects/${pid}/ask?connection=${cid}`} />}>
                <MessageSquareTextIcon />
                Ask this database
              </Button>
            )}
            {canManage && (
              <Button
                variant="outline"
                size="sm"
                disabled={refresh.isPending}
                onClick={() =>
                  refresh.mutate(undefined, {
                    onSuccess: (s) => toast.success(`Schema read again: ${plural(s.table_count, "table")}.`),
                    onError: (err) => toast.error(errorMessage(err)),
                  })
                }
              >
                <RefreshCwIcon className={cn(refresh.isPending && "animate-spin")} />
                {refresh.isPending ? "Reading..." : "Refresh schema"}
              </Button>
            )}
          </>
        }
      />
      {schema.data?.last_error && (
        <div role="status" className="mb-4 flex items-start gap-2 rounded-xl bg-warning-soft px-4 py-3 text-[13px] text-warning">
          <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" />
          The last refresh failed ({schema.data.last_error}). The schema below is the last one read successfully.
        </div>
      )}
      {schema.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <Skeleton className="h-96 rounded-[14px]" />
          <Skeleton className="h-96 rounded-[14px]" />
        </div>
      ) : schema.isError ? (
        <div className="surface">
          <ErrorState error={schema.error} title="The schema could not be read" onRetry={() => void schema.refetch()} />
        </div>
      ) : !tables.length ? (
        <div className="surface">
          <EmptyState icon={TableIcon} title="No tables visible" description="The login can see no tables or views outside the system schemas. Grant it SELECT on the tables people should ask about, then refresh." />
        </div>
      ) : (
        <div className="grid min-w-0 gap-4 lg:grid-cols-[280px_1fr]">
          <Surface className="min-w-0 self-start p-2">
            <div className="relative p-1.5">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-faint" />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a table or column" aria-label="Find a table or column" className="pl-9" />
            </div>
            <ul className="max-h-[60vh] overflow-y-auto p-1" aria-label="Tables">
              {shown.map((t) => {
                const active = current && qualified(t) === qualified(current);
                return (
                  <li key={qualified(t)}>
                    <button
                      type="button"
                      onClick={() => setSelected(qualified(t))}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring",
                        active && "bg-primary-soft text-primary hover:bg-primary-soft",
                      )}
                    >
                      {t.kind === "view" ? <EyeIcon className="size-3.5 shrink-0" aria-hidden /> : <TableIcon className="size-3.5 shrink-0" aria-hidden />}
                      <span className="min-w-0 flex-1 truncate font-medium">{qualified(t)}</span>
                      {t.row_count != null && <span className="shrink-0 text-[11px] text-subtle tabular">{formatCompact(t.row_count)}</span>}
                    </button>
                  </li>
                );
              })}
              {!shown.length && <li className="px-3 py-6 text-center text-[12.5px] text-muted-foreground">Nothing matches.</li>}
            </ul>
          </Surface>
          {current && <TableDetail table={current} />}
        </div>
      )}
    </>
  );
}

function TableDetail({ table: t }: { table: SchemaTable }) {
  const refs = new Map<string, string>();
  for (const fk of t.foreign_keys ?? []) fk.columns.forEach((c, i) => refs.set(c, `${fk.ref_table}.${fk.ref_columns[i] ?? ""}`));
  return (
    <Surface className="min-w-0 overflow-hidden" data-qa="schema-table">
      <SurfaceHeader
        title={qualified(t)}
        titleExtra={<Chip tone={t.kind === "view" ? "info" : "neutral"}>{t.kind}</Chip>}
        description={`${plural((t.columns ?? []).length, "column")}${t.row_count != null ? `, about ${formatCompact(t.row_count)} rows` : ""}`}
      />
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Column</TableHead>
              <TableHead>Type</TableHead>
              <TableHead className="hidden sm:table-cell">Keys</TableHead>
              <TableHead className="hidden md:table-cell">Example values</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(t.columns ?? []).map((c) => (
              <TableRow key={c.name}>
                <TableCell className="font-mono text-[12.5px] font-medium">{c.name}</TableCell>
                <TableCell className="font-mono text-[12px] text-muted-foreground">
                  {c.type}
                  {!c.nullable && <span className="ml-1.5 text-subtle">not null</span>}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {c.primary_key && (
                      <Chip tone="primary">
                        <KeyRoundIcon aria-hidden />
                        Primary
                      </Chip>
                    )}
                    {refs.has(c.name) && (
                      <Chip tone="info" title={refs.get(c.name)}>
                        <LinkIcon aria-hidden />
                        {refs.get(c.name)}
                      </Chip>
                    )}
                  </div>
                </TableCell>
                <TableCell className="hidden max-w-[320px] truncate text-[12px] text-muted-foreground md:table-cell" title={(c.sample_values ?? []).join(", ")}>
                  {(c.sample_values ?? []).join(", ") || <span className="text-faint">Not sampled</span>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {(t.indexes ?? []).length > 0 && (
        <div className="px-5 py-4 text-[12.5px]">
          <div className="mb-2 font-semibold">Indexes</div>
          <ul className="space-y-1 text-muted-foreground">
            {(t.indexes ?? []).map((ix) => (
              <li key={ix.name} className="font-mono text-[12px]">
                {ix.name} ({ix.columns.join(", ")}){ix.unique ? " unique" : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Surface>
  );
}
