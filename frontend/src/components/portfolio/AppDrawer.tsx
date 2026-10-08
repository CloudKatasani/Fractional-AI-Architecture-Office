import { ReactNode } from "react";
import { ApprovalRef } from "../../api/client";
import { useApi } from "../../state/AppState";
import { ApprovalControls } from "../AgentPanel";
import { EvidenceChip, EvidenceList } from "../Evidence";
import { Badge, ConfidenceBadge, ErrorBox, Loading, pct, usd } from "../ui";
import { humanize } from "./shared";

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <div>
      <div className="label mb-1">
        {title}
        {count !== undefined && <span className="ml-1 normal-case tracking-normal text-gray-400">({count})</span>}
      </div>
      {children}
    </div>
  );
}

/** Right-hand drawer with the full application record: TCO breakdown, contracts, integrations, repos, incidents, approvals. */
export function AppDrawer({ appId, onClose }: { appId: string | null; onClose: () => void }) {
  const { data, loading, error } = useApi<any>(appId ? `/portfolio/applications/${appId}` : null, undefined, [appId]);
  if (!appId) return null;
  const a = data?.application;
  const tco = data?.tco;
  const tcoParts = tco
    ? [
        { k: "Contract share", v: tco.contract_share, c: "#1f5bd6" },
        { k: "Tagged cloud", v: tco.cloud, c: "#0f9d8a" },
        { k: "Overhead (15%)", v: tco.overhead, c: "#9ca3af" },
      ]
    : [];
  const props = data?.kg_node?.props_json || {};
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <aside className="h-full w-full max-w-2xl overflow-auto border-l border-gray-200 bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
          <div>
            <div className="label">Application</div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-900">{a?.name || appId}</span>
              <span className="font-mono text-xs muted">{appId}</span>
              {data?.kg_node && <ConfidenceBadge value={data.kg_node.confidence} />}
            </div>
          </div>
          <button className="btn btn-sm" onClick={onClose}>Close</button>
        </div>
        <div className="space-y-5 p-4">
          {loading && !data && <Loading />}
          <ErrorBox error={error} />
          {a && (
            <>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
                <Field k="Vendor" v={a.vendor} />
                <Field k="Category" v={a.category} />
                <Field k="Hosting" v={humanize(a.hosting)} />
                <Field k="Criticality" v={a.criticality} />
                <Field k="Lifecycle" v={a.lifecycle_status} />
                <Field k="Users (90d)" v={a.user_count_90d?.toLocaleString()} />
                <Field k="Version" v={a.version} />
                <Field k="Vendor EOS" v={a.vendor_eos_date} />
                <Field k="Renewal" v={a.contract_renewal_date} />
                <Field k="Classification" v={a.data_classification} />
                <Field k="Owner" v={<>{a.owner_user_id ? <EvidenceChip id={a.owner_user_id} /> : "—"}{props.owner_confirmed ? <Badge color="green">confirmed</Badge> : <Badge color="amber">unconfirmed</Badge>}</>} />
                <Field k="Discovered via" v={(a.discovered_via || []).join(", ")} />
                <Field k="Capabilities" v={(a.capability_ids || []).map((c: string) => <EvidenceChip key={c} id={c} />)} />
                <Field k="Tech stack" v={(a.tech_stack || []).join(", ")} />
                <Field k="TIME" v={props.disposition ? `${props.disposition} (approved)` : props.proposed_disposition ? `${props.proposed_disposition} (proposed)` : "—"} />
              </div>

              {tco && (
                <Section title="Total cost of ownership (annual)">
                  <div className="text-2xl font-semibold text-gray-900">{usd(tco.total)}</div>
                  <div className="mt-2 flex h-3 w-full overflow-hidden rounded bg-gray-100">
                    {tcoParts.map((p) =>
                      p.v > 0 ? <div key={p.k} title={`${p.k}: ${usd(p.v)}`} style={{ width: `${(p.v / (tco.total || 1)) * 100}%`, background: p.c }} className="border-r-2 border-white last:border-r-0" /> : null,
                    )}
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-4 text-xs">
                    {tcoParts.map((p) => (
                      <span key={p.k} className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-sm" style={{ background: p.c }} />
                        <span className="muted">{p.k}</span> <span className="font-medium text-gray-800">{usd(p.v)}</span>
                      </span>
                    ))}
                  </div>
                </Section>
              )}

              <Section title="Evidence">
                <EvidenceList refs={data.evidence} max={20} />
                {(!data.evidence || data.evidence.length === 0) && <span className="text-sm muted">none</span>}
              </Section>

              <Section title="Approvals" count={data.approvals.length}>
                {data.approvals.length === 0 && <div className="text-sm muted">No proposals for this app.</div>}
                <ul className="space-y-1.5">
                  {data.approvals.map((ap: ApprovalRef) => (
                    <li key={ap.id} className="flex flex-wrap items-center gap-2 text-sm">
                      <Badge color="blue">{humanize(ap.action_type)}</Badge>
                      <span className="font-mono text-[11px] muted">{ap.id}</span>
                      <ApprovalControls approval={ap} />
                    </li>
                  ))}
                </ul>
              </Section>

              <Section title="Contracts" count={data.contracts.length}>
                {data.contracts.length > 0 ? (
                  <table className="tbl">
                    <thead><tr><th>Id</th><th>Vendor</th><th className="text-right">Annual</th><th className="text-right">Seats</th><th>Renewal</th><th>Auto</th><th className="text-right">Benchmark</th></tr></thead>
                    <tbody>
                      {data.contracts.map((c: any) => (
                        <tr key={c.id}>
                          <td className="whitespace-nowrap"><EvidenceChip id={c.id} /></td>
                          <td>{c.vendor}</td>
                          <td className="text-right">{usd(c.annual_value_usd)}</td>
                          <td className="text-right">{c.licensed_seats ?? "—"}{c.licensed_seats && a.user_count_90d !== undefined ? <span className="ml-1 text-[11px] muted">({pct(a.user_count_90d / c.licensed_seats)} used)</span> : null}</td>
                          <td className="whitespace-nowrap">{c.renewal_date}</td>
                          <td>{c.auto_renew ? <Badge color="amber">yes</Badge> : "no"}</td>
                          <td className="text-right">{usd(c.market_benchmark_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <div className="text-sm muted">none</div>}
              </Section>

              {data.cloud?.length > 0 && (
                <Section title="Tagged cloud resources" count={data.cloud.length}>
                  <div className="flex flex-wrap">{data.cloud.slice(0, 40).map((c: any) => <EvidenceChip key={c.id} id={c.id} title={`${c.resource_type || ""} $${c.monthly_cost_usd ?? ""}/mo`} />)}</div>
                </Section>
              )}

              <Section title="Integrations" count={data.integrations.length}>
                {data.integrations.length > 0 ? (
                  <table className="tbl">
                    <thead><tr><th>Id</th><th>From → To</th><th>Pattern</th><th>Class.</th><th>Status</th></tr></thead>
                    <tbody>
                      {data.integrations.map((i: any) => (
                        <tr key={i.id}>
                          <td className="whitespace-nowrap"><EvidenceChip id={i.id} /></td>
                          <td className="text-xs">{i.from_name} → {i.to_name}</td>
                          <td className="text-xs">{i.pattern} · {i.frequency}</td>
                          <td className="text-xs">{i.data_classification}</td>
                          <td>{i.approved ? <Badge color="green">approved</Badge> : <Badge color="red">unapproved</Badge>}{i.crosses_boundary && <Badge color="amber">boundary</Badge>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <div className="text-sm muted">none</div>}
              </Section>

              <Section title="Repositories" count={data.repos.length}>
                {data.repos.length > 0 ? (
                  <table className="tbl">
                    <thead><tr><th>Id</th><th>Name</th><th>Framework</th><th className="text-right">Crit. vulns</th><th className="text-right">Last commit</th></tr></thead>
                    <tbody>
                      {data.repos.map((r: any) => (
                        <tr key={r.id}>
                          <td className="whitespace-nowrap"><EvidenceChip id={r.id} /></td>
                          <td className="font-mono text-xs">{r.name}</td>
                          <td className="text-xs">{r.language} / {r.framework} {r.framework_version} {r.eol && <Badge color="amber">EOL</Badge>}</td>
                          <td className="text-right">{r.open_critical_vulns}</td>
                          <td className="text-right">{r.last_commit_days} d</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <div className="text-sm muted">none</div>}
              </Section>

              <Section title="Incidents (24 months)" count={data.incidents.length}>
                {data.incidents.length > 0 ? (
                  <table className="tbl">
                    <thead><tr><th>Id</th><th>Date</th><th>Sev</th><th>Root cause</th><th className="text-right">Minutes</th></tr></thead>
                    <tbody>
                      {[...data.incidents].sort((x: any, y: any) => (y.date || "").localeCompare(x.date || "")).slice(0, 15).map((i: any) => (
                        <tr key={i.id}>
                          <td className="whitespace-nowrap"><EvidenceChip id={i.id} /></td>
                          <td className="whitespace-nowrap text-xs">{i.date}</td>
                          <td><Badge color={i.severity <= 2 ? "red" : "gray"}>S{i.severity}</Badge></td>
                          <td className="text-xs">{humanize(i.root_cause_category)}</td>
                          <td className="text-right">{i.minutes_to_resolve}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <div className="text-sm muted">none</div>}
                {data.incidents.length > 15 && <div className="mt-1 text-xs muted">Showing latest 15 of {data.incidents.length}.</div>}
              </Section>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

function Field({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] muted">{k}</div>
      <div className="truncate text-gray-800">{v === null || v === undefined || v === "" ? "—" : v}</div>
    </div>
  );
}
