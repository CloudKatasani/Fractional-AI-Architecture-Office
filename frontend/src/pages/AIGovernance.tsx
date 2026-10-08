import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, AgentOutput, ApprovalRef, RunMeta } from "../api/client";
import { AgentPanel, ApprovalControls } from "../components/AgentPanel";
import { EvidenceList, TextWithChips } from "../components/Evidence";
import { PageHeader } from "../components/Layout";
import { Mermaid } from "../components/Mermaid";
import { Badge, Empty, ErrorBox, Loading, Modal, Stat, TierBadge, Tabs, Toggle, useTab, usd, usdShort } from "../components/ui";
import { EvidencePackButton } from "../components/ai/EvidencePackButton";
import {
  BlockedBanner, ControlsChecklist, IdChip, DocChecklist, FlagBadge, RefChip, RiskResult, ScoreBar, TriggerList,
} from "../components/ai/shared";
import { useApi, useApp } from "../state/AppState";

interface UseCase {
  id: string;
  title: string;
  sponsor_dept: string;
  description: string;
  status: string;
  pattern: string;
  dataset_ids: string[];
  value_estimate_usd: number;
  owner_user_id: string;
  uses_personal_data: boolean;
  affects_individuals: boolean;
  safety_relevant: boolean;
  automated_decision: boolean;
  tags: string[];
  sponsor_priority: number;
  intake: any | null;
  risk: any | null;
  risk_tier: string | null;
  proposed_risk_tier: string | null;
  tier_approval: ApprovalRef | null;
}
interface UseCaseList {
  items: UseCase[];
  intake_run: RunMeta | null;
  risk_run: RunMeta | null;
}

const TIER_ORDER: Record<string, number> = { unacceptable: 0, high: 1, limited: 2, minimal: 3 };
const effTier = (u: UseCase) => u.risk_tier || u.proposed_risk_tier || u.risk?.tier || null;
const isBlocked = (u: UseCase) => effTier(u) === "unacceptable" || !!u.risk?.blocked;

function setUrlTab(key: string, v: string) {
  const p = new URLSearchParams(window.location.search);
  p.set(key, v);
  window.history.replaceState(null, "", `${window.location.pathname}?${p.toString()}`);
}

/** Approved tier with the agent's proposal next to it while it is pending. */
function TierCell({ u }: { u: UseCase }) {
  const pending = u.tier_approval?.status === "pending";
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {u.risk_tier ? <TierBadge tier={u.risk_tier} /> : null}
      {(!u.risk_tier || (pending && u.proposed_risk_tier !== u.risk_tier)) && u.proposed_risk_tier && <TierBadge tier={u.proposed_risk_tier} proposed />}
      {!u.risk_tier && !u.proposed_risk_tier && <span className="text-xs muted">not classified</span>}
    </span>
  );
}

