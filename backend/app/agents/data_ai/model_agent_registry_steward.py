"""dai.model_agent_registry_steward — inventory of models, prompt apps, agents and vendor copilots."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class RegistryFinding(Finding):
    asset_id: str
    flags: list[str]
    monthly_cost_usd: float
    linked_usecase_id: str | None = None
    risk_tier: str | None = None


class ModelAgentRegistrySteward(Agent):
    id = "dai.model_agent_registry_steward"
    name = "Model and Agent Registry Steward"
    domain = "data_ai"
    description = ("Inventories AI assets; flags unregistered (shadow) AI, missing evaluation, unknown training data, "
                   "unapproved vendors and expense-paid tools; computes AI spend by department.")
    inputs = ["ai_assets", "ai_usecases", "invoice_lines"]
    outputs = "RegistryFinding"
    finding_model = RegistryFinding
    approver_role = "risk_officer"
    default_autonomy = 2
    demo_trigger = "Audit AI registry"
    action_types = ["register_asset", "require_eval", "suspend_asset"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        assets = ctx.repo.all("ai_assets")
        ucs = ctx.repo.by_id("ai_usecases")
        kg = ctx.kg
        approved = set(ctx.common["approved_genai_platforms"])
        known_genai = set(ctx.common["genai_vendors_known"])
        findings, actions = [], []
        spend: dict[str, float] = {}
        for a in assets:
            spend[a["department"]] = spend.get(a["department"], 0) + a["monthly_cost_usd"]
            flags = []
            if not a["registered"]:
                flags.append("unregistered")
            if a["eval_status"] == "none":
                flags.append("no_eval")
            if not a["data_used"]:
                flags.append("unknown_data")
            if a["paid_via"] == "expense":
                flags.append("expense_paid")
            if a["vendor"] in known_genai and a["vendor"] not in approved:
                flags.append("unapproved_vendor")
            if a["lifecycle"] == "production" and a["eval_status"] == "none":
                flags.append("production_without_eval")
            uc = ucs.get(a["usecase_id"]) if a["usecase_id"] else None
            tier = None
            if uc:
                node = kg.node(uc["id"])
                tier = node["props_json"].get("risk_tier") or node["props_json"].get("proposed_risk_tier")
            refs = [ev(a["id"], "ai_assets", f"{a['name']} ({a['type']}, {a['vendor']}): registered={a['registered']}, "
                                             f"eval={a['eval_status']}, ${a['monthly_cost_usd']:,.0f}/mo via {a['paid_via']}")]
            if uc:
                refs.append(ev(uc["id"], "ai_usecases", uc["title"]))
            findings.append(RegistryFinding(asset_id=a["id"], flags=flags, monthly_cost_usd=a["monthly_cost_usd"],
                                            linked_usecase_id=a["usecase_id"], risk_tier=tier, source_refs=refs, name=a["name"],
                                            type=a["type"], vendor=a["vendor"], department=a["department"],
                                            registered=a["registered"], eval_status=a["eval_status"]))
            if "unapproved_vendor" in flags and ("expense_paid" in flags or "unregistered" in flags):
                actions.append(ProposedAction(action_type="suspend_asset", target_id=a["id"], target_type="AIAsset",
                                              payload={"flags": flags, "name": a["name"]},
                                              rationale=f"{a['name']} uses unapproved GenAI vendor {a['vendor']} ({', '.join(flags)}); "
                                                        "suspend and move the use to an approved platform (STD-AI-01).",
                                              source_refs=refs, approver_role="risk_officer", priority=2))
            elif "unregistered" in flags:
                actions.append(ProposedAction(action_type="register_asset", target_id=a["id"], target_type="AIAsset",
                                              payload={"flags": flags, "name": a["name"], "owner": a["department"]},
                                              rationale=f"{a['name']} is in use by {a['department']} but not in the model registry (STD-AI-02).",
                                              source_refs=refs, approver_role="risk_officer", priority=3))
            if "no_eval" in flags and ("production_without_eval" in flags or tier in ("high", "limited")):
                actions.append(ProposedAction(action_type="require_eval", target_id=a["id"], target_type="AIAsset",
                                              payload={"flags": flags, "name": a["name"], "risk_tier": tier},
                                              rationale=f"{a['name']} has no evaluation" + (" and runs in production" if "production_without_eval" in flags else "")
                                                        + (f"; linked use case is {tier} risk" if tier else "") + ".",
                                              source_refs=refs, approver_role="risk_officer", priority=1 if "production_without_eval" in flags else 2))
        unreg = [f for f in findings if "unregistered" in f.flags]
        facts = {"n": len(findings), "unregistered": len(unreg), "expense": sum(1 for f in findings if "expense_paid" in f.flags),
                 "no_eval_prod": [{"name": f.name, "ref": f.asset_id} for f in findings if "production_without_eval" in f.flags],
                 "spend_by_dept": dict(sorted(spend.items(), key=lambda kv: -kv[1])),
                 "monthly_total": round(sum(spend.values()), 0), "shadow_monthly": round(sum(f.monthly_cost_usd for f in unreg), 0),
                 "unreg_refs": [f.asset_id for f in unreg][:3]}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.9)
