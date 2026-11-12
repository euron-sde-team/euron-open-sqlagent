import type { AnswerStatus, ConnectionKind } from "./api/types";

/** The tone a state is drawn in. Always shown with an icon and a word, never by color alone. */
export type Tone = "success" | "warning" | "danger" | "info" | "primary" | "neutral";

const ANSWER_LABEL: Record<AnswerStatus, string> = {
  queued: "Queued",
  running: "Answering",
  answered: "Answered",
  refused: "Refused",
  failed: "Failed",
  no_answer: "No answer",
};

const ANSWER_TONE: Record<AnswerStatus, Tone> = {
  queued: "neutral",
  running: "primary",
  answered: "success",
  refused: "danger",
  failed: "danger",
  no_answer: "warning",
};

export function answerLabel(status: string | null | undefined): string {
  return (status && ANSWER_LABEL[status as AnswerStatus]) || "Unknown";
}

export function answerTone(status: string | null | undefined): Tone {
  return (status && ANSWER_TONE[status as AnswerStatus]) || "neutral";
}

/** A question still being worked on (poll it). */
export function inFlight(status: string | null | undefined): boolean {
  return status === "queued" || status === "running";
}

export type ExecutionStatus = "succeeded" | "refused" | "failed" | "timeout" | "scan_limit";

const EXECUTION_LABEL: Record<ExecutionStatus, string> = {
  succeeded: "Succeeded",
  refused: "Refused by the guard",
  failed: "Failed",
  timeout: "Timed out",
  scan_limit: "Over the scan limit",
};

const EXECUTION_TONE: Record<ExecutionStatus, Tone> = {
  succeeded: "success",
  refused: "danger",
  failed: "danger",
  timeout: "warning",
  scan_limit: "warning",
};

export function executionLabel(status: string): string {
  return EXECUTION_LABEL[status as ExecutionStatus] ?? status;
}

export function executionTone(status: string): Tone {
  return EXECUTION_TONE[status as ExecutionStatus] ?? "neutral";
}

export const KIND_LABEL: Record<ConnectionKind, string> = {
  postgresql: "PostgreSQL",
  mysql: "MySQL",
  sqlite: "SQLite",
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind as ConnectionKind] ?? kind;
}
