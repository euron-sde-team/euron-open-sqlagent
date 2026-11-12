"use client";

import {
  CheckCircle2Icon,
  DatabaseIcon,
  MessageSquareTextIcon,
  MoreHorizontalIcon,
  PlugZapIcon,
  PlusIcon,
  ShieldCheckIcon,
  TableIcon,
  Trash2Icon,
  XCircleIcon,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { RoleNote } from "@/components/role-note";
import { KindChip } from "@/components/status-chips";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/features/projects/api";
import { errorMessage } from "@/lib/api/errors";
import type { Connection } from "@/lib/api/types";
import { formatBytes, formatCompact, formatRelative, plural } from "@/lib/format";

import { useConnections, useDeleteConnection, useTestConnection } from "../api";

import { ConnectionDialog } from "./connection-dialog";

export function ConnectionsScreen() {
  const { pid, canManage, canAsk } = useCurrentProject();
  const q = useConnections(pid);
  const [adding, setAdding] = React.useState(false);
  const list = q.data ?? [];
  return (
    <>
      <PageHeader
        title="Connections"
        description="The databases this project asks questions about. Every connection is opened read-only, and every query runs under its limits."
        actions={
          canManage && (
            <Button onClick={() => setAdding(true)}>
              <PlusIcon />
              Add a database
            </Button>
          )
        }
      />
      {!canManage && <RoleNote className="mb-4">You can browse connections and their schemas. Editors and admins add and change them.</RoleNote>}
      {q.isPending ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-56 rounded-[14px]" />
          ))}
        </div>
      ) : q.isError ? (
        <div className="surface">
          <ErrorState error={q.error} title="Connections could not be loaded" onRetry={() => void q.refetch()} />
        </div>
      ) : !list.length ? (
        <div className="surface">
          <EmptyState
            icon={DatabaseIcon}
            title="No databases yet"
            description="Connect PostgreSQL, MySQL or a SQLite file. SQLAgent reads its schema, and everyone in the project can then ask it questions in plain English."
            action={
              canManage ? (
                <Button onClick={() => setAdding(true)}>
                  <PlusIcon />
                  Add a database
                </Button>
              ) : undefined
            }
          />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {list.map((c) => (
            <ConnectionCard key={c.id} pid={pid} c={c} canManage={canManage} canAsk={canAsk} />
          ))}
        </div>
      )}
      <ConnectionDialog pid={pid} open={adding} onOpenChange={setAdding} />
    </>
  );
}

function ConnectionCard({ pid, c, canManage, canAsk }: { pid: string; c: Connection; canManage: boolean; canAsk: boolean }) {
  const test = useTestConnection(pid);
  const del = useDeleteConnection(pid);
  const [deleting, setDeleting] = React.useState(false);
  const where = c.kind === "sqlite" ? `${c.file_name ?? "file"} (${formatBytes(c.file_size)})` : `${c.username}@${c.host}:${c.port}/${c.database}`;
  return (
    <article className="surface flex min-w-0 flex-col gap-4 p-5" data-qa="connection">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
          <DatabaseIcon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-[15px] font-semibold tracking-[-0.01em]">{c.name}</h2>
            <KindChip kind={c.kind} />
          </div>
          <p className="mt-0.5 truncate font-mono text-[11.5px] text-subtle" title={where}>
            {where}
          </p>
          {c.description && <p className="mt-1 line-clamp-2 text-[12.5px] text-muted-foreground">{c.description}</p>}
        </div>
        {canManage && (
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="subtle" size="icon-sm" aria-label={`More for ${c.name}`} />}>
              <MoreHorizontalIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem variant="destructive" onClick={() => setDeleting(true)}>
                <Trash2Icon />
                Delete connection
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2 rounded-xl bg-muted/70 px-4 py-3 text-[12px]">
        <Figure label="Tables" value={c.tables != null ? String(c.tables) : "Not read yet"} />
        <Figure label="Row limit" value={formatCompact(c.max_rows)} hint="rowLimit" />
        <Figure label="Timeout" value={`${c.timeout_s} s`} hint="timeout" />
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px]">
        <span className="inline-flex items-center gap-1 font-medium text-savings">
          <ShieldCheckIcon className="size-3.5" aria-hidden />
          Read-only
          <Hint term="readOnlyConnection" />
        </span>
        {c.last_tested_at ? (
          c.last_test_ok ? (
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              <CheckCircle2Icon className="size-3.5 text-savings" aria-hidden />
              Tested {formatRelative(c.last_tested_at)}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-danger" title={c.last_test_message ?? ""}>
              <XCircleIcon className="size-3.5" aria-hidden />
              Last test failed
            </span>
          )
        ) : (
          <span className="text-subtle">Not tested yet</span>
        )}
        {c.server_version && <span className="truncate text-subtle">{c.server_version.split(" on ")[0]?.slice(0, 40)}</span>}
        <span className="text-subtle">{plural(c.conversations ?? 0, "conversation")}</span>
      </div>

      <div className="mt-auto flex flex-wrap gap-2">
        <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/projects/${pid}/connections/${c.id}`} />}>
          <TableIcon />
          Schema
        </Button>
        {canAsk && (
          <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/projects/${pid}/ask?connection=${c.id}`} />}>
            <MessageSquareTextIcon />
            Ask
          </Button>
        )}
        {canManage && (
          <Button
            variant="ghost"
            size="sm"
            disabled={test.isPending}
            onClick={() =>
              test.mutate(c.id, {
                onSuccess: (r) =>
                  r.ok ? toast.success(`${r.message} (${Math.round(r.latency_ms)} ms)`) : toast.error(r.message),
                onError: (err) => toast.error(errorMessage(err)),
              })
            }
          >
            <PlugZapIcon />
            {test.isPending ? "Testing..." : "Test"}
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${c.name}?`}
        description="Its schema cache, conversations and templates go with it. The database itself is untouched, and the audit log keeps every query that ran."
        confirmLabel="Delete connection"
        pending={del.isPending}
        onConfirm={() =>
          del.mutate(c.id, {
            onSuccess: () => {
              setDeleting(false);
              toast.success(`${c.name} deleted.`);
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </article>
  );
}

function Figure({ label, value, hint }: { label: string; value: string; hint?: "rowLimit" | "timeout" }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 text-subtle">
        {label}
        {hint && <Hint term={hint} />}
      </div>
      <div className="mt-0.5 truncate text-[14px] font-semibold tabular">{value}</div>
    </div>
  );
}
