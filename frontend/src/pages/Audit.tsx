import { Fragment, useState } from "react";
import { api } from "../api/client";
import { EvidenceChip } from "../components/Evidence";
import { PageHeader } from "../components/Layout";
import { Badge, Card, Empty, ErrorBox, Loading } from "../components/ui";
import { useApi, useApp } from "../state/AppState";

const EVENT_TYPES = [
  "agent_run_started",
  "agent_run_completed",
  "approval_created",
  "approval_decided",
  "graph_updated",
  "graph_built",
  "copilot_answered",
  "observations_promoted",
  "agent_settings_changed",
];
const ACTOR_COLOR: Record<string, string> = { agent: "blue", user: "green", system: "gray" };
const EVENT_COLOR: Record<string, string> = { approval_decided: "green", approval_created: "amber", graph_updated: "purple", agent_run_completed: "blue" };

function summarize(e: any): string {
  const d = e.details_json || {};
  switch (e.event_type) {
    case "agent_run_started":
      return `trigger ${d.trigger || "?"} · L${d.autonomy_level ?? "?"}${d.params && Object.keys(d.params).length ? " · " + Object.entries(d.params).map(([k, v]) => `${k}=${v}`).join(", ") : ""}`;
    case "agent_run_completed":
      return `${d.findings ?? 0} findings · ${d.proposed_actions ?? 0} proposals · ${d.approvals_created ?? 0} approvals · ${d.duration_ms ?? "?"} ms · ${d.llm_mode || ""}`;
    case "approval_created":
      return `${(d.action_type || "").replace(/_/g, " ")}${d.approver_role ? " → awaiting " + d.approver_role : ""}`;
    case "approval_decided":
      return `${d.decision || d.status || ""} · ${(d.action_type || "").replace(/_/g, " ")}${d.edited_payload ? " (edited)" : ""}${d.note ? ` — “${d.note}”` : ""}`;
    case "graph_updated":
      return `${(d.action_type || "").replace(/_/g, " ")} ${d.decision || ""}${(d.graph || []).length ? " · " + d.graph.join("; ") : ""}${(d.side_effects || []).length ? " · " + d.side_effects.join("; ") : ""}`;
    case "copilot_answered":
      return `answered (${d.mode || ""}) citing ${(d.citations || []).slice(0, 6).join(", ")}${(d.citations || []).length > 6 ? "…" : ""}`;
    default: {
      const s = Object.entries(d)
        .filter(([, v]) => v !== null && typeof v !== "object")
        .slice(0, 4)
        .map(([k, v]) => `${k}: ${v}`)
        .join(" · ");
      return s || (Object.keys(d).length ? JSON.stringify(d).slice(0, 120) : "");
    }
  }
}

