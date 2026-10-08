"""app.drift_detector — declared vs actual dependencies, unapproved integrations, boundary violations."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.kg.export import drift_diagrams


class DriftFinding(Finding):
    app_id: str
    type: str  # undeclared_dependency | unapproved_integration | boundary_violation
    details: str
    standard_id: str


class DriftDetector(Agent):
    id = "app.drift_detector"
    name = "Drift Detector"
    domain = "application"
    description = ("Compares declared vs runtime dependencies from repositories, finds unapproved integrations and "
                   "direct DB links across restricted boundaries (IT/OT, BSS/OSS); renders intended vs actual diagrams.")
    inputs = ["repos", "integrations", "applications"]
    outputs = "DriftFinding"
    finding_model = DriftFinding
    approver_role = "security_architect"
    default_autonomy = 3
    demo_trigger = "Detect drift"
    action_types = ["create_remediation_ticket", "approve_exception"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        apps = ctx.repo.by_id("applications")
        boundary_std = "STD-OT-01" if ctx.repo.get("standards", "STD-OT-01") else "STD-BSS-01"
        label = ctx.tenant["boundary_label"]
        findings, actions = [], []
        db_links = {(i["from_app_id"], i["to_app_id"]): i for i in ctx.repo.all("integrations") if i["pattern"] == "db_link"}
        boundary_pairs = set()
        for i in sorted(db_links.values(), key=lambda i: (not i["crosses_boundary"], i["id"])):
            a, b = apps[i["from_app_id"]], apps[i["to_app_id"]]
            refs = [ev(i["id"], "integrations", f"{a['name']} -> {b['name']}: {i['description']}"),
                    ev(a["id"], "applications", f"{a['name']} ({a['zone']})"), ev(b["id"], "applications", f"{b['name']} ({b['zone']})")]
            if i["crosses_boundary"]:
                boundary_pairs.add((a["id"], b["id"]))
                det = f"Direct DB link across the {label} boundary: {i['description']}"
                findings.append(DriftFinding(app_id=a["id"], type="boundary_violation", details=det, standard_id=boundary_std,
                                             source_refs=refs, integration_id=i["id"], to_app_id=b["id"], severity="critical"))
                actions.append(ProposedAction(action_type="create_remediation_ticket", target_id=i["id"], target_type="Integration",
                                              payload={"title": f"Remove {label} boundary DB link {a['name']} -> {b['name']}",
                                                       "standard_id": boundary_std, "severity": "critical"},
                                              rationale=det + f" violates {boundary_std} and STD-INT-02.", source_refs=refs,
                                              approver_role="security_architect", priority=1))
            else:
                det = f"Unapproved direct database link: {i['description']}"
                findings.append(DriftFinding(app_id=a["id"], type="unapproved_integration", details=det, standard_id="STD-INT-02",
                                             source_refs=refs, integration_id=i["id"], to_app_id=b["id"], severity="high"))
                actions.append(ProposedAction(action_type="create_remediation_ticket", target_id=i["id"], target_type="Integration",
                                              payload={"title": f"Replace DB link {a['name']} -> {b['name']} with API/events",
                                                       "standard_id": "STD-INT-02", "severity": "high"},
                                              rationale=det + " (STD-INT-02).", source_refs=refs,
                                              approver_role="security_architect", priority=2))
        for i in ctx.repo.all("integrations"):
            if i["pattern"] != "db_link" and not i["approved"]:
                a, b = apps[i["from_app_id"]], apps[i["to_app_id"]]
                refs = [ev(i["id"], "integrations", f"{a['name']} -> {b['name']} ({i['pattern']}, not approved)")]
                findings.append(DriftFinding(app_id=a["id"], type="unapproved_integration",
                                             details=f"{i['pattern']} integration to {b['name']} not in the approved catalogue",
                                             standard_id="STD-INT-03", source_refs=refs, integration_id=i["id"], to_app_id=b["id"],
                                             severity="medium"))
                actions.append(ProposedAction(action_type="approve_exception", target_id=i["id"], target_type="Integration",
                                              payload={"standard_id": "STD-INT-03", "pattern": i["pattern"]},
                                              rationale=f"Register and approve (or remove) the {i['pattern']} integration {a['name']} -> {b['name']}.",
                                              source_refs=refs, approver_role="security_architect", priority=4))
        for r in ctx.repo.all("repos"):
            undeclared = sorted(set(r["actual_dependencies"]) - set(r["declared_dependencies"]))
            for dep in undeclared:
                if (r["app_id"], dep) in db_links:
                    continue
                refs = [ev(r["id"], "repos", f"{r['name']}: runtime dependency on {apps[dep]['name']} not declared")]
                findings.append(DriftFinding(app_id=r["app_id"], type="undeclared_dependency",
                                             details=f"{apps[r['app_id']]['name']} calls {apps[dep]['name']} at runtime but does not declare it",
                                             standard_id="STD-INT-03", source_refs=refs, repo_id=r["id"], to_app_id=dep, severity="low"))
        order = {"boundary_violation": 0, "unapproved_integration": 1, "undeclared_dependency": 2}
        findings.sort(key=lambda f: (order[f.type], f.app_id))
        focus = sorted({f.app_id for f in findings if f.type != "undeclared_dependency"} |
                       {f.to_app_id for f in findings if f.type == "boundary_violation"})
        diagrams = drift_diagrams(ctx.kg, focus[:14], boundary_pairs)
        facts = {"boundary": sum(1 for f in findings if f.type == "boundary_violation"),
                 "unapproved": sum(1 for f in findings if f.type == "unapproved_integration"),
                 "undeclared": sum(1 for f in findings if f.type == "undeclared_dependency"), "label": label,
                 "boundary_refs": [f.integration_id for f in findings if f.type == "boundary_violation"]}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.9, artifacts=diagrams)
