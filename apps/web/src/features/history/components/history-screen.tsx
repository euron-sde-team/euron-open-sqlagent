"use client";

import { HistoryIcon, MessageSquareTextIcon, SearchIcon, TerminalSquareIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { AnswerStatusChip, ExecutionStatusChip } from "@/components/status-chips";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useConversations, useDeleteConversation } from "@/features/ask/api";
import { useConnections } from "@/features/connections/api";
import { useCurrentProject } from "@/features/projects/api";
import { errorMessage } from "@/lib/api/errors";
import type { Conversation } from "@/lib/api/types";
import { formatDateTime, formatDuration, formatNumber, formatRelative, plural } from "@/lib/format";
import { useTabParam } from "@/lib/use-tab-param";

import { useExecutions, type ExecutionStatusFilter } from "../api";

const TABS = ["conversations", "queries"] as const;

export function HistoryScreen() {
  const { pid } = useCurrentProject();
  const [tab, setTab] = useTabParam("conversations", TABS);
  const connections = useConnections(pid);
  const [connectionId, setConnectionId] = React.useState("");
  const options = [{ value: "", label: "Every database" }, ...(connections.data ?? []).map((c) => ({ value: c.id, label: c.name }))];
  return (
    <>
      <PageHeader title="History" description="Every conversation, replayable with its SQL and results, and every query that ran (or was refused) against your databases." />
      <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <TabsList>
            <TabsTrigger value="conversations">
              <MessageSquareTextIcon />
              Conversations
            </TabsTrigger>
            <TabsTrigger value="queries">
              <TerminalSquareIcon />
              Queries
            </TabsTrigger>
          </TabsList>
          <SimpleSelect aria-label="Database" value={connectionId} onValueChange={setConnectionId} options={options} className="w-full sm:w-60" />
        </div>
        <TabsContent value="conversations">
          <Conversations pid={pid} connectionId={connectionId} />
        </TabsContent>
        <TabsContent value="queries">
          <Queries pid={pid} connectionId={connectionId} />
        </TabsContent>
      </Tabs>
    </>
  );
}

