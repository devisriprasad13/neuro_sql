/**
 * NeuroSQL — Root application component with routing.
 */

import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import QueryPage from "./pages/QueryPage";
import ConnectionsPage from "./pages/ConnectionsPage";
import HistoryPage from "./pages/HistoryPage";

const NotFoundPage = () => (
  <div style={{
    display: "flex", flexDirection: "column", alignItems: "center",
    justifyContent: "center", height: "100vh",
    background: "#0f0f1a", color: "#cdd6f4", gap: "12px",
  }}>
    <h1 style={{ fontSize: "4rem", margin: 0, color: "#f38ba8" }}>404</h1>
    <p style={{ color: "#6c7086" }}>Page not found</p>
    <a href="/" style={{ color: "#89b4fa", fontSize: "14px" }}>← Back to home</a>
  </div>
);

export default function App() {
  return (
    <Routes>
      {/* Redirect root to query page */}
      <Route path="/" element={<Navigate to="/query" replace />} />

      {/* Main layout wraps all app pages */}
      <Route element={<Layout />}>
        <Route path="/query"       element={<QueryPage />} />
        <Route path="/connections" element={<ConnectionsPage />} />
        <Route path="/history"     element={<HistoryPage />} />
      </Route>

      {/* 404 */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}