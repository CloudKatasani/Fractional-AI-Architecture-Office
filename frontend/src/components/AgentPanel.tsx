import { ReactNode, useState } from "react";
import { api, AgentOutput, ApprovalRef, RunMeta } from "../api/client";
import { ROLE_LABELS, useApp } from "../state/AppState";
import { TextWithChips } from "./Evidence";
import { Badge, since, StatusBadge } from "./ui";

/** Header shown on every agent-generated panel: agent name, run time, Observe/Propose state, Re-run. */
export function AgentPanel({ agentId, agentName, run, params, children, title, onRan, runLabel, compact }: {
  agentId: string; agentName?: string; run?: RunMeta | null; params?: Record<string, unknown>; children?: ReactNode;
  title?: ReactNode; onRan?: (o: AgentOutput) => void; runLabel?: string; compact?: boolean;
}) {
  const { user, refresh, notify } = useApp();
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [lastOut, setLastOut] = useState<AgentOutput | null>(null);
  const meta: Partial<RunMeta> | null = lastOut || run || null;

  const doRun = async () => {
    setRunning(true);
    setErr(null);
    try {
      const out = await api.post<AgentOutput>("/agents/run", { agent_id: agentId, params: params || {}, user_id: user?.id });
      setLastOut(out);
      onRan?.(out);
      notify(`${out.agent_name}: ${out.findings.length} findings` + (out.approvals_created.length ? `, ${out.approvals_created.length} items in the approval inbox` : out.mode === "observe" ? " (observe only)" : ""));
      refresh();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded bg-accent-50 text-accent-700 text-xs font-bold">AI</span>
          <div>
            <div className="text-sm font-semibold text-gray-900">{title || meta?.agent_name || agentName || agentId}</div>
            <div className="text-[11px] muted font-mono">{agentId}</div>
          </div>
          {meta?.mode && (
            <Badge color={meta.mode === "observe" ? "gray" : "blue"} title="Autonomy level">
              {meta.mode === "observe" ? "Observe" : "Propose"} · L{meta.autonomy_level}
            </Badge>
          )}
          {meta?.llm_mode && <Badge color={meta.llm_mode === "live" ? "purple" : "gray"}>{meta.llm_mode}</Badge>}
        </div>
        <div className="flex items-center gap-3">
          {meta?.started_at && (
            <span className="text-[11px] muted">
              ran {since(meta.started_at)} · {meta.duration_ms} ms{meta.cost ? ` · $${meta.cost.usd.toFixed(4)}` : ""}
            </span>
          )}
          <button className="btn btn-sm" onClick={doRun} disabled={running}>
            {running ? "Running…" : runLabel || (meta ? "Re-run" : "Run")}
          </button>
        </div>
      </div>
      {running && (
        <div className="h-0.5 w-full overflow-hidden bg-accent-50">
          <div className="h-full w-1/3 animate-pulse bg-accent-500" />
        </div>
      )}
      {(meta?.summary || err) && (
        <div className="px-4 pt-3 text-sm leading-relaxed text-gray-700">
          {err ? <span className="text-red-700">{err}</span> : <TextWithChips text={meta!.summary!} />}
          {meta?.approvals_created && meta.approvals_created.length > 0 && (
            <span className="ml-1 text-xs muted">({meta.approvals_created.length} items sent to the approval inbox)</span>
          )}
        </div>
      )}
      {!meta && !running && <div className="px-4 pt-3 text-sm muted">Not run yet for this tenant.</div>}
      <div className={compact ? "p-3" : "p-4"}>{children}</div>
    </div>
  );
}

// Mirrors backend/app/orchestrator/approval_gate.py ROLE_CAN_APPROVE
export const ROLE_CAN_APPROVE: Record<string, string[]> = {
  principal_architect: ["principal_architect", "app_owner", "tech_lead", "security_architect", "data_governance_lead"],
  cio: ["cio"],
  app_owner: ["app_owner"],
  security_architect: ["security_architect"],
  data_governance_lead: ["data_governance_lead"],
  risk_officer: ["risk_officer"],
  tech_lead: ["tech_lead"],
};

/** Inline approval state + quick approve/reject for the current "Acting as" user. */
export function ApprovalControls({ approval, compact }: { approval?: ApprovalRef | null; compact?: boolean }) {
  const { user, refresh, notify } = useApp();
  const [busy, setBusy] = useState(false);
  if (!approval) return <span className="text-[11px] muted">no proposal</span>;
  const canDecide = user && ROLE_CAN_APPROVE[user.role]?.includes(approval.approver_role);
  const decide = async (decision: "approve" | "reject") => {
    let note: string | null = null;
    if (decision === "reject") {
      note = window.prompt("Reason for rejecting?") || null;
      if (note === null) return;
    }
    setBusy(true);
    try {
      const r = await api.post(`/approvals/${approval.id}/decide`, { decision, user_id: user!.id, note });
      notify(`${decision === "approve" ? "Approved" : "Rejected"} ${approval.id}` + (r.side_effects_json?.ticket ? ` — ticket ${r.side_effects_json.ticket} created` : ""));
      refresh();
    } catch (e: any) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (approval.status !== "pending") return <StatusBadge status={approval.status} />;
  return (
    <span className="inline-flex items-center gap-1.5">
      <StatusBadge status="pending" />
      {!compact && <span className="text-[11px] muted">{ROLE_LABELS[approval.approver_role] || approval.approver_role}</span>}
      {canDecide && (
        <>
          <button className="btn-primary btn-sm" disabled={busy} onClick={() => decide("approve")}>Approve</button>
          <button className="btn btn-sm" disabled={busy} onClick={() => decide("reject")}>Reject</button>
        </>
      )}
    </span>
  );
}
