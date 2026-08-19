/**
 * SQL Inspector — displays generated SQL with syntax highlighting
 * and a copy-to-clipboard button.
 */

import { useState } from "react";

interface SQLInspectorProps {
  sql: string;
  wasCorrected?: boolean;
  correctionAttempts?: number;
  executionTimeMs?: number;
}

// Simple SQL keyword highlighter
function highlightSQL(sql: string): React.ReactNode[] {
  const keywords = [
    "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
    "ON", "AND", "OR", "NOT", "IN", "IS", "NULL", "AS", "ORDER", "BY",
    "GROUP", "HAVING", "LIMIT", "OFFSET", "INSERT", "INTO", "VALUES",
    "UPDATE", "SET", "DELETE", "CREATE", "TABLE", "ALTER", "DROP",
    "DISTINCT", "COUNT", "SUM", "AVG", "MIN", "MAX", "CASE", "WHEN",
    "THEN", "ELSE", "END", "WITH", "UNION", "ALL", "EXISTS", "BETWEEN",
    "LIKE", "TRUE", "FALSE", "ASC", "DESC",
  ];

  const keywordSet = new Set(keywords);
  const tokens = sql.split(/(\s+|,|;|\(|\)|=|<|>|!|\.|'[^']*'|"[^"]*")/g);

  return tokens.map((token, i) => {
    const upper = token.trim().toUpperCase();

    if (keywordSet.has(upper)) {
      return <span key={i} style={sqlStyles.keyword}>{token}</span>;
    }
    if (/^'[^']*'$/.test(token) || /^"[^"]*"$/.test(token)) {
      return <span key={i} style={sqlStyles.string}>{token}</span>;
    }
    if (/^\d+(\.\d+)?$/.test(token.trim())) {
      return <span key={i} style={sqlStyles.number}>{token}</span>;
    }
    if (token.startsWith("--")) {
      return <span key={i} style={sqlStyles.comment}>{token}</span>;
    }
    return <span key={i} style={sqlStyles.default}>{token}</span>;
  });
}

const sqlStyles: Record<string, React.CSSProperties> = {
  keyword: { color: "#cba6f7", fontWeight: 600 },
  string:  { color: "#a6e3a1" },
  number:  { color: "#fab387" },
  comment: { color: "#6c7086", fontStyle: "italic" },
  default: { color: "#cdd6f4" },
};

export default function SQLInspector({
  sql,
  wasCorrected = false,
  correctionAttempts = 1,
  executionTimeMs,
}: SQLInspectorProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-HTTPS
      const el = document.createElement("textarea");
      el.value = sql;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.title}>SQL Inspector</span>
          {wasCorrected && (
            <span style={styles.correctedBadge}>
              ⚡ Self-corrected ({correctionAttempts} attempt{correctionAttempts !== 1 ? "s" : ""})
            </span>
          )}
        </div>
        <div style={styles.headerRight}>
          {executionTimeMs !== undefined && (
            <span style={styles.timing}>{executionTimeMs.toFixed(0)}ms</span>
          )}
          <button style={styles.copyBtn} onClick={handleCopy}>
            {copied ? "✓ Copied" : "Copy"}
          </button>
        </div>
      </div>

      {/* SQL code block */}
      <div style={styles.codeContainer}>
        <pre style={styles.pre}>
          <code>{highlightSQL(sql)}</code>
        </pre>
      </div>

      {/* Footer stats */}
      <div style={styles.footer}>
        <span style={styles.footerItem}>
          {sql.trim().split(/\s+/).length} tokens
        </span>
        <span style={styles.footerItem}>
          {sql.length} chars
        </span>
        <span style={styles.footerItem}>
          {sql.trim().toUpperCase().startsWith("SELECT")
            ? "READ query"
            : sql.trim().toUpperCase().startsWith("INSERT")
            ? "WRITE — INSERT"
            : sql.trim().toUpperCase().startsWith("UPDATE")
            ? "WRITE — UPDATE"
            : sql.trim().toUpperCase().startsWith("DELETE")
            ? "WRITE — DELETE"
            : "DDL query"}
        </span>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "var(--color-bg-secondary)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-lg)",
    overflow: "hidden",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "10px 16px",
    borderBottom: "1px solid var(--color-border)",
    background: "rgba(49,50,68,0.3)",
  },
  headerLeft: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
  },
  title: {
    fontSize: "12px",
    fontWeight: 600,
    color: "var(--color-text-muted)",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
  },
  correctedBadge: {
    fontSize: "11px",
    padding: "2px 8px",
    background: "rgba(249,226,175,0.12)",
    color: "var(--color-warning)",
    borderRadius: "var(--radius-full)",
    fontWeight: 500,
  },
  headerRight: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
  },
  timing: {
    fontSize: "12px",
    color: "var(--color-text-muted)",
    fontFamily: "var(--font-mono)",
  },
  copyBtn: {
    padding: "4px 12px",
    background: "transparent",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--radius-md)",
    color: "var(--color-text-secondary)",
    fontSize: "12px",
    cursor: "pointer",
    fontFamily: "var(--font-sans)",
  },
  codeContainer: {
    overflowX: "auto",
    maxHeight: "300px",
    overflowY: "auto",
  },
  pre: {
    margin: 0,
    padding: "16px",
    fontSize: "13px",
    fontFamily: "var(--font-mono)",
    lineHeight: 1.6,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  footer: {
    display: "flex",
    gap: "16px",
    padding: "8px 16px",
    borderTop: "1px solid var(--color-border)",
    background: "rgba(49,50,68,0.2)",
  },
  footerItem: {
    fontSize: "11px",
    color: "var(--color-text-muted)",
  },
};