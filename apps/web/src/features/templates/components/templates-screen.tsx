"use client";

import { BookmarkIcon, CodeIcon, MessageSquareTextIcon, PlayIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/features/projects/api";
import { errorMessage } from "@/lib/api/errors";
import type { Template } from "@/lib/api/types";
import { plural } from "@/lib/format";

import { useDeleteTemplate, useRunTemplate, useTemplates } from "../api";

export function TemplatesScreen() {
  const { pid, canAsk } = useCurrentProject();
  const q = useTemplates(pid);
  const list = q.data ?? [];
  return (
    <>
      <PageHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            Templates <Hint term="template" />
          </span>
        }
        description="Questions the team asks again and again. Run one to get today's answer in a new conversation."
      />
      {q.isPending ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-40 rounded-[14px]" />
          ))}
        </div>
      ) : q.isError ? (
        <div className="surface">
          <ErrorState error={q.error} title="Templates could not be loaded" onRetry={() => void q.refetch()} />
        </div>
      ) : !list.length ? (
        <div className="surface">
          <EmptyState
            icon={BookmarkIcon}
            title="No templates yet"
            description="Ask a question, then choose 'Save as template' under its answer. It shows up here for the whole project."
            action={
              canAsk ? (
                <Button nativeButton={false} render={<Link href={`/projects/${pid}/ask`} />}>
                  <MessageSquareTextIcon />
                  Ask a question
                </Button>
              ) : undefined
            }
          />
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {list.map((t) => (
            <TemplateCard key={t.id} pid={pid} t={t} canAsk={canAsk} />
          ))}
        </div>
      )}
    </>
  );
}

export function TemplateCard({ pid, t, canAsk, compact = false }: { pid: string; t: Template; canAsk: boolean; compact?: boolean }) {
  const run = useRunTemplate(pid);
  const del = useDeleteTemplate(pid);
  const router = useRouter();
  const [deleting, setDeleting] = React.useState(false);
  return (
    <article className="surface flex min-w-0 flex-col gap-3 p-5" data-qa="template">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-[14.5px] font-semibold">{t.name}</h2>
          <p className="mt-0.5 text-[13px] text-muted-foreground">&ldquo;{t.question}&rdquo;</p>
        </div>
        {t.sql && (
          <Chip tone="primary" title="Runs its saved SQL as is">
            <CodeIcon aria-hidden />
            Saved SQL
          </Chip>
        )}
      </div>
      {!compact && t.description && <p className="text-[12.5px] text-muted-foreground">{t.description}</p>}
      <div className="mt-auto flex items-center justify-between gap-2 text-[12px] text-subtle">
        <span className="truncate">
          {t.connection_name}, run {plural(t.use_count, "time")}
        </span>
        <div className="flex shrink-0 gap-1.5">
          {canAsk && !compact && (
            <Button variant="subtle" size="icon-xs" aria-label={`Delete ${t.name}`} onClick={() => setDeleting(true)}>
              <Trash2Icon />
            </Button>
          )}
          {canAsk && (
            <Button
              size="xs"
              disabled={run.isPending}
              onClick={() =>
                run.mutate(t.id, {
                  onSuccess: (msg) => router.push(`/projects/${pid}/ask?c=${msg.conversation_id}`),
                  onError: (err) => toast.error(errorMessage(err)),
                })
              }
            >
              <PlayIcon />
              {run.isPending ? "Running..." : "Run"}
            </Button>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${t.name}?`}
        description="The template goes; conversations it started stay in History."
        confirmLabel="Delete template"
        pending={del.isPending}
        onConfirm={() =>
          del.mutate(t.id, {
            onSuccess: () => {
              setDeleting(false);
              toast.success("Template deleted.");
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </article>
  );
}