export default function Audit() {
  const { users } = useApp();
  const { data: agents } = useApi<any>("/agents");
  const [f, setF] = useState({ actor: "", agent: "", subject: "", from: "", to: "", event_type: "" });
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState(150);
  const { data, loading, error } = useApi<any>("/audit", { ...f, limit: 1000 }, [JSON.stringify(f)]);
  const items: any[] = data?.items || [];
  const set = (k: keyof typeof f, v: string) => setF((x) => ({ ...x, [k]: v }));
  const userName = (id: string) => users.find((u) => u.id === id)?.name;
  const exportParams = { actor: f.actor, agent: f.agent, subject: f.subject, from: f.from, to: f.to, event_type: f.event_type };
  const toggle = (id: string) => setOpen((s) => {
    const n = new Set(s);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });
  const anyFilter = Object.values(f).some(Boolean);
  return (
    <div className="[&_button]:whitespace-nowrap">
      <PageHeader
        title="Audit"
        subtitle="Every agent run, proposal, human decision and graph change — with links to the run and the approval."
        actions={
          <>
            <a className="btn" href={api.url("/audit/export", { format: "json", ...exportParams })} download>Export JSON</a>
            <a className="btn" href={api.url("/audit/export", { format: "csv", ...exportParams })} download>Export CSV</a>
          </>
        }
      />
      <Card className="mb-3">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <div className="label">Actor</div>
            <select className="input mt-1" value={f.actor} onChange={(e) => set("actor", e.target.value)}>
              <option value="">Anyone</option>
              <option value="agent">Any agent</option>
              <option value="user">Any user</option>
              <option value="system">System</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </div>
          <div>
            <div className="label">Agent</div>
            <select className="input mt-1 max-w-[16rem]" value={f.agent} onChange={(e) => set("agent", e.target.value)}>
              <option value="">All agents</option>
              {(agents?.items || []).map((a: any) => <option key={a.id} value={a.id}>{a.id}</option>)}
            </select>
          </div>
          <div>
            <div className="label">Event type</div>
            <select className="input mt-1" value={f.event_type} onChange={(e) => set("event_type", e.target.value)}>
              <option value="">All events</option>
              {EVENT_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
            </select>
          </div>
          <div>
            <div className="label">Subject id contains</div>
            <input className="input mt-1 w-40 font-mono" placeholder="APP-0021" value={f.subject} onChange={(e) => set("subject", e.target.value)} />
          </div>
          <div>
            <div className="label">From</div>
            <input type="date" className="input mt-1" value={f.from} onChange={(e) => set("from", e.target.value)} />
          </div>
          <div>
            <div className="label">To</div>
            <input type="date" className="input mt-1" value={f.to} onChange={(e) => set("to", e.target.value)} />
          </div>
          {anyFilter && <button className="btn btn-sm mb-1" onClick={() => setF({ actor: "", agent: "", subject: "", from: "", to: "", event_type: "" })}>Clear</button>}
          <div className="ml-auto mb-1 text-xs muted">{data ? `${items.length} of ${data.total} events` : ""}</div>
        </div>
      </Card>
      <ErrorBox error={error} />
      {loading && !data && <Loading />}
      <Card>
        <div className="-m-4 overflow-auto">
          <table className="tbl">
            <thead>
              <tr><th className="w-6"></th><th>Time (UTC)</th><th>Actor</th><th>Event</th><th>Subject</th><th>Details</th><th>Run</th><th>Approval</th></tr>
            </thead>
            <tbody>
              {items.slice(0, shown).map((e) => {
                const isOpen = open.has(e.id);
                return (
                  <Fragment key={e.id}>
                    <tr className="cursor-pointer" onClick={() => toggle(e.id)}>
                      <td className="text-xs muted">{isOpen ? "▾" : "▸"}</td>
                      <td className="font-mono text-xs whitespace-nowrap">{(e.ts || "").slice(0, 10)}<div className="muted">{(e.ts || "").slice(11, 19)}</div></td>
                      <td className="whitespace-nowrap">
                        <Badge color={ACTOR_COLOR[e.actor_type] || "gray"}>{e.actor_type}</Badge>
                        <div className={e.actor_type === "agent" ? "font-mono text-[11px]" : "text-sm"}>
                          {e.actor_type === "user" ? userName(e.actor_id) || e.actor_id : e.actor_id}
                        </div>
                      </td>
                      <td><Badge color={EVENT_COLOR[e.event_type] || "gray"}>{e.event_type.replace(/_/g, " ")}</Badge></td>
                      <td className="whitespace-nowrap">
                        {!e.subject_id ? <span className="muted text-xs">—</span> : /^[A-Z]{2,5}-[A-Za-z0-9-]+$/.test(e.subject_id) ? <EvidenceChip id={e.subject_id} /> : <span className="font-mono text-xs mr-1" title={e.subject_id}>{e.subject_id.length > 22 ? e.subject_id.slice(0, 20) + "…" : e.subject_id}</span>}
                        {e.subject_type && <div className="text-[10px] muted">{e.subject_type}</div>}
                      </td>
                      <td className="text-xs text-gray-700 min-w-[12rem]">{summarize(e)}</td>
                      <td className="whitespace-nowrap">{e.run_id ? <EvidenceChip id={e.run_id} /> : <span className="muted text-xs">—</span>}</td>
                      <td className="whitespace-nowrap">{e.approval_id ? <EvidenceChip id={e.approval_id} /> : <span className="muted text-xs">—</span>}</td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td></td>
                        <td colSpan={7} className="bg-gray-50">
                          <div className="mb-1 text-[11px] muted font-mono">{e.id}</div>
                          <pre className="max-h-72 overflow-auto rounded border border-gray-200 bg-white p-2 text-[11px]">{JSON.stringify(e.details_json, null, 2)}</pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          {items.length > shown && (
            <div className="px-4 py-2"><button className="btn btn-sm" onClick={() => setShown((n) => n + 300)}>Show more ({items.length - shown} remaining)</button></div>
          )}
          {data && items.length === 0 && <Empty>No audit events match these filters.</Empty>}
        </div>
      </Card>
    </div>
  );
}
