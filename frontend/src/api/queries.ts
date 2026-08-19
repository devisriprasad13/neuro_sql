/**
 * API query functions and React Query hooks.
 *
 * All data fetching logic lives here — components just call these hooks.
 * Uses React Query for caching, loading states, and background refetch.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "./client";

// ------------------------------------------------------------------ //
// Types
// ------------------------------------------------------------------ //

export interface Connection {
  id: string;
  name: string;
  description: string | null;
  db_type: string;
  host: string | null;
  port: number | null;
  database_name: string | null;
  username: string | null;
  is_active: boolean;
  is_verified: boolean;
  crawl_status: string | null;
  last_crawled_at: string | null;
  created_at: string;
}

export interface QueryTaskResult {
  task_id: string;
  status: "pending" | "started" | "complete" | "failed";
  result?: {
    success: boolean;
    sql: string;
    columns: string[];
    rows: unknown[][];
    row_count: number;
    affected_rows: number;
    execution_time_ms: number;
    was_corrected: boolean;
    correction_attempts: number;
    intent: string;
    error: string | null;
    audit_log_id: string | null;
  };
  error?: string;
}

export interface HistoryItem {
  id: string;
  natural_language_query: string;
  generated_sql: string | null;
  intent_classification: string | null;
  status: string;
  execution_time_ms: number | null;
  result_row_count: number | null;
  was_self_corrected: boolean;
  correction_attempts: number;
  requested_at: string;
  connection_name: string | null;
}

// ------------------------------------------------------------------ //
// Connection hooks
// ------------------------------------------------------------------ //

export function useConnections() {
  return useQuery({
    queryKey: ["connections"],
    queryFn: () =>
      apiGet<{ connections: Connection[]; total: number }>("/connections"),
    staleTime: 30_000,
  });
}

export function useCreateConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      db_type: string;
      host?: string;
      port?: number;
      database_name?: string;
      username?: string;
      password?: string;
      description?: string;
    }) => apiPost<Connection>("/connections", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (connectionId: string) =>
      apiPost<{
        is_reachable: boolean;
        message: string;
        latency_ms: number | null;
      }>(`/connections/${connectionId}/test`),
  });
}

export function useCrawlConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (connectionId: string) =>
      apiPost<{
        table_count: number;
        column_count: number;
        embedded_count: number;
        status: string;
      }>(`/connections/${connectionId}/crawl`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}

export function useDeleteConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (connectionId: string) =>
      apiPost<{ message: string }>(`/connections/${connectionId}/delete`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });
}

// ------------------------------------------------------------------ //
// Query hooks
// ------------------------------------------------------------------ //

export function useSubmitQuery() {
  return useMutation({
    mutationFn: (data: {
      natural_language_query: string;
      connection_id: string;
      skip_dry_run?: boolean;
    }) => apiPost<{ task_id: string; status: string }>("/query", data),
  });
}

export function useQueryResult(taskId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["query-result", taskId],
    queryFn: () => apiGet<QueryTaskResult>(`/query/${taskId}`),
    enabled: enabled && !!taskId,
    // Poll every 2 seconds until complete or failed
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "complete" || status === "failed") return false;
      return 2000;
    },
    staleTime: 0,
  });
}

export function useQueryHistory(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["query-history", page, pageSize],
    queryFn: () =>
      apiGet<{ items: HistoryItem[]; total: number; page: number }>(
        `/query/history?page=${page}&page_size=${pageSize}`
      ),
    staleTime: 10_000,
  });
}