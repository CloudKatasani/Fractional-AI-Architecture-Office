import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AgentOutput } from "../../api/client";
import { useApi, useApp } from "../../state/AppState";
import { AgentPanel, ApprovalControls } from "../AgentPanel";
import { EvidenceChip, EvidenceList, TextWithChips } from "../Evidence";
import { Markdown } from "../Markdown";
import { Mermaid } from "../Mermaid";
import { Badge, Card, Empty, ErrorBox, Loading, Stat, Toggle, usd, usdShort } from "../ui";
import { Field, IdChips, NamedChip } from "./common";

// ---- Capability heat map -------------------------------------------------------------------------

/** white → red on the 0..20 heat scale */
export function heatColor(h: number): string {
  const t = Math.max(0, Math.min(1, h / 20));
  const r = Math.round(255 - t * (255 - 200));
  const g = Math.round(255 - t * (255 - 30));
  const b = Math.round(255 - t * (255 - 45));
  return `rgb(${r},${g},${b})`;
}

const FLAG_LABEL: Record<string, string> = {
  hot_spot: "hot spot",
  strategic_gap: "strategic gap",
  too_many_applications: "> 6 apps",
  no_applications: "no apps",
};

function Tile({ c, selected, onClick, big }: { c: any; selected: boolean; onClick: () => void; big?: boolean }) {
  const dark = c.heat_score >= 11;
  return (
    <button
      onClick={onClick}
      title={`${c.name}: heat ${c.heat_score} (importance ${c.strategic_importance} × (5 − maturity ${c.maturity})), ${c.app_count} apps`}
      className={`relative rounded border text-left px-2 py-1.5 transition hover:shadow ${selected ? "ring-2 ring-accent-600" : ""} ${big ? "" : "min-h-[3.6rem]"}`}
      style={{ background: heatColor(c.heat_score), borderColor: c.heat_score >= 11 ? "#b91c1c33" : "#e5e7eb", color: dark ? "#fff" : "#111827", flexGrow: Math.max(1, c.app_count), flexBasis: `${8 + Math.min(c.app_count, 12)}rem` }}
    >
      <div className={`text-xs font-semibold leading-tight ${dark ? "" : "text-gray-900"}`} style={{ whiteSpace: "normal" }}>{c.name}</div>
      <div className={`mt-0.5 flex items-center gap-2 text-[10px] ${dark ? "text-white/90" : "text-gray-600"}`}>
        <span>heat {c.heat_score}</span>
        <span>{c.app_count} app{c.app_count === 1 ? "" : "s"}</span>
        {c.flags?.includes("too_many_applications") && <span className="font-bold">⚑</span>}
      </div>
    </button>
  );
}

