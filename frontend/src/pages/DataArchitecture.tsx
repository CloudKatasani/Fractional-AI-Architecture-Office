import { useEffect, useMemo, useState } from "react";
import { AgentOutput, ApprovalRef } from "../api/client";
import { AgentPanel, ApprovalControls } from "../components/AgentPanel";
import { EvidenceList } from "../components/Evidence";
import { PageHeader } from "../components/Layout";
import { Mermaid } from "../components/Mermaid";
import { Badge, Card, Empty, ErrorBox, Loading, SeverityBadge, Stat, Tabs, Toggle, useTab } from "../components/ui";
import { EvidencePackButton } from "../components/ai/EvidencePackButton";
import { IdChip, mermaidMinWidth } from "../components/ai/shared";
import { ROLE_LABELS, useApi, useApp } from "../state/AppState";

interface Dataset {
  id: string;
  name: string;
  domain: string;
  owner_user_id: string | null;
  owner?: string | null;
  classification: string;
  system_app_id: string | null;
  system?: string | null;
  pii: boolean;
  retention_days: number | null;
  quality_score: number;
  has_contract: boolean;
  environment: string;
  region: string;
  zone: string;
  layer: string;
  tags: string[];
}

const DEFAULT_DS: Record<string, string> = { northgrid: "Customer Usage Daily", meridian: "Subscriber Usage Daily" };
const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const CLASS_COLOR: Record<string, string> = { restricted: "red", confidential: "amber", internal: "gray", public: "green" };

function setUrlParam(key: string, v: string) {
  const p = new URLSearchParams(window.location.search);
  p.set(key, v);
  window.history.replaceState(null, "", `${window.location.pathname}?${p.toString()}`);
}

function Quality({ v }: { v?: number | null }) {
  if (v === undefined || v === null) return <span className="muted text-xs">—</span>;
  const cls = v < 0.6 ? "text-red-700 font-semibold" : v < 0.8 ? "text-amber-700" : "text-gray-800";
  return <span className={`tabular-nums text-xs ${cls}`}>{v.toFixed(2)}</span>;
}

// ---- Lineage ------------------------------------------------------------------------------------------------------
function DatasetPicker({ datasets, value, onChange }: { datasets: Dataset[]; value: string; onChange: (id: string) => void }) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    const xs = s ? datasets.filter((d) => `${d.id} ${d.name} ${d.domain} ${d.layer}`.toLowerCase().includes(s)) : datasets;
    // keep the current selection visible in the select even when filtered out
    return xs.some((d) => d.id === value) ? xs : [...datasets.filter((d) => d.id === value), ...xs];
  }, [datasets, q, value]);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col gap-1">
        <span className="label">Search datasets</span>
        <input className="input w-56" placeholder="name, id, domain…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="dataset-search" />
      </label>
      <label className="flex flex-col gap-1">
        <span className="label">Dataset ({filtered.length})</span>
        <select className="input min-w-[24rem]" value={value} onChange={(e) => onChange(e.target.value)} data-testid="dataset-select">
          {filtered.map((d) => (
            <option key={d.id} value={d.id}>{d.id} · {d.name} ({d.domain}, {d.layer})</option>
          ))}
        </select>
      </label>
    </div>
  );
}

const GROUP_LABELS: Record<string, string> = {
  systems: "Systems of record", datasets: "Datasets", pipelines: "Pipelines", bi_assets: "BI assets", ai: "AI use cases & assets",
};

