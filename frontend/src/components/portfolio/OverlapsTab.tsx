import { useState } from "react";
import { AgentOutput, api, ApprovalRef } from "../../api/client";
import { ROLE_LABELS, useApi, useApp } from "../../state/AppState";
import { AgentPanel, ApprovalControls } from "../AgentPanel";
import { EvidenceChip, EvidenceList, TextWithChips } from "../Evidence";
import { Markdown } from "../Markdown";
import { Badge, Empty, ErrorBox, Loading, Modal, Stat, usd, usdShort } from "../ui";

export function OverlapsTab() {
  const { user, refresh, notify } = useApp();
  const { data, loading, error } = useApi<any>("/portfolio/overlaps");
  const [building, setBuilding] = useState<string | null>(null);
  const [caseOut, setCaseOut] = useState<{ clusterId: string; out: AgentOutput } | null>(null);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const items: any[] = data.items || [];
  const total = items.reduce((s, c) => s + (c.est_savings_usd || 0), 0);

  const build = async (clusterId: string) => {
    setBuilding(clusterId);
    try {
      const out = await api.post<AgentOutput>("/agents/run", { agent_id: "pf.business_case_builder", params: { cluster_id: clusterId }, user_id: user?.id });
      setCaseOut({ clusterId, out });
      refresh();
    } catch (e: any) {
      notify(e.message);
    } finally {
      setBuilding(null);
    }
  };

  // prefer the live approval state from the refreshed overlaps list; fall back to what the run returned
  const caseApproval: ApprovalRef | null = caseOut
    ? items.find((c) => c.cluster_id === caseOut.clusterId)?.business_case ||
      (caseOut.out.approvals_created[0]
        ? { id: caseOut.out.approvals_created[0], status: "pending", approver_role: caseOut.out.proposed_actions[0]?.approver_role || "cio" }
        : null)
    : null;

  return (
    <AgentPanel agentId="pf.overlap_finder" run={data.run}>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Clusters" value={items.length} sub="≥2 apps on the same L2 capability" />
        <Stat label="Est. savings" value={usdShort(total)} sub="per year, after migration overlap" accent />
        <Stat label="Consolidations approved" value={items.filter((c) => c.approval && c.approval.status !== "pending" && c.approval.status !== "rejected").length} sub={`of ${items.length} proposed to the principal architect`} />
        <Stat label="Business cases" value={items.filter((c) => c.business_case).length} sub={`${items.filter((c) => c.business_case?.status === "pending").length} pending with CIO`} />
      </div>
      {items.length === 0 && <Empty>No overlapping applications found.</Empty>}
      <div className="grid gap-3 xl:grid-cols-2">
        {items.map((c) => {
          const maxScore = Math.max(...Object.values(c.scores || {}).map(Number), 0.01);
          const order = c.app_ids
            .map((id: string, i: number) => ({ id, name: c.app_names?.[i] || id, score: c.scores?.[id] ?? 0 }))
            .sort((a: any, b: any) => b.score - a.score);
          return (
            <div key={c.cluster_id} className="rounded-lg border border-gray-200 p-3" data-testid={`cluster-${c.cluster_id}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px] muted">{c.cluster_id}</span>
                    <EvidenceChip id={c.capability_id} />
                  </div>
                  <div className="text-sm font-semibold text-gray-900">{c.capability_name} <span className="font-normal muted">· {c.category}</span></div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-lg font-semibold text-accent-600">{usd(c.est_savings_usd)}</div>
                  <div className="text-[11px] muted">est. savings / yr · feature overlap {Math.round((c.similarity || 0) * 100)}%</div>
                </div>
              </div>
              <ul className="mt-2 space-y-1">
                {order.map((a: any) => {
                  const surv = a.id === c.survivor_app_id;
                  return (
                    <li key={a.id} className={`flex items-center gap-2 rounded px-2 py-1 text-sm ${surv ? "bg-accent-50 ring-1 ring-accent-100" : ""}`}>
                      <EvidenceChip id={a.id} />
                      <span className={`flex-1 truncate ${surv ? "font-semibold text-gray-900" : "text-gray-700"}`}>{a.name}</span>
                      {surv ? <Badge color="blue">survivor</Badge> : <Badge>retire</Badge>}
                      <span className="flex w-28 items-center gap-1.5" title={`Combined score ${a.score}`}>
                        <span className="h-1.5 flex-1 rounded bg-gray-100">
                          <span className="block h-1.5 rounded" style={{ width: `${(a.score / maxScore) * 100}%`, background: surv ? "#1f5bd6" : "#9ca3af" }} />
                        </span>
                        <span className="w-8 text-right text-[11px] tabular-nums muted">{a.score.toFixed(2)}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
              <div className="mt-2 text-sm text-gray-700"><TextWithChips text={c.rationale} /></div>
              <div className="mt-1 flex flex-wrap items-center gap-1 text-xs"><span className="muted">Evidence:</span><EvidenceList refs={c.source_refs} max={6} /></div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-gray-100 pt-2 text-xs">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="inline-flex items-center gap-1.5"><span className="muted">Consolidation:</span><ApprovalControls approval={c.approval} /></span>
                  <span className="inline-flex items-center gap-1.5"><span className="muted">Business case:</span>{c.business_case ? <ApprovalControls approval={c.business_case} /> : <span className="muted">not built</span>}</span>
                </div>
                <button className="btn btn-sm" disabled={building !== null} onClick={() => build(c.cluster_id)}>
                  {building === c.cluster_id ? "Building…" : c.business_case ? "Rebuild business case" : "Build business case"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <Modal open={!!caseOut} onClose={() => setCaseOut(null)} title="Rationalization business case" wide>
        {caseOut && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge>{caseOut.out.agent_name}</Badge>
              <Badge>{caseOut.out.llm_mode}</Badge>
              <span className="muted">run</span> <EvidenceChip id={caseOut.out.run_id} />
              <span className="ml-auto inline-flex items-center gap-1.5">
                <span className="muted">Approval for {ROLE_LABELS[caseApproval?.approver_role || "cio"]}:</span>
                {caseApproval ? <><span className="font-mono text-[11px] muted">{caseApproval.id}</span><ApprovalControls approval={caseApproval} /></> : <span className="muted">already decided — not re-proposed</span>}
              </span>
            </div>
            <Markdown text={caseOut.out.artifacts?.body_md} />
          </div>
        )}
      </Modal>
    </AgentPanel>
  );
}
