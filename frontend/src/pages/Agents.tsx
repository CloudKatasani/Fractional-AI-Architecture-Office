import { useState } from "react";
import { AgentOutput, api } from "../api/client";
import { TextWithChips } from "../components/Evidence";
import { PageHeader } from "../components/Layout";
import { Badge, ErrorBox, Loading, since } from "../components/ui";
import { ROLE_LABELS, useApi, useApp } from "../state/AppState";

const LEVELS = [
  { n: 1, label: "L1", name: "Observe", help: "Findings only; no approval rows" },
  { n: 2, label: "L2", name: "Propose", help: "Approval rows created; nothing applied until decided" },
  { n: 3, label: "L3", name: "Act w/ approval", help: "On approval, side effects execute (graph write, ticket, ADR publish)" },
  { n: 4, label: "L4", name: "Act & notify", help: "not enabled in prototype" },
];

function promotion(level: number, acc: number | null | undefined, rules: Record<string, string>) {
  if (acc === null || acc === undefined) return { text: "No decisions recorded yet — acceptance unknown.", eligible: false };
  if (level < 3 && acc >= 0.9) return { text: `Eligible for L3 (${rules.L3 || "acceptance ≥ 90%"}).`, eligible: true };
  if (level < 2 && acc >= 0.8) return { text: `Eligible for L2 (${rules.L2 || "acceptance ≥ 80%"}).`, eligible: true };
  if (level === 1) return { text: `Stays at L1 until ${rules.L2 || "acceptance ≥ 80% over 4 weeks"}.`, eligible: false };
  if (level === 2) return { text: `L3 requires ${rules.L3 || "acceptance ≥ 90% over 8 weeks"}.`, eligible: false };
  return { text: acc < 0.9 ? `Below the L3 bar (${rules.L3 || "≥ 90%"}) — consider demoting.` : "Meets the L3 bar.", eligible: false };
}

