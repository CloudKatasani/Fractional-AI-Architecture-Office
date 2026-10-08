import { Children, cloneElement, isValidElement, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { RunMeta } from "../../api/client";
import { useApi } from "../../state/AppState";
import { EvidenceChip, TextWithChips } from "../Evidence";
import { Badge } from "../ui";

/** Row of evidence chips for plain id arrays, optionally labelled with names. */
export function IdChips({ ids, names, max = 12 }: { ids?: (string | null | undefined)[] | null; names?: (string | null | undefined)[] | null; max?: number }) {
  const xs = (ids || []).filter(Boolean) as string[];
  if (xs.length === 0) return <span className="text-xs muted">—</span>;
  return (
    <span className="inline-flex flex-wrap items-center">
      {xs.slice(0, max).map((id, i) => (
        <EvidenceChip key={`${id}-${i}`} id={id} title={names?.[i] || undefined} />
      ))}
      {xs.length > max && <span className="text-[11px] muted">+{xs.length - max}</span>}
    </span>
  );
}

/** Chip followed by a human name: [APP-0021] OutageWorks OMS */
export function NamedChip({ id, name }: { id?: string | null; name?: string | null }) {
  if (!id) return <span className="muted text-xs">—</span>;
  return (
    <span className="inline-flex items-center">
      <EvidenceChip id={id} title={name} />
      {name && <span className="text-sm">{name}</span>}
    </span>
  );
}

const VERDICT: Record<string, { color: string; label: string }> = {
  pass: { color: "green", label: "pass" },
  pass_with_conditions: { color: "amber", label: "pass with conditions" },
  changes_required: { color: "red", label: "changes required" },
};
export function VerdictBadge({ verdict }: { verdict?: string | null }) {
  if (!verdict) return <span className="text-xs muted">not reviewed</span>;
  const v = VERDICT[verdict] || { color: "gray", label: verdict };
  return <Badge color={v.color}>{v.label}</Badge>;
}

/** Keep a query-string parameter in sync without a router navigation. */
export function setUrlParam(key: string, value: string | null | undefined) {
  const u = new URL(window.location.href);
  if (value) u.searchParams.set(key, value);
  else u.searchParams.delete(key);
  window.history.replaceState(window.history.state, "", u.pathname + u.search);
}

export function getUrlParam(key: string): string | null {
  return new URLSearchParams(window.location.search).get(key);
}

/** Look up a run's metadata (for panels whose endpoint only returns a run id). */
export function useRunMeta(agentId: string, runId?: string | null, summary?: string): RunMeta | null {
  const { data } = useApi<any[]>(runId ? "/runs" : null, { agent_id: agentId, limit: 100 }, [runId]);
  if (!runId) return null;
  const r = (data || []).find((x) => x.id === runId);
  if (!r) return null;
  return {
    run_id: r.id,
    agent_id: r.agent_id,
    agent_name: "",
    summary: summary || r.summary,
    started_at: r.started_at,
    duration_ms: r.duration_ms ?? 0,
    mode: (r.autonomy_level ?? 1) >= 2 ? "propose" : "observe",
    autonomy_level: r.autonomy_level ?? 1,
    llm_mode: r.llm_mode || "mock",
    confidence: 0,
    cost: r.cost_json || null,
    approvals_created: [],
    flagged: [],
  };
}

// ---- Markdown with inline highlights -------------------------------------------------------------

export interface Highlight {
  text: string;
  label: string;
  severity?: string;
}

function highlightString(s: string, hs: Highlight[], keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = s;
  let k = 0;
  // repeatedly find the earliest matching excerpt
  for (;;) {
    let best: { idx: number; h: Highlight } | null = null;
    for (const h of hs) {
      if (!h.text) continue;
      const idx = rest.indexOf(h.text);
      if (idx >= 0 && (!best || idx < best.idx)) best = { idx, h };
    }
    if (!best) break;
    if (best.idx > 0) out.push(<TextWithChips key={`${keyBase}-t${k++}`} text={rest.slice(0, best.idx)} />);
    const red = best.h.severity === "high" || best.h.severity === "critical";
    out.push(
      <mark
        key={`${keyBase}-m${k++}`}
        className={`rounded px-0.5 ${red ? "bg-red-100 text-red-900 ring-1 ring-red-200" : "bg-yellow-100 text-yellow-900 ring-1 ring-yellow-200"}`}
        title={`${best.h.label} (${best.h.severity || ""})`}
      >
        {best.h.text}
        <span className="ml-1 align-middle"><EvidenceChip id={best.h.label} /></span>
      </mark>,
    );
    rest = rest.slice(best.idx + best.h.text.length);
  }
  if (rest) out.push(<TextWithChips key={`${keyBase}-t${k++}`} text={rest} />);
  return out;
}

function mark(children: ReactNode, hs: Highlight[], base = "h"): ReactNode {
  return Children.map(children, (c, i) => {
    if (typeof c === "string") return <>{highlightString(c, hs, `${base}${i}`)}</>;
    if (isValidElement(c) && (c.props as any)?.children) return cloneElement(c as any, {}, mark((c.props as any).children, hs, `${base}${i}-`));
    return c;
  });
}

/** Markdown renderer that wraps given excerpt strings in a highlight with the standard id chip. */
export function HighlightedMarkdown({ text, highlights }: { text?: string | null; highlights: Highlight[] }) {
  if (!text) return null;
  return (
    <div className="prose-sm-custom text-sm">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p>{mark(children, highlights)}</p>,
          li: ({ children }) => <li>{mark(children, highlights)}</li>,
          td: ({ children }) => <td>{mark(children, highlights)}</td>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

/** Small "label: value" item for detail panels. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="mt-0.5 text-sm">{children}</div>
    </div>
  );
}
