/**
 * NeuroSQL Frontend — Application entry point.
 *
 * This file is the root of the React component tree.
 * Vite imports this file first when the app loads.
 *
 * Providers registered here are available to every component:
 *   - QueryClientProvider: React Query for server state management
 *   - BrowserRouter: client-side routing with react-router-dom
 *   - Toaster: global toast notifications
 */

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { Toaster } from "react-hot-toast";

import App from "./App";
import "./index.css";

// ------------------------------------------------------------------ //
// React Query client configuration
//
// React Query manages all server state — API responses, loading states,
// caching, background refetching, and error handling.
//
// These defaults apply to every query unless overridden per-query.
// ------------------------------------------------------------------ //
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // How long fetched data is considered fresh (no refetch needed)
      // 5 minutes: schema data, user profile, connection list
      staleTime: 5 * 60 * 1000,

      // How long inactive query data stays in cache before garbage collection
      // 10 minutes: keeps data available when navigating back to a page
      gcTime: 10 * 60 * 1000,

      // Retry failed requests up to 2 times before showing an error
      // Handles transient network issues without bothering the user
      retry: 2,

      // Wait 1 second before first retry, 2 seconds before second
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),

      // Refetch when the browser tab regains focus
      // Ensures data is fresh when user returns to the app
      refetchOnWindowFocus: true,
    },
    mutations: {
      // Do not retry mutations (POST/PUT/DELETE) automatically
      // A failed INSERT should not be silently retried — the user
      // should be informed and decide whether to retry
      retry: 0,
    },
  },
});

// ------------------------------------------------------------------ //
// Root render
//
// React.StrictMode renders components twice in development to detect
// side effects and deprecated patterns. Has no effect in production.
// ------------------------------------------------------------------ //
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* React Query: provides queryClient to all child components */}
    <QueryClientProvider client={queryClient}>

      {/* Router: enables useNavigate, useParams, Link in all components */}
      <BrowserRouter>

        {/* Main application component tree */}
        <App />

        {/* Global toast notifications
            Position: top-right, auto-dismiss after 4 seconds */}
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            style: {
              background: "#1e1e2e",
              color: "#cdd6f4",
              border: "1px solid #313244",
              borderRadius: "8px",
              fontSize: "14px",
            },
            success: {
              iconTheme: {
                primary: "#a6e3a1",
                secondary: "#1e1e2e",
              },
            },
            error: {
              iconTheme: {
                primary: "#f38ba8",
                secondary: "#1e1e2e",
              },
            },
          }}
        />

      </BrowserRouter>

      {/* React Query Devtools
          Only renders in development — shows query cache state,
          active queries, and refetch controls in the browser */}
      <ReactQueryDevtools
        initialIsOpen={false}
        buttonPosition="bottom-left"
      />

    </QueryClientProvider>
  </React.StrictMode>
);