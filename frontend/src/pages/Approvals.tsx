import { useMemo, useState } from "react";
import { api, Approval } from "../api/client";
import { ROLE_CAN_APPROVE } from "../components/AgentPanel";
import { EvidenceChip, EvidenceList, TextWithChips } from "../components/Evidence";
import { PageHeader } from "../components/Layout";
import { Badge, Card, Empty, ErrorBox, Loading, StatusBadge, Tabs } from "../components/ui";
import { ROLE_LABELS, useApi, useApp } from "../state/AppState";

const HIDE_KEYS = new Set(["contract_yaml", "quarters", "controls", "raw_names"]);

function PayloadDiff({ a }: { a: Approval }) {
  const p = a.edited_payload_json || a.payload_json || {};
  const entries = Object.entries(p).filter(([k]) => !HIDE_KEYS.has(k));
  return (
    <div className="rounded border border-gray-200 bg-gray-50 p-2 text-xs">
      <div className="mb-1 font-medium text-gray-600">
        On approval: <span className="font-mono">{a.action_type}</span> on <span className="font-mono">{a.target_type || "record"} {a.target_id}</span>
      </div>
      <table className="w-full">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td className="pr-3 align-top text-gray-500 whitespace-nowrap">{k}</td>
              <td className="font-mono text-green-800 break-all">
                + {Array.isArray(v) ? (v as any[]).slice(0, 12).join(", ") + ((v as any[]).length > 12 ? " …" : "") : typeof v === "object" ? JSON.stringify(v).slice(0, 300) : String(v)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {p.contract_yaml && <pre className="mt-2 max-h-40 overflow-auto bg-white p-2 border border-gray-200">{p.contract_yaml}</pre>}
    </div>
  );
}

function ApprovalCard({ a, selectable, selected, onSelect }: { a: Approval; selectable: boolean; selected: boolean; onSelect: (v: boolean) => void }) {
  const { user, refresh, notify } = useApp();
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [edited, setEdited] = useState(JSON.stringify(a.payload_json, null, 2));
  const [busy, setBusy] = useState(false);
  const canDecide = !!user && ROLE_CAN_APPROVE[user.role]?.includes(a.approver_role);
  const decide = async (decision: string) => {
    setBusy(true);
    try {
      let edited_payload = undefined;
      if (decision === "edit") edited_payload = JSON.parse(edited);
      const r = await api.post<Approval>(`/approvals/${a.id}/decide`, { decision, user_id: user!.id, note: note || null, edited_payload });
      const fx = [...(r.side_effects_json?.graph || []), ...(r.side_effects_json?.side_effects || [])].join("; ");
      notify(`${r.status.toUpperCase()}: ${a.action_type} ${a.target_id}${fx ? " — " + fx : ""}`);
      refresh();
    } catch (e: any) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card p-3" data-testid={`approval-${a.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {selectable && <input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} />}
          <Badge color="blue">{a.action_type.replace(/_/g, " ")}</Badge>
          <EvidenceChip id={a.target_id} />
          <span className="text-xs muted">proposed by {a.agent_name} · run <span className="font-mono">{a.run_id}</span> · {a.created_at}</span>
        </div>
        <div className="flex items-center gap-2">
          <Badge>{ROLE_LABELS[a.approver_role] || a.approver_role}</Badge>
          <StatusBadge status={a.status} />
          <span className="font-mono text-[11px] muted">{a.id}</span>
        </div>
      </div>
      <div className="mt-2 text-sm text-gray-800"><TextWithChips text={a.rationale} /></div>
      <div className="mt-1 flex flex-wrap items-center gap-1 text-xs"><span className="muted">Evidence:</span><EvidenceList refs={a.source_refs_json} max={8} /></div>
      <div className="mt-2"><PayloadDiff a={a} /></div>
      {a.status === "pending" ? (
        canDecide ? (
          <div className="mt-2 space-y-2">
            {editing && <textarea className="input w-full font-mono text-xs h-40" value={edited} onChange={(e) => setEdited(e.target.value)} />}
            <div className="flex flex-wrap items-center gap-2">
              <input className="input flex-1 min-w-[12rem]" placeholder="Decision note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
              <button className="btn-primary" disabled={busy} onClick={() => decide("approve")}>Approve</button>
              {editing ? (
                <button className="btn" disabled={busy} onClick={() => decide("edit")}>Save edit & approve</button>
              ) : (
                <button className="btn" disabled={busy} onClick={() => setEditing(true)}>Edit…</button>
              )}
              <button className="btn-danger" disabled={busy} onClick={() => decide("reject")}>Reject</button>
            </div>
          </div>
        ) : (
          <div className="mt-2 text-xs muted">Awaiting {ROLE_LABELS[a.approver_role] || a.approver_role}. Switch “Acting as” to decide.</div>
        )
      ) : (
        <div className="mt-2 text-xs text-gray-600">
          {a.status} by <b>{a.decided_by}</b> at {a.decided_at}{a.decision_note ? ` — “${a.decision_note}”` : ""}
          {a.side_effects_json && (
            <div className="mt-1 muted">
              {(a.side_effects_json.graph || []).join("; ")}
              {(a.side_effects_json.side_effects || []).length > 0 && <> · <b>{a.side_effects_json.side_effects!.join("; ")}</b></>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Approvals() {
  const { user, refresh, notify } = useApp();
  const [tab, setTab] = useState("pending");
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [agentFilter, setAgentFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const params = scope === "mine" && user ? { role: user.role, user_id: user.id } : {};
  const { data, loading, error } = useApi<any>("/approvals", { ...params, status: tab === "pending" ? "pending" : undefined }, [user?.id, scope, tab]);
  const items: Approval[] = useMemo(() => {
    let xs: Approval[] = data?.items || [];
    if (tab === "decided") xs = xs.filter((a) => a.status !== "pending").sort((a, b) => (b.decided_at || "").localeCompare(a.decided_at || ""));
    if (agentFilter) xs = xs.filter((a) => a.agent_id === agentFilter);
    if (typeFilter) xs = xs.filter((a) => a.action_type === typeFilter);
    return xs;
  }, [data, tab, agentFilter, typeFilter]);
  const agents = Array.from(new Set((data?.items || []).map((a: Approval) => a.agent_id))) as string[];
  const types = Array.from(new Set((data?.items || []).map((a: Approval) => a.action_type))) as string[];
  const bulkTypes: string[] = data?.bulk_types || [];
  const bulk = async () => {
    try {
      await api.post("/approvals/bulk", { ids: Array.from(sel), user_id: user!.id, decision: "approve", note: "Bulk approved (low-risk)" });
      notify(`Bulk approved ${sel.size} low-risk items`);
      setSel(new Set());
      refresh();
    } catch (e: any) {
      notify(e.message);
    }
  };
  return (
    <div>
      <PageHeader
        title="Approvals"
        subtitle={<>Agents propose, humans decide. {user && <>Showing items for <b>{user.name}</b> ({ROLE_LABELS[user.role]}).</>}</>}
        actions={
          <>
            <select className="input" value={scope} onChange={(e) => setScope(e.target.value as any)}>
              <option value="mine">My inbox (by role)</option>
              <option value="all">All roles</option>
            </select>
            <select className="input" value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}>
              <option value="">All agents</option>
              {agents.map((a) => <option key={a}>{a}</option>)}
            </select>
            <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">All action types</option>
              {types.map((a) => <option key={a}>{a}</option>)}
            </select>
          </>
        }
      />
      <Tabs tabs={[{ id: "pending", label: `Pending (${tab === "pending" ? items.length : "…"})` }, { id: "decided", label: "Decided" }]} active={tab} onChange={setTab} />
      {tab === "pending" && sel.size > 0 && (
        <div className="mb-3 flex items-center gap-2"><button className="btn-primary" onClick={bulk}>Bulk approve {sel.size} low-risk items</button><span className="text-xs muted">Only {bulkTypes.join(", ")} can be bulk-approved.</span></div>
      )}
      <ErrorBox error={error} />
      {loading && !data && <Loading />}
      {data && items.length === 0 && <Card><Empty>Nothing {tab === "pending" ? "waiting for you" : "decided yet"}.</Empty></Card>}
      <div className="space-y-3">
        {items.slice(0, 150).map((a) => (
          <ApprovalCard key={a.id} a={a} selectable={tab === "pending" && bulkTypes.includes(a.action_type) && !!user && ROLE_CAN_APPROVE[user.role]?.includes(a.approver_role)}
            selected={sel.has(a.id)} onSelect={(v) => setSel((s) => { const n = new Set(s); v ? n.add(a.id) : n.delete(a.id); return n; })} />
        ))}
        {items.length > 150 && <div className="text-sm muted">Showing 150 of {items.length}. Use the filters to narrow down.</div>}
      </div>
    </div>
  );
}
