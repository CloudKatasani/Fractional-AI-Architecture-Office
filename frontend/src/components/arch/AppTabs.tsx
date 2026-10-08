import { Fragment, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AgentOutput } from "../../api/client";
import { useApi, useApp } from "../../state/AppState";
import { AgentPanel, ApprovalControls } from "../AgentPanel";
import { EvidenceChip, EvidenceList, TextWithChips } from "../Evidence";
import { Markdown } from "../Markdown";
import { Mermaid } from "../Mermaid";
import { Badge, Card, Empty, ErrorBox, Loading, Modal, SeverityBadge, Toggle, usd, usdShort } from "../ui";
import { IdChips, NamedChip } from "./common";

// ---- ADRs ----------------------------------------------------------------------------------------

export function Adrs() {
  const { data, loading, error } = useApi<any>("/app/adrs");
  const [disc, setDisc] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const discussions: any[] = data.discussions || [];
  const discussion = discussions.find((x) => x.id === disc);
  const drafts: any[] = data.drafts || [];
  const published: any[] = [...(data.published || [])].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return (
    <div className="space-y-4">
      <AgentPanel agentId="app.adr_writer" run={data.run}>
        <div className="mb-2 text-xs muted">
          Drafts extracted from design discussions. The agent runs at L3: approving a draft publishes it to the ADR repository.
        </div>
        {drafts.length === 0 && <Empty>No ADR drafts.</Empty>}
        <div className="space-y-3">
          {drafts.map((a) => (
            <div key={a.source_discussion_id + a.title} className="rounded border border-gray-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge color="amber">draft ADR</Badge>
                    <h3>{a.title}</h3>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-xs muted">
                    from <EvidenceChip id={a.source_discussion_id} />
                    <span>{a.channel}</span>
                    {a.participants?.length > 0 && <span>· {a.participants.join(", ")}</span>}
                    <button className="ml-1 text-accent-700 hover:underline" onClick={() => setDisc(a.source_discussion_id)}>view thread</button>
                  </div>
                </div>
                <ApprovalControls approval={a.approval} />
              </div>
              <div className="mt-2 grid gap-3 md:grid-cols-2 text-sm">
                <div><div className="label">Context</div><div className="mt-0.5"><TextWithChips text={a.context} /></div></div>
                <div>
                  <div className="label">Options considered</div>
                  <ol className="mt-0.5 list-decimal pl-5">
                    {(a.options || []).map((o: string) => <li key={o} className={a.decision?.toLowerCase().includes(o.toLowerCase().slice(0, 18)) ? "font-medium" : ""}>{o}</li>)}
                  </ol>
                </div>
                <div><div className="label">Decision</div><div className="mt-0.5 font-medium text-gray-900"><TextWithChips text={a.decision} /></div></div>
                <div><div className="label">Consequences</div><div className="mt-0.5"><TextWithChips text={a.consequences} /></div></div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1 text-xs">
                <span className="muted">Applications:</span> <IdChips ids={a.app_ids} />
                <span className="muted ml-2">Evidence:</span> <EvidenceList refs={a.source_refs} />
              </div>
            </div>
          ))}
        </div>
      </AgentPanel>

      <Card title="Published ADRs" subtitle={`${published.length} decisions in the ADR repository`}>
        <div className="-m-4">
          <table className="tbl">
            <thead><tr><th>Id</th><th>Title</th><th>Status</th><th>Date</th><th>Decision</th><th>Apps</th><th>Source</th></tr></thead>
            <tbody>
              {published.slice(0, showAll ? 999 : 12).map((a) => (
                <tr key={a.id}>
                  <td><EvidenceChip id={a.id} /></td>
                  <td className="font-medium">{a.title}</td>
                  <td><Badge color={a.status === "accepted" || a.status === "published" ? "green" : "gray"}>{a.status}</Badge></td>
                  <td className="text-xs whitespace-nowrap">{a.date}</td>
                  <td className="text-xs max-w-md">{a.decision}</td>
                  <td><IdChips ids={a.app_ids} max={4} /></td>
                  <td>{a.source_discussion_id ? <button className="text-xs text-accent-700 hover:underline" onClick={() => setDisc(a.source_discussion_id)}>{a.source_discussion_id}</button> : <span className="text-xs muted">ADR repo</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {published.length > 12 && (
            <div className="px-4 py-2"><button className="btn btn-sm" onClick={() => setShowAll((s) => !s)}>{showAll ? "Show fewer" : `Show all ${published.length}`}</button></div>
          )}
        </div>
      </Card>

      <Card title="Design discussions" subtitle="Slack / Teams threads the ADR Writer reads">
        <div className="flex flex-wrap gap-1.5">
          {discussions.map((x) => (
            <button key={x.id} className="btn btn-sm" onClick={() => setDisc(x.id)} title={x.title}>
              <span className="font-mono">{x.id}</span>
              <span className="max-w-[16rem] truncate">{x.title}</span>
            </button>
          ))}
        </div>
      </Card>

      <Modal open={!!discussion} onClose={() => setDisc(null)} title={discussion ? `${discussion.channel} — ${discussion.title}` : ""}>
        {discussion && (
          <>
            <div className="mb-2 flex flex-wrap gap-2 text-xs">
              <EvidenceChip id={discussion.id} />
              <Badge>{discussion.source_system}</Badge>
              <Badge>{discussion.date}</Badge>
              <span className="muted">{(discussion.participants || []).join(", ")}</span>
            </div>
            <Markdown text={discussion.body_md} />
          </>
        )}
      </Modal>
    </div>
  );
}

// ---- Drift ---------------------------------------------------------------------------------------

const DRIFT_ORDER = ["boundary_violation", "unapproved_integration", "undeclared_dependency"];
const DRIFT_LABEL: Record<string, string> = {
  boundary_violation: "Boundary violations",
  unapproved_integration: "Unapproved integrations",
  undeclared_dependency: "Undeclared dependencies",
};

export function Drift() {
  const { data, loading, error } = useApi<any>("/app/drift");
  const [stacked, setStacked] = useState(false);
  const groups = useMemo(() => {
    const g: Record<string, any[]> = {};
    (data?.items || []).forEach((x: any) => (g[x.type] = g[x.type] || []).push(x));
    return [...DRIFT_ORDER, ...Object.keys(g).filter((k) => !DRIFT_ORDER.includes(k))].filter((k) => g[k]).map((k) => [k, g[k]] as const);
  }, [data]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const tickets: any[] = data.tickets || [];
  return (
    <div className="space-y-4">
      <AgentPanel agentId="app.drift_detector" run={data.run}>
        <div className="mb-3 flex flex-wrap gap-2">
          {groups.map(([k, xs]) => (
            <Badge key={k} color={k === "boundary_violation" ? "red" : "amber"}>{DRIFT_LABEL[k] || k}: {xs.length}</Badge>
          ))}
          <span className="ml-auto"><Toggle checked={stacked} onChange={setStacked} label="Stack diagrams vertically" /></span>
        </div>
        <div className={`grid gap-4 ${stacked ? "" : "xl:grid-cols-2"}`}>
          <div className="rounded border border-gray-200 p-2 min-w-0">
            <div className="label mb-1">Intended — declared &amp; approved integrations</div>
            <Mermaid chart={data.diagrams?.intended} />
          </div>
          <div className="rounded border border-red-200 p-2 min-w-0">
            <div className="label mb-1 text-red-700">Actual — observed at runtime (red = boundary-crossing DB link, dashed = undeclared)</div>
            <Mermaid chart={data.diagrams?.actual} />
          </div>
        </div>
      </AgentPanel>

      <Card title="Drift findings" subtitle="Approving a remediation ticket at L3 creates a ticket in Jira (simulated).">
        <div className="-m-4 overflow-auto">
          <table className="tbl">
            <thead><tr><th>Flow (from → to)</th><th>Details</th><th>Standard</th><th>Severity</th><th>Evidence</th><th>Approval</th></tr></thead>
            <tbody>
              {groups.map(([k, xs]) => (
                <Fragment key={k}>
                  <tr>
                    <td colSpan={6} className={`text-xs font-semibold uppercase tracking-wide ${k === "boundary_violation" ? "bg-red-50 text-red-700" : "bg-gray-50 text-gray-600"}`}>
                      {DRIFT_LABEL[k] || k} ({xs.length})
                    </td>
                  </tr>
                  {xs.map((f: any, i: number) => (
                    <tr key={`${k}-${i}`} className={k === "boundary_violation" ? "bg-red-50/60" : ""}>
                      <td className="whitespace-nowrap">
                        <div><NamedChip id={f.app_id} name={f.app_name} /></div>
                        <div className="pl-3 text-gray-400">↳ <NamedChip id={f.to_app_id} name={f.to_app_name} /></div>
                      </td>
                      <td className={`text-xs min-w-[18rem] ${k === "boundary_violation" ? "font-medium text-red-800" : ""}`}>
                        {f.integration_id && <EvidenceChip id={f.integration_id} />}<TextWithChips text={f.details} />
                      </td>
                      <td className="whitespace-nowrap">{f.standard_id && <EvidenceChip id={f.standard_id} />}</td>
                      <td><SeverityBadge severity={f.severity} /></td>
                      <td className="min-w-[8rem]"><EvidenceList refs={f.source_refs} max={3} /></td>
                      <td className="whitespace-nowrap"><ApprovalControls approval={f.approval} compact /></td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Remediation tickets — Jira (simulated)" subtitle="Created automatically when a remediation is approved at autonomy L3">
        {tickets.length === 0 ? (
          <Empty>No tickets yet. Approve a boundary violation as Security Architect (or Principal Architect) to create one.</Empty>
        ) : (
          <div className="-m-4">
            <table className="tbl">
              <thead><tr><th>Key</th><th>Title</th><th>Status</th><th>Assignee</th><th>Target</th><th>Approval</th><th>Created</th></tr></thead>
              <tbody>
                {tickets.map((t) => (
                  <tr key={t.id}>
                    <td className="font-mono text-xs font-semibold">{t.key}</td>
                    <td>{t.title}<div className="text-xs muted"><TextWithChips text={t.description || ""} /></div></td>
                    <td><Badge color={t.status === "open" ? "amber" : "green"}>{t.status}</Badge></td>
                    <td className="text-xs">{t.assignee || "—"}</td>
                    <td>{t.target_id && <EvidenceChip id={t.target_id} />}</td>
                    <td>{t.approval_id && <EvidenceChip id={t.approval_id} />}</td>
                    <td className="text-xs whitespace-nowrap">{(t.created_at || "").replace("T", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ---- APIs ----------------------------------------------------------------------------------------

const API_TYPE: Record<string, { color: string; label: string }> = {
  duplicate: { color: "amber", label: "duplicate" },
  insecure: { color: "red", label: "insecure auth" },
  missing_gateway: { color: "red", label: "missing gateway" },
};

export function Apis() {
  const { data, loading, error } = useApi<any>("/app/apis");
  const [q, setQ] = useState("");
  const [only, setOnly] = useState("");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const findings: any[] = data.findings || [];
  const flagged = new Set<string>(findings.flatMap((f) => f.api_ids || []));
  const apis: any[] = (data.apis || []).filter((a: any) => {
    if (q && !`${a.id} ${a.name} ${a.owner_app} ${a.resource}`.toLowerCase().includes(q.toLowerCase())) return false;
    if (only === "flagged" && !flagged.has(a.id)) return false;
    if (only === "duplicates" && !a.duplicate_group) return false;
    if (only === "no_gateway" && a.via_gateway) return false;
    return true;
  });
  return (
    <div className="space-y-4">
      <AgentPanel agentId="app.integration_api_architect" run={data.run}>
        <div className="-mx-4 -mb-4 overflow-auto">
          <table className="tbl">
            <thead><tr><th>Finding</th><th>APIs</th><th>Recommendation</th><th>Migrate consumers</th><th>Severity</th><th>Evidence</th><th>Canonical designation</th></tr></thead>
            <tbody>
              {findings.map((f, i) => (
                <tr key={i}>
                  <td><Badge color={API_TYPE[f.type]?.color || "gray"}>{API_TYPE[f.type]?.label || f.type}</Badge>{f.group && <div className="mt-0.5 font-mono text-[10px] muted">{f.group}</div>}</td>
                  <td><IdChips ids={f.api_ids} /></td>
                  <td className="text-xs max-w-md"><TextWithChips text={f.recommendation || ""} /></td>
                  <td><IdChips ids={f.consumers_to_migrate} /></td>
                  <td>{f.severity ? <SeverityBadge severity={f.severity} /> : <span className="text-xs muted">—</span>}</td>
                  <td className="min-w-[10rem]"><EvidenceList refs={f.source_refs} max={3} /></td>
                  <td className="whitespace-nowrap">{f.canonical_api_id && <EvidenceChip id={f.canonical_api_id} />}{f.approval ? <ApprovalControls approval={f.approval} compact /> : <span className="text-[11px] muted">observation</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AgentPanel>
      <Card
        title="API catalogue"
        subtitle={`${data.apis?.length || 0} APIs · ${flagged.size} flagged by the agent`}
        actions={
          <>
            <input className="input py-1 text-xs w-56" placeholder="Search name, owner, resource…" value={q} onChange={(e) => setQ(e.target.value)} />
            <select className="input py-1 text-xs" value={only} onChange={(e) => setOnly(e.target.value)}>
              <option value="">All APIs</option>
              <option value="flagged">Flagged by agent</option>
              <option value="duplicates">In a duplicate group</option>
              <option value="no_gateway">Not via gateway</option>
            </select>
          </>
        }
      >
        <div className="-m-4 max-h-[36rem] overflow-auto">
          <table className="tbl">
            <thead className="sticky top-0"><tr><th>Id</th><th>Name</th><th>Owner app</th><th>Style</th><th>Auth</th><th>Classification</th><th>Gateway</th><th>Consumers</th><th></th></tr></thead>
            <tbody>
              {apis.map((a) => {
                const weak = (a.auth === "none" || a.auth === "apikey") && (a.data_classification === "confidential" || a.data_classification === "restricted");
                return (
                  <tr key={a.id}>
                    <td><EvidenceChip id={a.id} /></td>
                    <td className="font-medium">{a.name}{a.duplicate_group && <div className="font-mono text-[10px] muted">{a.duplicate_group}</div>}</td>
                    <td className="whitespace-nowrap"><NamedChip id={a.owner_app_id} name={a.owner_app} /></td>
                    <td className="text-xs">{a.style}</td>
                    <td><Badge color={weak ? "red" : a.auth === "none" ? "amber" : "gray"}>{a.auth}</Badge></td>
                    <td><Badge color={a.data_classification === "restricted" || a.data_classification === "confidential" ? "purple" : "gray"}>{a.data_classification}</Badge></td>
                    <td>{a.via_gateway ? <Badge color="green">gateway</Badge> : <Badge color={a.data_classification === "confidential" ? "red" : "amber"}>direct</Badge>}</td>
                    <td><IdChips ids={a.consumers} names={a.consumer_names} max={4} /></td>
                    <td className="whitespace-nowrap">
                      {a.canonical && <Badge color="green">canonical</Badge>} {a.deprecated && <Badge color="red">deprecated</Badge>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {apis.length === 0 && <Empty>No APIs match.</Empty>}
        </div>
      </Card>
    </div>
  );
}

// ---- Tech debt -----------------------------------------------------------------------------------

export function Debt() {
  const { data, loading, error } = useApi<any>("/app/debt");
  const [showAll, setShowAll] = useState(false);
  const { openEvidence } = useApp();
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const items: any[] = [...(data.items || [])].sort((a, b) => b.score - a.score);
  const top = items.slice(0, 20).map((x) => ({ ...x, label: `${x.app_name}` }));
  return (
    <div className="space-y-4">
      <AgentPanel agentId="app.tech_debt_radar" run={data.run}>
        <div className="grid gap-4 xl:grid-cols-5">
          <div className="xl:col-span-3">
            <div className="label mb-1">Top 20 by debt score (0–100) — click a bar to open the application</div>
            <div style={{ height: top.length * 24 + 40 }}>
              <ResponsiveContainer>
                <BarChart data={top} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="label" width={200} tick={{ fontSize: 11 }} interval={0} />
                  <Tooltip formatter={(v: any) => [v, "score"]} labelFormatter={(l: any) => l} />
                  <Bar dataKey="score" onClick={(d: any) => openEvidence(d.app_id)} cursor="pointer" radius={[0, 3, 3, 0]}>
                    {top.map((x) => <Cell key={x.app_id} fill={x.score >= 75 ? "#1a49ad" : "#2f6fec"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="xl:col-span-2 space-y-2 text-sm">
            <div className="label">Scoring model</div>
            <ul className="text-xs space-y-1 text-gray-700">
              <li><b>30</b> — application on an end-of-life framework</li>
              <li><b>0–20</b> — framework age</li>
              <li><b>0–25</b> — open critical vulnerabilities</li>
              <li><b>0–25</b> — incidents in the last 90 days, weighted by severity</li>
            </ul>
            <div className="grid grid-cols-3 gap-2 pt-2">
              <div className="card px-3 py-2"><div className="label">Scored</div><div className="text-lg font-semibold">{items.length}</div></div>
              <div className="card px-3 py-2"><div className="label">EOL apps</div><div className="text-lg font-semibold text-red-700">{items.filter((x) => x.eol).length}</div></div>
              <div className="card px-3 py-2"><div className="label">Incident cost</div><div className="text-lg font-semibold">{usdShort(items.reduce((s, x) => s + (x.incident_cost_est || 0), 0))}</div></div>
            </div>
          </div>
        </div>
      </AgentPanel>
      <Card title="Debt register candidates" subtitle="ranked; approving adds the app to the debt register">
        <div className="-m-4 overflow-auto">
          <table className="tbl">
            <thead><tr><th>#</th><th>Application</th><th>Score</th><th>Drivers</th><th>Effort</th><th>Incident cost est.</th><th>Evidence</th><th>Approval</th></tr></thead>
            <tbody>
              {items.slice(0, showAll ? 999 : 25).map((x, i) => (
                <tr key={x.app_id}>
                  <td className="text-xs muted">{i + 1}</td>
                  <td className="whitespace-nowrap"><NamedChip id={x.app_id} name={x.app_name} />{x.eol && <span className="ml-1"><Badge color="red">EOL</Badge></span>}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 rounded bg-gray-100"><div className={`h-1.5 rounded ${x.score >= 60 ? "bg-red-500" : x.score >= 35 ? "bg-amber-500" : "bg-accent-500"}`} style={{ width: `${Math.min(100, x.score)}%` }} /></div>
                      <span className="font-mono text-xs">{x.score.toFixed(1)}</span>
                    </div>
                  </td>
                  <td className="text-xs min-w-[18rem]">{(x.drivers || []).join(" · ") || <span className="muted">—</span>}</td>
                  <td><Badge color={x.effort_band === "L" ? "red" : x.effort_band === "M" ? "amber" : "gray"}>{x.effort_band}</Badge></td>
                  <td className="text-xs whitespace-nowrap">{usd(x.incident_cost_est)}</td>
                  <td className="min-w-[14rem]"><EvidenceList refs={x.source_refs} max={4} /></td>
                  <td className="whitespace-nowrap">{x.approval ? <ApprovalControls approval={x.approval} compact /> : <span className="text-[11px] muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length > 25 && <div className="px-4 py-2"><button className="btn btn-sm" onClick={() => setShowAll((s) => !s)}>{showAll ? "Show top 25" : `Show all ${items.length}`}</button></div>}
        </div>
      </Card>
    </div>
  );
}

// ---- Pattern advisor -----------------------------------------------------------------------------

const EXAMPLES: Record<string, string[]> = {
  northgrid: [
    "Stream smart meter events to a near-real-time outage dashboard for customers",
    "Let field crews capture inspection photos offline and sync them to the asset system",
    "Generative AI assistant that summarises regulatory filings for analysts",
  ],
  meridian: [
    "Expose subscriber usage to partners for a 5G network-slicing marketplace",
    "Real-time next-best-offer in the retail app based on usage events",
    "Replicate billing data into the lakehouse for churn analytics",
  ],
};

export function PatternAdvisor() {
  const { tenant } = useApp();
  const ex = EXAMPLES[tenant] || EXAMPLES.northgrid;
  const [text, setText] = useState(ex[0]);
  const [out, setOut] = useState<AgentOutput | null>(null);
  const recs = (out?.findings || []).slice(0, 2);
  return (
    <AgentPanel agentId="app.pattern_advisor" title="Pattern Advisor" params={{ text }} onRan={setOut} runLabel="Recommend patterns">
      <div className="space-y-3">
        <div>
          <label className="label">Describe the feature</label>
          <textarea className="input mt-1 w-full h-20" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Stream meter events to an outage dashboard" />
          <div className="mt-1 flex flex-wrap gap-1 text-xs">
            <span className="muted">Try:</span>
            {ex.map((e) => <button key={e} className="btn btn-sm" onClick={() => setText(e)}>{e.length > 60 ? e.slice(0, 58) + "…" : e}</button>)}
          </div>
        </div>
        {!out && <div className="text-sm muted">Enter a feature description and click “Recommend patterns”.</div>}
        {out && recs.length === 0 && <Empty>No matching pattern.</Empty>}
        <div className="grid gap-4 xl:grid-cols-2">
          {recs.map((r: any, i: number) => (
            <div key={r.pattern_id} className={`rounded border p-3 ${i === 0 ? "border-accent-500" : "border-gray-200"}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Badge color={i === 0 ? "blue" : "gray"}>{i === 0 ? "recommended" : "alternative"}</Badge>
                  <EvidenceChip id={r.pattern_id} />
                  <h3>{r.name}</h3>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="muted">fit</span>
                  <div className="h-1.5 w-20 rounded bg-gray-100"><div className="h-1.5 rounded bg-accent-600" style={{ width: `${Math.round((r.fit_score || 0) * 100)}%` }} /></div>
                  <span className="font-mono">{Math.round((r.fit_score || 0) * 100)}%</span>
                </div>
              </div>
              <div className="mt-2 text-sm"><TextWithChips text={r.why || ""} /></div>
              <div className="mt-2 grid gap-1 text-xs">
                <div><span className="muted">Standards: </span><IdChips ids={r.standard_ids} /></div>
                <div><span className="muted">Reuse APIs: </span><IdChips ids={r.reuse_api_ids} /></div>
                {r.components && <div><span className="muted">Components: </span>{r.components.join(" · ")}</div>}
              </div>
              <div className="mt-2 rounded border border-gray-100 bg-gray-50 p-2">
                <div className="label mb-1">Starter diagram</div>
                <Mermaid chart={r.starter_diagram_mermaid} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </AgentPanel>
  );
}
