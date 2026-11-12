"use client";

import { BookOpenTextIcon, ShieldCheckIcon, ShieldXIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import type { Explanation } from "@/lib/api/types";

import { useExplain } from "../api";

const EXAMPLE = `SELECT c.country, sum(o.total_amount) AS revenue
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.status = 'delivered'
GROUP BY c.country
ORDER BY revenue DESC
LIMIT 5`;

/** Paste any query and read what it does. It is parsed and explained, never run. */
export function ExplainDialog({ pid, connectionId, open, onOpenChange }: { pid: string; connectionId: string | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const explain = useExplain(pid);
  const [sql, setSql] = React.useState("");
  const [out, setOut] = React.useState<Explanation | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setOut(null);
      setError(null);
    }
  }, [open]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!sql.trim()) return setError("Paste a query to explain.");
    setError(null);
    explain.mutate(
      { sql, connection_id: connectionId, dialect: connectionId ? null : "postgresql", use_model: true },
      { onSuccess: setOut, onError: (err) => setError(errorMessage(err)) },
    );
  }

  const a = out?.analysis;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <form onSubmit={submit} noValidate className="flex min-h-0 flex-col">
          <DialogHeader>
            <DialogTitle>Explain a query</DialogTitle>
            <DialogDescription>Paste SQL from anywhere. SQLAgent reads it and says what it does in plain words. It is never run.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4 overflow-y-auto">
            <Field label="SQL" htmlFor="explain-sql" error={error}>
              <Textarea
                id="explain-sql"
                value={sql}
                onChange={(e) => setSql(e.target.value)}
                placeholder={EXAMPLE}
                rows={7}
                className="font-mono text-[12.5px]"
                spellCheck={false}
              />
            </Field>
            {out && a && (
              <div className="space-y-3 rounded-xl bg-muted/60 p-4" data-qa="explanation">
                <div className="flex flex-wrap items-center gap-2">
                  {a.read_only ? (
                    <Chip tone="success">
                      <ShieldCheckIcon aria-hidden />
                      One read-only query
                    </Chip>
                  ) : (
                    <Chip tone="danger">
                      <ShieldXIcon aria-hidden />
                      SQLAgent would not run this
                    </Chip>
                  )}
                  <Chip tone="neutral">Not executed</Chip>
                  <span className="text-[11.5px] text-subtle">{out.source === "model" ? `Explained by ${out.model}` : "Explained from the syntax tree"}</span>
                </div>
                <p className="text-[13.5px] leading-relaxed">{out.explanation}</p>
                <dl className="grid gap-x-4 gap-y-1.5 text-[12px] sm:grid-cols-[110px_1fr]">
                  <Fact label="Tables" value={(a.tables ?? []).join(", ")} />
                  <Fact label="Joins" value={(a.joins ?? []).join("; ")} />
                  <Fact label="Filters" value={(a.filters ?? []).join("; ")} />
                  <Fact label="Grouped by" value={(a.group_by ?? []).join(", ")} />
                  <Fact label="Computes" value={(a.aggregates ?? []).join(", ")} />
                  <Fact label="Sorted by" value={(a.order_by ?? []).join(", ")} />
                  <Fact label="Limit" value={a.limit != null ? String(a.limit) : ""} />
                  {!a.read_only && <Fact label="Why refused" value={a.refusal ?? ""} />}
                </dl>
              </div>
            )}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button type="submit" disabled={explain.isPending}>
              <BookOpenTextIcon />
              {explain.isPending ? "Reading..." : "Explain"}
            </Button>
          </DialogFooter>
          {error && <FieldError className="sr-only">{error}</FieldError>}
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <>
      <dt className="text-subtle">{label}</dt>
      <dd className="min-w-0 font-mono break-words text-foreground/85">{value}</dd>
    </>
  );
}
