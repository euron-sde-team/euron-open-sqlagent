"use client";

import { Building2Icon, CpuIcon, KeyRoundIcon, SlidersHorizontalIcon, Trash2Icon, UsersIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { RoleNote } from "@/components/role-note";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api/errors";
import type { Project } from "@/lib/api/types";
import { useUiPrefs } from "@/lib/store";
import { useTabParam } from "@/lib/use-tab-param";

import { useCurrentProject, useDeleteProject, useUpdateProject } from "../api";

import { ApiKeysTab } from "./api-keys-tab";
import { MembersTab } from "./members-tab";
import { OrganizationTab } from "./organization-tab";
import { ProvidersTab } from "./providers-tab";

const TABS = ["project", "members", "providers", "api-keys", "organization"] as const;

export function ProjectSettingsScreen() {
  const { pid, project, canAdmin, query } = useCurrentProject();
  const [rawTab, setTab] = useTabParam("project", TABS);
  // API keys are an admin's tool; everyone else lands on the project tab.
  const tab = rawTab === "api-keys" && project && !canAdmin ? "project" : rawTab;
  // On a phone the tab strip scrolls sideways; keep the open tab in view.
  const strip = React.useRef<HTMLDivElement>(null);
  const ready = !query.isPending && !query.isError;
  React.useEffect(() => {
    const active = strip.current?.querySelector<HTMLElement>("[aria-selected=true]");
    if (active && strip.current) strip.current.scrollLeft = Math.max(0, active.offsetLeft - 16);
  }, [tab, ready]);

  return (
    <>
      <PageHeader title="Settings" description="This project, who works in it, the models that write its SQL, the keys your apps use and the organization around it." />
      {query.isPending ? (
        <Skeleton className="h-96 w-full max-w-3xl rounded-[14px]" />
      ) : query.isError ? (
        <div className="surface">
          <ErrorState error={query.error} title="Project settings could not be loaded" onRetry={() => void query.refetch()} />
        </div>
      ) : (
        <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
          <div ref={strip} className="no-scrollbar relative -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <TabsList className="flex-nowrap">
              <TabsTrigger value="project">
                <SlidersHorizontalIcon />
                Project
              </TabsTrigger>
              <TabsTrigger value="members">
                <UsersIcon />
                Members
              </TabsTrigger>
              <TabsTrigger value="providers">
                <CpuIcon />
                Model providers
              </TabsTrigger>
              {canAdmin && (
                <TabsTrigger value="api-keys">
                  <KeyRoundIcon />
                  API keys
                </TabsTrigger>
              )}
              <TabsTrigger value="organization">
                <Building2Icon />
                Organization
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="project">
            <GeneralTab key={query.data.id} project={query.data} canAdmin={canAdmin} />
          </TabsContent>
          <TabsContent value="members">
            <MembersTab pid={pid} canAdmin={canAdmin} />
          </TabsContent>
          {canAdmin && (
            <TabsContent value="api-keys">
              <ApiKeysTab pid={pid} />
            </TabsContent>
          )}
          <TabsContent value="providers">
            <ProvidersTab pid={pid} canAdmin={canAdmin} />
          </TabsContent>
          <TabsContent value="organization">
            <OrganizationTab orgId={query.data.org_id} />
          </TabsContent>
        </Tabs>
      )}
    </>
  );
}

function GeneralTab({ project: p, canAdmin }: { project: Project; canAdmin: boolean }) {
  const update = useUpdateProject(p.id);
  const [name, setName] = React.useState(p.name);
  const [description, setDescription] = React.useState(p.description);
  const [error, setError] = React.useState<string | null>(null);
  const ro = !canAdmin;

  function save(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("The project needs a name.");
    setError(null);
    update.mutate(
      { name: name.trim(), description: description.trim() },
      { onSuccess: () => toast.success("Project settings saved."), onError: (err) => setError(errorMessage(err)) },
    );
  }

  return (
    <div className="max-w-3xl space-y-4">
      {ro && <RoleNote>Only project admins change these settings.</RoleNote>}
      <form onSubmit={save} noValidate>
        <Surface>
          <SurfaceHeader title="About" />
          <div className="grid gap-4 px-5 pb-5">
            <Field label="Name" htmlFor="ps-name">
              <Input id="ps-name" maxLength={120} disabled={ro} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Description" htmlFor="ps-desc">
              <Textarea id="ps-desc" maxLength={2000} disabled={ro} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
          </div>
          {canAdmin && (
            <div className="flex flex-col gap-2 rounded-b-[14px] bg-muted/50 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between">
              <div>{error && <FieldError>{error}</FieldError>}</div>
              <Button type="submit" disabled={update.isPending}>
                {update.isPending ? "Saving..." : "Save settings"}
              </Button>
            </div>
          )}
        </Surface>
      </form>
      {canAdmin && <DangerZone project={p} />}
    </div>
  );
}

function DangerZone({ project }: { project: Project }) {
  const del = useDeleteProject(project.id);
  const router = useRouter();
  const setLast = useUiPrefs((s) => s.setLastProject);
  const [open, setOpen] = React.useState(false);
  const [typed, setTyped] = React.useState("");
  React.useEffect(() => {
    if (open) setTyped("");
  }, [open]);

  return (
    <Surface>
      <SurfaceHeader title="Danger zone" />
      <div className="flex flex-col gap-3 px-5 pb-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Delete this project with its connections, conversations, query history, templates, model providers and API keys. The
          databases it connects to are never touched: SQLAgent only ever read them.
        </p>
        <Button variant="destructive-soft" onClick={() => setOpen(true)} className="shrink-0">
          <Trash2Icon />
          Delete project
        </Button>
      </div>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete ${project.name}?`}
        description="This cannot be undone. Apps that use its API keys start failing at once."
        confirmLabel="Delete forever"
        pending={del.isPending}
        confirmDisabled={typed !== project.name}
        onConfirm={() => {
          if (typed !== project.name) return;
          del.mutate(undefined, {
            onSuccess: () => {
              setLast(null);
              toast.success(`${project.name} deleted.`);
              router.replace("/projects");
            },
            onError: (err) => toast.error(errorMessage(err)),
          });
        }}
      >
        <Field label={<span>Type <span className="font-mono">{project.name}</span> to confirm</span>} htmlFor="del-confirm">
          <Input id="del-confirm" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} aria-invalid={typed.length > 0 && typed !== project.name ? true : undefined} />
        </Field>
        {typed.length > 0 && typed !== project.name && <p className="mt-1.5 text-[12px] text-muted-foreground">The name does not match yet.</p>}
      </ConfirmDialog>
    </Surface>
  );
}
