import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ForceGraph2D, { ForceGraphMethods } from "react-force-graph-2d";
import { api } from "../api/client";
import { getUrlParam, setUrlParam } from "../components/arch/common";
import { EvidenceChip } from "../components/Evidence";
import { PageHeader } from "../components/Layout";
import { Badge, ConfidenceBadge, ErrorBox, Loading } from "../components/ui";
import { useApi, useApp } from "../state/AppState";

const PALETTE: Record<string, string> = {
  Application: "#1f5bd6",
  Capability: "#7c3aed",
  Dataset: "#0d9488",
  AIUseCase: "#db2777",
  AIAsset: "#be185d",
  Goal: "#ea580c",
  Project: "#ca8a04",
  Person: "#475569",
  Team: "#64748b",
  Vendor: "#92400e",
  Contract: "#a16207",
  API: "#0284c7",
  Integration: "#0891b2",
  Standard: "#4d7c0f",
  Pattern: "#65a30d",
  Regulation: "#b91c1c",
  Policy: "#dc2626",
  Document: "#78716c",
  ConfigItem: "#94a3b8",
  Repo: "#334155",
  CloudResource: "#38bdf8",
  Pipeline: "#14b8a6",
  BIAsset: "#2dd4bf",
  ADR: "#6d28d9",
  Design: "#8b5cf6",
  Decision: "#a855f7",
};
const DEFAULT_TYPES = ["Application", "Capability", "Dataset", "AIUseCase", "Goal"];
const color = (t: string) => PALETTE[t] || "#9ca3af";

interface GNode { id: string; name: string; type: string; confidence: number; status: string; deg?: number; x?: number; y?: number }
interface GLink { id: string; source: any; target: any; type: string; status: string }