// ---- Use-case detail (row click / "Classify risk") ----------------------------------------------------------------
function UseCaseModal({ id, classify, onClose, onRefArch }: { id: string; classify: boolean; onClose: () => void; onRefArch: (id: string) => void }) {
  const { user, refresh, notify, users } = useApp();
  const { data: uc, loading, error } = useApi<any>(`/ai/usecases/${id}`, undefined, [id]);
  const [run, setRun] = useState<AgentOutput | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const doClassify = async () => {
    setRunning(true);
    setErr(null);
    try {
      const out = await api.post<AgentOutput>("/agents/run", { agent_id: "dai.ai_risk_classifier", params: { usecase_id: id }, user_id: user?.id });
      setRun(out);
      notify(`${out.agent_name}: ${out.findings[0]?.tier?.toUpperCase() || "done"}` + (out.approvals_created.length ? ` — sent to risk officer (${out.approvals_created.join(", ")})` : ""));
      refresh();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setRunning(false);
    }
  };

  const autoRan = useRef(false);
  useEffect(() => {
    if (classify && !autoRan.current) {
      autoRan.current = true; // StrictMode runs effects twice in dev; classify once
      doClassify();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, classify]);

  const owner = users.find((x) => x.id === uc?.owner_user_id);
  const fresh = run?.findings?.[0];
  const refArch = uc?.reference_architecture;
  const ra = refArch?.findings?.[0];

  return (
    <Modal open onClose={onClose} wide title={<span><span className="font-mono text-sm text-gray-500">{id}</span> {uc?.title || ""}</span>}>
      {loading && !uc && <Loading />}
      <ErrorBox error={error} />
      {uc && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge>{uc.status}</Badge>
            <Badge color="blue">pattern: {uc.pattern}</Badge>
            <span className="muted">Sponsor</span> {uc.sponsor_dept}
            <span className="muted">· Owner</span> {owner?.name || uc.owner_user_id} <IdChip id={uc.owner_user_id} />
            <span className="muted">· Value</span> {usd(uc.value_estimate_usd)}
            <span className="muted">· Priority</span> P{uc.sponsor_priority}
          </div>
          <div className="text-sm text-gray-700">{uc.description}</div>
          <div className="flex flex-wrap gap-1">
            {uc.uses_personal_data && <Badge color="amber">personal data</Badge>}
            {uc.affects_individuals && <Badge color="amber">affects individuals</Badge>}
            {uc.automated_decision && <Badge color="red">automated decision</Badge>}
            {uc.safety_relevant && <Badge color="red">safety relevant</Badge>}
            {uc.tags?.map((t: string) => <Badge key={t}>{t}</Badge>)}
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <Stat label="Intake rank" value={uc.intake ? `#${uc.intake.rank}` : "—"} sub={uc.intake ? `score ${uc.intake.score}` : undefined} />
            <Stat label="Value score" value={uc.intake?.value_score?.toFixed(2) ?? "—"} sub="of 5" />
            <Stat label="Feasibility" value={uc.intake?.feasibility_score?.toFixed(2) ?? "—"} sub="of 5" />
            <Stat label="Data readiness" value={uc.intake ? `${Math.round(uc.intake.data_readiness * 100)}%` : "—"} sub={uc.intake?.blockers?.length ? `${uc.intake.blockers.length} blockers` : "no blockers"} />
          </div>
          {uc.intake?.blockers?.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-amber-800">
              {uc.intake.blockers.map((b: string) => <li key={b}>{b}</li>)}
            </ul>
          )}

          <div className="card p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3>Risk classification</h3>
                <span className="text-[11px] font-mono muted">dai.ai_risk_classifier</span>
                <TierCell u={uc} />
                <ApprovalControls approval={uc.tier_approval} />
              </div>
              <button className="btn btn-sm" onClick={doClassify} disabled={running}>{running ? "Classifying…" : fresh ? "Re-classify" : "Classify risk"}</button>
            </div>
            <ErrorBox error={err} />
            {running && <Loading label="Applying tiering rules…" />}
            {run && (
              <div className="mb-2 text-sm text-gray-700">
                <TextWithChips text={run.summary} /> <IdChip id={run.run_id} />
                {run.approvals_created.length > 0 && <span className="text-xs muted"> · approval {run.approvals_created.map((a) => <IdChip key={a} id={a} />)}</span>}
              </div>
            )}
            {fresh || uc.risk ? <RiskResult risk={fresh || uc.risk} /> : !running && <Empty>Not classified yet.</Empty>}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="label mb-1">Datasets ({uc.datasets?.length || 0})</div>
              <table className="tbl">
                <thead><tr><th>Dataset</th><th>Class.</th><th>PII</th><th>Quality</th></tr></thead>
                <tbody>
                  {uc.datasets?.map((d: any) => (
                    <tr key={d.id}>
                      <td><IdChip id={d.id} /> {d.name}</td>
                      <td className="text-xs">{d.classification}</td>
                      <td>{d.pii ? <Badge color="amber">PII</Badge> : <span className="muted text-xs">no</span>}</td>
                      <td className={`tabular-nums text-xs ${d.quality_score < 0.6 ? "text-red-700 font-semibold" : ""}`}>{d.quality_score?.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(!uc.datasets || uc.datasets.length === 0) && <Empty>No datasets identified.</Empty>}
            </div>
            <div>
              <div className="label mb-1">AI assets in use ({uc.assets?.length || 0})</div>
              {uc.assets?.length ? (
                <ul className="space-y-1 text-sm">
                  {uc.assets.map((a: any) => (
                    <li key={a.id} className="flex flex-wrap items-center gap-1">
                      <IdChip id={a.id} /> {a.name} <span className="text-xs muted">{a.vendor} · {usd(a.monthly_cost_usd)}/mo</span>
                      {!a.registered && <FlagBadge flag="unregistered" />}
                    </li>
                  ))}
                </ul>
              ) : <div className="text-sm muted">No deployed assets linked.</div>}
              <div className="label mt-4 mb-1">Reference architecture</div>
              {ra ? (
                <div className="text-sm">
                  <Badge color="blue">{ra.pattern}</Badge> {ra.components?.length} components · {ra.controls?.length} controls · {ra.cost_band}{" "}
                  <IdChip id={refArch.run_id} />
                </div>
              ) : <div className="text-sm muted">None generated yet.</div>}
              <button className="btn btn-sm mt-2" onClick={() => onRefArch(id)}>{ra ? "Open reference design" : "Generate reference design"}</button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ---- Tabs ---------------------------------------------------------------------------------------------------------
function IntakeTab({ data, onOpen }: { data: UseCaseList; onOpen: (id: string, classify: boolean) => void }) {
  const items = useMemo(() => [...data.items].sort((a, b) => (a.intake?.rank ?? 999) - (b.intake?.rank ?? 999)), [data]);
  return (
    <AgentPanel agentId="dai.ai_usecase_intake" run={data.intake_run}>
      <div className="overflow-x-auto">
        <table className="tbl" data-testid="intake-table">
          <thead>
            <tr>
              <th>#</th><th>Use case</th>
              <th>Value</th><th>Feasibility</th><th>Data ready</th><th>Score</th><th>Blockers</th><th>Risk tier</th><th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((u) => (
              <tr key={u.id} className={`cursor-pointer ${isBlocked(u) ? "bg-red-50/60" : ""}`} onClick={() => onOpen(u.id, false)}>
                <td className="tabular-nums font-semibold text-gray-500">{u.intake?.rank ?? "—"}</td>
                <td className="min-w-[15rem]">
                  <div className="flex items-start gap-1"><IdChip id={u.id} /><span className="font-medium text-gray-900">{u.title}</span></div>
                  <div className="text-[11px] muted">{u.sponsor_dept} · {u.pattern} · {u.status} · {usdShort(u.value_estimate_usd)}</div>
                </td>
                <td><ScoreBar value={u.intake?.value_score} /></td>
                <td><ScoreBar value={u.intake?.feasibility_score} /></td>
                <td><ScoreBar value={u.intake?.data_readiness} max={1} color={(u.intake?.data_readiness ?? 1) < 0.5 ? "bg-red-500" : "bg-green-500"} /></td>
                <td className="tabular-nums font-semibold">{u.intake?.score ?? "—"}</td>
                <td className="min-w-[13rem] max-w-[18rem] text-[11px] text-amber-800">
                  {u.intake?.blockers?.length ? u.intake.blockers.slice(0, 2).map((b: string) => <div key={b}>{b}</div>) : <span className="muted">—</span>}
                  {u.intake?.blockers?.length > 2 && <div className="muted">+{u.intake.blockers.length - 2} more</div>}
                </td>
                <td><TierCell u={u} /></td>
                <td>
                  <button className="btn btn-sm whitespace-nowrap" onClick={(e) => { e.stopPropagation(); onOpen(u.id, true); }} data-testid={`classify-${u.id}`}>
                    Classify risk
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length === 0 && <Empty>No AI use cases in intake.</Empty>}
    </AgentPanel>
  );
}

function RiskTab({ data, onOpen }: { data: UseCaseList; onOpen: (id: string, classify: boolean) => void }) {
  const [showAll, setShowAll] = useState<Record<string, boolean>>({});
  const items = useMemo(
    () => [...data.items].sort((a, b) => (TIER_ORDER[effTier(a) || ""] ?? 9) - (TIER_ORDER[effTier(b) || ""] ?? 9) || a.id.localeCompare(b.id)),
    [data],
  );
  const blocked = items.filter(isBlocked);
  const counts = ["unacceptable", "high", "limited", "minimal"].map((t) => ({
    tier: t,
    approved: items.filter((u) => u.risk_tier === t).length,
    proposed: items.filter((u) => !u.risk_tier && (u.proposed_risk_tier || u.risk?.tier) === t).length,
  }));
  const pending = items.filter((u) => u.tier_approval?.status === "pending").length;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {counts.map((c) => (
          <Stat key={c.tier} label={c.tier === "unacceptable" ? "Blocked" : c.tier} value={c.approved + c.proposed}
            sub={`${c.approved} approved · ${c.proposed} proposed`} accent={c.tier === "high"} />
        ))}
        <Stat label="Awaiting risk officer" value={pending} sub="tier decisions pending" />
      </div>
      {blocked.map((u) => (
        <BlockedBanner key={u.id}>
          <div className="flex flex-wrap items-center gap-2">
            <IdChip id={u.id} /> <b>{u.title}</b> — prohibited practice
            <TriggerList triggers={u.risk?.triggers} compact />
            <span className="text-xs">{u.risk?.triggers?.[0]?.title}</span>
            <ApprovalControls approval={u.tier_approval} />
          </div>
        </BlockedBanner>
      ))}
      <AgentPanel agentId="dai.ai_risk_classifier" run={data.risk_run}>
        <div className="overflow-x-auto">
          <table className="tbl" data-testid="risk-table">
            <thead>
              <tr><th>Use case</th><th>Tier</th><th>Triggers</th><th>Required controls</th><th>Documentation</th><th>Tier approval</th></tr>
            </thead>
            <tbody>
              {items.map((u) => {
                const r = u.risk;
                const bl = isBlocked(u);
                const all = showAll[u.id];
                return (
                  <tr key={u.id} className={bl ? "bg-red-50" : ""}>
                    <td className="min-w-[13rem]">
                      <div className="flex items-start gap-1">
                        <IdChip id={u.id} />
                        <button className="text-left font-medium text-gray-900 hover:text-accent-700" onClick={() => onOpen(u.id, false)}>{u.title}</button>
                      </div>
                      <div className="text-[11px] muted">{u.sponsor_dept} · {u.pattern}</div>
                      {bl && <div className="mt-1 text-[11px] font-bold tracking-wide text-red-700">BLOCKED — may not proceed</div>}
                    </td>
                    <td><TierCell u={u} /></td>
                    <td className="min-w-[14rem] max-w-[18rem]">
                      <TriggerList triggers={r?.triggers} compact />
                      {r?.triggers?.map((t: any) => (
                        <div key={t.rule_id} className="mt-0.5 text-[11px] text-gray-600"><span className="font-mono">{t.rule_id}</span> {t.title}</div>
                      ))}
                    </td>
                    <td className="min-w-[20rem]">
                      <ControlsChecklist controls={r?.required_controls} max={all ? undefined : 4} />
                      {r?.required_controls?.length > 4 && (
                        <button className="text-[11px] text-accent-700 hover:underline" onClick={() => setShowAll((s) => ({ ...s, [u.id]: !all }))}>
                          {all ? "show fewer" : "show all"}
                        </button>
                      )}
                    </td>
                    <td className="min-w-[10rem]">
                      <div className="text-[11px] text-gray-700">{r?.documentation_checklist?.join(" · ") || "—"}</div>
                    </td>
                    <td className="whitespace-nowrap"><ApprovalControls approval={u.tier_approval} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </AgentPanel>
    </div>
  );
}

function AssetsTab() {
  const { data, loading, error } = useApi<any>("/ai/assets");
  const [shadowOnly, setShadowOnly] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  // the registry flag can be stale once a register_asset approval has been applied; trust the record's `registered` field
  const flagsOf = (a: any): string[] => (a.flags || []).filter((f: string) => !(f === "unregistered" && a.registered));
  const items: any[] = data.items;
  const total = items.reduce((s, a) => s + (a.monthly_cost_usd || 0), 0);
  const shadow = items.filter((a) => !a.registered);
  const shadowSpend = shadow.reduce((s, a) => s + (a.monthly_cost_usd || 0), 0);
  const expense = items.filter((a) => a.paid_via === "expense").length;
  const prodNoEval = items.filter((a) => flagsOf(a).includes("production_without_eval")).length;
  const spend = Object.entries(data.spend_by_department || {})
    .map(([dept, v]) => ({ dept, usd: Number(v) }))
    .sort((a, b) => b.usd - a.usd);
  const shown = shadowOnly ? shadow : items;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="AI assets in use" value={items.length} sub={`${usd(total)} / month`} />
        <Stat label="Registered" value={data.registered} sub="in model / agent registry" />
        <Stat label="Shadow AI (unregistered)" value={<span className="text-red-700">{data.unregistered}</span>} sub={`${usd(shadowSpend)} / month`} onClick={() => setShadowOnly(true)} />
        <Stat label="Paid on expenses" value={expense} sub="not through AP" />
        <Stat label="Production without eval" value={prodNoEval} />
      </div>
      <AgentPanel agentId="dai.model_agent_registry_steward" run={data.run}>
        <div className="space-y-4">
          <div>
            <div className="label mb-1">Monthly AI spend by department</div>
            <div style={{ height: Math.max(200, spend.length * 26) }}>
              <ResponsiveContainer>
                <BarChart data={spend} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => usdShort(v)} />
                  <YAxis type="category" dataKey="dept" width={170} tick={{ fontSize: 11 }} interval={0} />
                  <Tooltip formatter={(v: any) => [usd(v), "per month"]} />
                  <Bar dataKey="usd" fill="#1f5bd6" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="min-w-0">
            <div className="mb-1 flex items-center justify-between">
              <div className="label">Registry ({shown.length})</div>
              <Toggle checked={shadowOnly} onChange={setShadowOnly} label="shadow AI only" />
            </div>
            <div className="overflow-x-auto">
              <table className="tbl" data-testid="assets-table">
                <thead>
                  <tr><th>Asset</th><th>Vendor / dept</th><th>Eval</th><th className="text-right">$/mo</th><th>Use case</th><th>Flags</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {shown.map((a) => (
                    <tr key={a.id} className={!a.registered ? "bg-amber-50/40" : ""}>
                      <td className="min-w-[12rem]">
                        <div className="flex items-start gap-1"><IdChip id={a.id} /><span className="font-medium text-gray-900">{a.name}</span></div>
                        <div className="text-[11px] muted">
                          {a.type} · {a.lifecycle} · {a.registered ? "registered" : <span className="text-red-700 font-medium">not registered</span>}
                          {a.suspended && <> · <span className="text-red-700 font-semibold">suspended</span></>}
                        </div>
                        {a.data_used?.length > 0 && <div className="mt-0.5">{a.data_used.map((d: string) => <IdChip key={d} id={d} />)}</div>}
                      </td>
                      <td className="text-xs">
                        <div>{a.vendor}</div>
                        <div className="muted">{a.department} · via {a.paid_via}</div>
                      </td>
                      <td className="text-xs">{a.eval_status}</td>
                      <td className="text-right tabular-nums text-xs">{usd(a.monthly_cost_usd)}</td>
                      <td className="text-xs">
                        {a.usecase_id ? <IdChip id={a.usecase_id} /> : <span className="muted">—</span>}
                        {a.risk_tier && <TierBadge tier={a.risk_tier} />}
                      </td>
                      <td className="max-w-[12rem]">
                        <span className="inline-flex flex-wrap gap-1">{flagsOf(a).map((f) => <FlagBadge key={f} flag={f} />)}</span>
                        {flagsOf(a).length === 0 && <span className="text-xs muted">—</span>}
                      </td>
                      <td className="min-w-[13rem]">
                        {(a.approvals || []).map((ap: ApprovalRef) => (
                          <div key={ap.id} className="mb-1 flex flex-wrap items-center gap-1">
                            <span className="font-mono text-[11px] text-gray-600">{ap.action_type?.replace(/_/g, " ")}</span>
                            <ApprovalControls approval={ap} compact />
                          </div>
                        ))}
                        {(!a.approvals || a.approvals.length === 0) && <span className="text-xs muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </AgentPanel>
    </div>
  );
}

function RefArchTab({ data, selected, onSelect }: { data: UseCaseList; selected: string; onSelect: (id: string) => void }) {
  const { data: uc, loading } = useApi<any>(selected ? `/ai/usecases/${selected}` : null, undefined, [selected]);
  const { data: apr } = useApi<{ items: any[] }>("/approvals", { agent_id: "dai.ai_ref_arch_generator" });
  const [generated, setGenerated] = useState<Record<string, AgentOutput>>({});
  const out: AgentOutput | null = generated[selected] || uc?.reference_architecture || null;
  const f = out?.findings?.[0];
  const approval = useMemo(() => {
    const xs = (apr?.items || []).filter((a) => a.target_id === selected && a.action_type === "approve_reference_design");
    xs.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    return xs[0] ? ({ ...xs[0] } as ApprovalRef) : null;
  }, [apr, selected]);
  const sorted = useMemo(() => [...data.items].sort((a, b) => (a.intake?.rank ?? 999) - (b.intake?.rank ?? 999)), [data]);
  const u = data.items.find((x) => x.id === selected);
  const { user, notify, refresh } = useApp();
  const autoRan = useRef<Set<string>>(new Set());
  const [genErr, setGenErr] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  // selecting a use case with no design on record generates one (POST /agents/run) — once per use case per visit
  useEffect(() => {
    if (!uc || uc.id !== selected || uc.reference_architecture || generated[selected] || autoRan.current.has(selected)) return;
    autoRan.current.add(selected);
    setGenerating(true);
    setGenErr(null);
    api
      .post<AgentOutput>("/agents/run", { agent_id: "dai.ai_ref_arch_generator", params: { usecase_id: selected }, user_id: user?.id })
      .then((o) => {
        setGenerated((g) => ({ ...g, [selected]: o }));
        refresh();
        notify(`${o.agent_name}: reference design for ${selected}` + (o.approvals_created.length ? " sent to principal architect" : ""));
      })
      .catch((e) => setGenErr(e.message))
      .finally(() => setGenerating(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uc, selected]);
  const blocked = u ? isBlocked(u) : false;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="label">Use case</span>
          <select className="input min-w-[26rem]" value={selected} onChange={(e) => onSelect(e.target.value)} data-testid="refarch-select">
            {sorted.map((x) => (
              <option key={x.id} value={x.id}>
                {x.id} · {x.title} ({x.pattern}{effTier(x) ? `, ${effTier(x) === "unacceptable" ? "BLOCKED" : effTier(x)}` : ""})
              </option>
            ))}
          </select>
        </label>
        {u && <TierCell u={u} />}
      </div>
      {blocked && <BlockedBanner>This use case is classified as a prohibited practice. A reference design is shown for the record only; no approval will be requested.</BlockedBanner>}
      <AgentPanel
        key={selected}
        agentId="dai.ai_ref_arch_generator"
        agentName="AI Reference Architecture Generator"
        run={out}
        params={{ usecase_id: selected }}
        runLabel={out ? "Re-generate" : "Generate reference design"}
        onRan={(o) => setGenerated((g) => ({ ...g, [selected]: o }))}
      >
        <ErrorBox error={genErr} />
        {((loading && !uc) || generating) && <Loading label={generating ? "Generating reference design…" : undefined} />}
        {!f && !loading && !generating && <Empty>No reference design generated for this use case yet — click “Generate reference design”.</Empty>}
        {f && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge color="blue">pattern: {f.pattern}</Badge>
              {f.platform && <Badge>platform: {f.platform}</Badge>}
              {f.risk_tier && <TierBadge tier={f.risk_tier} />}
              <Badge color="purple">cost band: {f.cost_band}</Badge>
              <span className="ml-2 inline-flex items-center gap-1 text-xs"><span className="muted">Design approval</span> <ApprovalControls approval={approval} /></span>
              <EvidenceList refs={f.source_refs} />
            </div>
            <div className="grid gap-4 lg:grid-cols-5">
              <div className="lg:col-span-3 rounded border border-gray-200 bg-white p-3">
                <div className="label mb-2">Data flow</div>
                <Mermaid chart={f.diagram_mermaid} />
              </div>
              <div className="lg:col-span-2 space-y-3">
                <div>
                  <div className="label mb-1">Components ({f.components?.length})</div>
                  <ol className="list-decimal pl-5 text-sm space-y-0.5">
                    {f.components?.map((c: string) => <li key={c}>{c}</li>)}
                  </ol>
                </div>
                <div>
                  <div className="label mb-1">Evaluation plan</div>
                  <DocChecklist items={f.eval_plan} />
                </div>
              </div>
            </div>
            <div>
              <div className="label mb-1">Security & governance controls ({f.controls?.length})</div>
              <table className="tbl">
                <thead><tr><th>Control</th><th>Title</th><th>Source</th></tr></thead>
                <tbody>
                  {f.controls?.map((c: any, i: number) => (
                    <tr key={`${c.id}-${i}`}>
                      <td className="font-mono text-xs">{c.id}</td>
                      <td>{c.title}</td>
                      <td><RefChip id={c.source} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </AgentPanel>
    </div>
  );
}

// ---- Page ---------------------------------------------------------------------------------------------------------
export default function AIGovernance() {
  const [tab, setTabState] = useTab("intake", "tab");
  const setTab = (t: string) => { setTabState(t); setUrlTab("tab", t); };
  const { data, loading, error } = useApi<UseCaseList>("/ai/usecases");
  const [open, setOpen] = useState<{ id: string; classify: boolean } | null>(null);
  const [refSel, setRefSel] = useState<string>(() => new URLSearchParams(window.location.search).get("usecase") || "");

  useEffect(() => {
    if (!refSel && data?.items?.length) {
      const first = [...data.items].sort((a, b) => (a.intake?.rank ?? 999) - (b.intake?.rank ?? 999))[0];
      setRefSel(first.id);
    }
  }, [data, refSel]);

  const blocked = data?.items.filter(isBlocked).length || 0;
  const high = data?.items.filter((u) => effTier(u) === "high").length || 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="AI Governance"
        subtitle={data ? `${data.items.length} AI use cases · ${high} high risk · ${blocked} blocked — every tier traces to rule ids and source records.` : "Intake, risk tiering, registry and reference designs"}
        actions={<EvidencePackButton />}
      />
      <Tabs
        tabs={[
          { id: "intake", label: "Intake backlog" },
          { id: "risk", label: <span>Risk register{blocked ? <span className="ml-1.5 rounded bg-red-600 px-1 text-[10px] font-bold text-white">{blocked} BLOCKED</span> : null}</span> },
          { id: "registry", label: "AI asset registry" },
          { id: "refarch", label: "Reference architectures" },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab !== "registry" && loading && !data && <Loading />}
      {tab !== "registry" && <ErrorBox error={error} />}
      {tab === "intake" && data && <IntakeTab data={data} onOpen={(id, classify) => setOpen({ id, classify })} />}
      {tab === "risk" && data && <RiskTab data={data} onOpen={(id, classify) => setOpen({ id, classify })} />}
      {tab === "registry" && <AssetsTab />}
      {tab === "refarch" && data && refSel && <RefArchTab data={data} selected={refSel} onSelect={setRefSel} />}
      {open && (
        <UseCaseModal
          key={`${open.id}-${open.classify}`}
          id={open.id}
          classify={open.classify}
          onClose={() => setOpen(null)}
          onRefArch={(id) => { setOpen(null); setRefSel(id); setTab("refarch"); }}
        />
      )}
    </div>
  );
}
