import { Fragment, ReactNode } from "react";
import { Link } from "react-router-dom";
import { Evidence } from "../api/client";
import { useApi, useApp } from "../state/AppState";
import { Badge, ConfidenceBadge, Loading } from "./ui";

/** `[INV-01822]`-style chip; click opens the evidence drawer with the raw record and which agents used it. */
export function EvidenceChip({ id, label, title }: { id: string; label?: string; title?: string | null }) {
  const { openEvidence } = useApp();
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        openEvidence(id);
      }}
      title={title || "Open source record"}
      className="inline-flex items-center rounded border border-accent-100 bg-accent-50 px-1 py-px font-mono text-[11px] text-accent-700 hover:border-accent-500 hover:bg-accent-100 mr-1 mb-0.5"
    >
      [{label || id}]
    </button>
  );
}

export function EvidenceList({ refs, max = 6 }: { refs?: Evidence[] | null; max?: number }) {
  if (!refs || refs.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap">
      {refs.slice(0, max).map((r, i) => (
        <EvidenceChip key={`${r.record_id}-${i}`} id={r.record_id} title={r.excerpt} />
      ))}
      {refs.length > max && <span className="text-[11px] muted self-center">+{refs.length - max}</span>}
    </span>
  );
}

const ID_RE = /\[([A-Z]{2,5}-[A-Za-z0-9-]{2,14})\]/g;

/** Replace [ID] tokens in plain text with evidence chips. */
export function TextWithChips({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(ID_RE);
  while ((m = re.exec(text))) {
    parts.push(text.slice(last, m.index));
    parts.push(<EvidenceChip key={m.index} id={m[1]} />);
    last = m.index + m[0].length;
  }
  parts.push(text.slice(last));
  return <>{parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)}</>;
}

function Value({ v }: { v: any }) {
  if (v === null || v === undefined || v === "") return <span className="muted">—</span>;
  if (typeof v === "boolean") return <span>{v ? "true" : "false"}</span>;
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x === "string" && /^[A-Z]{2,5}-[A-Za-z0-9-]+$/.test(x))) return <>{v.map((x) => <EvidenceChip key={x} id={x} />)}</>;
    return <span className="font-mono text-xs break-all">{JSON.stringify(v)}</span>;
  }
  if (typeof v === "object") return <span className="font-mono text-xs break-all">{JSON.stringify(v)}</span>;
  const s = String(v);
  if (/^[A-Z]{2,5}-[A-Za-z0-9-]+$/.test(s) && s.length < 20) return <EvidenceChip id={s} />;
  if (s.length > 400) return <span className="whitespace-pre-wrap text-xs">{s.slice(0, 1200)}…</span>;
  return <span className="break-words">{s}</span>;
}

export function EvidenceDrawer() {
  const { evidenceId, openEvidence } = useApp();
  const { data, loading, error } = useApi<any>(evidenceId ? `/records/${evidenceId}` : null, undefined, [evidenceId]);
  if (!evidenceId) return null;
  const rec = data?.record || {};
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/20" onClick={() => openEvidence(null)}>
      <aside className="h-full w-full max-w-xl overflow-auto bg-white shadow-2xl border-l border-gray-200" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
          <div>
            <div className="label">Source record</div>
            <div className="font-mono text-sm font-semibold">{evidenceId}</div>
          </div>
          <button className="btn btn-sm" onClick={() => openEvidence(null)}>Close</button>
        </div>
        <div className="p-4 space-y-4">
          {loading && <Loading />}
          {error && <div className="text-sm text-red-700">{error}</div>}
          {data && (
            <>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge color="blue">table: {data.table}</Badge>
                {rec.source_system && <Badge>source system: {rec.source_system}</Badge>}
                {data.kg_node && <Badge>graph: {data.kg_node.type} · {data.kg_node.status}</Badge>}
                {data.kg_node && <ConfidenceBadge value={data.kg_node.confidence} />}
              </div>
              <table className="tbl">
                <tbody>
                  {Object.entries(rec)
                    .filter(([k]) => !["tenant_id", "props_json", "source_refs_json"].includes(k))
                    .map(([k, v]) => (
                      <tr key={k}>
                        <td className="w-40 text-xs font-medium text-gray-500">{k}</td>
                        <td><Value v={v} /></td>
                      </tr>
                    ))}
                  {data.table === "kg_nodes" &&
                    Object.entries(rec.props_json || {}).map(([k, v]) => (
                      <tr key={`p-${k}`}>
                        <td className="w-40 text-xs font-medium text-gray-500">{k}</td>
                        <td><Value v={v} /></td>
                      </tr>
                    ))}
                </tbody>
              </table>
              {data.kg_node && data.table !== "kg_nodes" && Object.keys(data.kg_node.props_json || {}).length > 0 && (
                <div>
                  <div className="label mb-1">Knowledge-graph properties</div>
                  <div className="font-mono text-xs bg-gray-50 border border-gray-200 rounded p-2 break-all">
                    {JSON.stringify(data.kg_node.props_json)}
                  </div>
                </div>
              )}
              <div>
                <div className="label mb-1">Used by agents</div>
                {data.used_by.length === 0 && <div className="text-sm muted">Not cited by any agent run yet.</div>}
                <ul className="space-y-1">
                  {data.used_by.map((u: any) => (
                    <li key={u.run_id} className="text-sm">
                      <span className="font-mono text-xs">{u.agent_id}</span> <span className="muted">· run</span>{" "}
                      <span className="font-mono text-xs">{u.run_id}</span> <span className="muted text-xs">{u.started_at}</span>
                    </li>
                  ))}
                </ul>
              </div>
              {data.kg_node && (
                <Link className="btn btn-sm" to={`/graph?focus=${evidenceId}`} onClick={() => openEvidence(null)}>
                  Show in graph explorer
                </Link>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
