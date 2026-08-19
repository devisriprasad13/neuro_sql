/**
 * Centralized Axios HTTP client for NeuroSQL API.
 *
 * All API calls go through this client — never use fetch() directly.
 * Handles: base URL, auth headers, error normalization.
 */

import axios, { AxiosError, AxiosResponse } from "axios";

// Base URL — in development Vite proxies /api to localhost:8000
const BASE_URL = "/api/v1";

// Dev user context headers (replaced by JWT in Milestone 13)
const DEV_HEADERS = {
  "X-User-Email": "dev@neurosql.local",
  "X-User-Role": "analyst",
  "X-Org-Id": "00000000-0000-0000-0000-000000000001",
  "X-Org-Name": "Test Organization",
};

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: {
    "Content-Type": "application/json",
    ...DEV_HEADERS,
  },
  timeout: 30000,
});

// Response interceptor — unwrap the standard envelope
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    const message =
      (error.response?.data as any)?.error?.message ||
      error.message ||
      "An unexpected error occurred";
    return Promise.reject(new Error(message));
  }
);

// Standard API response envelope
export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: { code: string; message: string } | null;
  request_id: string;
  timestamp: string;
}

// Helper to extract data from envelope
export async function apiGet<T>(url: string): Promise<T> {
  const res = await apiClient.get<ApiResponse<T>>(url);
  return res.data.data;
}

export async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  const res = await apiClient.post<ApiResponse<T>>(url, body);
  return res.data.data;
}