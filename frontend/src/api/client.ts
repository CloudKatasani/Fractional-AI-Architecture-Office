// Thin typed fetch client for the FastAPI backend (/api/v1). Every call is tenant-scoped via X-Tenant-Id.
// Response types for the OpenAPI surface can be regenerated with `npm run gen:api` (src/api/schema.d.ts).

let currentTenant = "northgrid";

export function setTenant(t: string) {
  currentTenant = t;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function qs(params?: Record<string, unknown>): string {
  if (!params) return "";
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
  const res = await fetch(`/api/v1${path}${qs(params)}`, {
    method,
    headers: { "Content-Type": "application/json", "X-Tenant-Id": currentTenant },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T = any>(path: string, params?: Record<string, unknown>) => request<T>("GET", path, undefined, params),
  post: <T = any>(path: string, body?: unknown, params?: Record<string, unknown>) => request<T>("POST", path, body ?? {}, params),
  patch: <T = any>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  url: (path: string, params?: Record<string, unknown>) => `/api/v1${path}${qs({ ...params, tenant_id: currentTenant })}`,
};

// ---- shared response shapes (subset; see backend/app/agents/base.py) -----------------------------
export interface Evidence {
  record_id: string;
  table: string;
  excerpt?: string | null;
}
export interface ProposedAction {
  action_type: string;
  target_id: string;
  target_type: string;
  payload: Record<string, any>;
  rationale: string;
  source_refs: Evidence[];
  approver_role: string;
  priority: number;
}
export interface AgentOutput {
  agent_id: string;
  agent_name: string;
  tenant_id: string;
  run_id: string;
  summary: string;
  findings: any[];
  proposed_actions: ProposedAction[];
  confidence: number;
  cost: { tokens_in: number; tokens_out: number; usd: number; model?: string } | null;
  duration_ms: number;
  autonomy_level: number;
  mode: "observe" | "propose";
  llm_mode: string;
  flagged: any[];
  artifacts: Record<string, any>;
  approvals_created: string[];
  started_at: string;
}
export interface RunMeta {
  run_id: string;
  agent_id: string;
  agent_name: string;
  summary: string;
  started_at: string;
  duration_ms: number;
  mode: "observe" | "propose";
  autonomy_level: number;
  llm_mode: string;
  confidence: number;
  cost: AgentOutput["cost"];
  approvals_created: string[];
  flagged: any[];
}
export interface ApprovalRef {
  id: string;
  status: "pending" | "approved" | "rejected" | "edited";
  approver_role: string;
  decided_by_user_id?: string | null;
  decided_at?: string | null;
  action_type?: string;
}
export interface Approval {
  id: string;
  run_id: string;
  agent_id: string;
  agent_name: string;
  action_type: string;
  target_id: string;
  target_type: string;
  payload_json: Record<string, any>;
  rationale: string;
  source_refs_json: Evidence[];
  approver_role: string;
  status: ApprovalRef["status"];
  decided_by_user_id: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  edited_payload_json: Record<string, any> | null;
  created_at: string;
  applied: boolean;
  side_effects_json: { graph?: string[]; side_effects?: string[]; ticket?: string } | null;
  priority: number;
}
export interface User {
  id: string;
  name: string;
  role: string;
  title: string;
  email: string;
}
