import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "../../state/AppState";
import { AgentPanel } from "../AgentPanel";
import { EvidenceChip, EvidenceList } from "../Evidence";
import { Badge, Card, ErrorBox, Loading, pct, Stat, usd, usdShort } from "../ui";
import { FlagBadge } from "./shared";

const C = { lever: "#2f6fec", total: "#1a49ad", approved: "#0f9d8a", realized: "#0b6b5e" };

function Tip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded border border-gray-200 bg-white px-2.5 py-1.5 text-xs shadow">
      <div className="font-semibold text-gray-900">{p.name}</div>
      <div>{usd(p.value)} / yr</div>
      {p.kind === "lever" && <div className="muted">running total {usd(p.base + p.value)}</div>}
    </div>
  );
}

function WrapTick({ x, y, payload }: any) {
  const words = String(payload.value).split(" ");
  const lines: string[] = [];
  words.forEach((w) => {
    const l = lines[lines.length - 1];
    if (l && (l + " " + w).length <= 14) lines[lines.length - 1] = l + " " + w;
    else lines.push(w);
  });
  return (
    <text x={x} y={y + 12} textAnchor="middle" fontSize={11} fill="#4b5563">
      {lines.map((l, i) => <tspan key={i} x={x} dy={i === 0 ? 0 : 13}>{l}</tspan>)}
    </text>
  );
}

export function SavingsTab() {
  const { data, loading, error } = useApi<any>("/portfolio/savings");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const t = data.totals;
  let acc = 0;
  const rows: any[] = (data.levers || []).map((l: any) => {
    const r = { name: l.lever, base: acc, value: l.usd, kind: "lever" };
    acc += l.usd;
    return r;
  });
  const leverSum = acc;
  rows.push({ name: "Identified", base: 0, value: t.identified ?? leverSum, kind: "total" });
  rows.push({ name: "Approved", base: 0, value: t.approved, kind: "approved" });
  rows.push({ name: "Realized", base: 0, value: t.realized, kind: "realized" });
  const findings: any[] = [...(data.findings || [])].sort((a, b) => (b.est_savings_usd || 0) - (a.est_savings_usd || 0));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Stat label="Identified" value={usd(t.identified)} accent sub={<span>from agent runs {t.source_refs.identified.map((r: string) => <EvidenceChip key={r} id={r} />)}</span>} />
        <Stat label="Approved" value={usd(t.approved)} sub={<span>{t.identified ? `${pct(t.approved / t.identified)} of identified · ` : ""}{t.source_refs.approved.slice(0, 5).map((r: string) => <EvidenceChip key={r} id={r} />)}{t.source_refs.approved.length > 5 ? `+${t.source_refs.approved.length - 5}` : ""}{t.source_refs.approved.length === 0 ? "none yet" : ""}</span>} />
        <Stat label="Realized" value={usd(t.realized)} sub={<span>{t.source_refs.realized.map((r: string) => <EvidenceChip key={r} id={r} />)}{t.source_refs.realized.length === 0 ? "none yet" : ""}</span>} />
      </div>

      <Card title="Savings waterfall by lever" subtitle="annual run-rate; each lever stacks on the previous, then identified → approved → realized">
        <div className="h-80" data-testid="savings-waterfall">
          <ResponsiveContainer>
            <BarChart data={rows} margin={{ top: 20, right: 10, left: 10, bottom: 5 }} barCategoryGap="18%">
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eef0f3" />
              <XAxis dataKey="name" tick={<WrapTick />} interval={0} stroke="#d1d5db" height={44} />
              <YAxis tickFormatter={(v) => usdShort(v)} tick={{ fontSize: 11, fill: "#6b7280" }} stroke="#d1d5db" width={60} />
              <Tooltip content={<Tip />} cursor={{ fill: "#f3f4f6" }} />
              <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
              <Bar dataKey="value" stackId="w" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                {rows.map((r, i) => <Cell key={i} fill={r.kind === "lever" ? C.lever : (C as any)[r.kind]} />)}
                <LabelList dataKey="value" position="top" formatter={(v: any) => usdShort(Number(v))} style={{ fontSize: 11, fill: "#374151" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-1 flex flex-wrap gap-4 text-xs muted">
          {[["Lever", C.lever], ["Identified total", C.total], ["Approved", C.approved], ["Realized", C.realized]].map(([k, c]) => (
            <span key={k} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />{k}</span>
          ))}
        </div>
      </Card>

      <AgentPanel agentId="pf.cost_license_optimizer" run={data.cost_run}>
        <div className="overflow-x-auto rounded border border-gray-200">
          <table className="tbl">
            <thead>
              <tr><th>Type</th><th>Subject</th><th>Finding</th><th className="text-right">Current cost</th><th className="text-right">Est. savings</th><th>Evidence</th></tr>
            </thead>
            <tbody>
              {findings.map((f, i) => (
                <tr key={i}>
                  <td><FlagBadge flag={f.type} /></td>
                  <td className="whitespace-nowrap">
                    {f.app_id ? <EvidenceChip id={f.app_id} /> : f.account ? <span className="font-mono text-xs">{f.account}</span> : "—"}
                    {f.contract_id && <EvidenceChip id={f.contract_id} />}
                  </td>
                  <td className="text-xs text-gray-700">
                    {f.evidence}
                    {f.utilization !== undefined && f.utilization !== null && <Badge color={f.utilization < 0.5 ? "amber" : "gray"}>{pct(f.utilization)} used</Badge>}
                  </td>
                  <td className="text-right tabular-nums">{usd(f.current_cost_usd)}</td>
                  <td className="text-right font-medium tabular-nums text-gray-900">{usd(f.est_savings_usd)}</td>
                  <td className="max-w-[16rem]"><EvidenceList refs={f.source_refs} max={4} /></td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={4} className="px-3 py-2 text-right text-xs font-semibold text-gray-600">Total from cost optimizer</td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums">{usd(findings.reduce((s, f) => s + (f.est_savings_usd || 0), 0))}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
        {data.overlap_run && (
          <div className="mt-2 text-xs muted">
            The “Consolidate overlaps” lever comes from the Overlap Finder run <EvidenceChip id={data.overlap_run.run_id} /> — see the Overlaps tab.
          </div>
        )}
      </AgentPanel>
    </div>
  );
}
