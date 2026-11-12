"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { Template } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

const one = (pid: string, tid: string) => ({ params: { path: { project_id: pid, template_id: tid } } });

export function useTemplates(pid: string) {
  return useQuery<Template[]>({
    queryKey: qk.templates(pid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/templates", { params: { path: { project_id: pid } } })),
    staleTime: STALE.list,
  });
}

/** Ask a template's question again in a new conversation (its saved SQL runs as is). */
export function useRunTemplate(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (tid: string) => unwrap(api.POST("/api/v1/projects/{project_id}/templates/{template_id}/run", { ...one(pid, tid), body: { wait: 0 } })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.templates(pid) });
      void client.invalidateQueries({ queryKey: qk.conversationsAll(pid) });
    },
  });
}

export function useDeleteTemplate(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (tid: string) => unwrap(api.DELETE("/api/v1/projects/{project_id}/templates/{template_id}", one(pid, tid))),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.templates(pid) }),
  });
}
