import {
  BanIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
  HelpCircleIcon,
  Loader2Icon,
  ScanSearchIcon,
  ShieldCheckIcon,
  ShieldXIcon,
  TimerOffIcon,
  XCircleIcon,
  type LucideIcon,
} from "lucide-react";

import { Chip } from "@/components/ui/chip";
import { cn } from "@/lib/cn";
import { answerLabel, answerTone, executionLabel, executionTone, kindLabel } from "@/lib/status";

const ANSWER_ICON: Record<string, LucideIcon> = {
  queued: CircleDashedIcon,
  running: Loader2Icon,
  answered: CheckCircle2Icon,
  refused: BanIcon,
  failed: XCircleIcon,
  no_answer: HelpCircleIcon,
};

/** A question's state: icon, word and tone together, never color alone. */
export function AnswerStatusChip({ status, className }: { status: string; className?: string }) {
  const Icon = ANSWER_ICON[status] ?? CircleDashedIcon;
  return (
    <Chip tone={answerTone(status)} className={className}>
      <Icon className={cn(status === "running" && "animate-spin")} aria-hidden />
      {answerLabel(status)}
    </Chip>
  );
}

const EXECUTION_ICON: Record<string, LucideIcon> = {
  succeeded: CheckCircle2Icon,
  refused: ShieldXIcon,
  failed: XCircleIcon,
  timeout: TimerOffIcon,
  scan_limit: ScanSearchIcon,
};

export function ExecutionStatusChip({ status, className }: { status: string; className?: string }) {
  const Icon = EXECUTION_ICON[status] ?? CircleDashedIcon;
  return (
    <Chip tone={executionTone(status)} className={className}>
      <Icon aria-hidden />
      {executionLabel(status)}
    </Chip>
  );
}

/** The badge next to every query: did the SQL guard accept it as read-only? */
export function GuardBadge({ validated, className }: { validated: boolean; className?: string }) {
  return validated ? (
    <Chip tone="success" className={className} data-qa="guard-validated">
      <ShieldCheckIcon aria-hidden />
      Validated read-only
    </Chip>
  ) : (
    <Chip tone="danger" className={className} data-qa="guard-refused">
      <ShieldXIcon aria-hidden />
      Refused by the SQL guard
    </Chip>
  );
}

export function KindChip({ kind, className }: { kind: string; className?: string }) {
  return (
    <Chip tone="info" className={className}>
      {kindLabel(kind)}
    </Chip>
  );
}
