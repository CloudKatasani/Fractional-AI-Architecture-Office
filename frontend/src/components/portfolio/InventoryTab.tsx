import { useMemo, useState } from "react";
import { useApi } from "../../state/AppState";
import { ApprovalControls } from "../AgentPanel";
import { EvidenceChip } from "../Evidence";
import { Badge, Card, ConfidenceBadge, Empty, ErrorBox, Loading, usd, usdShort } from "../ui";
import { AppDrawer } from "./AppDrawer";
import { FLAG_LABELS, FlagBadge, QUADRANTS, QuadrantBadge } from "./shared";

type SortKey = "cost" | "users" | "name" | "confidence";

export function InventoryTab() {
  const { data, loading, error } = useApi<any>("/portfolio/applications");
  const [q, setQ] = useState("");
  const [quadrant, setQuadrant] = useState("");
  const [flag, setFlag] = useState("");
  const [cap, setCap] = useState("");
  const [sort, setSort] = useState<SortKey>("cost");
  const [open, setOpen] = useState<string | null>(null);

  const apps: any[] = data?.items || [];
  const caps = useMemo(() => {
    const m = new Map<string, string>();
    apps.forEach((a) => a.capability_ids.forEach((id: string, i: number) => m.set(id, a.capabilities[i] || id)));
    return Array.from(m.entries()).sort((x, y) => x[1].localeCompare(y[1]));
  }, [apps]);
  const flags = useMemo(() => Array.from(new Set(apps.flatMap((a) => a.flags))).sort(), [apps]);

  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const xs = apps.filter((a) => {
      if (ql && !`${a.id} ${a.name} ${a.vendor} ${a.owner || ""} ${a.category}`.toLowerCase().includes(ql)) return false;
      if (quadrant && (a.disposition || a.proposed_disposition) !== quadrant) return false;
      if (flag && !a.flags.includes(flag)) return false;
      if (cap && !a.capability_ids.includes(cap)) return false;
      return true;
    });
    const by: Record<SortKey, (a: any, b: any) => number> = {
      cost: (a, b) => (b.annual_cost_usd || 0) - (a.annual_cost_usd || 0),
      users: (a, b) => (b.user_count_90d || 0) - (a.user_count_90d || 0),
      name: (a, b) => a.name.localeCompare(b.name),
      confidence: (a, b) => a.confidence - b.confidence,
    };
    return [...xs].sort(by[sort]);
  }, [apps, q, quadrant, flag, cap, sort]);

  const total = rows.reduce((s, a) => s + (a.annual_cost_usd || 0), 0);
  const unconfirmed = rows.filter((a) => !a.owner_confirmed).length;
  const filtered = q || quadrant || flag || cap;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input className="input w-64" placeholder="Search app, vendor, owner, id…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input" value={quadrant} onChange={(e) => setQuadrant(e.target.value)}>
          <option value="">All dispositions</option>
          {QUADRANTS.map((x) => <option key={x}>{x}</option>)}
        </select>
        <select className="input" value={flag} onChange={(e) => setFlag(e.target.value)}>
          <option value="">All flags</option>
          {flags.map((f) => <option key={f} value={f}>{FLAG_LABELS[f]?.label || f}</option>)}
        </select>
        <select className="input max-w-[16rem]" value={cap} onChange={(e) => setCap(e.target.value)}>
          <option value="">All capabilities</option>
          {caps.map(([id, n]) => <option key={id} value={id}>{n}</option>)}
        </select>
        <select className="input" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          <option value="cost">Sort: cost ↓</option>
          <option value="users">Sort: users ↓</option>
          <option value="confidence">Sort: confidence ↑</option>
          <option value="name">Sort: name</option>
        </select>
        {filtered && <button className="btn btn-sm" onClick={() => { setQ(""); setQuadrant(""); setFlag(""); setCap(""); }}>Clear</button>}
        <span className="ml-auto text-xs muted">
          {rows.length} of {apps.length} apps · {usd(total)}/yr · {unconfirmed} owner-unconfirmed
        </span>
      </div>
      <ErrorBox error={error} />
      {loading && !data && <Loading />}
      {data && (
        <Card className="overflow-hidden">
          <div className="-m-4 overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Application</th>
                  <th>Capability</th>
                  <th>Owner</th>
                  <th className="text-right">Cost / yr</th>
                  <th className="text-right">Users 90d</th>
                  <th>Conf.</th>
                  <th>Disposition</th>
                  <th>Flags</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const pendingDisp = a.approvals?.find((p: any) => p.action_type === "set_disposition" && p.status === "pending");
                  return (
                    <tr key={a.id} className="cursor-pointer" onClick={() => setOpen(a.id)} data-testid={`app-row-${a.id}`}>
                      <td className="min-w-[14rem]">
                        <div className="flex items-center gap-1.5">
                          <span className="whitespace-nowrap font-mono text-[11px] muted">{a.id}</span>
                          <span className="font-medium text-gray-900">{a.name}</span>
                          {a.shadow_it && <Badge color="purple">shadow IT</Badge>}
                          {!a.in_cmdb && <Badge color="amber" title="Not in CMDB">no CI</Badge>}
                        </div>
                        <div className="text-[11px] muted">{a.vendor} · {a.category}</div>
                      </td>
                      <td className="text-xs">{a.capabilities.join(", ") || <span className="muted">—</span>}</td>
                      <td className="whitespace-nowrap text-xs">
                        {a.owner || <span className="text-amber-700">no owner</span>}
                        {a.owner && !a.owner_confirmed && <span className="ml-1 text-amber-700" title="Owner not yet confirmed">?</span>}
                      </td>
                      <td className="text-right tabular-nums" title={usd(a.annual_cost_usd)}>{usdShort(a.annual_cost_usd)}</td>
                      <td className={`text-right tabular-nums ${a.user_count_90d === 0 ? "text-red-700 font-medium" : ""}`}>{a.user_count_90d?.toLocaleString() ?? "—"}</td>
                      <td><ConfidenceBadge value={a.confidence} /></td>
                      <td className="whitespace-nowrap" onClick={(e) => pendingDisp && e.stopPropagation()}>
                        {a.disposition ? <QuadrantBadge quadrant={a.disposition} /> : <QuadrantBadge quadrant={a.proposed_disposition} proposed />}
                        {pendingDisp && <div className="mt-0.5"><ApprovalControls approval={pendingDisp} compact /></div>}
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1">{a.flags.map((f: string) => <FlagBadge key={f} flag={f} />)}</div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {rows.length === 0 && <Empty>No applications match these filters.</Empty>}
          </div>
        </Card>
      )}
      {data?.time_run && (
        <div className="text-xs muted">
          Proposed dispositions from <span className="font-mono">{data.time_run.agent_id}</span> run <EvidenceChip id={data.time_run.run_id} />. Click a row for cost breakdown, contracts, integrations and evidence.
        </div>
      )}
      <AppDrawer appId={open} onClose={() => setOpen(null)} />
    </div>
  );
}