function RecentRuns({ agentId }: { agentId: string }) {
  const { data, loading, error } = useApi<any[]>("/runs", { agent_id: agentId, limit: 10 }, [agentId]);
  if (loading && !data) return <Loading label="Loading runs…" />;
  if (error) return <ErrorBox error={error} />;
  if (!data?.length) return <div className="text-xs muted">No runs yet for this tenant.</div>;
  return (
    <table className="tbl">
      <thead><tr><th>Run</th><th>When</th><th>Trigger</th><th>Level</th><th className="text-right">Findings</th><th className="text-right">Approvals</th><th>Summary</th></tr></thead>
      <tbody>
        {data.map((r) => (
          <tr key={r.id}>
            <td className="whitespace-nowrap font-mono text-[11px]">{r.id}</td>
            <td className="whitespace-nowrap text-xs" title={r.started_at}>{since(r.started_at)}</td>
            <td className="text-xs">{r.trigger}</td>
            <td className="text-xs">L{r.autonomy_level}</td>
            <td className="text-right text-xs tabular-nums">{r.findings}</td>
            <td className="text-right text-xs tabular-nums">{r.approvals_created}</td>
            <td className="text-xs text-gray-700"><div className="line-clamp-2 max-w-md">{r.summary ? <TextWithChips text={r.summary} /> : r.status}</div></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AgentCard({ a, rules }: { a: any; rules: Record<string, string> }) {
  const { user, refresh, notify } = useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [showRuns, setShowRuns] = useState(false);
  const [params, setParams] = useState<Record<string, string>>({});
  const [last, setLast] = useState<AgentOutput | null>(null);
  const isPA = user?.role === "principal_architect";
  const promo = promotion(a.autonomy_level, a.acceptance_rate_30d, rules);
  const spec: any[] = a.params_spec || [];

  const setLevel = async (n: number) => {
    if (n === a.autonomy_level || n === 4) return;
    setBusy("level");
    try {
      await api.patch(`/agents/${a.id}/settings`, { autonomy_level: n, user_id: user?.id });
      notify(`${a.name} set to L${n} (${LEVELS[n - 1].name})`);
      refresh();
    } catch (e: any) {
      notify(e.status === 403 ? `Only the Principal Architect can change autonomy levels (acting as ${ROLE_LABELS[user?.role || ""] || user?.role}).` : e.message);
    } finally {
      setBusy(null);
    }
  };
  const run = async () => {
    setBusy("run");
    try {
      const out = await api.post<AgentOutput>("/agents/run", { agent_id: a.id, params, user_id: user?.id });
      setLast(out);
      notify(`${out.agent_name}: ${out.findings.length} findings` + (out.approvals_created.length ? `, ${out.approvals_created.length} items in the approval inbox` : out.mode === "observe" ? " (observe only)" : ""));
      refresh();
    } catch (e: any) {
      notify(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="card flex flex-col p-3" data-testid={`agent-${a.id}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-gray-900">{a.name}</div>
          <div className="font-mono text-[11px] muted">{a.id}</div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          {!a.enabled && <Badge color="red">disabled</Badge>}
          {!a.runnable && <Badge title="Invoked by other agents or the Copilot">internal</Badge>}
          {promo.eligible && <Badge color="green">promotion eligible</Badge>}
        </div>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-gray-700">{a.description}</p>

      <dl className="mt-2 grid grid-cols-[5.5rem_1fr] gap-x-2 gap-y-1 text-xs">
        <dt className="muted">Inputs</dt>
        <dd className="flex flex-wrap gap-1">{(a.inputs || []).map((i: string) => <span key={i} className="rounded bg-gray-100 px-1 font-mono text-[11px] text-gray-700">{i}</span>)}</dd>
        <dt className="muted">Outputs</dt>
        <dd className="font-mono text-[11px]">{a.outputs}</dd>
        <dt className="muted">Actions</dt>
        <dd className="font-mono text-[11px]">{(a.action_types || []).join(", ") || <span className="font-sans muted">none (advisory)</span>}</dd>
        <dt className="muted">Approver</dt>
        <dd>{a.approver_role ? ROLE_LABELS[a.approver_role] || a.approver_role : <span className="muted">—</span>}</dd>
      </dl>

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between">
          <span className="label">Autonomy</span>
          <span className="text-[11px] muted">default L{a.default_autonomy}</span>
        </div>
        <div className="inline-flex w-full overflow-hidden rounded-md border border-gray-300" role="radiogroup" aria-label="Autonomy level">
          {LEVELS.map((l) => {
            const on = a.autonomy_level === l.n;
            const disabled = l.n === 4 || busy !== null;
            return (
              <button
                key={l.n}
                role="radio"
                aria-checked={on}
                title={l.n === 4 ? "L4 Act and notify — not enabled in prototype" : `${l.label} ${l.name}: ${l.help}${isPA ? "" : " (only the Principal Architect can change this)"}`}
                disabled={disabled}
                onClick={() => setLevel(l.n)}
                className={`flex-1 border-r border-gray-300 px-1 py-1 text-[11px] font-medium last:border-r-0 ${
                  on ? "bg-accent-600 text-white" : l.n === 4 ? "cursor-not-allowed bg-gray-50 text-gray-300" : "bg-white text-gray-700 hover:bg-gray-50"
                } ${!isPA && !on && l.n !== 4 ? "text-gray-400" : ""}`}
              >
                {l.label} <span className="hidden sm:inline">{l.name}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="muted">Acceptance 30d</div>
          <div className={`text-sm font-semibold ${a.acceptance_rate_30d >= 0.9 ? "text-green-700" : a.acceptance_rate_30d >= 0.8 ? "text-gray-900" : a.acceptance_rate_30d != null ? "text-amber-700" : "text-gray-400"}`}>
            {a.acceptance_rate_30d != null ? `${Math.round(a.acceptance_rate_30d * 1000) / 10}%` : "—"}
          </div>
          <div className="text-[11px] muted">{a.decided_30d ?? 0} decisions</div>
        </div>
        <div>
          <div className="muted">Last run</div>
          <div className="text-sm font-semibold text-gray-900" title={a.last_run_at || ""}>{since(a.last_run_at)}</div>
        </div>
        <div>
          <div className="muted">Runs</div>
          <div className="text-sm font-semibold text-gray-900">{a.run_count ?? 0}</div>
        </div>
      </div>
      <div className={`mt-1.5 text-[11px] ${promo.eligible ? "text-green-700" : "muted"}`}>{promo.text}</div>

      {a.runnable && spec.length > 0 && (
        <div className="mt-2 space-y-1">
          {spec.map((p) => (
            <input key={p.name} className="input w-full py-1 text-xs" placeholder={`${p.label}${p.kind === "select" ? ` (${p.source} id)` : ""}`}
              value={params[p.name] || ""} onChange={(e) => setParams((s) => ({ ...s, [p.name]: e.target.value }))} />
          ))}
        </div>
      )}

      {last && (
        <div className="mt-2 rounded border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs text-gray-700">
          <div className="mb-0.5 flex items-center gap-1.5"><Badge color={last.mode === "observe" ? "gray" : "blue"}>{last.mode} · L{last.autonomy_level}</Badge><span className="font-mono text-[11px] muted">{last.run_id}</span></div>
          <TextWithChips text={last.summary} />
        </div>
      )}

      <div className="mt-auto flex items-center justify-between gap-2 pt-3">
        <button className="btn btn-sm" onClick={() => setShowRuns((v) => !v)}>{showRuns ? "Hide runs" : "Recent runs"}</button>
        {a.runnable ? (
          <button className="btn-primary btn-sm" disabled={busy !== null || !a.enabled} onClick={run}>{busy === "run" ? "Running…" : a.demo_trigger || "Run"}</button>
        ) : (
          <span className="text-[11px] muted">runs via orchestrator / Copilot</span>
        )}
      </div>
      {showRuns && <div className="-mx-3 mt-2 overflow-x-auto border-t border-gray-100"><RecentRuns agentId={a.id} /></div>}
    </div>
  );
}

export default function Agents() {
  const { user, tenantName } = useApp();
  const { data, loading, error } = useApi<any>("/agents");
  const [q, setQ] = useState("");
  if (loading && !data) return <Loading />;
  const items: any[] = data?.items || [];
  const domains: Record<string, string> = data?.domains || {};
  const rules: Record<string, string> = data?.promotion_rules || {};
  const ql = q.trim().toLowerCase();
  const shown = items.filter((a) => !ql || `${a.id} ${a.name} ${a.description}`.toLowerCase().includes(ql));
  const order = [...Object.keys(domains), ...Array.from(new Set(items.map((a) => a.domain))).filter((d) => !(d in domains))];
  const isPA = user?.role === "principal_architect";
  const eligible = items.filter((a) => promotion(a.autonomy_level, a.acceptance_rate_30d, rules).eligible).length;

  return (
    <div>
      <PageHeader
        title="Agents"
        subtitle={<>{items.length} agents registered for {tenantName} · {eligible} eligible for promotion. Promotion guidance: L2 at {rules.L2}; L3 at {rules.L3}; L4 is {rules.L4 ? "display-only" : "not enabled"}.</>}
        actions={<input className="input w-56" placeholder="Filter agents…" value={q} onChange={(e) => setQ(e.target.value)} />}
      />
      {!isPA && (
        <div className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Acting as {ROLE_LABELS[user?.role || ""] || user?.role}: autonomy levels are read-only. Switch “Acting as” to the Principal Architect to change them.
        </div>
      )}
      <ErrorBox error={error} />
      <div className="space-y-6">
        {order.map((d) => {
          const xs = shown.filter((a) => a.domain === d);
          if (xs.length === 0) return null;
          return (
            <section key={d}>
              <div className="mb-2 flex items-baseline gap-2">
                <h2>{domains[d] || d}</h2>
                <span className="text-xs muted">{xs.length} agents</span>
              </div>
              <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
                {xs.map((a) => <AgentCard key={a.id} a={a} rules={rules} />)}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
