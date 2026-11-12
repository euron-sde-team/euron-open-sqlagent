"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, rawJson, unwrap } from "@/lib/api/client";
import type { Connection, ConnectionTest, ConnectionUpdate, DatabaseSchema, ServerConnection } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

const p = (pid: string) => ({ params: { path: { project_id: pid } } });
const one = (pid: string, cid: string) => ({ params: { path: { project_id: pid, connection_id: cid } } });

export function useConnections(pid: string) {
  return useQuery<Connection[]>({
    queryKey: qk.connections(pid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/connections", p(pid))),
    staleTime: STALE.list,
  });
}

export function useConnection(pid: string, cid: string) {
  return useQuery<Connection>({
    queryKey: qk.connection(pid, cid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/connections/{connection_id}", one(pid, cid))),
    staleTime: STALE.detail,
  });
}

export function useCreateConnection(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ServerConnection) => unwrap(api.POST("/api/v1/projects/{project_id}/connections", { ...p(pid), body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.connections(pid) }),
  });
}

/** A SQLite file goes up as a form (the one upload the API accepts). */
export function useUploadSqlite(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (form: FormData) => rawJson<Connection>("POST", `/api/v1/projects/${pid}/connections/sqlite`, form),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.connections(pid) }),
  });
}

export function useUpdateConnection(pid: string, cid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ConnectionUpdate) =>
      unwrap(api.PATCH("/api/v1/projects/{project_id}/connections/{connection_id}", { ...one(pid, cid), body })),
    onSuccess: (data) => {
      client.setQueryData(qk.connection(pid, cid), data);
      void client.invalidateQueries({ queryKey: qk.connections(pid) });
    },
  });
}

export function useDeleteConnection(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (cid: string) => unwrap(api.DELETE("/api/v1/projects/{project_id}/connections/{connection_id}", one(pid, cid))),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.project(pid) }),
  });
}

/** Test a saved connection: the real round trip, the server version, a read-only session. */
export function useTestConnection(pid: string) {
  const client = useQueryClient();
  return useMutation<ConnectionTest, Error, string>({
    mutationFn: (cid: string) => unwrap(api.POST("/api/v1/projects/{project_id}/connections/{connection_id}/test", one(pid, cid))),
    onSettled: () => client.invalidateQueries({ queryKey: qk.connections(pid) }),
  });
}

export function useTestUnsaved(pid: string) {
  return useMutation<ConnectionTest, Error, ServerConnection>({
    mutationFn: (body: ServerConnection) => unwrap(api.POST("/api/v1/projects/{project_id}/connections/test", { ...p(pid), body })),
  });
}

export function useSchema(pid: string, cid: string | null) {
  return useQuery<DatabaseSchema>({
    queryKey: qk.schema(pid, cid ?? ""),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/connections/{connection_id}/schema", one(pid, cid as string))),
    staleTime: STALE.static,
    enabled: !!cid,
    retry: false,
  });
}

export function useRefreshSchema(pid: string, cid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/projects/{project_id}/connections/{connection_id}/schema/refresh", one(pid, cid))),
    onSuccess: (data) => {
      client.setQueryData(qk.schema(pid, cid), data);
      void client.invalidateQueries({ queryKey: qk.connections(pid) });
    },
  });
}
