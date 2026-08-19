/**
 * Query page — the main NeuroSQL interface.
 * Updated in Milestone 12 with ChartRenderer and SQLInspector.
 */

import { useState, useEffect, useCallback } from "react";
import { useConnections, useSubmitQuery, useQueryResult } from "../api/queries";
import ChartRenderer from "../components/ChartRenderer";
import SQLInspector from "../components/SQLInspector";

export default function QueryPage() {
  const [query, setQuery] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [activeTab, setActiveTab] = useState<"table" | "chart" | "sql">("table");

  const { data: connectionsData } = useConnections();
  const connections = connectionsData?.connections ?? [];

  const submitMutation = useSubmitQuery();
  const { data: taskResult } = useQueryResult(taskId, isPolling);

  // Stop polling when complete or failed — correct placement in useEffect
  useEffect(() => {
    const status = taskResult?.status;
    if ((status === "complete" || status === "failed") && isPolling) {
      setIsPolling(false);
    }
  }, [taskResult?.status, isPolling]);

  const handleSubmit = useCallback(async () => {
    if (!query.trim() || !connectionId) return;
    setTaskId(null);
    setIsPolling(false);
    setActiveTab("table");

    try {
      const result = await submitMutation.mutateAsync({
        natural_language_query: query,
        connection_id: connectionId,
        skip_dry_run: true,
      });
      setTaskId(result.task_id);
      setIsPolling(true);
    } catch (err) {
      console.error("Submit failed:", err);
    }
  }, [query, connectionId, submitMutation]);

  const result = taskResult?.result;
  const status = taskResult?.status;
  const isLoading = submitMutation.isPending || isPolling;
  const hasResults = status === "complete" && result && result.columns.length > 0;

  return (
    <div style={styles.page}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>Query</h1>
        <p style={styles.subtitle}>Ask your database anything in plain English</p>
      </div>

      {/* Query input area */}
      <div style={styles.inputCard}>
        <select
          style={styles.select}
          value={connectionId}
          onChange={(e) => setConnectionId(e.target.value)}
        >
          <option value="">Select a database connection...</option>
          {connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.db_type})
            </option>
          ))}
        </select>

        <textarea
          style={styles.textarea}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Show me total revenue by customer region for Q1 2024..."
          rows={3}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit();
          }}
        />

        <div style={styles.submitRow}>
          <span style={styles.hint}>Ctrl+Enter to submit</span>
          <button
            style={{
              ...styles.submitBtn,
              ...(isLoading || !query.trim() || !connectionId
                ? styles.submitBtnDisabled
                : {}),
            }}
            onClick={handleSubmit}
            disabled={isLoading || !query.trim() || !connectionId}
          >
            {isLoading ? "Running..." : "Run Query ⚡"}
          </button>
        </div>
      </div>

      {/* Status bar */}
      {taskResult && (
        <div style={styles.statusBar}>
          <span
            style={{
              ...styles.statusDot,
              background:
                status === "complete"
                  ? "var(--color-success)"
                  : status === "failed"
                  ? "var(--color-error)"
                  : "#f9e2af",
            }}
          />
          <span style={styles.statusText}>
            {status === "complete" && result
              ? `${result.row_count} row${result.row_count !== 1 ? "s" : ""} · ${result.execution_time_ms.toFixed(0)}ms · ${result.intent}`
              : status === "failed"
              ? `Failed: ${taskResult.error ?? result?.error}`
              : "Processing..."}
          </span>
          {result?.was_corrected && (
            <span style={styles.correctedBadge}>
              ⚡ Self-corrected ({result.correction_attempts} attempts)
            </span>
          )}
        </div>
      )}

      {/* Result tabs */}
      {(hasResults || (status === "complete" && result?.sql)) && (
        <div style={styles.tabs}>
          {(["table", "chart", "sql"] as const).map((tab) => (
            <button
              key={tab}
              style={{
                ...styles.tab,
                ...(activeTab === tab ? styles.tabActive : {}),
              }}
              onClick={() => setActiveTab(tab)}
            >
              {tab === "table" && "📄 Table"}
              {tab === "chart" && "📊 Chart"}
              {tab === "sql" && "🔍 SQL Inspector"}
            </button>
          ))}
        </div>
      )}

      {/* Table view */}
      {activeTab === "table" && hasResults && (
        <div style={styles.tableCard}>
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  {result!.columns.map((col) => (
                    <th key={col} style={styles.th}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result!.rows.map((row, ri) => (
                  <tr key={ri} style={ri % 2 === 0 ? styles.trEven : styles.trOdd}>
                    {row.map((cell, ci) => (
                      <td key={ci} style={styles.td}>
                        {cell === null
                          ? <span style={styles.nullVal}>NULL</span>
                          : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Chart view */}
      {activeTab === "chart" && hasResults && (
        <ChartRenderer
          columns={result!.columns}
          rows={result!.rows}
        />
      )}

      {/* SQL Inspector view */}
      {activeTab === "sql" && result?.sql && (
        <SQLInspector
          sql={result.sql}
          wasCorrected={result.was_corrected}
          correctionAttempts={result.correction_attempts}
          executionTimeMs={result.execution_time_ms}
        />
      )}

      {/* Empty result state */}
      {status === "complete" && result && result.columns.length === 0 && (
        <div style={styles.emptyState}>
          <div style={styles.emptyIcon}>📭</div>
          <div style={styles.emptyText}>Query executed — no rows returned</div>
          {result.sql && (
            <code style={styles.emptySql}>{result.sql}</code>
          )}
        </div>
      )}

      {/* Initial empty state */}
      {!taskId && !isLoading && (
        <div style={styles.emptyState}>
          <div style={styles.emptyIcon}>⚡</div>
          <div style={styles.emptyText}>
            Select a connection and ask a question
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    padding: "28px 32px",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    height: "100%",
    overflow: "auto",
  },
  header: { marginBottom: "4px" },
  title: {
    fontSize: "22px", fontWeight: 600,
    color: "var(--color-text-primary)", margin: 0,
  },
  subtitle: {
    fontSize: "13px", color: "var(--color-text-muted)", margin: "4px 0 0",
  },
  inputCard: {
    background: "var(--color-bg-secondary)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-lg)",
    padding: "16px",
    display: "flex",
    flexDirection: "column",
    gap: "10px",
  },
  select: {
    padding: "8px 12px",
    background: "var(--color-bg-primary)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-md)",
    color: "var(--color-text-primary)",
    fontSize: "13px",
    outline: "none",
  },
  textarea: {
    width: "100%",
    padding: "10px 12px",
    background: "var(--color-bg-primary)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-md)",
    color: "var(--color-text-primary)",
    fontSize: "14px",
    resize: "vertical",
    fontFamily: "var(--font-sans)",
    outline: "none",
    boxSizing: "border-box",
  },
  submitRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  hint: { fontSize: "12px", color: "var(--color-text-muted)" },
  submitBtn: {
    padding: "9px 20px",
    background: "var(--color-accent)",
    color: "#0f0f1a",
    border: "none",
    borderRadius: "var(--radius-md)",
    fontSize: "13px",
    fontWeight: 600,
    cursor: "pointer",
  },
  submitBtnDisabled: { opacity: 0.5, cursor: "not-allowed" },
  statusBar: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "10px 16px",
    background: "var(--color-bg-secondary)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-md)",
    fontSize: "13px",
  },
  statusDot: {
    width: "8px", height: "8px",
    borderRadius: "50%", flexShrink: 0,
  },
  statusText: { color: "var(--color-text-secondary)", flex: 1 },
  correctedBadge: {
    padding: "2px 8px",
    background: "rgba(249,226,175,0.15)",
    color: "var(--color-warning)",
    borderRadius: "var(--radius-full)",
    fontSize: "11px", fontWeight: 500,
  },
  tabs: {
    display: "flex",
    gap: "4px",
    borderBottom: "1px solid var(--color-border)",
    paddingBottom: "0",
  },
  tab: {
    padding: "8px 16px",
    background: "transparent",
    border: "none",
    borderBottom: "2px solid transparent",
    color: "var(--color-text-muted)",
    fontSize: "13px",
    cursor: "pointer",
    fontFamily: "var(--font-sans)",
    marginBottom: "-1px",
  },
  tabActive: {
    color: "var(--color-accent)",
    borderBottomColor: "var(--color-accent)",
    fontWeight: 500,
  },
  tableCard: {
    background: "var(--color-bg-secondary)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-lg)",
    overflow: "hidden",
    flex: 1,
  },
  tableWrap: { overflowX: "auto" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: "13px" },
  th: {
    padding: "10px 14px",
    textAlign: "left",
    fontWeight: 500,
    fontSize: "12px",
    color: "var(--color-text-muted)",
    borderBottom: "1px solid var(--color-border)",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    whiteSpace: "nowrap",
  },
  td: {
    padding: "9px 14px",
    color: "var(--color-text-primary)",
    borderBottom: "1px solid rgba(49,50,68,0.5)",
    maxWidth: "300px",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  trEven: { background: "transparent" },
  trOdd: { background: "rgba(49,50,68,0.3)" },
  nullVal: { color: "var(--color-text-muted)", fontStyle: "italic" },
  emptyState: {
    display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center",
    gap: "12px", padding: "60px 20px",
  },
  emptyIcon: { fontSize: "40px" },
  emptyText: { fontSize: "15px", color: "var(--color-text-secondary)" },
  emptySql: {
    fontSize: "12px",
    fontFamily: "var(--font-mono)",
    color: "var(--color-text-muted)",
  },
};