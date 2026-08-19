/**
 * Connections page — register and manage database connections.
 */

import { useState } from "react";
import {
  useConnections,
  useCreateConnection,
  useTestConnection,
  useCrawlConnection,
  type Connection,
} from "../api/queries";

export default function ConnectionsPage() {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    db_type: "postgres",
    host: "",
    port: "",
    database_name: "",
    username: "",
    password: "",
    description: "",
  });
  const [testResults, setTestResults] = useState<Record<string, string>>({});
  const [crawlResults, setCrawlResults] = useState<Record<string, string>>({});

  const { data, isLoading } = useConnections();
  const connections = data?.connections ?? [];
  const createMutation = useCreateConnection();
  const testMutation = useTestConnection();
  const crawlMutation = useCrawlConnection();

  const handleCreate = async () => {
    if (!form.name || !form.db_type) return;
    try {
      await createMutation.mutateAsync({
        name: form.name,
        db_type: form.db_type,
        host: form.host || undefined,
        port: form.port ? parseInt(form.port) : undefined,
        database_name: form.database_name || undefined,
        username: form.username || undefined,
        password: form.password || undefined,
        description: form.description || undefined,
      });
      setShowForm(false);
      setForm({
        name: "", db_type: "postgres", host: "", port: "",
        database_name: "", username: "", password: "", description: "",
      });
    } catch (err) {
      console.error("Create failed:", err);
    }
  };

  const handleTest = async (id: string) => {
    setTestResults((p) => ({ ...p, [id]: "Testing..." }));
    try {
      const result = await testMutation.mutateAsync(id);
      setTestResults((p) => ({
        ...p,
        [id]: result.is_reachable
          ? `✓ Connected (${result.latency_ms?.toFixed(0)}ms)`
          : `✗ ${result.message}`,
      }));
    } catch {
      setTestResults((p) => ({ ...p, [id]: "✗ Test failed" }));
    }
  };

  const handleCrawl = async (id: string) => {
    setCrawlResults((p) => ({ ...p, [id]: "Crawling..." }));
    try {
      const result = await crawlMutation.mutateAsync(id);
      setCrawlResults((p) => ({
        ...p,
        [id]: `✓ ${result.table_count} tables, ${result.embedded_count} vectors`,
      }));
    } catch {
      setCrawlResults((p) => ({ ...p, [id]: "✗ Crawl failed" }));
    }
  };

  const dbTypeColor: Record<string, string> = {
    postgres: "#89b4fa",
    mysql: "#a6e3a1",
    bigquery: "#f9e2af",
    snowflake: "#cba6f7",
  };

  return (
    <div style={styles.page}>
      {/* Header */}
      <div style={styles.headerRow}>
        <div>
          <h1 style={styles.title}>Connections</h1>
          <p style={styles.subtitle}>
            {data?.total ?? 0} database{data?.total !== 1 ? "s" : ""} registered
          </p>
        </div>
        <button style={styles.addBtn} onClick={() => setShowForm(!showForm)}>
          {showForm ? "Cancel" : "+ Add Connection"}
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div style={styles.card}>
          <div style={styles.cardTitle}>Register New Connection</div>
          <div style={styles.formGrid}>
            <div style={styles.formGroup}>
              <label style={styles.label}>Name *</label>
              <input
                style={styles.input}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Production DB"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>Type *</label>
              <select
                style={styles.input}
                value={form.db_type}
                onChange={(e) => setForm({ ...form, db_type: e.target.value })}
              >
                <option value="postgres">PostgreSQL</option>
                <option value="mysql">MySQL</option>
                <option value="bigquery">BigQuery</option>
                <option value="snowflake">Snowflake</option>
              </select>
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>Host</label>
              <input
                style={styles.input}
                value={form.host}
                onChange={(e) => setForm({ ...form, host: e.target.value })}
                placeholder="localhost"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>Port</label>
              <input
                style={styles.input}
                value={form.port}
                onChange={(e) => setForm({ ...form, port: e.target.value })}
                placeholder="5432"
                type="number"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>Database</label>
              <input
                style={styles.input}
                value={form.database_name}
                onChange={(e) =>
                  setForm({ ...form, database_name: e.target.value })
                }
                placeholder="mydb"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>Username</label>
              <input
                style={styles.input}
                value={form.username}
                onChange={(e) =>
                  setForm({ ...form, username: e.target.value })
                }
                placeholder="dbuser"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>Password</label>
              <input
                style={styles.input}
                value={form.password}
                onChange={(e) =>
                  setForm({ ...form, password: e.target.value })
                }
                type="password"
                placeholder="••••••••"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>Description</label>
              <input
                style={styles.input}
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                placeholder="Optional"
              />
            </div>
          </div>
          <div style={styles.formActions}>
            <button
              style={styles.primaryBtn}
              onClick={handleCreate}
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? "Creating..." : "Create Connection"}
            </button>
          </div>
        </div>
      )}

      {/* Connections list */}
      {isLoading ? (
        <div style={styles.loading}>Loading connections...</div>
      ) : connections.length === 0 ? (
        <div style={styles.empty}>
          <div style={{ fontSize: "36px" }}>🔌</div>
          <div>No connections yet. Add your first database above.</div>
        </div>
      ) : (
        <div style={styles.list}>
          {connections.map((conn: Connection) => (
            <div key={conn.id} style={styles.connCard}>
              <div style={styles.connTop}>
                <div style={styles.connLeft}>
                  <span
                    style={{
                      ...styles.dbBadge,
                      color: dbTypeColor[conn.db_type] || "#cdd6f4",
                      borderColor: dbTypeColor[conn.db_type] || "#cdd6f4",
                    }}
                  >
                    {conn.db_type.toUpperCase()}
                  </span>
                  <div>
                    <div style={styles.connName}>{conn.name}</div>
                    <div style={styles.connHost}>
                      {conn.host
                        ? `${conn.host}:${conn.port}/${conn.database_name}`
                        : conn.db_type}
                    </div>
                  </div>
                </div>
                <div style={styles.connRight}>
                  <span
                    style={{
                      ...styles.verifiedBadge,
                      background: conn.is_verified
                        ? "rgba(166,227,161,0.15)"
                        : "rgba(108,112,134,0.15)",
                      color: conn.is_verified
                        ? "var(--color-success)"
                        : "var(--color-text-muted)",
                    }}
                  >
                    {conn.is_verified ? "✓ Verified" : "Unverified"}
                  </span>
                  <span
                    style={{
                      ...styles.verifiedBadge,
                      background: conn.crawl_status === "completed"
                        ? "rgba(137,180,250,0.15)"
                        : "rgba(108,112,134,0.15)",
                      color: conn.crawl_status === "completed"
                        ? "var(--color-accent)"
                        : "var(--color-text-muted)",
                    }}
                  >
                    {conn.crawl_status === "completed" ? "✓ Indexed" : "Not indexed"}
                  </span>
                </div>
              </div>

              {/* Action buttons */}
              <div style={styles.connActions}>
                <button
                  style={styles.actionBtn}
                  onClick={() => handleTest(conn.id)}
                  disabled={testMutation.isPending}
                >
                  Test
                </button>
                <button
                  style={styles.actionBtn}
                  onClick={() => handleCrawl(conn.id)}
                  disabled={crawlMutation.isPending}
                >
                  Index Schema
                </button>
                {testResults[conn.id] && (
                  <span style={styles.resultText}>{testResults[conn.id]}</span>
                )}
                {crawlResults[conn.id] && (
                  <span style={styles.resultText}>{crawlResults[conn.id]}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: { padding: "28px 32px", display: "flex", flexDirection: "column", gap: "20px", overflow: "auto" },
  headerRow: { display: "flex", justifyContent: "space-between", alignItems: "flex-start" },
  title: { fontSize: "22px", fontWeight: 600, color: "var(--color-text-primary)", margin: 0 },
  subtitle: { fontSize: "13px", color: "var(--color-text-muted)", margin: "4px 0 0" },
  addBtn: { padding: "9px 18px", background: "var(--color-accent)", color: "#0f0f1a", border: "none", borderRadius: "var(--radius-md)", fontSize: "13px", fontWeight: 600, cursor: "pointer" },
  card: { background: "var(--color-bg-secondary)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-lg)", padding: "20px" },
  cardTitle: { fontSize: "14px", fontWeight: 600, color: "var(--color-text-primary)", marginBottom: "16px" },
  formGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" },
  formGroup: { display: "flex", flexDirection: "column", gap: "5px" },
  label: { fontSize: "12px", color: "var(--color-text-muted)", fontWeight: 500 },
  input: { padding: "8px 10px", background: "var(--color-bg-primary)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", color: "var(--color-text-primary)", fontSize: "13px", outline: "none" },
  formActions: { marginTop: "16px", display: "flex", justifyContent: "flex-end" },
  primaryBtn: { padding: "9px 20px", background: "var(--color-accent)", color: "#0f0f1a", border: "none", borderRadius: "var(--radius-md)", fontSize: "13px", fontWeight: 600, cursor: "pointer" },
  loading: { color: "var(--color-text-muted)", fontSize: "14px" },
  empty: { display: "flex", flexDirection: "column", alignItems: "center", gap: "12px", padding: "60px", color: "var(--color-text-muted)", fontSize: "14px" },
  list: { display: "flex", flexDirection: "column", gap: "12px" },
  connCard: { background: "var(--color-bg-secondary)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-lg)", padding: "16px", display: "flex", flexDirection: "column", gap: "12px" },
  connTop: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  connLeft: { display: "flex", alignItems: "center", gap: "12px" },
  dbBadge: { padding: "3px 8px", border: "1px solid", borderRadius: "var(--radius-sm)", fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em" },
  connName: { fontSize: "14px", fontWeight: 500, color: "var(--color-text-primary)" },
  connHost: { fontSize: "12px", color: "var(--color-text-muted)", marginTop: "2px" },
  connRight: { display: "flex", gap: "8px" },
  verifiedBadge: { padding: "3px 10px", borderRadius: "var(--radius-full)", fontSize: "12px", fontWeight: 500 },
  connActions: { display: "flex", alignItems: "center", gap: "8px" },
  actionBtn: { padding: "6px 14px", background: "transparent", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", color: "var(--color-text-secondary)", fontSize: "12px", cursor: "pointer" },
  resultText: { fontSize: "12px", color: "var(--color-text-secondary)" },
};