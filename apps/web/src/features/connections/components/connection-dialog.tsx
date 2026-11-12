"use client";

import { CheckCircle2Icon, PlugZapIcon, UploadIcon, XCircleIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Hint } from "@/components/hint";
import { Segmented } from "@/components/segmented";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/api/errors";
import type { ConnectionTest, ServerConnection } from "@/lib/api/types";
import { cn } from "@/lib/cn";

import { useCreateConnection, useTestUnsaved, useUploadSqlite } from "../api";

type Kind = "postgresql" | "mysql" | "sqlite";
const PORTS: Record<"postgresql" | "mysql", number> = { postgresql: 5432, mysql: 3306 };

interface Limits {
  max_rows: string;
  max_scan_rows: string;
  timeout_s: string;
}

function limitsOf(l: Limits): { max_rows: number; max_scan_rows: number; timeout_s: number } | string {
  const rows = Number(l.max_rows);
  const scan = Number(l.max_scan_rows);
  const t = Number(l.timeout_s);
  if (!Number.isInteger(rows) || rows < 1 || rows > 100000) return "The row limit is a whole number from 1 to 100,000.";
  if (!Number.isInteger(scan) || scan < 1) return "The scan limit is a whole number of rows.";
  if (!Number.isInteger(t) || t < 1 || t > 600) return "The timeout is from 1 to 600 seconds.";
  return { max_rows: rows, max_scan_rows: scan, timeout_s: t };
}

