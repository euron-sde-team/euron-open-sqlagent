"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

export type ExecutionStatusFilter = "succeeded" | "refused" | "failed" | "timeout" | "scan_limit";

export function useExecutions(pid: string, filters: { connectionId?: string; status?: ExecutionStatusFilter | "" } = {}) {
  return useInfiniteQuery({
    queryKey: qk.executions(pid, filters),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/projects/{project_id}/executions", {
          params: {
            path: { project_id: pid },
            query: { cursor: pageParam, limit: 40, connection_id: filters.connectionId || null, status: filters.status || null },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    staleTime: STALE.list,
  });
}
