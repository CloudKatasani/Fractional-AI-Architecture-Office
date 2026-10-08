"""app.tech_debt_radar — debt score per application and correlation with incidents."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.agents.common import debt_scores


class DebtItem(Finding):
    app_id: str
    score: float
    drivers: list[str]
    effort_band: str
    incident_cost_est: float


class TechDebtRadar(Agent):
    id = "app.tech_debt_radar"
    name = "Tech Debt Radar"
    domain = "application"
    description = ("Scores each application on EOL framework (30), framework age (0-20), critical vulnerabilities (0-25) "
                   "and severity-weighted incidents in 90 days (0-25); ranks and estimates fix effort (S/M/L).")
    inputs = ["repos", "incidents", "applications"]
    outputs = "DebtItem"
    finding_model = DebtItem
    approver_role = "tech_lead"
    default_autonomy = 2
    demo_trigger = "Scan debt"
    action_types = ["add_to_debt_register"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        apps = ctx.repo.by_id("applications")
        scores = debt_scores(ctx)
        items = sorted(scores.items(), key=lambda kv: (-kv[1]["score"], kv[0]))
        all_inc = ctx.repo.all("incidents")
        inc_count: dict[str, int] = {}
        for i in all_inc:
            inc_count[i["app_id"]] = inc_count.get(i["app_id"], 0) + 1
        findings, actions = [], []
        for app_id, s in items:
            refs = [ev(app_id, "applications", apps[app_id]["name"])] + s["refs"]
            findings.append(DebtItem(app_id=app_id, score=s["score"], drivers=s["drivers"], effort_band=s["effort_band"],
                                     incident_cost_est=s["incident_cost_est"], source_refs=refs, app_name=apps[app_id]["name"],
                                     incidents_24m=inc_count.get(app_id, 0), eol=s["eol"]))
        for f in findings[:10]:
            actions.append(ProposedAction(action_type="add_to_debt_register", target_id=f.app_id, target_type="Application",
                                          payload={"score": f.score, "effort_band": f.effort_band, "drivers": f.drivers},
                                          rationale=f"{f.app_name} debt score {f.score}: {'; '.join(f.drivers)}.",
                                          source_refs=f.source_refs, approver_role="tech_lead", priority=3))
        eol_apps = [f for f in findings if f.eol]
        eol_inc = sum(f.incidents_24m for f in eol_apps)
        share = eol_inc / max(1, len(all_inc))
        facts = {"n": len(findings), "avg": round(sum(f.score for f in findings) / max(1, len(findings)), 1),
                 "top": [{"name": f.app_name, "ref": f.app_id, "score": f.score} for f in findings[:3]],
                 "eol_apps": len(eol_apps), "eol_incident_share": round(share, 2)}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.85)
