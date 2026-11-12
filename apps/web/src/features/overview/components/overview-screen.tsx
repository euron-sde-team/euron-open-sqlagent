"use client";

import { ArrowRightIcon, CpuIcon, DatabaseIcon, GaugeIcon, MessageSquareTextIcon, ShieldXIcon, TimerIcon, TrendingUpIcon } from "lucide-react";
import Link from "next/link";

import { QuestionsByDayChart } from "@/components/charts/day-charts";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { Stat } from "@/components/stat";
import { AnswerStatusChip, KindChip } from "@/components/status-chips";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/features/projects/api";
import { useProviders } from "@/features/providers/api";
import { TemplateCard } from "@/features/templates/components/templates-screen";
import { formatDuration, formatNumber, formatPercent, formatRelative, plural } from "@/lib/format";

import { useOverview } from "../api";

export function OverviewScreen() {
  const { pid, project, canAsk, canAdmin, canManage } = useCurrentProject();
  const q = useOverview(pid);
  const providers = useProviders(pid);
  const d = q.data;
  const answeredRate = d && d.questions_7d ? d.answered_7d / d.questions_7d : null;
  const noProvider = providers.isSuccess && !providers.data.some((p) => p.enabled);

  return (
    <>
      <PageHeader
        title={project?.name ?? "Overview"}
        description={project?.description || "Questions asked in this project, what ran, and what the SQL guard stopped."}
        actions={
          canAsk && (
            <Button nativeButton={false} render={<Link href={`/projects/${pid}/ask`} />}>
              <MessageSquareTextIcon />
              Ask a question
            </Button>
          )
        }
      />
      {noProvider && (
        <div role="status" className="mb-4 flex flex-col gap-2 rounded-xl bg-warning-soft px-4 py-3 text-[13px] text-warning sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-center gap-2">
            <CpuIcon className="size-4 shrink-0" />
            No model provider yet, so questions cannot be answered. {canAdmin ? "Add one (the built-in mock needs no key)." : "Ask a project admin to add one."}
          </span>
          {canAdmin && (
            <Button size="sm" variant="outline" nativeButton={false} render={<Link href={`/projects/${pid}/settings?tab=providers`} />}>
              Model providers
            </Button>
          )}
        </div>
      )}
      {q.isError ? (
        <div className="surface">
          <ErrorState error={q.error} title="The overview could not be loaded" onRetry={() => void q.refetch()} />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Questions, 7 days" icon={MessageSquareTextIcon} loading={!d} value={d ? formatNumber(d.questions_7d) : ""} detail={d ? `${plural(d.conversations, "conversation")} in all` : undefined} />
            <Stat
              label="Answered"
              icon={TrendingUpIcon}
              loading={!d}
              value={answeredRate == null ? "None yet" : formatPercent(answeredRate, 0)}
              tone={answeredRate != null && answeredRate >= 0.8 ? "good" : "default"}
              detail={d ? `${formatNumber(d.rows_returned_7d)} rows returned` : undefined}
            />
            <Stat
              label="Refused by the guard"
              icon={ShieldXIcon}
              loading={!d}
              value={d ? formatNumber(d.refused_7d) : ""}
              tone={d && d.refused_7d > 0 ? "warn" : "default"}
              detail={<span className="inline-flex items-center gap-1">Never reached a database <Hint term="sqlGuard" /></span>}
            />
            <Stat label="Median query time" icon={TimerIcon} loading={!d} value={d?.median_query_ms != null ? formatDuration(d.median_query_ms) : "None yet"} detail={d ? `${formatNumber(d.executions_7d)} queries run` : undefined} />
          </div>

          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[1.4fr_1fr]">
            <Surface>
              <SurfaceHeader title="Questions per day" description="The last 14 days." />
              <div className="px-5 pb-5">{d ? <QuestionsByDayChart days={d.by_day} /> : <Skeleton className="h-[250px] w-full" />}</div>
            </Surface>
            <Surface>
              <SurfaceHeader
                title="Databases"
                action={
                  <Link href={`/projects/${pid}/connections`} className="text-[12.5px] font-medium text-primary hover:underline">
                    All connections
                  </Link>
                }
              />
              <div className="px-3 pb-3">
                {!d ? (
                  <Skeleton className="mx-2 h-40" />
                ) : !d.connections.length ? (
                  <EmptyState
                    compact
                    icon={DatabaseIcon}
                    title="Connect your first database"
                    description="PostgreSQL, MySQL or a SQLite file. It is opened read-only, and its schema is read for you."
                    action={
                      canManage ? (
                        <Button size="sm" nativeButton={false} render={<Link href={`/projects/${pid}/connections`} />}>
                          Add a database
                        </Button>
                      ) : undefined
                    }
                  />
                ) : (
                  <ul className="space-y-1">
                    {d.connections.map((c) => (
                      <li key={c.id}>
                        <Link
                          href={`/projects/${pid}/connections/${c.id}`}
                          className="flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                        >
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
                            <DatabaseIcon className="size-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className="truncate text-[13.5px] font-medium">{c.name}</span>
                              <KindChip kind={c.kind} />
                            </span>
                            <span className="block truncate text-[12px] text-subtle">
                              {c.tables != null ? plural(c.tables, "table") : "Schema not read yet"}, {plural(c.conversations ?? 0, "conversation")}
                            </span>
                          </span>
                          <ArrowRightIcon className="size-3.5 text-faint" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Surface>
          </div>

          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[1.4fr_1fr]">
            <Surface>
              <SurfaceHeader
                title="Recent conversations"
                action={
                  <Link href={`/projects/${pid}/history`} className="text-[12.5px] font-medium text-primary hover:underline">
                    History
                  </Link>
                }
              />
              <div className="px-3 pb-3">
                {!d ? (
                  <Skeleton className="mx-2 h-48" />
                ) : !d.recent.length ? (
                  <EmptyState
                    compact
                    icon={GaugeIcon}
                    title="No questions yet"
                    description="Ask something like 'How many orders per status?'. The answer, its SQL and its chart land here."
                  />
                ) : (
                  <ul className="space-y-0.5">
                    {d.recent.map((c) => (
                      <li key={c.id}>
                        <Link
                          href={`/projects/${pid}/ask?c=${c.id}`}
                          className="flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[13.5px] font-medium">{c.title}</span>
                            <span className="block truncate text-[12px] text-subtle">
                              {c.connection_name}, {c.created_by_label}, {formatRelative(c.last_message_at)}
                            </span>
                          </span>
                          {c.last_status && <AnswerStatusChip status={c.last_status} />}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Surface>
            <div className="min-w-0 space-y-3">
              <div className="flex items-center justify-between px-1">
                <h2 className="text-[14px] font-semibold">Templates</h2>
                <Link href={`/projects/${pid}/templates`} className="text-[12.5px] font-medium text-primary hover:underline">
                  All templates
                </Link>
              </div>
              {!d ? (
                <Skeleton className="h-32 rounded-[14px]" />
              ) : !d.templates.length ? (
                <div className="surface px-5 py-6 text-[13px] text-muted-foreground">Save a question as a template to run it again in one click.</div>
              ) : (
                d.templates.slice(0, 3).map((t) => <TemplateCard key={t.id} pid={pid} t={t} canAsk={canAsk} compact />)
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}
