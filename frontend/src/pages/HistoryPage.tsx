/**
 * History page — paginated query history from audit logs.
 */

import { useState } from "react";
import { useQueryHistory } from "../api/queries";

export default function HistoryPage() {
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 15;

  const { data, isLoading } = useQueryHistory(page, PAGE_SIZE);
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  const statusColor: Record<string, string> = {
    success: "var(--color-success)",
    failed:  "var(--color-error)",
    blocked: "var(--color-warning)",
    pending_confirmation: "var(--color-warning)",
  };

  const intentColor: Record<string, string> = {
    READ:   "#89b4fa",
    INSERT: "#a6e3a1",
    UPDATE: "#f9e2af",
    DELETE: "#f38ba8",
    DDL:    "#cba6f7",
  };

  function formatTime(iso: string | null) {
    if (!iso) return "—";
    return new Date(iso).toLocaleString();
  }

  function truncate(str: string | null, n: number) {
    if (!str) return "—";
    return str.length > n ? str.slice(0, n) + "..." : str;
  }

  return (
    <div style={styles.page}>
      {/* Header */}
      <div>
        <h1 style={styles.title}>Query History</h1>
        <p style={styles.subtitle}>
          {total} total queries · page {page} of {totalPages || 1}
        </p>
      </div>

      {/* Table */}
      {isLoading ? (
        <div style={styles.loading}>Loading history...</div>
      ) : items.length === 0 ? (
        <div style={styles.empty}>
          <div style={{ fontSize: "36px" }}>📋</div>
          <div>No queries yet. Run your first query on the Query page.</div>
        </div>
      ) : (
        <div style={styles.tableCard}>
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  {["Query", "SQL", "Intent", "Status", "Rows", "Time", "Executed At"].map(
                    (h) => (
                      <th key={h} style={styles.th}>
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody>
                {items.map((item, i) => (
                  <tr key={item.id} style={i % 2 === 0 ? styles.trEven : styles.trOdd}>
                    {/* Query */}
                    <td style={{ ...styles.td, maxWidth: "220px" }}>
                      <span
                        title={item.natural_language_query}
                        style={styles.queryText}
                      >
                        {truncate(item.natural_language_query, 60)}
                      </span>
                    </td>

                    {/* SQL */}
                    <td style={{ ...styles.td, maxWidth: "200px" }}>
                      <code style={styles.sqlText}>
                        {truncate(item.generated_sql, 50)}
                      </code>
                    </td>

                    {/* Intent */}
                    <td style={styles.td}>
                      {item.intent_classification ? (
                        <span
                          style={{
                            ...styles.intentBadge,
                            color:
                              intentColor[item.intent_classification] ||
                              "#cdd6f4",
                            borderColor:
                              intentColor[item.intent_classification] ||
                              "#cdd6f4",
                          }}
                        >
                          {item.intent_classification}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>

                    {/* Status */}
                    <td style={styles.td}>
                      <span
                        style={{
                          ...styles.statusBadge,
                          color:
                            statusColor[item.status] ||
                            "var(--color-text-muted)",
                        }}
                      >
                        {item.status === "success" ? "✓" : "✗"}{" "}
                        {item.status}
                      </span>
                    </td>

                    {/* Row count */}
                    <td style={{ ...styles.td, textAlign: "right" }}>
                      {item.result_row_count ?? "—"}
                    </td>

                    {/* Execution time */}
                    <td style={{ ...styles.td, textAlign: "right" }}>
                      {item.execution_time_ms
                        ? `${item.execution_time_ms}ms`
                        : "—"}
                    </td>

                    {/* Timestamp */}
                    <td style={{ ...styles.td, whiteSpace: "nowrap" }}>
                      {formatTime(item.requested_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={styles.pagination}>
              <button
                style={styles.pageBtn}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                ← Previous
              </button>
              <span style={styles.pageInfo}>
                Page {page} of {totalPages}
              </span>
              <button
                style={styles.pageBtn}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
              >
                Next →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: { padding: "28px 32px", display: "flex", flexDirection: "column", gap: "20px", overflow: "auto", height: "100%" },
  title: { fontSize: "22px", fontWeight: 600, color: "var(--color-text-primary)", margin: 0 },
  subtitle: { fontSize: "13px", color: "var(--color-text-muted)", margin: "4px 0 0" },
  loading: { color: "var(--color-text-muted)", fontSize: "14px" },
  empty: { display: "flex", flexDirection: "column", alignItems: "center", gap: "12px", padding: "60px", color: "var(--color-text-muted)", fontSize: "14px" },
  tableCard: { background: "var(--color-bg-secondary)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-lg)", overflow: "hidden", flex: 1 },
  tableWrap: { overflowX: "auto" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: "13px" },
  th: { padding: "10px 14px", textAlign: "left", fontWeight: 500, fontSize: "11px", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)", textTransform: "uppercase", letterSpacing: "0.04em", whiteSpace: "nowrap" },
  td: { padding: "9px 14px", color: "var(--color-text-primary)", borderBottom: "1px solid rgba(49,50,68,0.5)", overflow: "hidden", textOverflow: "ellipsis" },
  trEven: { background: "transparent" },
  trOdd: { background: "rgba(49,50,68,0.3)" },
  queryText: { color: "var(--color-text-secondary)", fontSize: "13px" },
  sqlText: { fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-accent)" },
  intentBadge: { padding: "2px 7px", border: "1px solid", borderRadius: "var(--radius-sm)", fontSize: "11px", fontWeight: 600, letterSpacing: "0.04em" },
  statusBadge: { fontSize: "12px", fontWeight: 500 },
  pagination: { display: "flex", alignItems: "center", justifyContent: "center", gap: "16px", padding: "12px 16px", borderTop: "1px solid var(--color-border)" },
  pageBtn: { padding: "6px 14px", background: "transparent", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", color: "var(--color-text-secondary)", fontSize: "13px", cursor: "pointer" },
  pageInfo: { fontSize: "13px", color: "var(--color-text-muted)" },
};