function LineageGroups({ side, names }: { side: Record<string, any>; names: Record<string, { name: string; type: string }> }) {
  const groups = Object.entries(side).filter(([k, v]) => k !== "edges" && k !== "root_id" && Array.isArray(v));
  const total = groups.reduce((s, [, v]) => s + (v as string[]).length, 0);
  if (total === 0) return <div className="text-sm muted">Nothing.</div>;
  return (
    <div className="space-y-3">
      {groups.filter(([, v]) => (v as string[]).length > 0).map(([k, ids]) => (
        <div key={k}>
          <div className="label mb-1">{GROUP_LABELS[k] || k} ({(ids as string[]).length})</div>
          <ul className="grid max-h-60 gap-x-4 gap-y-0.5 overflow-auto text-sm md:grid-cols-2">
            {(ids as string[]).map((id) => (
              <li key={id} className="flex min-w-0 items-center gap-1">
                <IdChip id={id} />
                <span className="truncate" title={names[id]?.name}>{names[id]?.name || ""}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function LineageTab({ datasets }: { datasets: Dataset[] }) {
  const { tenant } = useApp();
  const [dsId, setDsId] = useState<string>(() => {
    const p = new URLSearchParams(window.location.search).get("dataset");
    return p || datasets.find((d) => d.name === DEFAULT_DS[tenant])?.id || datasets[0]?.id || "";
  });
  const select = (id: string) => { setDsId(id); setUrlParam("dataset", id); };
  const { data: lin, loading, error } = useApi<any>(dsId ? "/kg/lineage" : null, { dataset_id: dsId });
  // latest lineage_mapper run for this dataset (GET /runs → /runs/{id}); the agent defaults to the tenant's showcase dataset
  const { data: runs } = useApi<any[]>("/runs", { agent_id: "dai.lineage_mapper", limit: 200 });
  const defaultId = datasets.find((d) => d.name === DEFAULT_DS[tenant])?.id;
  const runId = useMemo(
    () => (runs || []).find((r) => r.status === "completed" && ((r.input_json || {}).dataset_id || defaultId) === dsId)?.id || null,
    [runs, dsId, defaultId],
  );
  const { data: runRow } = useApi<any>(runId ? `/runs/${runId}` : null, undefined, [runId]);
  const [fresh, setFresh] = useState<Record<string, AgentOutput>>({});
  const out: AgentOutput | null = fresh[dsId] || (runRow?.id === runId ? runRow?.output_json : null) || null;
  const finding = out?.findings?.[0];
  const ds = datasets.find((d) => d.id === dsId);
  const names = { ...(lin?.names || {}), ...(ds ? { [ds.id]: { name: ds.name, type: "Dataset" } } : {}) };

  return (
    <div className="space-y-4">
      <DatasetPicker datasets={datasets} value={dsId} onChange={select} />
      {ds && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <IdChip id={ds.id} /> <b>{ds.name}</b>
          <Badge color={CLASS_COLOR[ds.classification] || "gray"}>{ds.classification}</Badge>
          {ds.pii && <Badge color="amber">PII</Badge>}
          <Badge>{ds.layer}</Badge>
          <span className="text-xs muted">{ds.domain} · owner {ds.owner || "none"} · {ds.system || ds.system_app_id || "no system"} · quality</span>
          <Quality v={ds.quality_score} />
        </div>
      )}
      <ErrorBox error={error} />
      {loading && !lin && <Loading />}
      {lin && (
        <>
          <Card title="Lineage graph" subtitle="from the knowledge graph — systems → pipelines → datasets → BI / AI consumers" className="min-w-0">
            <div className="max-h-[36rem] overflow-auto">
              <div style={{ minWidth: mermaidMinWidth(lin.mermaid) }}>
                <Mermaid chart={lin.mermaid} />
              </div>
            </div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Upstream" subtitle="where the data comes from">
              <LineageGroups side={lin.upstream} names={names} />
            </Card>
            <Card title="Downstream" subtitle="who consumes it">
              <LineageGroups side={lin.downstream} names={names} />
            </Card>
          </div>
        </>
      )}
      <AgentPanel
        key={dsId}
        agentId="dai.lineage_mapper"
        agentName="Lineage Mapper"
        run={out}
        params={{ dataset_id: dsId }}
        onRan={(o) => setFresh((f) => ({ ...f, [dsId]: o }))}
      >
        {finding ? (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="muted">{finding.upstream?.length || 0} upstream · {finding.downstream?.length || 0} downstream nodes</span>
              <EvidenceList refs={finding.source_refs} />
            </div>
            <div className="label">Quality flags — AI consuming data with quality &lt; 0.6 ({finding.quality_flags?.length || 0})</div>
            {finding.quality_flags?.length ? (
              <table className="tbl">
                <thead><tr><th>Dataset</th><th>Quality</th><th>Used by AI asset</th></tr></thead>
                <tbody>
                  {finding.quality_flags.map((f: any, i: number) => (
                    <tr key={i}>
                      <td><IdChip id={f.dataset_id} /> {f.dataset}</td>
                      <td><Quality v={f.quality_score} /></td>
                      <td><IdChip id={f.ai_asset_id} /> {f.ai_asset}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-sm muted">No low-quality inputs feeding AI.</div>
            )}
          </div>
        ) : (
          <div className="text-sm muted">Run the Lineage Mapper for this dataset to get its lineage report and quality flags.</div>
        )}
      </AgentPanel>
    </div>
  );
}

// ---- Policy findings ----------------------------------------------------------------------------------------------
function PoliciesTab() {
  const { data, loading, error } = useApi<any>("/data/policy-findings");
  const [pol, setPol] = useState("");
  const [sev, setSev] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const items: any[] = [...data.items].sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9) || a.policy_id.localeCompare(b.policy_id));
  const shown = items.filter((f) => (!pol || f.policy_id === pol) && (!sev || f.severity === sev) && (!openOnly || !f.approval || f.approval.status === "pending"));
  const bySev = ["critical", "high", "medium", "low"].map((s) => ({ s, n: items.filter((f) => f.severity === s).length }));
  const policies: any[] = data.policies || [];
  const pending = items.filter((f) => f.approval?.status === "pending").length;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {bySev.map(({ s, n }) => (
          <Stat key={s} label={s} value={<span className={s === "critical" ? "text-red-700" : ""}>{n}</span>} onClick={() => setSev(sev === s ? "" : s)} />
        ))}
        <Stat label="Fixes awaiting decision" value={pending} sub="data governance lead" />
      </div>
      <AgentPanel agentId="dai.governance_policy_checker" run={data.run}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <select className="input" value={pol} onChange={(e) => setPol(e.target.value)} data-testid="policy-filter">
            <option value="">All policies</option>
            {policies.map((p) => (
              <option key={p.id} value={p.id}>{p.id} · {p.title} ({items.filter((f) => f.policy_id === p.id).length})</option>
            ))}
          </select>
          <select className="input" value={sev} onChange={(e) => setSev(e.target.value)} data-testid="severity-filter">
            <option value="">All severities</option>
            {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <Toggle checked={openOnly} onChange={setOpenOnly} label="open only" />
          <span className="text-xs muted ml-auto">{shown.length} of {items.length} findings</span>
        </div>
        <div className="overflow-x-auto">
          <table className="tbl" data-testid="policy-table">
            <thead>
              <tr><th>Sev.</th><th>Policy</th><th>Subject</th><th>Fix</th><th>Evidence</th><th>Decision</th></tr>
            </thead>
            <tbody>
              {shown.map((f, i) => (
                <tr key={`${f.policy_id}-${f.subject_id}-${i}`} className={f.severity === "critical" ? "bg-red-50/50" : ""}>
                  <td><SeverityBadge severity={f.severity} /></td>
                  <td className="min-w-[14rem]">
                    <div className="flex items-start gap-1"><IdChip id={f.policy_id} /><span className="text-gray-900">{f.policy_title}</span></div>
                    <div className="text-[11px] muted">{f.regulation}</div>
                  </td>
                  <td className="min-w-[12rem]">
                    <div className="flex items-start gap-1"><IdChip id={f.subject_id} /><span className="break-words">{f.subject_name}</span></div>
                    <div className="text-[11px] muted">{f.subject_type}{f.check ? ` · ${f.check}` : ""}</div>
                  </td>
                  <td className="min-w-[14rem] text-xs text-gray-700">{f.fix}</td>
                  <td className="min-w-[9rem] max-w-[12rem]"><EvidenceList refs={f.source_refs} max={4} /></td>
                  <td className="min-w-[12rem] whitespace-nowrap">
                    {f.approval?.action_type && <div className="mb-0.5 font-mono text-[11px] text-gray-600">{f.approval.action_type.replace(/_/g, " ")}</div>}
                    <ApprovalControls approval={f.approval as ApprovalRef} compact />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {shown.length === 0 && <Empty>No findings match the filters.</Empty>}
      </AgentPanel>
    </div>
  );
}

// ---- Data products ------------------------------------------------------------------------------------------------
function ProductsTab() {
  const { users } = useApp();
  const { data, loading, error } = useApi<any>("/data/products");
  const [showYaml, setShowYaml] = useState<Record<string, boolean>>({});
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const items: any[] = data.items;
  return (
    <AgentPanel agentId="dai.data_product_designer" run={data.run}>
      {items.length === 0 && <Empty>No data products proposed (needs ≥3 datasets and ≥2 consuming teams per domain).</Empty>}
      <div className="grid gap-4 lg:grid-cols-2">
        {items.map((p) => {
          const owner = users.find((u) => u.id === p.owner_user_id);
          const key = p.target_id || p.domain;
          const open = showYaml[key] ?? true;
          return (
            <div key={key} className="card p-3" data-testid={`product-${key}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="font-semibold text-gray-900">{p.name}</div>
                  <div className="text-xs muted">
                    domain <b className="text-gray-700">{p.domain}</b> · <span className="font-mono">{p.target_id}</span>
                    {p.pii && <> · <Badge color="amber">PII</Badge></>}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <ApprovalControls approval={p.approval} compact />
                  <span className="text-[11px] muted">approve data contract · {ROLE_LABELS[p.approval?.approver_role] || "Data Governance Lead"}</span>
                </div>
              </div>
              <div className="mt-2 text-sm">
                <span className="label mr-1">Owner</span>
                {owner?.name || p.owner_user_id || "unassigned"} {p.owner_user_id && <IdChip id={p.owner_user_id} />}
              </div>
              <div className="mt-2">
                <div className="label mb-0.5">Datasets ({p.dataset_ids.length})</div>
                <div className="flex flex-wrap">{p.dataset_ids.map((d: string) => <IdChip key={d} id={d} />)}</div>
              </div>
              <div className="mt-2">
                <div className="label mb-0.5">Consumers ({p.consumers.length})</div>
                <div className="flex flex-wrap gap-1">{p.consumers.map((c: string) => <Badge key={c} color={c.startsWith("AI") ? "purple" : "gray"}>{c}</Badge>)}</div>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <span className="label">Evidence</span> <EvidenceList refs={p.source_refs} max={5} />
              </div>
              <div className="mt-2">
                <button className="text-xs text-accent-700 hover:underline" onClick={() => setShowYaml((s) => ({ ...s, [key]: !open }))}>
                  {open ? "Hide" : "Show"} data contract (YAML)
                </button>
                {open && <pre className="mt-1 max-h-56 overflow-auto rounded border border-gray-200 bg-gray-50 p-2 text-[11px] leading-snug">{p.contract_yaml}</pre>}
              </div>
            </div>
          );
        })}
      </div>
    </AgentPanel>
  );
}

// ---- Datasets catalogue -------------------------------------------------------------------------------------------
function CatalogueTab({ datasets }: { datasets: Dataset[] }) {
  const [q, setQ] = useState("");
  const [domain, setDomain] = useState("");
  const [layer, setLayer] = useState("");
  const [piiOnly, setPiiOnly] = useState(false);
  const domains = useMemo(() => Array.from(new Set(datasets.map((d) => d.domain))).sort(), [datasets]);
  const layers = useMemo(() => Array.from(new Set(datasets.map((d) => d.layer))).sort(), [datasets]);
  const s = q.trim().toLowerCase();
  const shown = datasets.filter(
    (d) =>
      (!s || `${d.id} ${d.name} ${d.owner || ""} ${d.system || ""}`.toLowerCase().includes(s)) &&
      (!domain || d.domain === domain) && (!layer || d.layer === layer) && (!piiOnly || d.pii),
  );
  return (
    <Card
      title={`Datasets catalogue (${shown.length} of ${datasets.length})`}
      subtitle="from the data catalog; click an id for the raw record"
      actions={
        <>
          <input className="input w-48 py-1" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input py-1" value={domain} onChange={(e) => setDomain(e.target.value)}>
            <option value="">All domains</option>
            {domains.map((d) => <option key={d}>{d}</option>)}
          </select>
          <select className="input py-1" value={layer} onChange={(e) => setLayer(e.target.value)}>
            <option value="">All layers</option>
            {layers.map((d) => <option key={d}>{d}</option>)}
          </select>
          <Toggle checked={piiOnly} onChange={setPiiOnly} label="PII only" />
        </>
      }
    >
      <div className="overflow-x-auto">
        <table className="tbl" data-testid="datasets-table">
          <thead>
            <tr>
              <th>Dataset</th><th>Domain</th><th>Layer</th><th>Class.</th><th>PII</th><th className="text-right">Retention</th>
              <th className="text-right">Quality</th><th>Owner</th><th>System</th><th>Region</th><th>Env</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((d) => (
              <tr key={d.id}>
                <td className="min-w-[14rem]"><div className="flex items-start gap-1"><IdChip id={d.id} /><span>{d.name}</span></div></td>
                <td className="text-xs">{d.domain}</td>
                <td className="text-xs">{d.layer}</td>
                <td><Badge color={CLASS_COLOR[d.classification] || "gray"}>{d.classification}</Badge></td>
                <td>{d.pii ? <Badge color="amber">PII</Badge> : <span className="text-xs muted">—</span>}</td>
                <td className={`text-right tabular-nums text-xs ${d.pii && !d.retention_days ? "text-red-700 font-semibold" : ""}`}>
                  {d.retention_days ? `${d.retention_days} d` : "none"}
                </td>
                <td className="text-right"><Quality v={d.quality_score} /></td>
                <td className="text-xs whitespace-nowrap">{d.owner || <span className="text-red-700">no owner</span>}</td>
                <td className="text-xs">{d.system || <span className="muted">—</span>}</td>
                <td className="text-xs whitespace-nowrap">{d.region}{d.zone ? ` · ${d.zone}` : ""}</td>
                <td className="text-xs">{d.environment !== "prod" ? <Badge color="amber">{d.environment}</Badge> : d.environment}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length === 0 && <Empty>No datasets match.</Empty>}
    </Card>
  );
}

// ---- Page ---------------------------------------------------------------------------------------------------------
export default function DataArchitecture() {
  const [tab, setTabState] = useTab("lineage", "tab");
  const setTab = (t: string) => { setTabState(t); setUrlParam("tab", t); };
  const { data, loading, error } = useApi<{ items: Dataset[] }>("/data/datasets");
  const datasets = data?.items || [];
  const pii = datasets.filter((d) => d.pii).length;
  const noOwner = datasets.filter((d) => !d.owner_user_id).length;

  useEffect(() => {
    // tolerate old links (?tab=policy)
    if (tab === "policy") setTab("policies");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Data Architecture"
        subtitle={data ? `${datasets.length} datasets · ${pii} with personal data · ${noOwner} without owner — lineage, policy findings and data products, each traced to source records.` : "Lineage, policy findings and data products"}
        actions={<EvidencePackButton />}
      />
      <Tabs
        tabs={[
          { id: "lineage", label: "Lineage explorer" },
          { id: "policies", label: "Policy findings" },
          { id: "products", label: "Data products" },
          { id: "datasets", label: "Datasets catalogue" },
        ]}
        active={tab}
        onChange={setTab}
      />
      {(tab === "lineage" || tab === "datasets") && (
        <>
          <ErrorBox error={error} />
          {loading && !data && <Loading />}
        </>
      )}
      {tab === "lineage" && data && <LineageTab datasets={datasets} />}
      {tab === "policies" && <PoliciesTab />}
      {tab === "products" && <ProductsTab />}
      {tab === "datasets" && data && <CatalogueTab datasets={datasets} />}
    </div>
  );
}
