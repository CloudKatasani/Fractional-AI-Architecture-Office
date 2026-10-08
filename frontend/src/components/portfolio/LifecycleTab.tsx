import { useState } from "react";
import { useApi } from "../../state/AppState";
import { AgentPanel } from "../AgentPanel";
import { EvidenceChip, EvidenceList } from "../Evidence";
import { Badge, ErrorBox, Loading, pct, SeverityBadge, Stat, usd } from "../ui";

const SEV_BAR: Record<string, string> = { critical: "#c62828", high: "#e0a100", medium: "#9ca3af", low: "#d1d5db" };
const HORIZON = 365;

export function LifecycleTab() {
  const { data, loading, error } = useApi<any>("/portfolio/lifecycle");
  const [type, setType] = useState<"all" | "vendor_eos" | "contract_renewal">("all");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const items: any[] = data.items || [];
  const timed = items
    .filter((i) => i.days_remaining !== null && i.days_remaining !== undefined && (type === "all" || i.type === type))
    .sort((a, b) => a.days_remaining - b.days_remaining);
  const eol = items.filter((i) => i.type === "eol_framework").sort((a, b) => (a.criticality || 9) - (b.criticality || 9));
  const eos = items.filter((i) => i.type === "vendor_eos");
  const ren = items.filter((i) => i.type === "contract_renewal");
  const autoLow = ren.filter((r) => r.auto_renew && (r.utilization ?? 1) < 0.5);

  return (
    <AgentPanel agentId="pf.lifecycle_watcher" run={data.run}>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Vendor EOS ≤ 12 months" value={eos.length} sub={eos[0] ? `nearest: ${[...eos].sort((a, b) => a.days_remaining - b.days_remaining)[0].name}` : "none"} />
        <Stat label="Renewals ≤ 180 days" value={ren.length} sub={`${usd(ren.reduce((s, r) => s + (r.annual_value_usd || 0), 0))}/yr in contract value`} />
        <Stat label="Auto-renew, < 50% used" value={autoLow.length} sub="decide before the notice window" accent={autoLow.length > 0} />
        <Stat label="EOL frameworks" value={eol.length} sub={`${eol.filter((e) => e.severity === "critical").length} critical · ${eol.filter((e) => e.severity === "high").length} high severity`} />
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="mr-2">Timeline</h3>
        {(["all", "vendor_eos", "contract_renewal"] as const).map((t) => (
          <button key={t} className={`btn btn-sm ${type === t ? "border-accent-500 text-accent-700" : ""}`} onClick={() => setType(t)}>
            {t === "all" ? "All" : t === "vendor_eos" ? "Vendor EOS" : "Contract renewals"}
          </button>
        ))}
        <span className="ml-auto text-[11px] muted">bar = days remaining (0 – {HORIZON} d)</span>
      </div>
      <div className="overflow-x-auto rounded border border-gray-200">
        <table className="tbl">
          <thead>
            <tr><th>Date</th><th className="w-[22%]">Days remaining</th><th>Type</th><th>Subject</th><th>Severity</th><th>Terms</th><th>Recommended action</th></tr>
          </thead>
          <tbody>
            {timed.map((i, idx) => (
              <tr key={`${i.type}-${i.contract_id || i.app_id}-${idx}`}>
                <td className="whitespace-nowrap font-mono text-xs">{i.date}</td>
                <td>
                  <div className="flex items-center gap-2">
                    <div className="h-2 flex-1 rounded bg-gray-100">
                      <div className="h-2 rounded" style={{ width: `${Math.max(2, Math.min(100, (i.days_remaining / HORIZON) * 100))}%`, background: SEV_BAR[i.severity] || "#9ca3af" }} />
                    </div>
                    <span className="w-12 text-right text-xs tabular-nums">{i.days_remaining} d</span>
                  </div>
                </td>
                <td>{i.type === "vendor_eos" ? <Badge color="red">vendor EOS</Badge> : <Badge>renewal</Badge>}</td>
                <td className="min-w-[12rem]">
                  <div className="text-gray-900">{i.name}</div>
                  <div><EvidenceList refs={i.source_refs} max={3} /></div>
                </td>
                <td><SeverityBadge severity={i.severity} /></td>
                <td className="whitespace-nowrap text-xs">
                  {i.type === "contract_renewal" ? (
                    <div className="space-y-0.5">
                      <div>{usd(i.annual_value_usd)}/yr</div>
                      <div className="flex items-center gap-1">
                        {i.auto_renew ? <Badge color="amber">auto-renew</Badge> : <Badge>manual</Badge>}
                        {i.utilization !== undefined && i.utilization !== null && (
                          <span className={i.utilization < 0.5 ? "font-medium text-red-700" : "muted"} title="Seat utilisation">{pct(i.utilization)} used</span>
                        )}
                      </div>
                    </div>
                  ) : (
                    <span className="muted">criticality {i.criticality ?? "—"}</span>
                  )}
                </td>
                <td className="text-xs text-gray-700">{i.recommended_action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="mb-2 mt-6">End-of-life frameworks</h3>
      <div className="overflow-x-auto rounded border border-gray-200">
        <table className="tbl">
          <thead><tr><th>Application</th><th>Criticality</th><th>Severity</th><th>Evidence</th><th>Recommended action</th></tr></thead>
          <tbody>
            {eol.map((i) => (
              <tr key={`${i.app_id}-${i.source_refs?.[0]?.record_id}`}>
                <td className="whitespace-nowrap"><EvidenceChip id={i.app_id} /> {i.name}</td>
                <td>{i.criticality ?? "—"}</td>
                <td><SeverityBadge severity={i.severity} /></td>
                <td><EvidenceList refs={i.source_refs} max={3} /><div className="text-[11px] muted">{i.source_refs?.[0]?.excerpt}</div></td>
                <td className="text-xs text-gray-700">{i.recommended_action}</td>
              </tr>
            ))}
            {eol.length === 0 && <tr><td colSpan={5} className="text-center muted">none</td></tr>}
          </tbody>
        </table>
      </div>
    </AgentPanel>
  );
}
