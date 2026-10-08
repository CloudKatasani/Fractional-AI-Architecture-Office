import { ReactNode, useState } from "react";
import { api } from "../../api/client";
import { useApi, useApp } from "../../state/AppState";
import { AgentPanel, ApprovalControls } from "../AgentPanel";
import { EvidenceChip, EvidenceList } from "../Evidence";
import { Badge, ConfidenceBadge, Empty, ErrorBox, Loading, usd } from "../ui";

function Section({ title, subtitle, actions, children }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3>{title}</h3>
          {subtitle && <div className="text-xs muted">{subtitle}</div>}
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}

const SOURCE_LABEL: Record<string, string> = { invoice: "invoice", sso: "SSO", cloud: "cloud tag", cmdb: "CMDB", expense: "expense" };

export function DiscoveryTab() {
  const { user, refresh, notify } = useApp();
  const { data, loading, error } = useApi<any>("/portfolio/discovery");
  const [busy, setBusy] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const items: any[] = data.items || [];
  const byType = (t: string) => items.filter((i) => i.type === t);
  const candidates = byType("new_app").sort((a, b) => Number(b.genai) - Number(a.genai) || (b.annual_cost_usd || 0) - (a.annual_cost_usd || 0));
  const dups = byType("cmdb_duplicate");
  const stale = byType("cmdb_stale");
  const aliases = byType("alias_merge");
  const run = data.run;
  const unsentCandidates = candidates.filter((c) => !c.approval).length;
  const unsentCmdb = [...dups, ...stale].filter((c) => !c.approval).length;
  const shadowCost = candidates.reduce((s, c) => s + (c.annual_cost_usd || 0), 0);

  const send = async (key: string, action_types: string[], what: string) => {
    if (!run || !user) return;
    setBusy(key);
    try {
      const r = await api.post<{ approvals_created: string[] }>(`/runs/${run.run_id}/propose`, { user_id: user.id, action_types });
      notify(`${r.approvals_created.length} ${what} sent to the approval inbox`);
      refresh();
    } catch (e: any) {
      notify(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <AgentPanel agentId="pf.app_discovery" run={run}>
      <div className="mb-4 rounded border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
        Discovery runs at <b>L1 Observe</b>: these are observations only. Nothing reaches an owner or the CMDB until you send it for confirmation.
      </div>
      <div className="space-y-6">
        <Section
          title={<>Shadow IT candidates <span className="font-normal muted">({candidates.length} · {usd(shadowCost)}/yr)</span></>}
          subtitle="Names seen in invoices, expense claims or SSO logs that match no inventory or CMDB record."
          actions={
            <button className="btn-primary btn-sm" disabled={!run || busy !== null || candidates.length === 0} onClick={() => send("owners", ["confirm_app"], "candidates")} data-testid="send-owners">
              {busy === "owners" ? "Sending…" : `Send to owners for confirmation${unsentCandidates ? ` (${unsentCandidates} new)` : ""}`}
            </button>
          }
        >
          {candidates.length === 0 ? <Empty>No unknown applications found.</Empty> : (
            <div className="overflow-x-auto rounded border border-gray-200">
              <table className="tbl">
                <thead>
                  <tr><th>Candidate</th><th>Raw names</th><th>Seen in</th><th className="text-right">Annual cost</th><th>Conf.</th><th>Evidence</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {candidates.map((c) => (
                    <tr key={c.app_id}>
                      <td className="min-w-[12rem]">
                        <div className="flex flex-wrap items-center gap-1">
                          <span className="font-medium text-gray-900">{c.candidate_name}</span>
                          {c.genai && <Badge color="purple">GenAI</Badge>}
                          {c.paid_via_expense && <Badge color="amber" title="Paid through employee expense claims, not procurement">paid via expense</Badge>}
                        </div>
                        <div className="font-mono text-[11px] muted">{c.app_id}</div>
                      </td>
                      <td className="max-w-[13rem]">
                        <div className="font-mono text-[11px] text-gray-600">{(c.raw_names || []).slice(0, 4).join(" · ")}{c.raw_names?.length > 4 ? ` +${c.raw_names.length - 4}` : ""}</div>
                      </td>
                      <td><div className="flex gap-1">{(c.sources || []).map((s: string) => <Badge key={s}>{SOURCE_LABEL[s] || s}</Badge>)}</div></td>
                      <td className="text-right tabular-nums">{usd(c.annual_cost_usd)}</td>
                      <td><ConfidenceBadge value={c.confidence} /></td>
                      <td className="min-w-[19rem]"><EvidenceList refs={c.source_refs} max={4} /><div className="text-[11px] leading-snug muted">{c.evidence}</div></td>
                      <td className="whitespace-nowrap">{c.approval ? <ApprovalControls approval={c.approval} /> : <Badge>observed</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        <Section
          title={<>CMDB clean-up <span className="font-normal muted">({dups.length} duplicates · {stale.length} stale)</span></>}
          subtitle="Duplicate configuration items to merge and operational CIs that nothing else references."
          actions={
            <button className="btn btn-sm" disabled={!run || busy !== null || dups.length + stale.length === 0} onClick={() => send("cmdb", ["merge_cmdb_ci", "retire_cmdb_ci"], "CMDB clean-up items")} data-testid="send-cmdb">
              {busy === "cmdb" ? "Sending…" : `Send CMDB clean-up to architect${unsentCmdb ? ` (${unsentCmdb} new)` : ""}`}
            </button>
          }
        >
          <div className="grid gap-3 2xl:grid-cols-2">
            <div className="overflow-x-auto rounded border border-gray-200">
              <table className="tbl">
                <thead><tr><th>Duplicate CI</th><th>Keep</th><th>Application</th><th>Conf.</th><th>Status</th></tr></thead>
                <tbody>
                  {dups.map((d) => (
                    <tr key={d.ci_id}>
                      <td className="whitespace-nowrap"><EvidenceChip id={d.ci_id} /><div className="text-[11px] muted">{d.raw_names?.join(" / ")}</div></td>
                      <td className="whitespace-nowrap">{d.keep_ci_id && <EvidenceChip id={d.keep_ci_id} />}</td>
                      <td className="whitespace-nowrap">{d.app_id && <EvidenceChip id={d.app_id} />}</td>
                      <td><ConfidenceBadge value={d.confidence} /></td>
                      <td className="whitespace-nowrap">{d.approval ? <ApprovalControls approval={d.approval} compact /> : <Badge>observed</Badge>}</td>
                    </tr>
                  ))}
                  {dups.length === 0 && <tr><td colSpan={5} className="muted text-center">none</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="overflow-x-auto rounded border border-gray-200">
              <table className="tbl">
                <thead><tr><th>Stale CI</th><th>Why</th><th>Conf.</th><th>Status</th></tr></thead>
                <tbody>
                  {stale.map((d) => (
                    <tr key={d.ci_id}>
                      <td className="whitespace-nowrap"><EvidenceChip id={d.ci_id} /><div className="text-[11px] muted">{d.raw_names?.join(" / ")}</div></td>
                      <td className="text-xs text-gray-700">{d.evidence}</td>
                      <td><ConfidenceBadge value={d.confidence} /></td>
                      <td className="whitespace-nowrap">{d.approval ? <ApprovalControls approval={d.approval} compact /> : <Badge>observed</Badge>}</td>
                    </tr>
                  ))}
                  {stale.length === 0 && <tr><td colSpan={4} className="muted text-center">none</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </Section>

        <details className="rounded border border-gray-200">
          <summary className="cursor-pointer select-none px-3 py-2 text-sm font-semibold text-gray-900">
            Alias merges <span className="font-normal muted">({aliases.length} applications · {aliases.reduce((s, a) => s + (a.raw_names?.length || 0), 0)} raw names reconciled)</span>
          </summary>
          <div className="overflow-x-auto border-t border-gray-200">
            <table className="tbl">
              <thead><tr><th>Application</th><th>Raw names reconciled</th><th>How</th><th>Conf.</th><th>Evidence</th></tr></thead>
              <tbody>
                {aliases.map((a) => (
                  <tr key={a.app_id}>
                    <td className="whitespace-nowrap"><EvidenceChip id={a.app_id} /></td>
                    <td className="font-mono text-[11px] text-gray-600 max-w-[26rem]">{a.raw_names?.join(" · ")}</td>
                    <td className="text-xs text-gray-700">{a.evidence}</td>
                    <td><ConfidenceBadge value={a.confidence} /></td>
                    <td><EvidenceList refs={a.source_refs?.slice(1)} max={3} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    </AgentPanel>
  );
}