/** Add a database: test it first (real latency, version, read-only), then save it. */
export function ConnectionDialog({ pid, open, onOpenChange }: { pid: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [kind, setKind] = React.useState<Kind>("postgresql");
  const [name, setName] = React.useState("");
  const [host, setHost] = React.useState("");
  const [port, setPort] = React.useState("");
  const [database, setDatabase] = React.useState("");
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [ssl, setSsl] = React.useState("prefer");
  const [description, setDescription] = React.useState("");
  const [samples, setSamples] = React.useState(false);
  const [limits, setLimits] = React.useState<Limits>({ max_rows: "1000", max_scan_rows: "10000000", timeout_s: "30" });
  const [file, setFile] = React.useState<File | null>(null);
  const [tested, setTested] = React.useState<ConnectionTest | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const create = useCreateConnection(pid);
  const upload = useUploadSqlite(pid);
  const test = useTestUnsaved(pid);

  React.useEffect(() => {
    if (!open) return;
    setKind("postgresql");
    setName("");
    setHost("");
    setPort("");
    setDatabase("");
    setUsername("");
    setPassword("");
    setSsl("prefer");
    setDescription("");
    setSamples(false);
    setLimits({ max_rows: "1000", max_scan_rows: "10000000", timeout_s: "30" });
    setFile(null);
    setTested(null);
    setError(null);
  }, [open]);

  function body(): ServerConnection | string {
    if (!name.trim()) return "Name the connection, like 'Production replica'.";
    if (!host.trim() || !database.trim() || !username.trim()) return "Host, database and username are needed.";
    const l = limitsOf(limits);
    if (typeof l === "string") return l;
    const p = port.trim() ? Number(port) : null;
    if (p !== null && (!Number.isInteger(p) || p < 1 || p > 65535)) return "The port is a number from 1 to 65535.";
    return {
      name: name.trim(),
      kind: kind as "postgresql" | "mysql",
      host: host.trim(),
      port: p,
      database: database.trim(),
      username: username.trim(),
      password: password || null,
      ssl_mode: ssl as ServerConnection["ssl_mode"],
      sample_values: samples,
      description: description.trim(),
      ...l,
    };
  }

  function runTest() {
    const b = body();
    if (typeof b === "string") return setError(b);
    setError(null);
    test.mutate(b, { onSuccess: setTested, onError: (err) => setError(errorMessage(err)) });
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const done = () => {
      toast.success("Connected. SQLAgent is reading its schema.");
      onOpenChange(false);
    };
    if (kind === "sqlite") {
      if (!name.trim()) return setError("Name the connection.");
      if (!file) return setError("Choose a SQLite database file.");
      const l = limitsOf(limits);
      if (typeof l === "string") return setError(l);
      const form = new FormData();
      form.set("name", name.trim());
      form.set("file", file);
      form.set("max_rows", String(l.max_rows));
      form.set("max_scan_rows", String(l.max_scan_rows));
      form.set("timeout_s", String(l.timeout_s));
      form.set("sample_values", String(samples));
      form.set("description", description.trim());
      setError(null);
      return upload.mutate(form, { onSuccess: done, onError: (err) => setError(errorMessage(err)) });
    }
    const b = body();
    if (typeof b === "string") return setError(b);
    setError(null);
    create.mutate(b, { onSuccess: done, onError: (err) => setError(errorMessage(err)) });
  }

  const busy = create.isPending || upload.isPending;
  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="max-w-2xl">
        <form onSubmit={submit} noValidate className="flex min-h-0 flex-col">
          <DialogHeader>
            <DialogTitle>Add a database</DialogTitle>
            <DialogDescription>
              Use a login that can only read if you have one. SQLAgent opens every session read-only anyway, and seals the password: it is never shown again.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4 overflow-y-auto">
            <Segmented
              ariaLabel="Database type"
              value={kind}
              onChange={(v) => {
                setKind(v);
                setTested(null);
              }}
              options={[
                { value: "postgresql", label: "PostgreSQL" },
                { value: "mysql", label: "MySQL" },
                { value: "sqlite", label: "SQLite file" },
              ]}
            />
            <Field label="Name" htmlFor="cn-name">
              <Input id="cn-name" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="Shop (production replica)" />
            </Field>
            {kind === "sqlite" ? (
              <Field label="Database file" htmlFor="cn-file" hint="A .sqlite or .db file. It is stored and always opened read-only.">
                <label
                  htmlFor="cn-file"
                  className={cn(
                    "flex cursor-pointer items-center gap-3 rounded-xl bg-muted/60 px-4 py-3.5 text-[13px] transition-colors hover:bg-muted",
                    file && "text-foreground",
                  )}
                >
                  <UploadIcon className="size-4 text-subtle" aria-hidden />
                  {file ? file.name : "Choose a file"}
                </label>
                <input id="cn-file" type="file" accept=".sqlite,.sqlite3,.db,application/vnd.sqlite3" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </Field>
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-[1fr_110px]">
                  <Field label="Host" htmlFor="cn-host">
                    <Input id="cn-host" value={host} onChange={(e) => setHost(e.target.value)} placeholder="db.internal" autoComplete="off" />
                  </Field>
                  <Field label="Port" htmlFor="cn-port">
                    <Input id="cn-port" inputMode="numeric" value={port} onChange={(e) => setPort(e.target.value)} placeholder={String(PORTS[kind])} />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Database" htmlFor="cn-db">
                    <Input id="cn-db" value={database} onChange={(e) => setDatabase(e.target.value)} autoComplete="off" />
                  </Field>
                  <Field label="SSL" htmlFor="cn-ssl">
                    <SimpleSelect
                      id="cn-ssl"
                      value={ssl}
                      onValueChange={setSsl}
                      options={[
                        { value: "prefer", label: "Prefer" },
                        { value: "require", label: "Require" },
                        { value: "verify-full", label: "Verify the certificate" },
                        { value: "disable", label: "Off" },
                      ]}
                    />
                  </Field>
                  <Field label="Username" htmlFor="cn-user">
                    <Input id="cn-user" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
                  </Field>
                  <Field label="Password" htmlFor="cn-pass">
                    <Input id="cn-pass" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
                  </Field>
                </div>
              </>
            )}
            <Field label="What is in it (optional)" htmlFor="cn-desc" hint="A sentence for the model, like 'Online store: orders and customers since 2024'.">
              <Textarea id="cn-desc" rows={2} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Row limit" htmlFor="cn-rows" labelExtra={<Hint term="rowLimit" />}>
                <Input id="cn-rows" inputMode="numeric" value={limits.max_rows} onChange={(e) => setLimits({ ...limits, max_rows: e.target.value })} />
              </Field>
              <Field label="Scan limit (rows)" htmlFor="cn-scan" labelExtra={<Hint term="scanLimit" />}>
                <Input id="cn-scan" inputMode="numeric" value={limits.max_scan_rows} onChange={(e) => setLimits({ ...limits, max_scan_rows: e.target.value })} />
              </Field>
              <Field label="Timeout (seconds)" htmlFor="cn-timeout" labelExtra={<Hint term="timeout" />}>
                <Input id="cn-timeout" inputMode="numeric" value={limits.timeout_s} onChange={(e) => setLimits({ ...limits, timeout_s: e.target.value })} />
              </Field>
            </div>
            <label className="flex items-start gap-3 rounded-xl bg-muted/60 px-3.5 py-3 text-[13px]">
              <Switch checked={samples} onCheckedChange={setSamples} aria-label="Include example values in prompts" />
              <span>
                <span className="inline-flex items-center gap-1 font-medium">
                  Include example values in prompts <Hint term="sampleValues" />
                </span>
                <span className="block text-muted-foreground">Helps the model spell filters right (a status, a country). They are real data, so it is off by default.</span>
              </span>
            </label>
            {tested && (
              <div
                role="status"
                className={cn("flex items-start gap-2.5 rounded-xl px-4 py-3 text-[13px]", tested.ok ? "bg-savings-soft text-savings" : "bg-danger-soft text-danger")}
              >
                {tested.ok ? <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" /> : <XCircleIcon className="mt-0.5 size-4 shrink-0" />}
                <div className="text-foreground/85">
                  <div className="font-medium">{tested.message}</div>
                  <div className="mt-0.5 text-[12px] text-muted-foreground">
                    {Math.round(tested.latency_ms)} ms round trip{tested.server_version ? `, ${tested.server_version}` : ""}
                    {tested.read_only ? ", session confirmed read-only" : ""}
                  </div>
                </div>
              </div>
            )}
            {error && <FieldError role="alert">{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            {kind !== "sqlite" && (
              <Button type="button" variant="outline" onClick={runTest} disabled={test.isPending} className="sm:mr-auto">
                <PlugZapIcon />
                {test.isPending ? "Testing..." : "Test connection"}
              </Button>
            )}
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Saving..." : "Save connection"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
