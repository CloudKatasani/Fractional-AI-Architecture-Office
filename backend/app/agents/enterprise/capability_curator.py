"""ea.capability_curator — capability heat map (importance x (5 - maturity)) and app coverage."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class CapabilityAssessment(Finding):
    capability_id: str
    heat_score: int
    app_count: int
    flags: list[str]


class CapabilityCurator(Agent):
    id = "ea.capability_curator"
    name = "Capability Map Curator"
    domain = "enterprise"
    description = ("Computes the capability heat map (importance x (5 - maturity)), counts realising applications and "
                   "flags capabilities with no application or more than six.")
    inputs = ["capabilities", "applications"]
    outputs = "CapabilityAssessment"
    finding_model = CapabilityAssessment
    approver_role = "principal_architect"
    default_autonomy = 2
    demo_trigger = "Assess capabilities"
    action_types = ["update_capability_scores"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        kg = ctx.kg
        caps = ctx.repo.all("capabilities")
        apps = ctx.repo.by_id("applications")
        findings, actions = [], []
        for c in caps:
            app_ids = kg.apps_for_capability(c["id"], include_children=True)
            direct = kg.apps_for_capability(c["id"], include_children=False)
            heat = c["strategic_importance"] * (5 - c["maturity"])
            flags = []
            if not app_ids:
                flags.append("no_applications")
            if c["level"] >= 2 and len(app_ids) > 6:
                flags.append("too_many_applications")
            if heat >= 12:
                flags.append("hot_spot")
            if c["strategic_importance"] >= 4 and c["maturity"] <= 2:
                flags.append("strategic_gap")
            refs = [ev(c["id"], "capabilities", f"{c['name']}: importance {c['strategic_importance']}, maturity {c['maturity']}")]
            refs += [ev(a, "applications", apps[a]["name"]) for a in app_ids[:3]]
            findings.append(CapabilityAssessment(capability_id=c["id"], heat_score=heat, app_count=len(app_ids), flags=flags,
                                                 source_refs=refs, name=c["name"], level=c["level"], parent_id=c["parent_id"],
                                                 importance=c["strategic_importance"], maturity=c["maturity"],
                                                 direct_app_count=len(direct), app_ids=app_ids[:20],
                                                 annual_cost_usd=round(sum(apps[a]["annual_cost_usd"] for a in app_ids), 0)))
            if c["level"] <= 2 and ("too_many_applications" in flags or ("hot_spot" in flags and "strategic_gap" in flags)):
                actions.append(ProposedAction(action_type="update_capability_scores", target_id=c["id"], target_type="Capability",
                                              payload={"heat_score": heat, "app_count": len(app_ids), "flags": flags},
                                              rationale=f"{c['name']}: heat {heat}, {len(app_ids)} applications ({', '.join(flags)}).",
                                              source_refs=refs, approver_role="principal_architect", priority=3))
        hot = sorted([f for f in findings if f.level == 1], key=lambda f: (-f.heat_score, f.name))
        facts = {"n": len(findings), "hot": [{"name": f.name, "ref": f.capability_id, "heat": f.heat_score, "apps": f.app_count}
                                             for f in hot[:3]],
                 "no_apps": sum(1 for f in findings if "no_applications" in f.flags),
                 "too_many": sum(1 for f in findings if "too_many_applications" in f.flags)}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.9)
