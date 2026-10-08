import { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { ROLE_LABELS, TENANTS, useApp } from "../state/AppState";
import { EvidenceDrawer } from "./Evidence";
import { Badge } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/ai-governance", label: "AI Governance" },
  { to: "/application", label: "Application Architecture" },
  { to: "/enterprise", label: "Enterprise Architecture" },
  { to: "/data", label: "Data Architecture" },
  { to: "/copilot", label: "Copilot" },
  { to: "/approvals", label: "Approvals" },
  { to: "/audit", label: "Audit" },
  { to: "/graph", label: "Graph Explorer" },
  { to: "/agents", label: "Agents" },
  { to: "/sources", label: "Ingested Sources" },
];

export function Layout({ children }: { children: ReactNode }) {
  const { tenant, setTenant, users, user, setUserId, config, setLlmMode, pending, toast, notify } = useApp();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 flex h-12 items-center justify-between border-b border-gray-200 bg-white px-4">
        <div className="flex items-center gap-3">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-accent-600 text-xs font-bold text-white">AO</div>
          <div className="text-sm font-semibold text-gray-900">Fractional AI Architecture Office</div>
          <select className="input py-1 ml-3" value={tenant} onChange={(e) => setTenant(e.target.value)} data-testid="tenant-select">
            {TENANTS.map((t) => (
              <option key={t.id} value={t.id}>{t.name} ({t.industry})</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs muted">Acting as</label>
          <select className="input py-1 max-w-[22rem]" value={user?.id || ""} onChange={(e) => setUserId(e.target.value)} data-testid="user-select">
            {users.map((u) => (
              <option key={u.id} value={u.id}>{u.name} — {ROLE_LABELS[u.role] || u.role}</option>
            ))}
          </select>
          {config && (
            <button
              title={config.live_available ? "Toggle LLM mode" : "Set ANTHROPIC_API_KEY to enable live mode"}
              onClick={() =>
                config.live_available
                  ? setLlmMode(config.llm_mode === "live" ? "mock" : "live").catch((e) => notify(e.message))
                  : notify("Live mode needs ANTHROPIC_API_KEY in the environment; running in deterministic mock mode.")
              }
            >
              <Badge color={config.llm_mode === "live" ? "purple" : "gray"}>{config.llm_mode === "live" ? `Live · ${config.model}` : "Mock LLM"}</Badge>
            </button>
          )}
          <NavLink to="/approvals" className="relative">
            <Badge color={pending ? "amber" : "gray"}>{pending} pending approvals</Badge>
          </NavLink>
        </div>
      </header>
      <div className="flex">
        <nav className="sticky top-12 h-[calc(100vh-3rem)] w-56 shrink-0 overflow-auto border-r border-gray-200 bg-white py-3">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `block px-4 py-1.5 text-sm ${isActive ? "bg-accent-50 font-medium text-accent-700 border-r-2 border-accent-600" : "text-gray-600 hover:bg-gray-50"}`
              }
            >
              {n.label}
            </NavLink>
          ))}
          {config && <div className="mt-6 px-4 text-[11px] muted">Demo date {config.demo_today}</div>}
        </nav>
        <main className="min-w-0 flex-1 p-5">{children}</main>
      </div>
      <EvidenceDrawer />
      {toast && (
        <div className="fixed bottom-4 right-4 z-50 max-w-md rounded-md bg-gray-900 px-4 py-2.5 text-sm text-white shadow-lg">{toast}</div>
      )}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1>{title}</h1>
        {subtitle && <div className="mt-0.5 text-sm muted">{subtitle}</div>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
