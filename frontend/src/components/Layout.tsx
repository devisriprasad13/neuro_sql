/**
 * Main application layout with sidebar navigation.
 * Wraps all authenticated pages via React Router's Outlet.
 */

import { NavLink, Outlet } from "react-router-dom";

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/query",       label: "Query",       icon: "⚡" },
  { path: "/connections", label: "Connections", icon: "🔌" },
  { path: "/history",     label: "History",     icon: "📋" },
];

export default function Layout() {
  return (
    <div style={styles.shell}>
      {/* Sidebar */}
      <aside style={styles.sidebar}>
        {/* Logo */}
        <div style={styles.logo}>
          <span style={styles.logoIcon}>⚙</span>
          <span style={styles.logoText}>NeuroSQL</span>
        </div>

        {/* Navigation */}
        <nav style={styles.nav}>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              style={({ isActive }) => ({
                ...styles.navLink,
                ...(isActive ? styles.navLinkActive : {}),
              })}
            >
              <span style={styles.navIcon}>{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div style={styles.sidebarFooter}>
          <div style={styles.badge}>Milestone 11</div>
          <div style={styles.badgeSub}>Core UI</div>
        </div>
      </aside>

      {/* Main content area */}
      <main style={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  shell: {
    display: "flex",
    height: "100vh",
    background: "var(--color-bg-primary)",
    overflow: "hidden",
  },
  sidebar: {
    width: "220px",
    minWidth: "220px",
    background: "var(--color-bg-secondary)",
    borderRight: "1px solid var(--color-border)",
    display: "flex",
    flexDirection: "column",
    padding: "0",
  },
  logo: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "20px 20px 16px",
    borderBottom: "1px solid var(--color-border)",
  },
  logoIcon: {
    fontSize: "20px",
  },
  logoText: {
    fontSize: "16px",
    fontWeight: 600,
    color: "var(--color-text-primary)",
    letterSpacing: "-0.3px",
  },
  nav: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    padding: "12px 8px",
    flex: 1,
  },
  navLink: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "9px 12px",
    borderRadius: "var(--radius-md)",
    fontSize: "14px",
    fontWeight: 400,
    color: "var(--color-text-secondary)",
    textDecoration: "none",
    transition: "all var(--transition-fast)",
  },
  navLinkActive: {
    background: "rgba(137, 180, 250, 0.12)",
    color: "var(--color-accent)",
    fontWeight: 500,
  },
  navIcon: {
    fontSize: "16px",
    width: "20px",
    textAlign: "center",
  },
  sidebarFooter: {
    padding: "16px 20px",
    borderTop: "1px solid var(--color-border)",
  },
  badge: {
    fontSize: "11px",
    fontWeight: 600,
    color: "var(--color-accent)",
    letterSpacing: "0.05em",
    textTransform: "uppercase",
  },
  badgeSub: {
    fontSize: "11px",
    color: "var(--color-text-muted)",
    marginTop: "2px",
  },
  main: {
    flex: 1,
    overflow: "auto",
    display: "flex",
    flexDirection: "column",
  },
};