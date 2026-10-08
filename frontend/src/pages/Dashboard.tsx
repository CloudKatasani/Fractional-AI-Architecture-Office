import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { PageHeader } from "../components/Layout";
import { EvidenceChip, TextWithChips } from "../components/Evidence";
import { Markdown } from "../components/Markdown";
import { Badge, Card, ErrorBox, Loading, Modal, Stat, usd, usdShort } from "../components/ui";
import { ROLE_LABELS, useApi, useApp } from "../state/AppState";

export default function Dashboard() {
  const { tenantName, user } = useApp();
  const { data: m, loading, error } = useApi<any>("/metrics/dashboard");
  const [brief, setBrief] = useState<any>(null);
  const [briefing, setBriefing] = useState(false);
  const nav = useNavigate();

  const genBriefing = async () => {
    setBriefing(true);
    try {
      setBrief(await api.post("/briefing/generate", { user_id: user?.id }));
    } finally {
      setBriefing(false);
    }
  };

  if (loading && !m) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!m) return null;
  const tierData = Object.entries(m.ai_tiers).map(([tier, v]: any) => ({ tier: tier === "unacceptable" ? "blocked" : tier, approved: v.approved, proposed: v.proposed }));
  const s = m.savings;
  return (
    <div className="space-y-4">
      <PageHeader
        title={`Dashboard — ${tenantName}`}
        subtitle={`As of ${m.as_of}. Every number links to the records and approvals it was computed from.`}
        actions={<button className="btn-primary" onClick={genBriefing} disabled={briefing}>{briefing ? "Generating…" : "Generate executive briefing"}</button>}
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Inventory accuracy" value={`${m.inventory_accuracy.value}%`} sub={`${m.inventory_accuracy.confirmed} of ${m.inventory_accuracy.total} apps confirmed by owners`} onClick={() => nav("/portfolio")} accent />
        <Stat label="Savings identified / approved / realized" value={<span>{usdShort(s.identified)} <span className="text-base text-gray-400">/</span> {usdShort(s.approved)} <span className="text-base text-gray-400">/</span> {usdShort(s.realized)}</span>} sub="per year · from agent findings and approved decisions" onClick={() => nav("/portfolio?tab=savings")} />
        <Stat label="Design review median turnaround" value={m.design_review.median_hours !== null ? `${m.design_review.median_hours} h` : "—"} sub={`${m.design_review.reviewed} reviewed · ${m.design_review.pending} pending`} onClick={() => nav("/application")} />
        <Stat label="Open policy & standard violations" value={m.violations.value} sub={`${m.violations.policy} data-policy · ${m.violations.standards} architecture`} onClick={() => nav("/data?tab=policies")} />
        <Stat label="Upcoming EOS / renewals (180 d)" value={m.upcoming.count} sub={m.upcoming.items[0] ? `next: ${m.upcoming.items[0].name} in ${m.upcoming.items[0].days} d` : "none"} onClick={() => nav("/portfolio?tab=lifecycle")} />
        <Stat label="Agent acceptance rate" value={m.acceptance.value !== null ? `${m.acceptance.value}%` : "—"} sub={`${m.acceptance.decided} decisions recorded`} onClick={() => nav("/agents")} />
        <Stat label="Pending approvals" value={m.pending_approvals} sub="across all roles" onClick={() => nav("/approvals")} />
        <Stat label="Knowledge graph" value={m.counts.applications} sub={`applications · ${m.counts.datasets} datasets · ${m.counts.ai_usecases} AI use cases`} onClick={() => nav("/graph")} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="AI use cases by risk tier" subtitle="approved by risk officer vs proposed by agent">
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={tierData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="tier" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="approved" stackId="a" fill="#1f5bd6" />
                <Bar dataKey="proposed" stackId="a" fill="#a7c0f5" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Tech debt score trend" subtitle="average across scored apps (6 months; earlier points synthetic)">
          <div className="h-56">
            <ResponsiveContainer>
              <LineChart data={m.debt_trend.points}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis domain={["auto", "auto"]} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Line dataKey="score" stroke="#1f5bd6" strokeWidth={2} dot />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Upcoming EOS & renewals" subtitle="next 180 days">
          <ul className="space-y-1.5 text-sm max-h-56 overflow-auto">
            {m.upcoming.items.map((u: any) => (
              <li key={u.id} className="flex items-center justify-between gap-2">
                <span className="truncate">
                  <EvidenceChip id={u.id} /> {u.name}
                </span>
                <span className="flex items-center gap-1 shrink-0">
                  <Badge color={u.type === "vendor_eos" ? "red" : u.auto_renew ? "amber" : "gray"}>{u.type === "vendor_eos" ? "EOS" : u.auto_renew ? "auto-renew" : "renewal"}</Badge>
                  <span className="text-xs muted w-14 text-right">{u.days} d</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Decisions needed this week" subtitle="top pending approvals by priority" className="lg:col-span-2"
          actions={<button className="btn btn-sm" onClick={() => nav("/approvals")}>Open inbox</button>}>
          <ul className="divide-y divide-gray-100">
            {m.decisions_needed.map((d: any) => (
              <li key={d.id} className="py-2 text-sm">
                <div className="flex items-center gap-2">
                  <Badge color="blue">{d.action_type.replace(/_/g, " ")}</Badge>
                  <EvidenceChip id={d.target_id} />
                  <span className="text-xs muted">for {ROLE_LABELS[d.approver_role] || d.approver_role} · {d.agent_id}</span>
                </div>
                <div className="mt-1 text-gray-700"><TextWithChips text={d.rationale} /></div>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="How the numbers are traced">
          <div className="space-y-2 text-sm">
            <div>Savings approved come from these approvals:</div>
            <div>{s.source_refs.approved.slice(0, 8).map((r: string) => <EvidenceChip key={r} id={r} />)}{s.source_refs.approved.length === 0 && <span className="muted">none yet</span>}</div>
            <div>Savings realized:</div>
            <div>{s.source_refs.realized.map((r: string) => <EvidenceChip key={r} id={r} />)}{s.source_refs.realized.length === 0 && <span className="muted">none yet</span>}</div>
            <div>Identified savings come from agent runs:</div>
            <div>{s.source_refs.identified.map((r: string) => <EvidenceChip key={r} id={r} />)}</div>
            <div className="text-xs muted pt-2">Identified {usd(s.identified)} · approved {usd(s.approved)} · realized {usd(s.realized)} per year.</div>
          </div>
        </Card>
      </div>

      <Modal open={!!brief} onClose={() => setBrief(null)} title="Executive briefing" wide>
        {brief && (
          <>
            <div className="mb-2 flex gap-2"><Badge>{brief.llm_mode}</Badge><Badge>run {brief.run_id}</Badge></div>
            <Markdown text={brief.markdown} />
          </>
        )}
      </Modal>
    </div>
  );
}
