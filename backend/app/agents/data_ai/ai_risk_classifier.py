"""dai.ai_risk_classifier — rule-based AI risk tiering (EU AI Act-style), with required controls per tier."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.kg.queries import update_node_props


class RiskClassification(Finding):
    usecase_id: str
    tier: str
    triggers: list[dict]  # [{rule_id, title, reason}]
    required_controls: list[dict]  # [{id, title, source}]
    documentation_checklist: list[str]


def rule_matches(rule: dict, uc: dict) -> str | None:
    when = rule.get("when") or {}
    reasons = []
    for k, v in when.items():
        if k == "tags_any":
            hit = [t for t in v if t in (uc["tags"] or [])]
            if not hit:
                return None
            reasons.append("tags: " + ", ".join(hit))
        else:
            if uc.get(k) != v:
                return None
            reasons.append(f"{k} = {str(v).lower()}")
    return "; ".join(reasons) or "no higher-tier rule matched"


def classify(ctx: AgentContext, uc: dict) -> dict:
    rr = ctx.risk_rules
    order = rr["tier_order"]
    regs = rr["tenant_regulations"].get(ctx.tenant_id, {})
    triggers = []
    for rule in rr["rules"]:
        if rule["id"] == "AIR-M1":
            continue
        reason = rule_matches(rule, uc)
        if reason:
            triggers.append({"rule_id": rule["id"], "title": rule["title"], "tier": rule["tier"], "reason": reason,
                             "reference": rule["reference"], "regulation": regs.get(rule["id"], regs.get("default"))})
    tier = "minimal"
    for t in triggers:
        if order.index(t["tier"]) > order.index(tier):
            tier = t["tier"]
    if not triggers:
        m1 = next(r for r in rr["rules"] if r["id"] == "AIR-M1")
        triggers.append({"rule_id": "AIR-M1", "title": m1["title"], "tier": "minimal", "reason": "no higher-tier rule matched",
                         "reference": m1["reference"], "regulation": regs.get("default")})
    controls = [{"id": c["id"], "title": c["title"], "source": c["source_rule"],
                 "source_text": f"Required for {tier} tier by {c['source_rule']}"} for c in rr["controls"] if tier in c["tiers"]]
    return {"tier": tier, "triggers": triggers, "controls": controls, "docs": rr["documentation"][tier]}


class AIRiskClassifier(Agent):
    id = "dai.ai_risk_classifier"
    name = "AI Risk Classifier"
    domain = "data_ai"
    description = ("Tiers AI use cases (unacceptable / high / limited / minimal) with EU AI Act-style rules; lists the "
                   "triggering rule ids, required controls and documentation. Unacceptable use cases are blocked.")
    inputs = ["ai_usecases", "datasets"]
    outputs = "RiskClassification"
    finding_model = RiskClassification
    approver_role = "risk_officer"
    default_autonomy = 2
    demo_trigger = "Classify risk"
    action_types = ["set_risk_tier"]
    params_spec = [{"name": "usecase_id", "label": "Use case (blank = all)", "kind": "select", "source": "usecases"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        ucs = ctx.repo.all("ai_usecases")
        if ctx.params.get("usecase_id"):
            ucs = [u for u in ucs if u["id"] == ctx.params["usecase_id"]]
        ds = ctx.repo.by_id("datasets")
        findings, actions = [], []
        for u in ucs:
            c = classify(ctx, u)
            refs = [ev(u["id"], "ai_usecases", f"{u['title']}: personal_data={u['uses_personal_data']}, "
                                               f"affects_individuals={u['affects_individuals']}, safety_relevant={u['safety_relevant']}, "
                                               f"automated_decision={u['automated_decision']}, tags={u['tags']}")]
            refs += [ev(d, "datasets", f"{ds[d]['name']} (pii={ds[d]['pii']})") for d in u["dataset_ids"] if ds[d]["pii"]][:2]
            findings.append(RiskClassification(usecase_id=u["id"], tier=c["tier"], triggers=c["triggers"],
                                               required_controls=c["controls"], documentation_checklist=c["docs"],
                                               source_refs=refs, title=u["title"], blocked=c["tier"] == "unacceptable"))
            update_node_props(ctx.repo, u["id"], {"proposed_risk_tier": c["tier"],
                                                  "risk_rules": [t["rule_id"] for t in c["triggers"]]})
            rule_ids = ", ".join(t["rule_id"] for t in c["triggers"])
            actions.append(ProposedAction(
                action_type="set_risk_tier", target_id=u["id"], target_type="AIUseCase",
                payload={"tier": c["tier"], "rule_ids": [t["rule_id"] for t in c["triggers"]], "title": u["title"],
                         "controls": [x["id"] for x in c["controls"]], "block": c["tier"] == "unacceptable"},
                rationale=f"{u['title']} → {c['tier'].upper()} ({rule_ids}): " + "; ".join(t["reason"] for t in c["triggers"]),
                source_refs=refs, approver_role="risk_officer",
                priority={"unacceptable": 1, "high": 1, "limited": 3, "minimal": 4}[c["tier"]]))
        dist = {t: sum(1 for f in findings if f.tier == t) for t in ("unacceptable", "high", "limited", "minimal")}
        facts = {"dist": dist, "n": len(findings), "single": findings[0].model_dump() if len(findings) == 1 else None,
                 "high": [{"title": f.title, "ref": f.usecase_id, "rules": [t["rule_id"] for t in f.triggers]}
                          for f in findings if f.tier == "high"][:4],
                 "blocked": [{"title": f.title, "ref": f.usecase_id} for f in findings if f.tier == "unacceptable"]}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.9)

    def narrative_key(self, ctx: AgentContext) -> str:
        return ctx.params.get("usecase_id") or "default"
