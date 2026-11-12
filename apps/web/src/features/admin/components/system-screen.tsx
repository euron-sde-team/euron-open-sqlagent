"use client";

import {
  ActivityIcon,
  Building2Icon,
  DatabaseIcon,
  FolderIcon,
  HourglassIcon,
  ListOrderedIcon,
  MessagesSquareIcon,
  TerminalSquareIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";

import { AdminOnly } from "@/components/admin-only";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Stat } from "@/components/stat";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/features/auth/api";
import { formatDuration, formatNumber } from "@/lib/format";

import { useSystemInfo } from "../api";

function Row({ label, icon: Icon, value }: { label: string; icon?: LucideIcon; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5 text-[13px]">
      <span className="inline-flex min-w-0 items-center gap-1.5 text-muted-foreground">
        {Icon && <Icon className="size-3.5 shrink-0" aria-hidden />}
        {label}
      </span>
      <span className="min-w-0 truncate text-right font-medium">{value}</span>
    </div>
  );
}

function RowsSkeleton({ n }: { n: number }) {
  return (
    <div className="space-y-3 py-3" aria-busy aria-label="Loading">
      {Array.from({ length: n }).map((_, i) => (
        <Skeleton key={i} className="h-4 w-full" />
      ))}
    </div>
  );
}

const STORAGE: Record<string, string> = { s3: "S3", local: "Local disk" };
const KEYS: Record<string, string> = { kms: "KMS", local: "Local master key" };
const CACHE: Record<string, string> = { redis: "Redis", memory: "In process", local: "In process" };
const MAIL: Record<string, string> = { log: "Written to the log (not sent)", smtp: "SMTP", ses: "Amazon SES" };

const ok = (on: boolean, yes = "Connected", no = "Unreachable") =>
  on ? (
    <Chip tone="success" dot>
      {yes}
    </Chip>
  ) : (
    <Chip tone="warning" dot>
      {no}
    </Chip>
  );

export function SystemScreen() {
  const { user, admin } = usePermissions();
  const info = useSystemInfo();
  const d = info.data;
  const q = d?.queue;
  // Questions queued for more than two minutes usually mean no worker is running, or every worker is busy.
  const stuck = q && (q.oldest_queued_s ?? 0) > 120;

  if (user && !admin) return <AdminOnly what="System status" />;
  return (
    <>
      <PageHeader title="System" description="The question queue and how this SQLAgent deployment is configured. Refreshes every 15 seconds." />
      {stuck && (
        <div role="status" className="mb-4 rounded-xl bg-warning-soft px-4 py-3 text-[13px] leading-relaxed text-warning">
          The oldest queued question has waited {formatDuration((q?.oldest_queued_s ?? 0) * 1000)}. Check that a worker is running (
          <code className="rounded bg-card/60 px-1 font-mono text-[12px]">sqlagent worker</code>), or start more workers.
        </div>
      )}
      {info.isError && !d ? (
        <div className="surface">
          <ErrorState error={info.error} title="System details could not be read" onRetry={() => void info.refetch()} />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Stat label="Queued questions" icon={ListOrderedIcon} value={q ? formatNumber(q.queued) : ""} loading={!q} detail="Waiting for a worker" />
            <Stat label="Being answered" icon={ActivityIcon} value={q ? formatNumber(q.running) : ""} loading={!q} detail="On a worker now" />
            <Stat
              label="Oldest queued"
              icon={HourglassIcon}
              value={q ? (q.oldest_queued_s ? formatDuration(q.oldest_queued_s * 1000) : "None") : ""}
              tone={stuck ? "warn" : "default"}
              loading={!q}
              detail="How long the next question has waited"
              className="col-span-2 lg:col-span-1"
            />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Surface>
              <SurfaceHeader title="Deployment" description="Where files live, how passwords and keys are sealed, and what this server talks to." />
              <div className="divide-y divide-hairline px-5 pb-3">
                {d ? (
                  <>
                    <Row label="Version" value={`v${d.version}`} />
                    <Row label="Environment" value={<Chip tone={d.environment === "production" ? "primary" : "neutral"}>{d.environment}</Chip>} />
                    <Row label="SQLite files and results" value={STORAGE[d.storage] ?? d.storage} />
                    <Row label="Secret sealing" value={KEYS[d.key_mode] ?? d.key_mode} />
                    <Row label="Cache" value={CACHE[d.cache] ?? d.cache} />
                    <Row label="Mail" value={MAIL[d.mail] ?? d.mail} />
                    <Row label="Redis" value={ok(d.redis)} />
                  </>
                ) : (
                  <RowsSkeleton n={7} />
                )}
              </div>
            </Surface>
            <Surface>
              <SurfaceHeader title="Contents" description="What this server holds, across every organization." />
              <div className="divide-y divide-hairline px-5 pb-3">
                {d ? (
                  <>
                    <Row label="Organizations" icon={Building2Icon} value={formatNumber(d.organizations)} />
                    <Row label="Projects" icon={FolderIcon} value={formatNumber(d.projects)} />
                    <Row label="Users" icon={UsersIcon} value={formatNumber(d.users)} />
                    <Row label="Connections" icon={DatabaseIcon} value={formatNumber(d.connections)} />
                    <Row label="Conversations" icon={MessagesSquareIcon} value={formatNumber(d.conversations)} />
                    <Row label="Queries run" icon={TerminalSquareIcon} value={formatNumber(d.executions)} />
                  </>
                ) : (
                  <RowsSkeleton n={6} />
                )}
              </div>
            </Surface>
          </div>
        </>
      )}
    </>
  );
}