function Conversations({ pid, connectionId }: { pid: string; connectionId: string }) {
  const { canAsk } = useCurrentProject();
  const [input, setInput] = React.useState("");
  const [search, setSearch] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setSearch(input.trim()), 300);
    return () => clearTimeout(t);
  }, [input]);
  const q = useConversations(pid, { connectionId, q: search });
  const del = useDeleteConversation(pid);
  const [deleting, setDeleting] = React.useState<Conversation | null>(null);
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <>
      <div className="relative mb-3 w-full sm:w-80">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
        <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Search questions" aria-label="Search conversations" className="pl-9" />
      </div>
      <Surface className="overflow-hidden">
        {q.isPending ? (
          <div className="pt-3">
            <TableSkeleton rows={8} cols={4} />
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} title="Conversations could not be loaded" onRetry={() => void q.refetch()} />
        ) : !rows.length ? (
          <EmptyState
            icon={HistoryIcon}
            title={search ? "Nothing matches" : "No conversations yet"}
            description={search ? "Try other words from the question." : "Every question asked in this project lands here, with its SQL and result, so anyone can replay it later."}
            action={
              canAsk && !search ? (
                <Button nativeButton={false} render={<Link href={`/projects/${pid}/ask`} />}>
                  <MessageSquareTextIcon />
                  Ask a question
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Question</TableHead>
                  <TableHead className="hidden md:table-cell">Database</TableHead>
                  <TableHead className="hidden sm:table-cell">Latest</TableHead>
                  <TableHead className="hidden lg:table-cell">Asked by</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="max-w-[380px]">
                      <Link href={`/projects/${pid}/ask?c=${c.id}`} className="block truncate font-medium text-foreground hover:text-primary">
                        {c.title}
                      </Link>
                      <div className="text-[11.5px] text-subtle">
                        {plural(c.message_count, "question")}, {formatRelative(c.last_message_at)}
                      </div>
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground md:table-cell">{c.connection_name}</TableCell>
                    <TableCell className="hidden sm:table-cell">{c.last_status && <AnswerStatusChip status={c.last_status} />}</TableCell>
                    <TableCell className="hidden truncate text-muted-foreground lg:table-cell">{c.created_by_label}</TableCell>
                    <TableCell>
                      {canAsk && (
                        <Button variant="subtle" size="icon-xs" aria-label={`Delete ${c.title}`} onClick={() => setDeleting(c)}>
                          <Trash2Icon />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Footer count={rows.length} noun="conversation" hasMore={!!q.hasNextPage} loading={q.isFetchingNextPage} onMore={() => void q.fetchNextPage()} />
          </>
        )}
      </Surface>
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this conversation?"
        description="Its questions and results go. The audit log keeps every query that ran."
        confirmLabel="Delete"
        pending={del.isPending}
        onConfirm={() =>
          deleting &&
          del.mutate(deleting.id, {
            onSuccess: () => {
              setDeleting(null);
              toast.success("Conversation deleted.");
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </>
  );
}

const STATUS_OPTIONS: { value: ExecutionStatusFilter | ""; label: string }[] = [
  { value: "", label: "Every status" },
  { value: "succeeded", label: "Succeeded" },
  { value: "refused", label: "Refused by the guard" },
  { value: "failed", label: "Failed" },
  { value: "timeout", label: "Timed out" },
  { value: "scan_limit", label: "Over the scan limit" },
];

function Queries({ pid, connectionId }: { pid: string; connectionId: string }) {
  const [status, setStatus] = React.useState<ExecutionStatusFilter | "">("");
  const q = useExecutions(pid, { connectionId, status });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <>
      <SimpleSelect aria-label="Status" value={status} onValueChange={(v) => setStatus(v as ExecutionStatusFilter | "")} options={STATUS_OPTIONS} className="mb-3 w-full sm:w-60" />
      <Surface className="overflow-hidden">
        {q.isPending ? (
          <div className="pt-3">
            <TableSkeleton rows={8} cols={4} />
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} title="Queries could not be loaded" onRetry={() => void q.refetch()} />
        ) : !rows.length ? (
          <EmptyState
            icon={TerminalSquareIcon}
            title={status ? "No queries with this status" : "No queries yet"}
            description="Every query SQLAgent runs, or refuses to run, is listed here with its SQL, status, row count and duration."
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>SQL</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="hidden text-right sm:table-cell">Rows</TableHead>
                  <TableHead className="hidden text-right md:table-cell">Took</TableHead>
                  <TableHead className="hidden lg:table-cell">When</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="max-w-[420px]">
                      <div className="truncate font-mono text-[12px]" title={e.sql}>
                        {e.sql.replace(/\s+/g, " ")}
                      </div>
                      <div className="truncate text-[11.5px] text-subtle">
                        {e.actor_label}
                        {e.error ? `: ${e.error}` : ""}
                      </div>
                    </TableCell>
                    <TableCell>
                      <ExecutionStatusChip status={e.status} />
                    </TableCell>
                    <TableCell className="hidden text-right tabular sm:table-cell">{formatNumber(e.row_count)}</TableCell>
                    <TableCell className="hidden text-right tabular md:table-cell">{e.status === "refused" ? "Not run" : formatDuration(e.duration_ms)}</TableCell>
                    <TableCell className="hidden whitespace-nowrap text-muted-foreground lg:table-cell" title={formatDateTime(e.created_at)}>
                      {formatRelative(e.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Footer count={rows.length} noun="query" nouns="queries" hasMore={!!q.hasNextPage} loading={q.isFetchingNextPage} onMore={() => void q.fetchNextPage()} />
          </>
        )}
      </Surface>
    </>
  );
}

function Footer({ count, noun, nouns, hasMore, loading, onMore }: { count: number; noun: string; nouns?: string; hasMore: boolean; loading: boolean; onMore: () => void }) {
  return (
    <div className="flex items-center justify-between px-5 py-3 text-xs text-muted-foreground">
      <span>{plural(count, noun, nouns)}</span>
      {hasMore ? (
        <Button variant="outline" size="sm" onClick={onMore} disabled={loading}>
          {loading ? "Loading..." : "Load older"}
        </Button>
      ) : (
        <span>That is all</span>
      )}
    </div>
  );
}
