"""dai.governance_policy_checker — evaluate machine-checkable data policy predicates."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class PolicyFinding(Finding):
    policy_id: str
    subject_id: str
    subject_type: str
    severity: str
    fix: str


FIX_ACTION = {
    "pii_requires_retention": "set_retention", "retention_max": "set_retention", "retention_min": "set_retention",
    "no_restricted_nonprod": "apply_masking", "masking_nonprod": "apply_masking", "no_bi_direct_pii": "apply_masking",
    "owner_required": "assign_owner", "cross_zone": "block_pipeline", "residency": "block_pipeline",
    "pci_scope": "block_pipeline", "cpni_marketing": "block_pipeline", "ai_eval_required": "block_pipeline",
}


class GovernancePolicyChecker(Agent):
    id = "dai.governance_policy_checker"
    name = "Governance Policy Checker"
    domain = "data_ai"
    description = ("Evaluates data policy predicates: PII without retention, retention over/under policy, restricted data "
                   "in non-production, BI reading PII directly, datasets without owner, residency, PCI scope, CPNI use.")
    inputs = ["datasets", "pipelines", "bi_assets", "data_policies", "ai_assets", "ai_usecases"]
    outputs = "PolicyFinding"
    finding_model = PolicyFinding
    approver_role = "data_governance_lead"
    default_autonomy = 2
    demo_trigger = "Check policies"
    action_types = ["apply_masking", "set_retention", "assign_owner", "block_pipeline"]
    max_actions = 80

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        ds = ctx.repo.by_id("datasets")
        pipelines = ctx.repo.all("pipelines")
        bi = ctx.repo.all("bi_assets")
        apps = ctx.repo.by_id("applications")
        findings: list[PolicyFinding] = []

        def add(pol: dict, subject: dict, stype: str, fix: str, excerpt: str, extra_refs: list | None = None) -> None:
            refs = [ev(subject["id"], stype, excerpt), ev(pol["id"], "data_policies", pol["title"])] + (extra_refs or [])
            findings.append(PolicyFinding(policy_id=pol["id"], subject_id=subject["id"], subject_type=stype,
                                          severity=pol["severity"], fix=fix, source_refs=refs, policy_title=pol["title"],
                                          regulation=pol["regulation"], subject_name=subject.get("name"),
                                          check=pol["check"]["type"]))

        for pol in ctx.repo.all("data_policies"):
            chk = pol["check"]
            t = chk["type"]
            tag = chk.get("tag")

            def tagged(d: dict, tag: str | None = tag) -> bool:
                return tag is None or tag in (d["tags"] or [])

            if t == "pii_requires_retention":
                for d in ds.values():
                    if d["pii"] and d["retention_days"] is None:
                        add(pol, d, "datasets", "Set a retention period aligned to the privacy schedule",
                            f"{d['name']}: PII, retention not set")
            elif t == "retention_max":
                for d in ds.values():
                    if d["retention_days"] and d["retention_days"] > chk["days"] and tagged(d) and \
                            (not chk.get("pii") or d["pii"]) and (not chk.get("domains") or d["domain"] in chk["domains"]):
                        add(pol, d, "datasets", f"Reduce retention to {chk['days']} days and purge older records",
                            f"{d['name']}: retention {d['retention_days']} days > {chk['days']}")
            elif t == "retention_min":
                for d in ds.values():
                    if tagged(d) and d["retention_days"] is not None and d["retention_days"] < chk["days"]:
                        add(pol, d, "datasets", f"Extend retention to at least {chk['days']} days",
                            f"{d['name']}: retention {d['retention_days']} days < {chk['days']}")
            elif t in ("no_restricted_nonprod", "masking_nonprod"):
                for p in pipelines:
                    outs = [ds[o] for o in p["outputs"]]
                    ins = [ds[i] for i in p["inputs"]]
                    if any(o["environment"] == "nonprod" for o in outs) and \
                            any(i["classification"] == "restricted" or i["pii"] for i in ins):
                        if t == "masking_nonprod" and not any(i["pii"] for i in ins):
                            continue
                        add(pol, p, "pipelines", "Mask or synthesise personal fields before loading non-production; block until fixed",
                            f"{p['name']} copies {ins[0]['name']} ({ins[0]['classification']}) into non-production",
                            [ev(ins[0]["id"], "datasets", ins[0]["name"]), ev(outs[0]["id"], "datasets", outs[0]["name"])])
            elif t == "no_bi_direct_pii":
                for b in bi:
                    for i in b["dataset_ids"]:
                        if ds[i]["pii"] and ds[i]["layer"] == "source":
                            add(pol, b, "bi_assets", "Re-point the dashboard to a curated, de-identified dataset",
                                f"{b['name']} ({b['tool']}) reads PII source {ds[i]['name']}", [ev(i, "datasets", ds[i]["name"])])
            elif t == "owner_required":
                for d in ds.values():
                    if not d["owner_user_id"] and tagged(d):
                        add(pol, d, "datasets", "Assign an accountable data owner", f"{d['name']}: no owner")
            elif t == "cross_zone":
                for p in pipelines:
                    ins = [ds[i] for i in p["inputs"]]
                    outs = [ds[o] for o in p["outputs"]]
                    if not p["approved_cross_zone"] and any(tag in (i["tags"] or []) for i in ins) and \
                            any(o["zone"] != i["zone"] for o in outs for i in ins):
                        add(pol, p, "pipelines", "Block the direct extract; route through the OT DMZ historian replica",
                            f"{p['name']} moves {ins[0]['name']} from OT to IT without an approved cross-zone path",
                            [ev(ins[0]["id"], "datasets", ins[0]["name"])])
            elif t == "residency":
                for d in ds.values():
                    if tagged(d) and d["region"] != chk["region"]:
                        add(pol, d, "datasets", f"Stop the export and keep subscriber data in {chk['region']}",
                            f"{d['name']} stored in {d['region']} by {apps[d['system_app_id']]['name']}")
            elif t == "pci_scope":
                for d in ds.values():
                    if tagged(d) and d["layer"] != "source":
                        add(pol, d, "datasets", "Remove cardholder data from the analytics platform; tokenise at source",
                            f"{d['name']} ({d['layer']}) copied outside the PCI zone")
            elif t == "cpni_marketing":
                marketing_apps = {a["id"] for a in apps.values() if "Marketing" in a["category"] or a["category"] == "Customer data platform"}
                for p in pipelines:
                    ins = [ds[i] for i in p["inputs"]]
                    outs = [ds[o] for o in p["outputs"]]
                    if any("cpni" in (i["tags"] or []) for i in ins) and any(o["system_app_id"] in marketing_apps for o in outs) \
                            and not all(o["has_contract"] for o in outs) and ins[0]["domain"] != outs[0]["domain"]:
                        add(pol, p, "pipelines", "Block the feed until consent filtering and a data contract are in place",
                            f"{p['name']} sends CPNI {ins[0]['name']} to marketing dataset {outs[0]['name']}")
            elif t == "ai_eval_required":
                ucs = ctx.repo.by_id("ai_usecases")
                for a in ctx.repo.all("ai_assets"):
                    uc = ucs.get(a["usecase_id"]) if a["usecase_id"] else None
                    if uc and "customer_facing" in (uc["tags"] or []) and a["eval_status"] != "passed":
                        add(pol, a, "ai_assets", "Complete evaluation before production use",
                            f"{a['name']} serves customer-facing '{uc['title']}' with eval_status={a['eval_status']}")

        actions: list[ProposedAction] = []
        policies = ctx.repo.by_id("data_policies")
        for f in findings:
            act = FIX_ACTION[f.check]
            if f.subject_type == "datasets" and act == "block_pipeline":
                act = "apply_masking" if f.check == "pci_scope" else "block_pipeline"
            payload = {"policy_id": f.policy_id, "fix": f.fix, "subject_type": f.subject_type}
            if act == "set_retention":
                payload["retention_days"] = policies[f.policy_id]["check"].get("days", 1825)
            if act == "assign_owner":
                d = ds.get(f.subject_id)
                payload["owner_user_id"] = next((x["owner_user_id"] for x in ds.values() if d and x["domain"] == d["domain"] and x["owner_user_id"]), None)
            actions.append(ProposedAction(action_type=act, target_id=f.subject_id, target_type=f.subject_type,
                                          payload=payload, rationale=f"{f.policy_id} {f.policy_title}: {f.source_refs[0].excerpt}",
                                          source_refs=f.source_refs, approver_role="data_governance_lead",
                                          priority=1 if f.severity == "critical" else (2 if f.severity == "high" else 3)))
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        findings.sort(key=lambda f: (sev_order.get(f.severity, 4), f.policy_id))
        by_policy: dict[str, int] = {}
        for f in findings:
            by_policy[f.policy_id] = by_policy.get(f.policy_id, 0) + 1
        facts = {"count": len(findings), "critical": sum(1 for f in findings if f.severity == "critical"),
                 "high": sum(1 for f in findings if f.severity == "high"), "by_policy": by_policy,
                 "examples": [{"policy": f.policy_id, "ref": f.subject_id, "text": f.source_refs[0].excerpt} for f in findings[:3]]}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.93)
