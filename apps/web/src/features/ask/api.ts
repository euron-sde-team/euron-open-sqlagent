"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { Answer, AskRequest, ConversationDetail, Explanation, ExplainRequestBody, RowsPage } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";
import { inFlight } from "@/lib/status";

const p = (pid: string) => ({ params: { path: { project_id: pid } } });

/** Ask a question. The API waits up to `wait` seconds; a slower answer is polled. */
export function useAsk(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AskRequest) => unwrap(api.POST("/api/v1/projects/{project_id}/chat", { ...p(pid), body: { wait: 25, ...body } })),
    onSuccess: (msg) => {
      client.setQueryData(qk.message(pid, msg.id), msg);
      void client.invalidateQueries({ queryKey: qk.conversation(pid, msg.conversation_id) });
      void client.invalidateQueries({ queryKey: qk.conversationsAll(pid) });
      void client.invalidateQueries({ queryKey: qk.overview(pid) });
    },
  });
}

/** One question, polled while it is queued or being answered. */
export function useMessage(pid: string, mid: string, initial?: Answer) {
  return useQuery<Answer>({
    queryKey: qk.message(pid, mid),
    queryFn: () =>
      unwrap(api.GET("/api/v1/projects/{project_id}/messages/{message_id}", { params: { path: { project_id: pid, message_id: mid }, query: { wait: 10 } } })),
    initialData: initial,
    staleTime: STALE.live,
    refetchInterval: (q) => (inFlight(q.state.data?.status) ? 500 : false),
  });
}

export function useConversation(pid: string, cid: string | null) {
  return useQuery<ConversationDetail>({
    queryKey: qk.conversation(pid, cid ?? ""),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/conversations/{conversation_id}", { params: { path: { project_id: pid, conversation_id: cid as string } } })),
    enabled: !!cid,
    staleTime: STALE.detail,
  });
}

export function useConversations(pid: string, filters: { connectionId?: string; q?: string } = {}) {
  return useInfiniteQuery({
    queryKey: qk.conversations(pid, filters),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/conversations", {
          params: { path: { project_id: pid }, query: { cursor: pageParam, limit: 30, connection_id: filters.connectionId || null, q: filters.q || null } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    staleTime: STALE.list,
  });
}

export function useDeleteConversation(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (cid: string) =>
      unwrap(api.DELETE("/api/v1/projects/{project_id}/conversations/{conversation_id}", { params: { path: { project_id: pid, conversation_id: cid } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.conversationsAll(pid) }),
  });
}

/** A page of a stored result (the database is not queried again). */
export function useRows(pid: string, eid: string, offset: number, limit: number, initial?: RowsPage | null) {
  return useQuery<RowsPage>({
    queryKey: qk.rows(pid, eid, offset, limit),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/executions/{execution_id}/rows", {
          params: { path: { project_id: pid, execution_id: eid }, query: { offset, limit } },
        }),
      ),
    initialData: offset === 0 && initial && initial.limit === limit ? initial : undefined,
    staleTime: STALE.static,
    placeholderData: (prev) => prev,
  });
}

/** Explain any query in plain language. It is never executed. */
export function useExplain(pid: string) {
  return useMutation<Explanation, Error, ExplainRequestBody>({
    mutationFn: (body) => unwrap(api.POST("/api/v1/projects/{project_id}/sql/explain", { ...p(pid), body })),
  });
}

export function useSaveTemplate(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { message_id: string; name: string; keep_sql: boolean }) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/templates/from-message", { ...p(pid), body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.templates(pid) }),
  });
}
