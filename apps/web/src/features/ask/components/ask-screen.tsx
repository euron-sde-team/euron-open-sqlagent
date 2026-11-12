"use client";

import { ArrowUpIcon, BookOpenTextIcon, DatabaseIcon, MessageSquarePlusIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { RoleNote } from "@/components/role-note";
import { KindChip } from "@/components/status-chips";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useConnections, useSchema } from "@/features/connections/api";
import { useCurrentProject } from "@/features/projects/api";
import { useTemplates } from "@/features/templates/api";
import { errorMessage } from "@/lib/api/errors";
import type { Answer, Connection } from "@/lib/api/types";

import { useAsk, useConversation } from "../api";
import { suggestionsFor } from "../suggestions";

import { AnswerCard } from "./answer-card";
import { ExplainDialog } from "./explain-dialog";

export function AskScreen() {
  const { pid, canAsk, query: projectQuery } = useCurrentProject();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const conversationId = params.get("c");
  const connections = useConnections(pid);
  const conversation = useConversation(pid, conversationId);
  const [picked, setPicked] = React.useState<string>(params.get("connection") ?? "");
  const [question, setQuestion] = React.useState(params.get("q") ?? "");
  const [pending, setPending] = React.useState<Answer[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [explaining, setExplaining] = React.useState(false);
  const ask = useAsk(pid);
  const bottom = React.useRef<HTMLDivElement>(null);

  const list = connections.data ?? [];
  const connectionId = conversation.data?.connection_id ?? (picked || list[0]?.id || "");
  const connection = list.find((c) => c.id === connectionId);
  const schema = useSchema(pid, connectionId || null);
  const templates = useTemplates(pid);
  const messages = conversation.data?.messages ?? [];
  const known = new Set(messages.map((m) => m.id));
  const shown = [...messages, ...pending.filter((p) => !known.has(p.id))];

  React.useEffect(() => {
    setPending([]);
  }, [conversationId]);
  React.useEffect(() => {
    if (shown.length) bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [shown.length]);

  function submit(text: string) {
    const q = text.trim();
    if (!q) return setError("Type a question first, like 'How many orders per status?'");
    if (!connectionId) return setError("Choose the database to ask about.");
    setError(null);
    ask.mutate(
      { question: q, ...(conversationId ? { conversation_id: conversationId } : { connection_id: connectionId }) },
      {
        onSuccess: (msg) => {
          setQuestion("");
          setPending((p) => [...p, msg]);
          if (!conversationId) router.replace(`${pathname}?c=${msg.conversation_id}`, { scroll: false });
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  const templateQuestions = (templates.data ?? []).filter((t) => t.connection_id === connectionId).map((t) => t.question);
  const suggestions = suggestionsFor(schema.data?.tables ?? [], templateQuestions);

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col">
      <PageHeader
        title={conversation.data ? conversation.data.title : "Ask your data"}
        description={
          conversation.data
            ? `A conversation on ${conversation.data.connection_name}. Follow-up questions see the earlier ones.`
            : "Ask in plain English. SQLAgent writes one query against the real schema, checks it is read-only, and runs it on a read-only connection."
        }
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => setExplaining(true)} disabled={!canAsk}>
              <BookOpenTextIcon />
              Explain SQL
            </Button>
            {conversationId && (
              <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/projects/${pid}/ask?connection=${connectionId}`} />}>
                <MessageSquarePlusIcon />
                New conversation
              </Button>
            )}
          </>
        }
      />

      {connections.isPending || projectQuery.isPending || (conversationId && conversation.isPending) ? (
        <div className="space-y-3">
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-48 w-full rounded-2xl" />
        </div>
      ) : connections.isError ? (
        <div className="surface">
          <ErrorState error={connections.error} onRetry={() => void connections.refetch()} />
        </div>
      ) : conversation.isError ? (
        <div className="surface">
          <ErrorState error={conversation.error} title="This conversation could not be opened" onRetry={() => void conversation.refetch()} />
        </div>
      ) : !list.length ? (
        <div className="surface">
          <EmptyState
            icon={DatabaseIcon}
            title="Connect a database to ask about"
            description="SQLAgent answers questions about a PostgreSQL, MySQL or SQLite database you connect. The connection is read-only, and every query is checked before it runs."
            action={
              <Button nativeButton={false} render={<Link href={`/projects/${pid}/connections`} />}>
                <DatabaseIcon />
                Add a connection
              </Button>
            }
          />
        </div>
      ) : (
        <>
          {!conversationId && (
            <div className="mb-4 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
              <span>Database</span>
              <SimpleSelect
                aria-label="Database to ask about"
                value={connectionId}
                onValueChange={(v) => setPicked(v)}
                options={list.map((c: Connection) => ({ value: c.id, label: c.name }))}
                className="w-64"
              />
              {connection && <KindChip kind={connection.kind} />}
              {connection?.tables != null && <span className="text-subtle">{connection.tables} tables</span>}
            </div>
          )}

          <div className="space-y-7 pb-4">
            {shown.length === 0 && (
              <div className="surface px-5 py-8 text-center sm:px-10">
                <div className="mx-auto mb-3.5 flex size-11 items-center justify-center rounded-xl bg-primary-soft text-primary">
                  <SparklesIcon className="size-5" />
                </div>
                <h2 className="text-[15px] font-semibold">What do you want to know?</h2>
                <p className="mx-auto mt-1 max-w-md text-[13px] leading-relaxed text-muted-foreground">
                  Questions about {connection?.name ?? "this database"} in plain English. You will see the SQL, whether it passed the guard, the result and a
                  chart when one fits.
                </p>
                {canAsk && suggestions.length > 0 && (
                  <div className="mt-5 flex flex-wrap justify-center gap-2" aria-label="Suggested questions">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => submit(s)}
                        disabled={ask.isPending}
                        className="rounded-full bg-muted px-3.5 py-1.5 text-[12.5px] font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {shown.map((m) => (
              <AnswerCard key={m.id} pid={pid} answer={m} canAsk={canAsk} />
            ))}
            <div ref={bottom} />
          </div>

          {canAsk ? (
            <form
              className="sticky bottom-0 z-10 -mx-2 mt-2 bg-background px-2 pt-2 pb-3 before:pointer-events-none before:absolute before:inset-x-0 before:-top-6 before:h-6 before:bg-gradient-to-t before:from-background before:to-transparent"
              onSubmit={(e) => {
                e.preventDefault();
                submit(question);
              }}
            >
              <div className="surface flex items-end gap-2 p-2 shadow-[var(--elev-3)]">
                <Textarea
                  aria-label={conversationId ? "Ask a follow-up question" : "Ask a question"}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      submit(question);
                    }
                  }}
                  placeholder={conversationId ? "Ask a follow-up, like 'and last year?'" : "How many orders were placed this year?"}
                  rows={1}
                  className="min-h-10 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
                />
                <Button type="submit" size="icon" aria-label="Ask" disabled={ask.isPending || !question.trim()}>
                  <ArrowUpIcon />
                </Button>
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-2 px-1 text-[11.5px] text-subtle">
                {error ? <FieldError>{error}</FieldError> : <span>Enter to ask, Shift and Enter for a new line.</span>}
                {conversationId && (
                  <span className="hidden items-center gap-1 sm:inline-flex">
                    Follow-ups keep the context <Hint term="followUp" />
                  </span>
                )}
              </div>
            </form>
          ) : (
            <RoleNote>Viewers read conversations and results. Ask a project admin for the editor role to ask questions.</RoleNote>
          )}
        </>
      )}
      <ExplainDialog pid={pid} connectionId={connectionId || null} open={explaining} onOpenChange={setExplaining} />
    </div>
  );
}
