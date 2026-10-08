import { useMemo, useState } from "react";
import { EvidenceChip } from "../components/Evidence";
import { PageHeader } from "../components/Layout";
import { Badge, Card, Empty, ErrorBox, Loading, Toggle } from "../components/ui";
import { useApi, useApp } from "../state/AppState";

const ID_RE = /^[A-Z]{2,5}-[A-Za-z0-9-]{2,14}$/;
const HIDE_COLS = new Set(["tenant_id"]);
const MAX_ROWS = 50;

function Cell({ k, v }: { k: string; v: any }) {
  if (v === null || v === undefined || v === "") return <span className="text-gray-300">—</span>;
  if (typeof v === "boolean") return <span className={v ? "text-gray-900" : "muted"}>{String(v)}</span>;
  if (Array.isArray(v) && v.every((x) => typeof x === "string" && ID_RE.test(x))) return <span className="font-mono text-[11px]">{v.join(", ")}</span>;
  if (typeof v === "object") return <span className="font-mono text-[11px] text-gray-600">{JSON.stringify(v)}</span>;
  const s = String(v);
  if (k === "id" || k.endsWith("_id") || ID_RE.test(s)) return <span className="font-mono text-[11px]">{s}</span>;
  if (typeof v === "number") return <span className="tabular-nums">{v.toLocaleString()}</span>;
  return <span title={s.length > 80 ? s : undefined}>{s.length > 80 ? s.slice(0, 80) + "…" : s}</span>;
}

function SourceDetail({ source, planted }: { source: string; planted: boolean }) {
  const { data, loading, error } = useApi<any>(`/raw/${source}`, { planted: planted || undefined }, [source, planted]);
  const rows: any[] = (data?.rows || []).slice(0, MAX_ROWS);
  const cols = useMemo(() => {
    const seen: string[] = [];
    rows.forEach((r) => Object.keys(r).forEach((k) => !HIDE_COLS.has(k) && !seen.includes(k) && seen.push(k)));
    return seen;
  }, [rows]);
  const notes: any[] = Array.isArray(data?.planted) ? data.planted : [];

  return (
    <div className="space-y-4">
      {planted && data && (
        <Card title={<>Planted anomalies <Badge color="purple">demo narration</Badge></>} subtitle="Ground truth seeded into this source by the synthetic data generator — what the agents are expected to find.">
          {notes.length === 0 ? <Empty>No anomalies planted in this source.</Empty> : (
            <div className="-m-4 max-h-80 overflow-auto">
              <table className="tbl">
                <thead><tr><th>Id</th><th>Anomaly</th><th>Subject</th><th>Details</th></tr></thead>
                <tbody>
                  {notes.map((n) => (
                    <tr key={n.id}>
                      <td className="font-mono text-[11px] muted">{n.id}</td>
                      <td><Badge color="purple">{String(n.anomaly).replace(/_/g, " ")}</Badge></td>
                      <td>{n.subject_id ? (ID_RE.test(n.subject_id) && !n.subject_id.startsWith("CAND") ? <EvidenceChip id={n.subject_id} /> : <span className="font-mono text-[11px]">{n.subject_id}</span>) : "—"}</td>
                      <td className="font-mono text-[11px] text-gray-600">{n.details ? Object.entries(n.details).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ") : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
      <Card
        title={<>Sample rows · {data?.label || source}</>}
        subtitle={data ? <>showing {rows.length} of {data.total?.toLocaleString()} rows as ingested (unmodified){data.description ? ` · ${data.description}` : ""}</> : undefined}
      >
        <ErrorBox error={error} />
        {loading && !data && <Loading />}
        {data && rows.length === 0 && <Empty>No rows.</Empty>}
        {rows.length > 0 && (
          <div className="-m-4 max-h-[36rem] overflow-auto">
            <table className="tbl">
              <thead className="sticky top-0 z-[1]">
                <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.id || i}>
                    {cols.map((c) => (
                      <td key={c} className="whitespace-nowrap text-xs">
                        {c === "id" ? <EvidenceChip id={r.id} /> : <Cell k={c} v={r[c]} />}
                      </td>
                    ))}
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

export default function IngestedSources() {
  const { tenantName } = useApp();
  const [planted, setPlanted] = useState(false);
  const { data, loading, error } = useApi<any[]>("/raw", { planted: planted || undefined }, [planted]);
  const [sel, setSel] = useState<string | null>(null);
  const sources = data || [];
  const active = sel && sources.some((s) => s.source === sel) ? sel : sources[0]?.source || null;
  const totalRows = sources.reduce((s, x) => s + (x.rows || 0), 0);

  return (
    <div>
      <PageHeader
        title="Ingested sources"
        subtitle={<>What the office ingested for {tenantName}: {sources.length} source systems, {totalRows.toLocaleString()} raw rows. Agents reconcile these into the knowledge graph; nothing here is cleaned up by hand.</>}
        actions={<Toggle checked={planted} onChange={setPlanted} label="show what we planted" />}
      />
      <ErrorBox error={error} />
      {loading && !data && <Loading />}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {sources.map((s) => {
          const plantedTotal = s.planted ? Object.values(s.planted as Record<string, number>).reduce((a: number, b: number) => a + b, 0) : 0;
          return (
            <div
              key={s.source}
              role="button"
              tabIndex={0}
              onClick={() => setSel(s.source)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setSel(s.source)}
              data-testid={`source-${s.source}`}
              className={`card cursor-pointer px-3 py-2.5 text-left hover:border-accent-500 ${active === s.source ? "border-accent-600 ring-1 ring-accent-100" : ""}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-semibold text-gray-900">{s.label}</div>
                <span className="shrink-0 text-sm font-semibold tabular-nums text-gray-900">{s.rows.toLocaleString()}</span>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[11px] muted">
                <span>table</span><span className="font-mono">{s.table}</span>
              </div>
              <div className="mt-1 text-xs text-gray-600">{s.description}</div>
              {planted && s.planted && (
                <div className="mt-2 flex flex-wrap gap-1 border-t border-gray-100 pt-2">
                  {plantedTotal === 0 && <span className="text-[11px] muted">nothing planted</span>}
                  {Object.entries(s.planted as Record<string, number>).map(([k, v]) => (
                    <Badge key={k} color="purple">{k.replace(/_/g, " ")} × {v}</Badge>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {active && <SourceDetail source={active} planted={planted} />}
    </div>
  );
}
