/**
 * Vite configuration for NeuroSQL frontend.
 *
 * Key responsibilities:
 * - Configure React plugin with Fast Refresh (hot reload)
 * - Set up API proxy to avoid CORS in development
 * - Configure path aliases so we can import with '@/components/...'
 *   instead of '../../../components/...'
 * - Set build output options for production
 */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [
    react({
      // Fast Refresh: React components update in the browser
      // instantly when you save a file, without losing component state
      fastRefresh: true,
    }),
  ],

  resolve: {
    alias: {
      // Path alias: '@' maps to the 'src' directory
      // Allows clean imports: import { Button } from '@/components/Button'
      // Instead of:          import { Button } from '../../components/Button'
      "@": path.resolve(__dirname, "./src"),
    },
  },

  server: {
    // Listen on all interfaces so Docker can expose the port
    host: "0.0.0.0",

    // Vite default port
    port: 5173,

    // API proxy configuration
    // Any request starting with /api is forwarded to the FastAPI backend
    // This means the frontend never directly calls localhost:8000 —
    // it calls its own server at /api/... and Vite forwards it
    proxy: {
      "/api": {
        target: "http://api:8000",
        changeOrigin: true,
        // Uncomment to debug proxy requests:
        // configure: (proxy) => {
        //   proxy.on('proxyReq', (req) => console.log('Proxying:', req.path))
        // }
      },
    },

    // Automatically open browser on dev server start
    open: false,
  },

  build: {
    // Output directory for production build
    outDir: "dist",

    // Generate source maps for production debugging
    // Set to false to reduce bundle size if not needed
    sourcemap: true,

    // Warn when a chunk exceeds this size (in KB)
    chunkSizeWarningLimit: 1000,

    rollupOptions: {
      output: {
        // Split vendor libraries into separate chunks
        // This means React, Recharts, Monaco etc. are cached separately
        // from your application code — better browser caching
        manualChunks: {
          // React core
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          // Data fetching
          "vendor-query": ["@tanstack/react-query"],
          // Charts
          "vendor-charts": ["recharts"],
          // Monaco editor (large — always split this one)
          "vendor-monaco": ["@monaco-editor/react"],
        },
      },
    },
  },

  // Expose environment variables to the frontend
  // Only variables prefixed with VITE_ are exposed
  // (prevents accidentally leaking server secrets to the browser)
  envPrefix: "VITE_",
});