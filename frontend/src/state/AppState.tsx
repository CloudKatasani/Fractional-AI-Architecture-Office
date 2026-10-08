import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setTenant as setApiTenant, User } from "../api/client";

export const TENANTS = [
  { id: "northgrid", name: "NorthGrid Energy", industry: "Utilities" },
  { id: "meridian", name: "Meridian Telecom", industry: "Telecom" },
];

export const ROLE_LABELS: Record<string, string> = {
  principal_architect: "Principal Architect",
  cio: "CIO",
  app_owner: "App Owner",
  security_architect: "Security Architect",
  data_governance_lead: "Data Governance Lead",
  risk_officer: "Risk Officer",
  tech_lead: "Tech Lead",
};

interface Config {
  llm_mode: string;
  model: string;
  live_available: boolean;
  demo_today: string;
}

interface AppState {
  tenant: string;
  tenantName: string;
  setTenant: (t: string) => void;
  users: User[];
  user: User | null;
  setUserId: (id: string) => void;
  config: Config | null;
  setLlmMode: (m: string) => Promise<void>;
  pending: number;
  /** bump to make every useApi hook refetch (after a run or a decision) */
  refreshKey: number;
  refresh: () => void;
  evidenceId: string | null;
  openEvidence: (id: string | null) => void;
  toast: string | null;
  notify: (msg: string) => void;
}

const Ctx = createContext<AppState | null>(null);

function initialTenant(): string {
  const p = new URLSearchParams(window.location.search).get("tenant");
  return p || localStorage.getItem("tenant") || "northgrid";
}

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [tenant, setTenantState] = useState(initialTenant());
  const [users, setUsers] = useState<User[]>([]);
  const [userId, setUserIdState] = useState<string | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [pending, setPending] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  setApiTenant(tenant);

  const setTenant = (t: string) => {
    localStorage.setItem("tenant", t);
    setApiTenant(t);
    setTenantState(t);
    setUserIdState(null);
    setRefreshKey((k) => k + 1);
  };

  useEffect(() => {
    api.get<User[]>("/users").then((us) => {
      setUsers(us);
      const saved = localStorage.getItem(`user:${tenant}`);
      const pa = us.find((u) => u.role === "principal_architect");
      setUserIdState(us.find((u) => u.id === saved)?.id || pa?.id || us[0]?.id || null);
    });
  }, [tenant]);

  useEffect(() => {
    api.get<Config>("/config").then(setConfig);
  }, []);

  useEffect(() => {
    api.get("/approvals", { status: "pending" }).then((r) => setPending(r.items.length)).catch(() => {});
  }, [tenant, refreshKey]);

  const setUserId = (id: string) => {
    localStorage.setItem(`user:${tenant}`, id);
    setUserIdState(id);
  };
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  const notify = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 3500);
  }, []);
  const setLlmMode = async (m: string) => {
    const c = await api.patch<Config>("/config", { llm_mode: m });
    setConfig(c);
  };

  const value = useMemo<AppState>(
    () => ({
      tenant,
      tenantName: TENANTS.find((t) => t.id === tenant)?.name || tenant,
      setTenant,
      users,
      user: users.find((u) => u.id === userId) || null,
      setUserId,
      config,
      setLlmMode,
      pending,
      refreshKey,
      refresh,
      evidenceId,
      openEvidence: setEvidenceId,
      toast,
      notify,
    }),
    [tenant, users, userId, config, pending, refreshKey, evidenceId, toast],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside provider");
  return v;
}

/** Fetch helper that refetches when tenant / refreshKey / deps change. */
export function useApi<T = any>(path: string | null, params?: Record<string, unknown>, deps: unknown[] = []) {
  const { tenant, refreshKey } = useApp();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [local, setLocal] = useState(0);
  const key = JSON.stringify(params || {});
  useEffect(() => {
    if (!path) return;
    let alive = true;
    setLoading(true);
    api
      .get<T>(path, params)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(String(e.message || e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path, key, tenant, refreshKey, local, ...deps]);
  return { data, error, loading, reload: () => setLocal((x) => x + 1), setData };
}
