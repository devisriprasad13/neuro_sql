import { Routes, Route } from "react-router-dom";

const DashboardPage = () => (
  <div style={{
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    fontFamily: "system-ui, sans-serif",
    background: "#0f0f1a",
    color: "#cdd6f4",
    gap: "16px",
  }}>
    <h1 style={{ fontSize: "2.5rem", fontWeight: 600, margin: 0 }}>
      NeuroSQL
    </h1>
    <p style={{ fontSize: "1.1rem", color: "#6c7086", margin: 0 }}>
      AI-powered database management platform
    </p>
    <div style={{
      marginTop: "24px",
      padding: "16px 24px",
      background: "#1e1e2e",
      border: "1px solid #313244",
      borderRadius: "8px",
      fontSize: "14px",
      color: "#a6e3a1",
    }}>
      Milestone 1 complete — environment is running
    </div>
    <p style={{ fontSize: "13px", color: "#6c7086" }}>
      API health check: http://localhost:8000/api/v1/health
    </p>
  </div>
);

const LoginPage = () => (
  <div style={{
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    fontFamily: "system-ui, sans-serif",
    background: "#0f0f1a",
    color: "#cdd6f4",
  }}>
    <h2>Login — Coming in Milestone 13</h2>
  </div>
);

const RegisterPage = () => (
  <div style={{
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    fontFamily: "system-ui, sans-serif",
    background: "#0f0f1a",
    color: "#cdd6f4",
  }}>
    <h2>Register — Coming in Milestone 13</h2>
  </div>
);

const NotFoundPage = () => (
  <div style={{
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    height: "100vh",
    fontFamily: "system-ui, sans-serif",
    background: "#0f0f1a",
    color: "#cdd6f4",
    gap: "12px",
  }}>
    <h1 style={{ fontSize: "4rem", margin: 0, color: "#f38ba8" }}>404</h1>
    <p style={{ color: "#6c7086" }}>Page not found</p>
    <a href="/" style={{ color: "#89b4fa", fontSize: "14px" }}>Back to dashboard</a>
  </div>
);

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}