/** Mermaid mindmap treats ( ) [ ] { } in node text as shape delimiters — swap them for look-alikes (root line excepted). */
function sanitizeMindmap(src?: string): string | undefined {
  if (!src) return src;
  return src
    .split("\n")
    .map((l, i) => (i === 0 || /root\(\(/.test(l) ? l : l.replace(/\(/g, "（").replace(/\)/g, "）").replace(/\[/g, "［").replace(/\]/g, "］").replace(/[{}]/g, "")))
    .join("\n");
}

export function CapabilityHeatMap() {
  const { data, loading, error } = useApi<any>("/ea/capabilities");
  const [sel, setSel] = useState<string | null>(null);
  const [mindmap, setMindmap] = useState(false);
  const { data: diag } = useApi<any>(mindmap ? "/kg/diagram" : null, { kind: "capability_map" }, [mindmap]);
  const caps: any[] = data?.items || [];
  const byId = useMemo(() => Object.fromEntries(caps.map((c) => [c.id, c])), [caps]);
  const l1 = caps.filter((c) => c.level === 1);
  const children = (id: string) => caps.filter((c) => c.parent_id === id);
  const cur = sel ? byId[sel] : null;
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <div className="space-y-4">
      <AgentPanel agentId="ea.capability_curator" run={data?.run}>
        <div className="mb-3 flex flex-wrap items-center gap-3 text-xs">
          <span className="muted">Heat = importance × (5 − maturity)</span>
          <span className="flex items-center gap-1">
            0
            <span className="inline-block h-2.5 w-40 rounded" style={{ background: `linear-gradient(to right, ${heatColor(0)}, ${heatColor(10)}, ${heatColor(20)})`, border: "1px solid #e5e7eb" }} />
            20
          </span>
          <span className="muted">tile width ∝ number of realizing apps · ⚑ more than six apps</span>
          <span className="ml-auto"><Toggle checked={mindmap} onChange={setMindmap} label="Capability map (Mermaid mindmap)" /></span>
        </div>
        {mindmap ? (
          diag ? <Mermaid chart={sanitizeMindmap(diag.mermaid)} /> : <Loading />
        ) : (
          <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
            <div className="space-y-2">
              {l1.map((p) => (
                <div key={p.id} className="rounded border border-gray-200">
                  <button className="flex w-full items-center justify-between gap-2 border-b border-gray-100 px-2 py-1 text-left hover:bg-gray-50" onClick={() => setSel(p.id)}>
                    <span className="flex items-center gap-2">
                      <span className="h-3 w-3 rounded-sm border border-gray-300" style={{ background: heatColor(p.heat_score) }} />
                      <span className="text-sm font-semibold">{p.name}</span>
                      <span className="font-mono text-[10px] muted">{p.id}</span>
                    </span>
                    <span className="text-[11px] muted">L1 · heat {p.heat_score} · {p.app_count} apps · imp {p.strategic_importance} / mat {p.maturity}</span>
                  </button>
                  <div className="flex flex-wrap gap-1.5 p-1.5">
                    {children(p.id).map((c) => <Tile key={c.id} c={c} selected={sel === c.id} onClick={() => setSel(c.id)} />)}
                    {children(p.id).length === 0 && <span className="text-xs muted px-1">no L2 capabilities</span>}
                  </div>
                </div>
              ))}
            </div>
            <div className="xl:sticky xl:top-16 self-start">
              {cur ? <CapabilityDetail c={cur} kids={children(cur.id)} parent={cur.parent_id ? byId[cur.parent_id] : null} onPick={setSel} /> : (
                <div className="rounded border border-dashed border-gray-300 p-4 text-sm muted">Click a capability tile to see importance, maturity, owner and realizing applications.</div>
              )}
            </div>
          </div>
        )}
      </AgentPanel>
    </div>
  );
}

function CapabilityDetail({ c, kids, parent, onPick }: { c: any; kids: any[]; parent: any; onPick: (id: string) => void }) {
  return (
    <div className="rounded border border-gray-200 p-3 space-y-3">
      <div>
        <div className="flex items-center gap-1"><EvidenceChip id={c.id} /><Badge>L{c.level}</Badge></div>
        <div className="mt-1 text-base font-semibold">{c.name}</div>
        {parent && <button className="text-xs text-accent-700 hover:underline" onClick={() => onPick(parent.id)}>↑ {parent.name}</button>}
        <div className="text-xs muted mt-1">{c.description}</div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Heat"><span className="inline-block rounded px-1.5 font-semibold" style={{ background: heatColor(c.heat_score), color: c.heat_score >= 11 ? "#fff" : "#111" }}>{c.heat_score}</span></Field>
        <Field label="Importance">{c.strategic_importance} / 5</Field>
        <Field label="Maturity">{c.maturity} / 5</Field>
        <Field label="Apps">{c.app_count}</Field>
        <Field label="Run cost">{usdShort(c.annual_cost_usd)}</Field>
        <Field label="Owner">{c.owner_user_id ? <NamedChip id={c.owner_user_id} name={c.owner} /> : "—"}</Field>
      </div>
      <div className="flex flex-wrap gap-1">
        {(c.flags || []).map((f: string) => <Badge key={f} color={f === "too_many_applications" ? "amber" : "red"}>{FLAG_LABEL[f] || f}</Badge>)}
        {(c.flags || []).length === 0 && <span className="text-xs muted">no flags</span>}
      </div>
      <Field label="Realizing applications"><IdChips ids={c.app_ids} max={20} /></Field>
      {kids.length > 0 && (
        <Field label="Sub-capabilities">
          <div className="flex flex-wrap gap-1">
            {kids.map((k) => <button key={k.id} className="rounded border px-1.5 py-0.5 text-xs" style={{ background: heatColor(k.heat_score) }} onClick={() => onPick(k.id)}>{k.name} · {k.heat_score}</button>)}
          </div>
        </Field>
      )}
    </div>
  );
}

// ---- Goals → capabilities → projects ------------------------------------------------------------

export function GoalsLinkage() {
  const { data, loading, error } = useApi<any>("/ea/goals");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const goals: any[] = data.items || [];
  return (
    <AgentPanel agentId="ea.strategy_capability_mapper" run={data.run}>
      <div className="-mx-4 -mb-4">
        <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)] border-b border-gray-200 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
          <div className="px-4 py-2">Strategic goal</div>
          <div className="px-4 py-2">→ Capabilities needed</div>
          <div className="px-4 py-2">→ Funding projects</div>
        </div>
        {goals.map((g) => {
          const weak = new Set<string>(g.link?.weak_capabilities || []);
          const projects: any[] = g.projects || [];
          const caps: any[] = g.capability_links || [];
          return (
            <div key={g.id} className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)] border-b border-gray-100 text-sm hover:bg-gray-50/60">
              <div className="px-4 py-2">
                <div className="flex flex-wrap items-center gap-1">
                  <EvidenceChip id={g.id} />
                  {g.link?.gap_flag && <Badge color="red" title="Depends on high-importance, low-maturity capabilities">capability gap</Badge>}
                  {projects.length === 0 && <Badge color="red">unfunded</Badge>}
                  {caps.length === 0 && <Badge color="amber">no capability</Badge>}
                </div>
                <div className="mt-0.5 font-medium text-gray-900">{g.statement}</div>
                <div className="mt-0.5 text-xs muted">
                  {g.kpi && <>KPI: {g.kpi} · </>}by {g.horizon_year} · from <EvidenceChip id={g.source_doc_id} />{g.source_doc}
                </div>
              </div>
              <div className="px-4 py-2 space-y-0.5">
                {caps.map((c) => (
                  <div key={c.capability_id} className="flex flex-wrap items-center gap-1">
                    <EvidenceChip id={c.capability_id} />
                    <span className={weak.has(c.name) ? "text-red-700 font-medium" : ""}>{c.name}</span>
                    <Badge color={c.status === "approved" ? "green" : "amber"}>{c.status}</Badge>
                    {weak.has(c.name) && <Badge color="red" title="importance ≥ 4 and maturity ≤ 2">low maturity</Badge>}
                  </div>
                ))}
                {caps.length === 0 && <span className="text-xs text-amber-700">No capability linked</span>}
              </div>
              <div className="px-4 py-2 space-y-0.5">
                {projects.map((p) => (
                  <div key={p.id} className="flex items-center gap-1">
                    <EvidenceChip id={p.id} />
                    <span className="truncate">{p.name}</span>
                    <span className="ml-auto text-xs muted whitespace-nowrap">{usdShort(p.budget_usd)}</span>
                  </div>
                ))}
                {projects.length === 0 && <span className="text-xs font-medium text-red-700">No project funds this goal</span>}
                {projects.length > 0 && <div className="text-right text-[11px] muted">total {usdShort(projects.reduce((s, p) => s + (p.budget_usd || 0), 0))}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </AgentPanel>
  );
}

// ---- Investment alignment ------------------------------------------------------------------------

const ALIGN_COLORS: Record<string, string> = { aligned: "#1f5bd6", orphan: "#d1242f" };

export function InvestmentAlignment() {
  const { data, loading, error } = useApi<any>("/ea/investment-alignment");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const f = data.facts || {};
  const items: any[] = data.items || [];
  const aligned = items.filter((x) => x.status === "aligned").sort((a, b) => b.budget_usd - a.budget_usd);
  const orphan = items.filter((x) => x.status === "orphan").sort((a, b) => b.budget_usd - a.budget_usd);
  const unfunded = items.filter((x) => x.status === "unfunded");
  const pie = [
    { name: "aligned", value: (f.total_budget || 0) - (f.orphan_budget || 0) },
    { name: "orphan", value: f.orphan_budget || 0 },
  ];
  const bars = aligned.map((x) => ({ id: x.goal_id, label: x.goal_id, statement: x.statement, budget: x.budget_usd }));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Budget aligned to goals" value={`${f.aligned_pct ?? "—"}%`} sub={`of ${usd(f.total_budget)} project budget`} accent />
        <Stat label="Orphan budget" value={usdShort(f.orphan_budget)} sub={`${orphan.length} projects with no strategic goal`} />
        <Stat label="Unfunded goals" value={unfunded.length} sub={unfunded.map((u) => u.goal_id).join(", ") || "none"} />
        <Stat label="Funded goals" value={aligned.length} sub="goals with at least one project" />
      </div>
      <AgentPanel agentId="ea.investment_traceability" run={data.run}>
        <div className="grid gap-4 lg:grid-cols-3">
          <div>
            <div className="label mb-1">Budget split</div>
            <div className="h-52">
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={pie} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80} label={(e: any) => `${e.name} ${usdShort(e.value)}`} labelLine={false} fontSize={11}>
                    {pie.map((p) => <Cell key={p.name} fill={ALIGN_COLORS[p.name]} />)}
                  </Pie>
                  <Tooltip formatter={(v: any) => usd(v)} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="lg:col-span-2">
            <div className="label mb-1">Budget per goal</div>
            <div className="h-52">
              <ResponsiveContainer>
                <BarChart data={bars} margin={{ left: 8, right: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} />
                  <YAxis tickFormatter={(v) => usdShort(v)} tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: any) => usd(v)} labelFormatter={(_l: any, p: any) => p?.[0]?.payload?.statement || _l} />
                  <Bar dataKey="budget" fill="#1f5bd6" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </AgentPanel>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={`Unfunded goals (${unfunded.length})`} subtitle="strategic goals with no project — propose a funding review (CIO)">
          {unfunded.length === 0 && <Empty>None.</Empty>}
          <ul className="space-y-2">
            {unfunded.map((u) => (
              <li key={u.goal_id} className="rounded border border-red-200 bg-red-50/40 p-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-1"><EvidenceChip id={u.goal_id} /><span className="text-sm font-medium">{u.statement}</span></span>
                  <ApprovalControls approval={u.approval} compact />
                </div>
                <div className="mt-1 text-xs"><span className="muted">Evidence: </span><EvidenceList refs={u.source_refs} /></div>
              </li>
            ))}
          </ul>
        </Card>
        <Card title={`Orphan projects (${orphan.length})`} subtitle={`${usd(f.orphan_budget)} with no strategic goal — flag for review (CIO)`}>
          <div className="-m-4 max-h-96 overflow-auto">
            <table className="tbl">
              <thead className="sticky top-0"><tr><th>Project</th><th>Budget</th><th>Evidence</th><th>Approval</th></tr></thead>
              <tbody>
                {orphan.map((o) => (
                  <tr key={o.project_ids[0]}>
                    <td><NamedChip id={o.project_ids[0]} name={o.name} /></td>
                    <td className="text-xs whitespace-nowrap">{usd(o.budget_usd)}</td>
                    <td><EvidenceList refs={o.source_refs} max={2} /></td>
                    <td className="whitespace-nowrap"><ApprovalControls approval={o.approval} compact /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <Card title={`Aligned investment (${aligned.length} goals)`}>
        <div className="-m-4">
          <table className="tbl">
            <thead><tr><th>Goal</th><th>Projects</th><th>Budget</th><th>Evidence</th></tr></thead>
            <tbody>
              {aligned.map((a) => (
                <tr key={a.goal_id}>
                  <td><EvidenceChip id={a.goal_id} /> {a.statement}</td>
                  <td><IdChips ids={a.project_ids} max={8} /></td>
                  <td className="text-xs whitespace-nowrap">{usd(a.budget_usd)}</td>
                  <td><EvidenceList refs={a.source_refs} max={3} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ---- Roadmap scenarios ---------------------------------------------------------------------------

const ITEM_TYPE: Record<string, { color: string; label: string }> = {
  eos: { color: "red", label: "EOS" },
  consolidation: { color: "blue", label: "consolidation" },
  risk_fix: { color: "amber", label: "risk fix" },
  strategic: { color: "purple", label: "strategic" },
};

export function Roadmaps() {
  const { data, loading, error } = useApi<any>("/ea/roadmaps");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const scenarios: any[] = data.items || [];
  const bestSavings = Math.max(...scenarios.map((s) => s.savings_in_year_1 || 0));
  const bestRisk = Math.max(...scenarios.map((s) => s.high_risks_closed_in_2q || 0));
  return (
    <AgentPanel agentId="ea.roadmap_drafter" run={data.run}>
      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        {Object.entries(ITEM_TYPE).map(([k, v]) => <Badge key={k} color={v.color}>{v.label}</Badge>)}
        <span className="muted">Adopting a scenario needs CIO approval.</span>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {scenarios.map((s) => (
          <div key={s.name} className={`flex flex-col rounded border ${s.approval?.status === "approved" ? "border-green-400 ring-1 ring-green-200" : "border-gray-200"}`}>
            <div className="border-b border-gray-100 p-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-base">{s.name}</h3>
                <span className="font-mono text-[10px] muted">{s.target_id}</span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div className={`rounded px-2 py-1 ${s.savings_in_year_1 === bestSavings && bestSavings > 0 ? "bg-green-50" : "bg-gray-50"}`}>
                  <div className="label">Savings in year 1</div>
                  <div className="text-lg font-semibold">{usdShort(s.savings_in_year_1)}</div>
                </div>
                <div className={`rounded px-2 py-1 ${s.high_risks_closed_in_2q === bestRisk ? "bg-green-50" : "bg-gray-50"}`}>
                  <div className="label">High risks closed in 2Q</div>
                  <div className="text-lg font-semibold">{s.high_risks_closed_in_2q}</div>
                </div>
              </div>
              <div className="mt-2 text-xs text-gray-700"><span className="font-medium">Trade-offs: </span>{s.tradeoffs}</div>
              <div className="mt-2 flex items-center gap-2 text-xs"><span className="muted">Adopt:</span><ApprovalControls approval={s.approval} /></div>
            </div>
            <div className="flex-1 divide-y divide-gray-100">
              {(s.quarters || []).map((q: any) => (
                <div key={q.label} className="grid grid-cols-[4.5rem_1fr] gap-2 px-3 py-2">
                  <div className="text-xs font-semibold text-gray-600">{q.label}</div>
                  <div className="space-y-1.5">
                    {(q.items || []).map((it: any) => (
                      <div key={it.id} className="text-xs">
                        <div className="flex items-start gap-1">
                          <Badge color={ITEM_TYPE[it.type]?.color || "gray"}>{ITEM_TYPE[it.type]?.label || it.type}</Badge>
                          <span className="text-gray-900">{it.title}</span>
                        </div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-1">
                          <IdChips ids={it.ref_ids} max={5} />
                          {it.depends_on?.length > 0 && <span className="text-[10px] muted">after {it.depends_on.join(", ")}</span>}
                        </div>
                      </div>
                    ))}
                    {(q.items || []).length === 0 && <span className="text-xs muted">—</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </AgentPanel>
  );
}

// ---- Impact analysis -----------------------------------------------------------------------------

const GROUPS: { key: string; label: string }[] = [
  { key: "capabilities", label: "Capabilities" },
  { key: "applications", label: "Applications" },
  { key: "datasets", label: "Datasets" },
  { key: "ai_assets", label: "AI assets & use cases" },
  { key: "people", label: "People & teams" },
  { key: "projects", label: "Projects" },
];

export function ImpactAnalysis() {
  const { data: triggers } = useApi<any[]>("/ea/impact-triggers");
  const [mode, setMode] = useState<"preset" | "node">("preset");
  const [trig, setTrig] = useState("");
  const [node, setNode] = useState("");
  const [out, setOut] = useState<AgentOutput | null>(null);
  const trigger = trig || triggers?.[0]?.id || "";
  const params = mode === "preset" ? { trigger_id: trigger } : { node_id: node.trim() };
  const f = out?.findings?.[0];
  const cur = (triggers || []).find((t) => t.id === trigger);
  return (
    <AgentPanel agentId="ea.impact_analyst" title="Impact Analyst" params={params} onRan={setOut} runLabel="Analyse impact">
      <div className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="label flex items-center gap-1"><input type="radio" checked={mode === "preset"} onChange={() => setMode("preset")} /> Preset trigger</label>
            <select className="input mt-1 min-w-[22rem]" value={trigger} onChange={(e) => { setTrig(e.target.value); setMode("preset"); }}>
              {(triggers || []).map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <label className="label flex items-center gap-1"><input type="radio" checked={mode === "node"} onChange={() => setMode("node")} /> Or any graph node</label>
            <input className="input mt-1 w-48 font-mono" placeholder="e.g. APP-0021" value={node} onChange={(e) => { setNode(e.target.value); setMode("node"); }} />
          </div>
          {mode === "preset" && cur && (
            <div className="text-xs muted pb-2">
              <Badge>{cur.type?.replace(/_/g, " ")}</Badge>{" "}
              {cur.vendor || cur.app || cur.regulation || ""}
              {cur.capabilities ? ` · ${cur.capabilities.join(", ")}` : ""}
            </div>
          )}
        </div>
        {!f && <div className="text-sm muted">Pick a trigger and click “Analyse impact” — the agent traverses the knowledge graph to depth 3.</div>}
        {f && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Trigger" value={<span className="text-base">{f.trigger}</span>} sub={f.kind?.replace(/_/g, " ")} />
              <Stat label="Estimated cost exposure" value={usdShort(f.est_cost_usd)} sub="annual run cost of affected apps" accent />
              <Stat label="Applications affected" value={f.affected?.applications?.length || 0} sub={`${f.affected?.capabilities?.length || 0} capabilities · ${f.affected?.datasets?.length || 0} datasets`} />
              <Stat label="Root nodes" value={<span className="text-base"><IdChips ids={f.root_ids} /></span>} />
            </div>
            {f.hotspots?.length > 0 && (
              <div>
                <div className="label mb-1">Hotspots (most dependents)</div>
                <div className="flex flex-wrap gap-2">
                  {f.hotspots.map((h: any) => (
                    <span key={h.id} className="inline-flex items-center rounded border border-red-200 bg-red-50 px-2 py-1 text-xs">
                      <EvidenceChip id={h.id} />{h.name}<Badge color="red">{h.dependents} dependents</Badge>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {GROUPS.map((g) => {
                const xs: any[] = [...(f.affected?.[g.key] || [])].sort((a, b) => (a.depth ?? 0) - (b.depth ?? 0));
                return (
                  <div key={g.key} className="rounded border border-gray-200">
                    <div className="flex items-center justify-between border-b border-gray-100 px-3 py-1.5">
                      <span className="text-sm font-semibold">{g.label}</span>
                      <Badge color={xs.length ? "blue" : "gray"}>{xs.length}</Badge>
                    </div>
                    <ul className="max-h-64 overflow-auto px-3 py-1.5 space-y-0.5">
                      {xs.map((x) => (
                        <li key={x.id} className="flex items-center gap-1 text-sm">
                          <EvidenceChip id={x.id} />
                          <span className="truncate">{x.name}</span>
                          <span className="ml-auto"><Badge color={x.depth === 0 ? "red" : x.depth === 1 ? "amber" : "gray"} title={x.via_edge ? `via ${x.via_edge}` : "trigger"}>depth {x.depth}</Badge></span>
                        </li>
                      ))}
                      {xs.length === 0 && <li className="text-xs muted">none</li>}
                    </ul>
                  </div>
                );
              })}
            </div>
            <div className="text-xs"><span className="muted">Evidence: </span><EvidenceList refs={f.source_refs} max={10} /></div>
          </>
        )}
      </div>
    </AgentPanel>
  );
}

// ---- Board pack ----------------------------------------------------------------------------------

export function BoardPack() {
  const { data, loading, error } = useApi<any>("/ea/board-pack");
  const { openEvidence } = useApp();
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const p = data.pack || {};
  return (
    <AgentPanel agentId="ea.board_assistant" run={data.run} runLabel="Regenerate pack">
      <div className="grid gap-4 xl:grid-cols-5">
        <div className="xl:col-span-3 rounded border border-gray-200 p-4">
          <Markdown text={data.body_md} />
        </div>
        <div className="xl:col-span-2 space-y-4">
          <div>
            <div className="label mb-1">Agenda</div>
            <ol className="space-y-1 text-sm">
              {(p.agenda || []).map((a: string) => <li key={a}><TextWithChips text={a} /></li>)}
            </ol>
          </div>
          <div>
            <div className="label mb-1">Design submissions — principle checks</div>
            <table className="tbl">
              <tbody>
                {(p.submissions || []).map((s: any) => (
                  <tr key={s.id}>
                    <td className="whitespace-nowrap"><EvidenceChip id={s.id} /></td>
                    <td className="text-xs">{s.title}<div className="muted">{s.team}</div></td>
                    <td>
                      <div className="flex flex-wrap gap-0.5">
                        {(s.principle_checks || []).map((c: any) => c.standard_id === "all" ? <Badge key="all" color="green">all pass</Badge> : (
                          <button key={c.standard_id} onClick={() => openEvidence(c.standard_id)} title={c.excerpt}>
                            <Badge color={c.result === "fail" ? "red" : c.result === "warn" ? "amber" : "green"}>{c.standard_id}</Badge>
                          </button>
                        ))}
                        {(s.principle_checks || []).length === 0 && <Badge color="green">all pass</Badge>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <div className="label mb-1">Top decisions pending</div>
            <ul className="space-y-1 text-xs">
              {(p.decisions_pending || []).slice(0, 8).map((d: any) => (
                <li key={d.approval_id} className="flex items-start gap-1">
                  <EvidenceChip id={d.approval_id} />
                  <span><Badge color="blue">{d.action_type.replace(/_/g, " ")}</Badge> <TextWithChips text={d.rationale} /></span>
                </li>
              ))}
            </ul>
          </div>
          <div className="text-xs"><span className="muted">Evidence: </span><EvidenceList refs={p.source_refs} max={10} /></div>
        </div>
      </div>
    </AgentPanel>
  );
}
