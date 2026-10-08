import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { ROLE_LABELS, useApi, useApp } from "../../state/AppState";
import { AgentPanel, ApprovalControls } from "../AgentPanel";
import { EvidenceChip, EvidenceList, TextWithChips } from "../Evidence";
import { Badge, Card, Empty, ErrorBox, Loading, SeverityBadge, since } from "../ui";
import { getUrlParam, HighlightedMarkdown, IdChips, setUrlParam, useRunMeta, VerdictBadge } from "./common";
import { ThreatTable } from "./ThreatModels";

export function DesignReviews() {
  const { data, loading, error } = useApi<any>("/app/designs");
  const [sel, setSel] = useState<string | null>(getUrlParam("design"));
  const [filter, setFilter] = useState("");
  const items: any[] = data?.items || [];
  const shown = items.filter((d) => !filter || (filter === "pending" ? d.status === "submitted" : d.review?.verdict === filter));
  const pick = (id: string | null) => {
    setSel(id);
    setUrlParam("design", id);
  };
  return (
    <div className="space-y-4">
      <Card
        title="Design submissions"
        subtitle={`${items.length} designs · ${items.filter((d) => d.status === "submitted").length} awaiting review · reviewed against architecture standards by app.design_review`}
        actions={
          <select className="input py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All</option>
            <option value="pending">Submitted (pending)</option>
            <option value="changes_required">Changes required</option>
            <option value="pass_with_conditions">Pass with conditions</option>
            <option value="pass">Pass</option>
          </select>
        }
      >
        <ErrorBox error={error} />
        {loading && !data && <Loading />}
        <div className="max-h-80 overflow-auto -m-4">
          <table className="tbl">
            <thead className="sticky top-0">
              <tr><th>Id</th><th>Title</th><th>Team</th><th>Status</th><th>Submitted</th><th>Verdict</th><th>Concerns</th><th>Review approval</th></tr>
            </thead>
            <tbody>
              {shown.map((d) => (
                <tr key={d.id} onClick={() => pick(d.id)} className={`cursor-pointer ${sel === d.id ? "!bg-accent-50" : ""}`}>
                  <td className="font-mono text-xs whitespace-nowrap">{d.id}</td>
                  <td className="font-medium">{d.title}</td>
                  <td className="text-xs">{d.team}</td>
                  <td><Badge color={d.status === "approved" ? "green" : d.status === "submitted" ? "blue" : "gray"}>{d.status}</Badge></td>
                  <td className="text-xs whitespace-nowrap">{(d.submitted_at || "").slice(0, 10)}</td>
                  <td><VerdictBadge verdict={d.review?.verdict} /></td>
                  <td className="text-center">{d.review ? <Badge color={d.review.concerns.length ? "red" : "green"}>{d.review.concerns.length}</Badge> : <span className="muted text-xs">—</span>}</td>
                  <td onClick={(e) => e.stopPropagation()}>{d.review ? <ApprovalControls approval={d.approval} compact /> : <span className="text-[11px] muted">{d.reviewed_at ? `reviewed ${d.reviewed_at.slice(0, 10)}` : "—"}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {sel ? <DesignDetail id={sel} onClose={() => pick(null)} /> : <Card><Empty>Select a design to see the full text with inline review highlights.</Empty></Card>}
    </div>
  );
}

function DesignDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { user, notify, refresh } = useApp();
  const { data: d, loading, error } = useApi<any>(`/app/designs/${id}`, undefined, [id]);
  const review = d?.review;
  const SEV: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const concerns: any[] = [...(review?.concerns || [])].sort((a, b) => (SEV[a.severity] ?? 9) - (SEV[b.severity] ?? 9));
  const runMeta = useRunMeta(
    "app.design_review",
    review?.run_id,
    review ? `Verdict for ${d.title} [${id}]: ${review.verdict.replace(/_/g, " ")} — ${concerns.length} concern${concerns.length === 1 ? "" : "s"} mapped to standards.` : undefined,
  );
  const highlights = useMemo(() => concerns.map((c) => ({ text: c.excerpt, label: c.standard_id, severity: c.severity })), [concerns]);
  const body: string = d?.body_md || "";
  const unplaced = concerns.filter((c) => !c.excerpt || !body.includes(c.excerpt));

  const requestException = async (c: any) => {
    const rationale = window.prompt(`Rationale for an exception to ${c.standard_id} (${c.standard_title}) on ${id}:`, `Request a time-boxed exception to ${c.standard_id} for ${d.title}.`);
    if (!rationale) return;
    try {
      const r = await api.post("/approvals", {
        action_type: "request_exception",
        target_id: id,
        target_type: "Design",
        rationale,
        source_refs: [{ record_id: id, table: "design_docs", excerpt: c.excerpt }, { record_id: c.standard_id, table: "standards", excerpt: c.standard_title }],
        approver_role: "security_architect",
        payload: { standard_id: c.standard_id },
        user_id: user?.id,
      });
      notify(`Exception request ${r.approval_ids?.[0] || ""} sent to the Security Architect`);
      refresh();
    } catch (e: any) {
      notify(e.message);
    }
  };

  if (loading && !d) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!d) return null;
  const approvals: any[] = d.approvals || [];
  const tm = d.threat_model;
  const tmFinding = tm?.findings?.[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <EvidenceChip id={d.id} />
          <h2>{d.title}</h2>
          <Badge>{d.team}</Badge>
          <Badge color={d.status === "approved" ? "green" : "blue"}>{d.status}</Badge>
          <VerdictBadge verdict={review?.verdict} />
        </div>
        <button className="btn btn-sm" onClick={onClose}>Close</button>
      </div>
      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3" title="Design document" subtitle={<>submitted {(d.submitted_at || "").replace("T", " ")} · apps <IdChips ids={d.app_ids} /></>}>
          <div className="mb-2 flex flex-wrap gap-1 text-xs">
            <span className="muted">Components:</span>
            {(d.components || []).map((c: string) => <Badge key={c}>{c}</Badge>)}
          </div>
          <HighlightedMarkdown text={body} highlights={highlights} />
          {concerns.length > 0 && (
            <div className="mt-3 flex gap-3 text-[11px] muted border-t border-gray-100 pt-2">
              <span><mark className="bg-red-100 ring-1 ring-red-200 px-1 rounded">high</mark> concern</span>
              <span><mark className="bg-yellow-100 ring-1 ring-yellow-200 px-1 rounded">medium/low</mark> concern</span>
            </div>
          )}
          {unplaced.length > 0 && (
            <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-xs">
              <div className="font-medium text-amber-900 mb-1">Concerns not tied to a specific passage</div>
              <ul className="space-y-0.5">
                {unplaced.map((c) => (
                  <li key={c.standard_id}><EvidenceChip id={c.standard_id} /> {c.excerpt}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
        <div className="xl:col-span-2 space-y-4">
          <AgentPanel agentId="app.design_review" agentName="Design Review Agent" run={runMeta} params={{ design_id: id }} runLabel={review ? "Re-run review" : "Run review"} compact>
            {!review && <div className="text-sm muted">No review yet. Run the review to check this design against the standards.</div>}
            {review && (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="label">Verdict</span>
                  <VerdictBadge verdict={review.verdict} />
                  <span className="label ml-2">Publish review</span>
                  <ApprovalControls approval={approvals.find((a) => a.action_type === "publish_review") || d.approval} />
                </div>
                {concerns.length === 0 && <div className="text-sm text-green-700">No concerns: the design conforms to all checked standards.</div>}
                <ul className="space-y-2">
                  {concerns.map((c) => (
                    <li key={c.standard_id} className={`rounded border p-2 ${c.severity === "high" || c.severity === "critical" ? "border-red-200 bg-red-50/40" : "border-amber-200 bg-amber-50/40"}`}>
                      <div className="flex flex-wrap items-center justify-between gap-1">
                        <div className="flex flex-wrap items-center gap-1">
                          <EvidenceChip id={c.standard_id} />
                          <span className="text-sm font-medium">{c.standard_title}</span>
                          <SeverityBadge severity={c.severity} />
                        </div>
                        <button className="btn btn-sm" onClick={() => requestException(c)}>Request exception</button>
                      </div>
                      {c.excerpt && <div className="mt-1 text-xs italic text-gray-600">“{c.excerpt}”</div>}
                      <div className="mt-1 text-xs text-gray-800"><span className="font-medium">Recommendation: </span><TextWithChips text={c.recommendation} /></div>
                    </li>
                  ))}
                </ul>
                {review.reuse_suggestions?.length > 0 && (
                  <div>
                    <div className="label mb-1">Reuse existing APIs</div>
                    <div className="flex flex-wrap gap-2">
                      {review.reuse_suggestions.map((a: string, i: number) => (
                        <span key={a} className="inline-flex items-center text-xs"><EvidenceChip id={a} />{review.reuse_names?.[i]}</span>
                      ))}
                    </div>
                  </div>
                )}
                <div className="text-xs"><span className="muted">Evidence: </span><EvidenceList refs={review.source_refs} max={10} /></div>
              </div>
            )}
          </AgentPanel>
          {approvals.length > 0 && (
            <Card title="Decisions on this design">
              <ul className="-my-2 divide-y divide-gray-100">
                {approvals.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span className="flex items-center gap-1">
                      <Badge color="blue">{(a.action_type || "").replace(/_/g, " ")}</Badge>
                      <EvidenceChip id={a.id} />
                      <span className="text-[11px] muted">{ROLE_LABELS[a.approver_role] || a.approver_role}</span>
                    </span>
                    <ApprovalControls approval={a} compact />
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
      <AgentPanel
        agentId="app.threat_model_assistant"
        title="Threat model (STRIDE)"
        run={tm || null}
        params={{ design_id: id }}
        runLabel={tm ? "Re-run threat model" : "Run threat model"}
      >
        {tmFinding ? (
          <>
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="muted">Publish:</span>
              <ApprovalControls approval={approvals.find((a) => a.action_type === "publish_threat_model")} />
              {tm.started_at && <span className="muted">model from {since(tm.started_at)}</span>}
            </div>
            <ThreatTable threats={tmFinding.threats} />
          </>
        ) : (
          <div className="text-sm muted">No threat model for this design yet.</div>
        )}
      </AgentPanel>
    </div>
  );
}
