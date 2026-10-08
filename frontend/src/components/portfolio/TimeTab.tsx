import { useMemo, useState } from "react";
import { CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { useApi, useApp } from "../../state/AppState";
import { AgentPanel } from "../AgentPanel";
import { EvidenceChip, EvidenceList } from "../Evidence";
import { ErrorBox, Loading, usd, usdShort } from "../ui";
import { QUADRANT_COLORS, QUADRANTS, QuadrantBadge } from "./shared";

const QUADRANT_HINT: Record<string, string> = {
  Invest: "high fit · healthy",
  Tolerate: "low fit · healthy",
  Migrate: "high fit · unhealthy",
  Eliminate: "low fit · unhealthy",
};

function Tip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded border border-gray-200 bg-white px-2.5 py-1.5 text-xs shadow">
      <div className="font-semibold text-gray-900">{p.app_name} <span className="font-mono font-normal muted">{p.app_id}</span></div>
      <div className="muted">fit {p.business_fit.toFixed(2)} · health {p.tech_health.toFixed(2)} · {usd(p.annual_cost_usd)}/yr</div>
      <div className="mt-0.5">{p.disposition ? `${p.disposition} (approved)` : `${p.quadrant} (proposed)`}</div>
      <div className="mt-0.5 muted">click to open record</div>
    </div>
  );
}

export function TimeTab() {
  const { openEvidence } = useApp();
  const { data, loading, error } = useApi<any>("/portfolio/time");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [listQ, setListQ] = useState<string>("Eliminate");
  const items: any[] = data?.items || [];
  const byQ = useMemo(() => {
    const m: Record<string, any[]> = {};
    QUADRANTS.forEach((q) => (m[q] = []));
    items.forEach((i) => (m[i.disposition || i.quadrant] ||= []).push(i));
    return m;
  }, [items]);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;

  const toggle = (q: string) => setHidden((s) => { const n = new Set(s); n.has(q) ? n.delete(q) : n.add(q); return n; });
  const list = [...(byQ[listQ] || [])].sort((a, b) => (b.annual_cost_usd || 0) - (a.annual_cost_usd || 0));

  return (
    <AgentPanel agentId="pf.time_classifier" run={data.run}>
      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div>
          <div className="mb-2 flex flex-wrap gap-2">
            {QUADRANTS.map((q) => {
              const cost = (byQ[q] || []).reduce((s, i) => s + (i.annual_cost_usd || 0), 0);
              return (
                <button key={q} onClick={() => toggle(q)} title="Show / hide on chart"
                  className={`flex items-center gap-2 rounded border px-2.5 py-1.5 text-left text-xs ${hidden.has(q) ? "border-gray-200 opacity-40" : "border-gray-300 bg-white"}`}>
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: QUADRANT_COLORS[q] }} />
                  <span>
                    <span className="font-semibold text-gray-900">{q}</span> <span className="tabular-nums text-gray-800">{byQ[q]?.length || 0}</span>
                    <span className="block muted">{QUADRANT_HINT[q]} · {usdShort(cost)}</span>
                  </span>
                </button>
              );
            })}
          </div>
          <div className="h-[30rem]" data-testid="time-chart">
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" />
                <ReferenceArea x1={3} x2={5} y1={3} y2={5} fill={QUADRANT_COLORS.Invest} fillOpacity={0.03} label={{ value: "INVEST", position: "insideTopRight", fill: "#6b7280", fontSize: 11 }} />
                <ReferenceArea x1={1} x2={3} y1={3} y2={5} fill={QUADRANT_COLORS.Tolerate} fillOpacity={0.03} label={{ value: "TOLERATE", position: "insideTopLeft", fill: "#6b7280", fontSize: 11 }} />
                <ReferenceArea x1={3} x2={5} y1={1} y2={3} fill={QUADRANT_COLORS.Migrate} fillOpacity={0.04} label={{ value: "MIGRATE", position: "insideBottomRight", fill: "#6b7280", fontSize: 11 }} />
                <ReferenceArea x1={1} x2={3} y1={1} y2={3} fill={QUADRANT_COLORS.Eliminate} fillOpacity={0.03} label={{ value: "ELIMINATE", position: "insideBottomLeft", fill: "#6b7280", fontSize: 11 }} />
                <XAxis type="number" dataKey="business_fit" domain={[1, 5]} ticks={[1, 2, 3, 4, 5]} tick={{ fontSize: 12, fill: "#6b7280" }} stroke="#d1d5db"
                  label={{ value: "Business fit →", position: "insideBottom", offset: -15, fontSize: 12, fill: "#4b5563" }} />
                <YAxis type="number" dataKey="tech_health" domain={[1, 5]} ticks={[1, 2, 3, 4, 5]} tick={{ fontSize: 12, fill: "#6b7280" }} stroke="#d1d5db"
                  label={{ value: "Technical health →", angle: -90, position: "insideLeft", offset: 10, fontSize: 12, fill: "#4b5563" }} />
                <ZAxis range={[60, 60]} />
                <ReferenceLine x={3} stroke="#9ca3af" strokeDasharray="4 3" />
                <ReferenceLine y={3} stroke="#9ca3af" strokeDasharray="4 3" />
                <Tooltip content={<Tip />} cursor={{ strokeDasharray: "3 3" }} />
                {QUADRANTS.filter((q) => !hidden.has(q)).map((q) => (
                  <Scatter key={q} name={q} data={byQ[q]} fill={QUADRANT_COLORS[q]} stroke="#fff" strokeWidth={1.5} fillOpacity={0.9}
                    cursor="pointer" isAnimationActive={false} onClick={(p: any) => p?.app_id && openEvidence(p.app_id)} />
                ))}
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="text-xs muted">Thresholds at 3.0 on both axes. Each dot is an application, coloured by its approved disposition or, if none yet, the agent's proposal. Click a dot to open its source record.</div>
        </div>
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <span className="label">Apps in</span>
            <select className="input py-1" value={listQ} onChange={(e) => setListQ(e.target.value)}>
              {QUADRANTS.map((q) => <option key={q}>{q}</option>)}
            </select>
          </div>
          <ul className="max-h-[32rem] divide-y divide-gray-100 overflow-auto rounded border border-gray-200">
            {list.map((i) => (
              <li key={i.app_id} className="px-2.5 py-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate"><EvidenceChip id={i.app_id} /> <span className="text-gray-900">{i.app_name}</span></span>
                  <span className="shrink-0 text-xs tabular-nums muted">{usdShort(i.annual_cost_usd)}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2">
                  <QuadrantBadge quadrant={i.disposition || i.quadrant} proposed={!i.disposition} />
                  <span className="text-[11px] muted">fit {i.business_fit.toFixed(2)} · health {i.tech_health.toFixed(2)}</span>
                </div>
                <div className="mt-0.5 text-xs text-gray-600">{i.rationale}</div>
                <div className="mt-0.5"><EvidenceList refs={i.source_refs} max={4} /></div>
              </li>
            ))}
            {list.length === 0 && <li className="px-2.5 py-4 text-center text-sm muted">none</li>}
          </ul>
        </div>
      </div>
    </AgentPanel>
  );
}
