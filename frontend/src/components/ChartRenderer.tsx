/**
 * Auto chart renderer — selects and renders the best chart type
 * based on query result schema and data shape.
 *
 * Uses Recharts for all visualizations.
 */

import {
  BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from "recharts";

interface ChartRendererProps {
  columns: string[];
  rows: unknown[][];
}

// ------------------------------------------------------------------ //
// Column type detection
// ------------------------------------------------------------------ //

type ColType = "numeric" | "date" | "text";

function detectColumnType(values: unknown[]): ColType {
  const sample = values.filter((v) => v !== null && v !== "").slice(0, 10);
  if (sample.length === 0) return "text";

  const numericCount = sample.filter((v) => !isNaN(Number(v))).length;
  if (numericCount / sample.length >= 0.8) return "numeric";

  const dateCount = sample.filter((v) => {
    const d = new Date(String(v));
    return !isNaN(d.getTime()) && String(v).length > 4;
  }).length;
  if (dateCount / sample.length >= 0.8) return "date";

  return "text";
}

// ------------------------------------------------------------------ //
// Chart type selection
// ------------------------------------------------------------------ //

type ChartType = "bar" | "line" | "stat" | "none";

function selectChartType(
  columns: string[],
  rows: unknown[][],
  colTypes: ColType[]
): ChartType {
  if (rows.length === 0 || columns.length === 0) return "none";

  if (columns.length === 1 && colTypes[0] === "numeric") return "stat";

  if (columns.length === 2) {
    if (colTypes[0] === "date" && colTypes[1] === "numeric") return "line";
    if ((colTypes[0] === "text" || colTypes[0] === "date") && colTypes[1] === "numeric")
      return "bar";
  }

  if (columns.length >= 2) {
    const textIdx = colTypes.findIndex((t) => t === "text" || t === "date");
    const numIdx = colTypes.findIndex((t) => t === "numeric");
    if (textIdx !== -1 && numIdx !== -1) return "bar";
  }

  return "none";
}

// ------------------------------------------------------------------ //
// Chart colors
// ------------------------------------------------------------------ //

const COLORS = [
  "#89b4fa", "#a6e3a1", "#f9e2af", "#cba6f7",
  "#f38ba8", "#94e2d5", "#fab387", "#74c7ec",
];

// ------------------------------------------------------------------ //
// Subcomponents
// ------------------------------------------------------------------ //

function StatCard({ value, label }: { value: unknown; label: string }) {
  return (
    <div style={statStyles.card}>
      <div style={statStyles.value}>{String(value)}</div>
      <div style={statStyles.label}>{label}</div>
    </div>
  );
}

const statStyles: Record<string, React.CSSProperties> = {
  card: {
    display: "flex", flexDirection: "column", alignItems: "center",
    justifyContent: "center", padding: "32px", gap: "8px",
  },
  value: {
    fontSize: "48px", fontWeight: 700,
    color: "var(--color-accent)", lineHeight: 1,
  },
  label: {
    fontSize: "13px", color: "var(--color-text-muted)",
    textTransform: "uppercase", letterSpacing: "0.06em",
  },
};

function BarChartView({
  data, xKey, yKey,
}: {
  data: Record<string, unknown>[];
  xKey: string;
  yKey: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(49,50,68,0.8)" />
        <XAxis
          dataKey={xKey}
          tick={{ fontSize: 11, fill: "#6c7086" }}
          tickLine={false}
          axisLine={{ stroke: "#313244" }}
        />
        <YAxis
          tick={{ fontSize: 11, fill: "#6c7086" }}
          tickLine={false}
          axisLine={false}
          width={50}
        />
        <Tooltip
          contentStyle={{
            background: "#1e1e2e",
            border: "1px solid #313244",
            borderRadius: "8px",
            fontSize: "12px",
          }}
        />
        <Bar dataKey={yKey} radius={[4, 4, 0, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function LineChartView({
  data, xKey, yKey,
}: {
  data: Record<string, unknown>[];
  xKey: string;
  yKey: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(49,50,68,0.8)" />
        <XAxis
          dataKey={xKey}
          tick={{ fontSize: 11, fill: "#6c7086" }}
          tickLine={false}
          axisLine={{ stroke: "#313244" }}
        />
        <YAxis
          tick={{ fontSize: 11, fill: "#6c7086" }}
          tickLine={false}
          axisLine={false}
          width={50}
        />
        <Tooltip
          contentStyle={{
            background: "#1e1e2e",
            border: "1px solid #313244",
            borderRadius: "8px",
            fontSize: "12px",
          }}
        />
        <Line
          type="monotone"
          dataKey={yKey}
          stroke="#89b4fa"
          strokeWidth={2}
          dot={{ fill: "#89b4fa", r: 3 }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ------------------------------------------------------------------ //
// Main component
// ------------------------------------------------------------------ //

export default function ChartRenderer({ columns, rows }: ChartRendererProps) {
  if (rows.length === 0 || columns.length === 0) return null;

  // Detect column types from sample data
  const colTypes: ColType[] = columns.map((_, ci) =>
    detectColumnType(rows.map((r) => r[ci]))
  );

  const chartType = selectChartType(columns, rows, colTypes);
  if (chartType === "none") return null;

  // Convert rows to recharts-friendly format
  const data = rows.map((row) => {
    const obj: Record<string, unknown> = {};
    columns.forEach((col, ci) => {
      obj[col] = colTypes[ci] === "numeric" ? Number(row[ci]) : row[ci];
    });
    return obj;
  });

  // Find x and y keys for bar/line charts
  const xKey = columns.find((_, ci) => colTypes[ci] !== "numeric") ?? columns[0];
  const yKey = columns.find((_, ci) => colTypes[ci] === "numeric") ?? columns[1];

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.chartType}>
          {chartType === "bar" && "📊 Bar Chart"}
          {chartType === "line" && "📈 Line Chart"}
          {chartType === "stat" && "🔢 Stat"}
        </span>
        <span style={styles.hint}>Auto-selected based on result schema</span>
      </div>

      {chartType === "stat" && rows[0] && (
        <StatCard value={rows[0][0]} label={columns[0]} />
      )}

      {chartType === "bar" && (
        <BarChartView data={data} xKey={xKey} yKey={yKey} />
      )}

      {chartType === "line" && (
        <LineChartView data={data} xKey={xKey} yKey={yKey} />
      )}
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
  },
  chartType: {
    fontSize: "12px",
    fontWeight: 600,
    color: "var(--color-text-secondary)",
  },
  hint: {
    fontSize: "11px",
    color: "var(--color-text-muted)",
  },
};