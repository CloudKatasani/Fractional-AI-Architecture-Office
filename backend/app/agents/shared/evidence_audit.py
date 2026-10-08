"""shared.evidence_audit — evidence pack for a regulation or policy: controls, findings, approvals, approvers."""

from __future__ import annotations

import json

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ev
from app.agents.data_ai.ai_risk_classifier import classify


class EvidenceItem(Finding):
    control: str
    status: str  # compliant | open_findings | remediation_approved | not_assessed
    detail: str


class EvidenceAudit(Agent):
    id = "shared.evidence_audit"
    name = "Evidence and Audit Agent"
    domain = "shared"
    description = ("Assembles an evidence pack for a regulation or policy: applicable controls, current findings, "
                   "approvals with timestamps and approvers; exports markdown and JSON.")
    inputs = ["data_policies", "agent_runs", "approvals", "audit_events", "ai_usecases", "applications"]
    outputs = "EvidenceItem"
    finding_model = EvidenceItem
    approver_role = None
    default_autonomy = 1
    demo_trigger = "Generate evidence pack"
    params_spec = [{"name": "regulation_or_policy_id", "label": "Regulation or policy", "kind": "select", "source": "regulations"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        target = ctx.params.get("regulation_or_policy_id") or ctx.catalog["evidence_regulations"][0]
        policies = [p for p in ctx.repo.all("data_policies") if p["id"] == target or p["regulation"] == target]
        regulation = policies[0]["regulation"] if policies and policies[0]["id"] == target else target
        approvals = ctx.repo.all("approvals")
        users = ctx.repo.by_id("users")
        gov = ctx.latest_output("dai.governance_policy_checker")
        gov_findings = gov["findings"] if gov else []
        items: list[EvidenceItem] = []
        decided_log = []

        def appr_for(subject_ids: set[str], agent: str | None = None) -> list[dict]:
            return [a for a in approvals if a["target_id"] in subject_ids and (agent is None or a["agent_id"] == agent)]

        for p in policies:
            fs = [f for f in gov_findings if f["policy_id"] == p["id"]]
            subj = {f["subject_id"] for f in fs}
            aps = appr_for(subj, "dai.governance_policy_checker")
            done = {a["target_id"] for a in aps if a["status"] in ("approved", "edited")}
            open_ = [f for f in fs if f["subject_id"] not in done]
            status = "compliant" if gov and not fs else ("remediation_approved" if fs and not open_ else
                                                          ("open_findings" if fs else "not_assessed"))
            refs = [ev(p["id"], "data_policies", p["rule"])]
            refs += [ev(f["subject_id"], f["subject_type"], f["source_refs"][0]["excerpt"]) for f in open_[:3]]
            refs += [ev(a["id"], "approvals", f"{a['status']} by {users.get(a['decided_by_user_id'], {}).get('name', '-')} at {a['decided_at']}")
                     for a in aps if a["status"] != "pending"][:3]
            if gov:
                refs.append(ev(gov["run_id"], "agent_runs", "dai.governance_policy_checker run"))
            items.append(EvidenceItem(control=f"{p['id']} {p['title']}", status=status, source_refs=refs,
                                      detail=f"{len(fs)} findings, {len(open_)} open, {len(done)} remediations approved.",
                                      policy_id=p["id"], findings=len(fs), open=len(open_)))
            decided_log += [a for a in aps if a["status"] != "pending"]

        # AI controls whose rule maps to this regulation (from the risk rule table)
        regs = ctx.risk_rules["tenant_regulations"].get(ctx.tenant_id, {})
        rule_ids = [r for r, name in regs.items() if name == regulation]
        if rule_ids:
            for u in ctx.repo.all("ai_usecases"):
                c = classify(ctx, u)
                if not any(t["rule_id"] in rule_ids for t in c["triggers"]):
                    continue
                aps = appr_for({u["id"]}, "dai.ai_risk_classifier")
                ok = [a for a in aps if a["status"] in ("approved", "edited")]
                status = "remediation_approved" if ok else "open_findings"
                refs = [ev(u["id"], "ai_usecases", f"{u['title']} → {c['tier']} ({', '.join(t['rule_id'] for t in c['triggers'])})")]
                refs += [ev(a["id"], "approvals", f"tier {a['payload_json'].get('tier')} {a['status']} by "
                                                  f"{users.get(a['decided_by_user_id'], {}).get('name', '-')} at {a['decided_at']}") for a in aps][:2]
                items.append(EvidenceItem(control=f"AI risk tiering: {u['title']}", status=status, source_refs=refs,
                                          detail=f"Tier {c['tier']}; required controls " + ", ".join(x["id"] for x in c["controls"]),
                                          usecase_id=u["id"], tier=c["tier"]))
                decided_log += [a for a in aps if a["status"] != "pending"]
        # Applications in scope of the regulation
        in_scope = [a for a in ctx.repo.all("applications") if regulation in (a["regulatory_scope"] or [])]
        if in_scope:
            items.append(EvidenceItem(control=f"Systems in scope of {regulation}", status="compliant" if in_scope else "not_assessed",
                                      source_refs=[ev(a["id"], "applications", a["name"]) for a in in_scope[:6]],
                                      detail=f"{len(in_scope)} applications tagged with {regulation}: " + ", ".join(a["name"] for a in in_scope[:8])))
        if not items:
            items.append(EvidenceItem(control=f"{regulation}", status="not_assessed", detail="No controls mapped to this regulation yet.",
                                      source_refs=[ev(target, "data_policies", "no mapped controls")]))
        md = [f"# Evidence pack — {regulation}", "", f"Tenant: {ctx.tenant['name']} · generated {ctx.today.isoformat()} · run {ctx.run_id}", "",
              "| Control | Status | Detail | Evidence |", "|---|---|---|---|"]
        for it in items:
            md.append(f"| {it.control} | {it.status.replace('_', ' ')} | {it.detail} | " + ", ".join(f"[{r.record_id}]" for r in it.source_refs[:5]) + " |")
        md += ["", "## Decision log", "| Approval | Action | Target | Decision | Approver | Timestamp |", "|---|---|---|---|---|---|"]
        for a in sorted(decided_log, key=lambda a: a["decided_at"] or ""):
            md.append(f"| {a['id']} | {a['action_type']} | {a['target_id']} | {a['status']} | "
                      f"{users.get(a['decided_by_user_id'], {}).get('name', '-')} | {a['decided_at']} |")
        if not decided_log:
            md.append("| — | — | — | no decisions recorded yet | — | — |")
        body = "\n".join(md)
        pack_json = {"regulation": regulation, "tenant": ctx.tenant_id, "generated": ctx.today.isoformat(),
                     "controls": [i.model_dump() for i in items], "decisions": [
                         {k: a[k] for k in ("id", "action_type", "target_id", "status", "decided_by_user_id", "decided_at")} for a in decided_log]}
        facts = {"regulation": regulation, "controls": len(items), "open": sum(1 for i in items if i.status == "open_findings"),
                 "decisions": len(decided_log)}
        return AnalysisResult(findings=items, facts=facts, confidence=0.9,
                              artifacts={"body_md": body, "json": json.loads(json.dumps(pack_json, default=str))})

    def narrative_key(self, ctx: AgentContext) -> str:
        return "default"
