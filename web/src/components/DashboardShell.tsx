import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

type DashboardShellProps = {
  location: string;
  setLocation: (value: string) => void;
  children: ReactNode;
};

const links = [
  { to: "/", label: "Overview" },
  { to: "/plan-copilot", label: "Plan Copilot" },
  { to: "/outfit-packing", label: "Outfit + Packing" },
  { to: "/health-alerts", label: "Health Alerts" },
  { to: "/anomalies", label: "Anomalies" },
];

export function DashboardShell({ location, setLocation, children }: DashboardShellProps) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1 className="brand-title">ForecastHub</h1>
        <p className="brand-subtitle">Weather Intelligence Command Center</p>

        <div className="location-panel">
          <label htmlFor="location-input">Location</label>
          <input
            id="location-input"
            value={location}
            onChange={(event) => setLocation(event.target.value)}
            placeholder="City name"
          />
        </div>

        <nav className="nav-links">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/"}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="content">{children}</main>
    </div>
  );
}
