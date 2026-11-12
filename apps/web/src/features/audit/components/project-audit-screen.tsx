"use client";

import * as React from "react";

import { AdminOnly } from "@/components/admin-only";
import { PageHeader } from "@/components/page-header";
import { SimpleSelect } from "@/components/ui/select";
import { useConnections } from "@/features/connections/api";
import { useCurrentProject, useMembers } from "@/features/projects/api";

import { useProjectAudit } from "../api";

import { AuditLogPanel, useActionFilter } from "./audit-log-panel";

/**
 * The project's append-only audit log: every question, every query run or refused (with its
 * SQL, status, row count and who ran it), and every change, filtered by database or person.
 */
export function ProjectAuditScreen() {
  const { pid, canAdmin, project } = useCurrentProject();
  const connections = useConnections(pid);
  const members = useMembers(pid);
  const [connectionId, setConnectionId] = React.useState("");
  const [actorId, setActorId] = React.useState("");
  const [input, action, setInput] = useActionFilter();
  const q = useProjectAudit(pid, { action, connectionId, actorId }, canAdmin);
  if (project && !canAdmin) return <AdminOnly what="The project audit log" who="project admins" />;
  return (
    <>
      <PageHeader
        title="Audit log"
        description="Append-only: every question asked, every query run or refused with its SQL and row count, and who did it. Nobody can edit or delete an entry, not even the database's own admin through SQLAgent."
      />
      <div className="mb-3 flex flex-col gap-2 sm:flex-row">
        <SimpleSelect
          aria-label="Database"
          value={connectionId}
          onValueChange={setConnectionId}
          options={[{ value: "", label: "Every database" }, ...(connections.data ?? []).map((c) => ({ value: c.id, label: c.name }))]}
          className="w-full sm:w-56"
        />
        <SimpleSelect
          aria-label="Person"
          value={actorId}
          onValueChange={setActorId}
          options={[{ value: "", label: "Everyone" }, ...(members.data ?? []).map((m) => ({ value: m.user_id, label: m.name }))]}
          className="w-full sm:w-56"
        />
      </div>
      <AuditLogPanel
        query={q}
        input={input}
        action={action}
        setInput={setInput}
        emptyText="Questions, queries and changes in this project are recorded here as they happen."
      />
    </>
  );
}
