"use client";

import { BookmarkPlusIcon, CpuIcon, Loader2Icon, ShieldXIcon, TimerIcon, TriangleAlertIcon, UserIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { CodeBlock } from "@/components/code-block";
import { Hint } from "@/components/hint";
import { AnswerStatusChip, GuardBadge } from "@/components/status-chips";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/api/errors";
import type { Answer } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDuration, formatRelative } from "@/lib/format";
import { inFlight } from "@/lib/status";

import { useMessage, useSaveTemplate } from "../api";

import { ResultView } from "./result-view";

/**
 * One question and everything SQLAgent did with it: the generated SQL with its guard
 * verdict, the plain-language explanation, then the result (or why nothing ran).
 */
export function AnswerCard({ pid, answer, canAsk }: { pid: string; answer: Answer; canAsk: boolean }) {
  const live = useMessage(pid, answer.id, answer);
  const a = live.data ?? answer;
  const pending = inFlight(a.status);
  const [saving, setSaving] = React.useState(false);
  return (
    <article className="space-y-3" data-qa="answer" aria-busy={pending}>
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[14px] leading-relaxed text-primary-foreground shadow-[var(--elev-1)]">
          {a.question}
        </div>
      </div>
      <div className="surface min-w-0 space-y-3.5 p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <AnswerStatusChip status={a.status} />
            {a.sql && !pending && <GuardBadge validated={a.validated} />}
            {a.validated && <Hint term="sqlGuard" />}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-subtle">
            {a.model && (
              <span className="inline-flex items-center gap-1">
                <CpuIcon className="size-3" aria-hidden />
                {a.provider_name}/{a.model}
              </span>
            )}
            {!pending && a.total_ms > 0 && (
              <span className="inline-flex items-center gap-1 tabular">
                <TimerIcon className="size-3" aria-hidden />
                {formatDuration(a.total_ms)}
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              <UserIcon className="size-3" aria-hidden />
              {a.actor_label}, {formatRelative(a.created_at)}
            </span>
          </div>
        </div>

        {pending ? (
          <div className="flex items-center gap-2.5 rounded-xl bg-muted/60 px-4 py-3 text-[13px] text-muted-foreground" role="status">
            <Loader2Icon className="size-4 animate-spin text-primary" aria-hidden />
            {a.status === "queued" ? "Waiting for a worker..." : "Reading the schema, writing the query, checking it and running it read-only..."}
          </div>
        ) : (
          <>
            {a.sql && <CodeBlock value={a.sql} label="SQL" maxLines={18} />}
            {a.explanation && a.status !== "no_answer" && <p className="text-[13.5px] leading-relaxed text-foreground/90">{a.explanation}</p>}
            {a.status === "refused" && (
              <Notice tone="danger" icon={ShieldXIcon} title="This query was not run">
                The SQL guard refused it: {a.error}. Only one read-only SELECT ever reaches the database.
              </Notice>
            )}
            {a.status === "failed" && (
              <Notice tone="warning" icon={TriangleAlertIcon} title="The query did not finish">
                {a.error}
              </Notice>
            )}
            {a.status === "no_answer" && (
              <Notice tone="warning" icon={TriangleAlertIcon} title="No query for this question">
                {a.error || a.explanation}
              </Notice>
            )}
            {a.status === "answered" && a.execution && <ResultView pid={pid} execution={a.execution} firstPage={a.page} />}
            {a.status === "answered" && canAsk && (
              <div className="flex justify-end">
                <Button variant="subtle" size="xs" onClick={() => setSaving(true)}>
                  <BookmarkPlusIcon />
                  Save as template
                </Button>
              </div>
            )}
          </>
        )}
      </div>
      {saving && <SaveTemplateDialog pid={pid} answer={a} onClose={() => setSaving(false)} />}
    </article>
  );
}

function Notice({
  tone,
  icon: Icon,
  title,
  children,
}: {
  tone: "danger" | "warning";
  icon: typeof ShieldXIcon;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div role="alert" className={cn("flex gap-2.5 rounded-xl px-4 py-3 text-[13px] leading-relaxed", tone === "danger" ? "bg-danger-soft text-danger" : "bg-warning-soft text-warning")}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div>
        <div className="font-semibold">{title}</div>
        <div className="mt-0.5 text-foreground/80">{children}</div>
      </div>
    </div>
  );
}

function SaveTemplateDialog({ pid, answer, onClose }: { pid: string; answer: Answer; onClose: () => void }) {
  const save = useSaveTemplate(pid);
  const [name, setName] = React.useState(answer.question.slice(0, 60));
  const [keepSql, setKeepSql] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Give the template a short name.");
    save.mutate(
      { message_id: answer.id, name: name.trim(), keep_sql: keepSql },
      {
        onSuccess: () => {
          toast.success("Saved. Run it again from Templates.");
          onClose();
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={submit} noValidate>
          <DialogHeader>
            <DialogTitle>Save as a template</DialogTitle>
            <DialogDescription>Ask this question again with one click, from Templates or the overview.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <Field label="Name" htmlFor="tpl-name" error={error}>
              <Input id="tpl-name" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            </Field>
            <label className="flex items-start gap-3 rounded-xl bg-muted/60 px-3.5 py-3 text-[13px]">
              <Switch checked={keepSql} onCheckedChange={setKeepSql} aria-label="Keep the SQL" />
              <span>
                <span className="font-medium">Keep this SQL</span>
                <span className="block text-muted-foreground">Run the checked query as is next time, without asking the model again.</span>
              </span>
            </label>
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "Saving..." : "Save template"}
            </Button>
          </DialogFooter>
          {error && <FieldError className="sr-only">{error}</FieldError>}
        </form>
      </DialogContent>
    </Dialog>
  );
}