export default function GraphExplorer() {
  const { openEvidence } = useApp();
  const nav = useNavigate();
  const { data: stats } = useApi<any>("/kg/stats");
  const [types, setTypes] = useState<string[]>(DEFAULT_TYPES);
  const [focus, setFocusState] = useState<string | null>(getUrlParam("focus"));
  const [depth, setDepth] = useState(1);
  const [sel, setSel] = useState<string | null>(getUrlParam("focus"));
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[]>([]);
  const [showLabels, setShowLabels] = useState(true);
  const [filterInFocus, setFilterInFocus] = useState(false);
  const params = focus ? { focus, depth } : { types: types.join(","), limit: 600 };
  const { data, loading, error } = useApi<{ nodes: GNode[]; links: GLink[] }>("/kg/graph", params, [focus, depth, types.join(",")]);

  const setFocus = (id: string | null) => {
    setFocusState(id);
    setUrlParam("focus", id);
    if (id) setSel(id);
  };

  // container size
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height) }));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  // search
  useEffect(() => {
    if (q.trim().length < 2) {
      setHits([]);
      return;
    }
    const t = window.setTimeout(() => {
      api.get<any[]>("/kg/nodes", { q: q.trim(), limit: 20 }).then((r) => setHits(Array.isArray(r) ? r : (r as any).items || [])).catch(() => setHits([]));
    }, 200);
    return () => window.clearTimeout(t);
  }, [q]);

  const graph = useMemo(() => {
    if (!data) return { nodes: [] as GNode[], links: [] as GLink[] };
    let nodes = data.nodes.map((n) => ({ ...n }));
    if (focus && filterInFocus) nodes = nodes.filter((n) => n.id === focus || types.includes(n.type));
    const ids = new Set(nodes.map((n) => n.id));
    const links = data.links
      .map((l) => ({ ...l, source: typeof l.source === "object" ? l.source.id : l.source, target: typeof l.target === "object" ? l.target.id : l.target }))
      .filter((l) => ids.has(l.source) && ids.has(l.target));
    const deg: Record<string, number> = {};
    links.forEach((l) => {
      deg[l.source] = (deg[l.source] || 0) + 1;
      deg[l.target] = (deg[l.target] || 0) + 1;
    });
    nodes.forEach((n) => (n.deg = deg[n.id] || 0));
    return { nodes, links };
  }, [data, focus, types, filterInFocus]);

  const fg = useRef<ForceGraphMethods<any, any>>();
  useEffect(() => {
    const g = fg.current as any;
    if (g) {
      g.d3Force("charge")?.strength(focus ? -140 : -40);
      g.d3Force("link")?.distance(focus ? 60 : 30);
      g.d3ReheatSimulation?.();
    }
    const t = window.setTimeout(() => {
      const f = fg.current;
      if (!f) return;
      f.zoomToFit(400, 50);
      window.setTimeout(() => {
        if (f.zoom() > 2.2) f.zoom(2.2, 300);
      }, 450);
    }, 1400);
    return () => window.clearTimeout(t);
  }, [graph]);

  const neighbors = useMemo(() => {
    const s = new Set<string>();
    if (!sel) return s;
    graph.links.forEach((l: any) => {
      const a = typeof l.source === "object" ? l.source.id : l.source;
      const b = typeof l.target === "object" ? l.target.id : l.target;
      if (a === sel) s.add(b);
      if (b === sel) s.add(a);
    });
    return s;
  }, [graph, sel]);

  const nodeTypes: [string, number][] = stats ? Object.entries(stats.node_types as Record<string, number>).sort((a, b) => b[1] - a[1]) : [];
  const toggleType = (t: string) => setTypes((ts) => (ts.includes(t) ? ts.filter((x) => x !== t) : [...ts, t]));
  const presentTypes = new Set(graph.nodes.map((n) => n.type));

  return (
    <div className="[&_button]:whitespace-nowrap">
      <PageHeader
        title="Graph Explorer"
        subtitle={stats ? `Knowledge graph: ${stats.nodes} nodes · ${stats.edges} edges · ${stats.drafts} draft (agent-proposed) edges` : "Knowledge graph"}
        actions={
          <div className="relative">
            <input className="input w-80" placeholder="Search nodes by name or id…" value={q} onChange={(e) => setQ(e.target.value)} />
            {hits.length > 0 && (
              <div className="absolute right-0 z-30 mt-1 max-h-80 w-[28rem] overflow-auto rounded-md border border-gray-200 bg-white shadow-lg">
                {hits.map((h) => (
                  <button
                    key={h.id}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-gray-50"
                    onClick={() => {
                      setFocus(h.id);
                      setQ("");
                      setHits([]);
                    }}
                  >
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color(h.type) }} />
                    <span className="font-mono text-xs">{h.id}</span>
                    <span className="truncate">{h.name}</span>
                    <span className="ml-auto text-[11px] muted">{h.type}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        }
      />
      <div className="flex gap-3" style={{ height: "calc(100vh - 170px)", minHeight: 480 }}>
        <aside className="card w-56 shrink-0 overflow-auto p-3 text-sm">
          {focus ? (
            <div className="mb-3 rounded border border-accent-100 bg-accent-50 p-2">
              <div className="label">Focused on</div>
              <div className="mt-1"><EvidenceChip id={focus} /></div>
              <div className="mt-2 flex items-center gap-2 text-xs">
                <span className="muted">Depth</span>
                {[1, 2].map((d) => (
                  <button key={d} className={`btn btn-sm ${depth === d ? "!border-accent-500 !text-accent-700" : ""}`} onClick={() => setDepth(d)}>{d}</button>
                ))}
              </div>
              <button className="btn btn-sm mt-2 w-full justify-center" onClick={() => setFocus(null)}>Show whole graph</button>
            </div>
          ) : (
            <div className="mb-2 text-xs muted">Showing up to 600 nodes of the selected types.</div>
          )}
          <div className="mb-1 flex items-center justify-between">
            <span className="label">Node types</span>
            <span className="flex gap-1">
              <button className="text-[11px] text-accent-700 hover:underline" onClick={() => setTypes(DEFAULT_TYPES)}>default</button>
              <button className="text-[11px] text-accent-700 hover:underline" onClick={() => setTypes([])}>none</button>
            </span>
          </div>
          {focus && (
            <label className="mb-1 flex items-center gap-2 text-[11px] muted">
              <input type="checkbox" checked={filterInFocus} onChange={(e) => setFilterInFocus(e.target.checked)} /> apply type filter to the neighbourhood
            </label>
          )}
          <ul className="space-y-0.5">
            {nodeTypes.map(([t, n]) => (
              <li key={t}>
                <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-gray-50">
                  <input type="checkbox" checked={types.includes(t)} onChange={() => toggleType(t)} />
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: color(t) }} />
                  <span className={presentTypes.has(t) ? "text-gray-900" : "text-gray-500"}>{t}</span>
                  <span className="ml-auto text-[11px] muted">{n}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="mt-4 space-y-1 border-t border-gray-100 pt-2 text-[11px] text-gray-600">
            <div className="label mb-1">Legend</div>
            <div className="flex items-center gap-2"><svg width="28" height="6"><line x1="0" y1="3" x2="28" y2="3" stroke="#9ca3af" strokeWidth="1.5" /></svg> approved edge</div>
            <div className="flex items-center gap-2"><svg width="28" height="6"><line x1="0" y1="3" x2="28" y2="3" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4 3" /></svg> draft (agent-proposed)</div>
            <div className="flex items-center gap-2"><svg width="14" height="14"><circle cx="7" cy="7" r="4" fill="#1f5bd6" stroke="#f59e0b" strokeWidth="2" /></svg> confidence &lt; 0.7</div>
            <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} /> show labels</label>
          </div>
        </aside>

        <div className="card flex min-w-0 flex-1 overflow-hidden">
        <div ref={wrap} className="relative min-w-0 flex-1 overflow-hidden">
          {error && <div className="absolute left-3 top-3 z-10"><ErrorBox error={error} /></div>}
          {loading && <div className="absolute left-3 top-1 z-10"><Loading label="Loading graph…" /></div>}
          <div className="absolute right-3 top-2 z-10 text-[11px] muted">{graph.nodes.length} nodes · {graph.links.length} edges</div>
          {graph.nodes.length === 0 && !loading && <div className="absolute inset-0 flex items-center justify-center text-sm muted">No nodes — tick some node types.</div>}
          <ForceGraph2D
            ref={fg}
            width={size.w}
            height={size.h}
            graphData={graph}
            nodeId="id"
            cooldownTicks={120}
            nodeLabel={(n: any) => `${n.name} (${n.type}) · ${n.id}`}
            nodeRelSize={4}
            linkColor={(l: any) => (l.status === "draft" ? "rgba(245,158,11,0.75)" : sel && (l.source?.id === sel || l.target?.id === sel) ? "rgba(31,91,214,0.6)" : "rgba(156,163,175,0.45)")}
            linkWidth={(l: any) => (sel && (l.source?.id === sel || l.target?.id === sel) ? 1.6 : 0.8)}
            linkLineDash={(l: any) => (l.status === "draft" ? [4, 3] : null)}
            linkDirectionalArrowLength={2.5}
            linkDirectionalArrowRelPos={1}
            linkLabel={(l: any) => `${l.type}${l.status === "draft" ? " (draft)" : ""}`}
            onNodeClick={(n: any) => setSel(n.id)}
            onBackgroundClick={() => setSel(null)}
            nodeCanvasObject={(n: any, ctx, scale) => {
              const r = 3 + Math.min(7, Math.sqrt(n.deg || 0) * 1.4) + (n.id === focus ? 3 : 0);
              const dim = sel && n.id !== sel && !neighbors.has(n.id);
              ctx.globalAlpha = dim ? 0.25 : 1;
              ctx.beginPath();
              ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
              ctx.fillStyle = color(n.type);
              ctx.fill();
              if (n.confidence < 0.7) {
                ctx.lineWidth = 2.5 / Math.max(scale, 0.6);
                ctx.strokeStyle = "#f59e0b";
                ctx.stroke();
              }
              if (n.status === "draft") {
                ctx.setLineDash([2, 2]);
                ctx.lineWidth = 1;
                ctx.strokeStyle = "#f59e0b";
                ctx.stroke();
                ctx.setLineDash([]);
              }
              if (n.id === sel || n.id === focus) {
                ctx.lineWidth = 2 / scale;
                ctx.strokeStyle = "#111827";
                ctx.beginPath();
                ctx.arc(n.x, n.y, r + 2 / scale, 0, 2 * Math.PI);
                ctx.stroke();
              }
              const label = showLabels && (scale > 1.6 || n.id === sel || n.id === focus || (sel && neighbors.has(n.id)) || (n.deg || 0) >= 12);
              if (label) {
                const fs = Math.max(10 / scale, 1.5);
                ctx.font = `${fs}px Inter, sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                ctx.fillStyle = "#111827";
                ctx.fillText(n.name.length > 28 ? n.name.slice(0, 27) + "…" : n.name, n.x, n.y + r + 1);
              }
              ctx.globalAlpha = 1;
            }}
            nodePointerAreaPaint={(n: any, c, ctx) => {
              const r = 3 + Math.min(7, Math.sqrt(n.deg || 0) * 1.4) + 2;
              ctx.fillStyle = c;
              ctx.beginPath();
              ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
              ctx.fill();
            }}
          />
        </div>
          {sel && (
            <NodeDrawer
              id={sel}
              onClose={() => setSel(null)}
              onFocus={(id) => setFocus(id)}
              onSelect={setSel}
              onExplain={(id) => nav(`/copilot?q=${encodeURIComponent(`Explain ${id}`)}`)}
              onOpen={(id) => openEvidence(id)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function NodeDrawer({ id, onClose, onFocus, onSelect, onExplain, onOpen }: {
  id: string; onClose: () => void; onFocus: (id: string) => void; onSelect: (id: string) => void; onExplain: (id: string) => void; onOpen: (id: string) => void;
}) {
  const { data: n, loading, error } = useApi<any>(`/kg/nodes/${encodeURIComponent(id)}`, undefined, [id]);
  const edges = n ? [...(n.out_edges || []).map((e: any) => ({ ...e, dir: "out" })), ...(n.in_edges || []).map((e: any) => ({ ...e, dir: "in" }))] : [];
  return (
    <aside className="flex h-full w-[24rem] shrink-0 flex-col border-l border-gray-200 bg-white">
      <div className="flex items-start justify-between gap-2 border-b border-gray-200 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            {n && <span className="h-2.5 w-2.5 rounded-full" style={{ background: color(n.type) }} />}
            <span className="label">{n?.type || "Node"}</span>
          </div>
          <div className="mt-0.5 truncate text-base font-semibold" title={n?.name}>{n?.name || id}</div>
          <div className="font-mono text-xs muted">{id}</div>
        </div>
        <button className="btn btn-sm" onClick={onClose}>Close</button>
      </div>
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {loading && !n && <Loading />}
        <ErrorBox error={error} />
        {n && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <ConfidenceBadge value={n.confidence} />
              <Badge color={n.status === "approved" ? "green" : n.status === "draft" ? "amber" : "gray"}>{n.status}</Badge>
              <span className="text-[11px] muted">by {n.created_by}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <button className="btn-primary btn-sm" onClick={() => onFocus(id)}>Focus here</button>
              <button className="btn btn-sm" onClick={() => onExplain(id)}>Explain this node</button>
              <button className="btn btn-sm" onClick={() => onOpen(id)}>Open record</button>
            </div>
            <div>
              <div className="label mb-1">Properties</div>
              <table className="w-full text-xs">
                <tbody>
                  {Object.entries(n.props_json || {}).map(([k, v]) => (
                    <tr key={k} className="border-b border-gray-50">
                      <td className="w-36 py-0.5 pr-2 align-top text-gray-500">{k}</td>
                      <td className="py-0.5 break-all">{v === null || v === undefined ? <span className="muted">—</span> : typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(n.source_refs_json || []).length > 0 && (
                <div className="mt-1 text-xs"><span className="muted">Sources: </span>{n.source_refs_json.map((r: string) => <EvidenceChip key={r} id={r} />)}</div>
              )}
            </div>
            <div>
              <div className="label mb-1">Edges ({edges.length})</div>
              <ul className="space-y-1">
                {edges.map((e: any) => (
                  <li key={e.id + e.dir} className="flex items-center gap-1 text-xs">
                    <span className="w-4 text-center muted">{e.dir === "out" ? "→" : "←"}</span>
                    <Badge color={e.status === "draft" ? "amber" : "gray"}>{e.type}{e.status === "draft" ? " · draft" : ""}</Badge>
                    <button className="truncate text-left text-accent-700 hover:underline" title={e.other?.type} onClick={() => onSelect(e.other?.id)}>
                      <span className="font-mono">{e.other?.id}</span> {e.other?.name}
                    </button>
                    {e.confidence < 0.9 && <span className="ml-auto"><ConfidenceBadge value={e.confidence} /></span>}
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
