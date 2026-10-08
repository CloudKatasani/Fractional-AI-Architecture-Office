"""pf.time_classifier — Gartner-style TIME dispositions (Tolerate / Invest / Migrate / Eliminate)."""

from __future__ import annotations

import math

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.agents.common import debt_scores
from app.config import settings
from app.kg.queries import update_node_props

OLD_TECH = ("Java 6", "Java 7", "Java 8", ".NET Framework 3.5", ".NET Framework 4.5", "AngularJS", "Python 2", "COBOL", "VBA",
            "Access", "Oracle 10g", "Oracle 11g", "SQL Server 2008", "SQL Server 2012", "Perl", "SAS 9.2", "JSP")


class TimeDisposition(Finding):
    app_id: str
    business_fit: float
    tech_health: float
    quadrant: str
    rationale: str


def quadrant(fit: float, health: float) -> str:
    hi_fit, hi_health = fit >= settings.time_fit_threshold, health >= settings.time_health_threshold
    if hi_fit and hi_health:
        return "Invest"
    if hi_fit and not hi_health:
        return "Migrate"
    if not hi_fit and hi_health:
        return "Tolerate"
    return "Eliminate"


class TimeClassifier(Agent):
    id = "pf.time_classifier"
    name = "TIME Classifier"
    domain = "portfolio"
    description = ("Scores business fit (capability importance, usage, owner confirmation) and technical health "
                   "(debt score, vendor end of support, incidents) and places each app in a TIME quadrant.")
    inputs = ["applications", "capabilities", "repos", "incidents"]
    outputs = "TimeDisposition"
    finding_model = TimeDisposition
    approver_role = "app_owner"
    default_autonomy = 2
    demo_trigger = "Classify portfolio"
    action_types = ["set_disposition"]
    max_actions = 40

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        apps = ctx.repo.all("applications")
        caps = ctx.repo.by_id("capabilities")
        debt = debt_scores(ctx)
        inc: dict[str, int] = {}
        for i in ctx.repo.all("incidents"):
            inc[i["app_id"]] = inc.get(i["app_id"], 0) + (3 if i["severity"] <= 2 else 1)
        kg = ctx.kg
        findings, actions = [], []
        for a in apps:
            imp = max(caps[c]["strategic_importance"] for c in a["capability_ids"])
            usage = min(1.0, math.log1p(a["user_count_90d"]) / math.log1p(5000))
            node = kg.node(a["id"]) or {"props_json": {}}
            confirmed = 1.0 if node["props_json"].get("owner_confirmed") else 0.5
            crit = (4 - a["criticality"]) / 3
            fit = round(1 + 4 * (0.3 * (imp - 1) / 4 + 0.4 * usage + 0.1 * confirmed + 0.2 * crit), 2)
            d = debt.get(a["id"])
            stack = " ".join(a["tech_stack"] or [])
            old_stack = any(x in stack for x in OLD_TECH)
            if d:
                debt_pen = 0.4 + d["score"] / 100 * 3.2
            elif a["hosting"] == "saas":
                debt_pen = 0.9
            else:
                debt_pen = 1.3 + (1.0 if old_stack else 0)
            eos_days = ctx.days_until(a["vendor_eos_date"])
            eos_pen = 1.2 if eos_days is not None and eos_days < 365 else (0.4 if eos_days is not None and eos_days < 730 else 0)
            inc_pen = min(1.2, inc.get(a["id"], 0) * 0.04)
            health = round(max(1.0, 5 - debt_pen - eos_pen - inc_pen), 2)
            q = quadrant(fit, health)
            drivers = []
            if d and d["drivers"]:
                drivers.append(d["drivers"][0])
            if eos_days is not None and eos_days < 365:
                drivers.append(f"vendor EOS in {eos_days} days")
            if a["user_count_90d"] == 0:
                drivers.append("no users in 90 days")
            rationale = (f"Business fit {fit} (capability importance {imp}, {a['user_count_90d']} users); technical health "
                         f"{health}" + (f" ({'; '.join(drivers)})" if drivers else "") + f" → {q}.")
            refs = [ev(a["id"], "applications", f"{a['name']}: {a['user_count_90d']} users, criticality {a['criticality']}"),
                    ev(a["capability_ids"][0], "capabilities", f"{caps[a['capability_ids'][0]]['name']} importance {imp}")]
            if d:
                refs += d["refs"][:2]
            findings.append(TimeDisposition(app_id=a["id"], business_fit=fit, tech_health=health, quadrant=q,
                                            rationale=rationale, source_refs=refs, app_name=a["name"],
                                            annual_cost_usd=a["annual_cost_usd"], owner_user_id=a["owner_user_id"]))
            update_node_props(ctx.repo, a["id"], {"proposed_disposition": q, "business_fit": fit, "tech_health": health})
            if q in ("Eliminate", "Migrate") and (q == "Eliminate" or a["criticality"] <= 2):
                actions.append(ProposedAction(
                    action_type="set_disposition", target_id=a["id"], target_type="Application",
                    payload={"quadrant": q, "business_fit": fit, "tech_health": health, "app_name": a["name"],
                             "owner_user_id": a["owner_user_id"]},
                    rationale=rationale, source_refs=refs, approver_role="app_owner", priority=2 if q == "Migrate" else 3))
        counts = {q: sum(1 for f in findings if f.quadrant == q) for q in ("Tolerate", "Invest", "Migrate", "Eliminate")}
        elim_cost = sum(f.annual_cost_usd for f in findings if f.quadrant == "Eliminate")
        migrate_crit = [f for f in findings if f.quadrant == "Migrate"]
        migrate_crit.sort(key=lambda f: f.tech_health)
        facts = {"counts": counts, "total": len(findings), "eliminate_cost": round(elim_cost, -3),
                 "worst_migrate": [{"name": f.app_name, "ref": f.app_id, "health": f.tech_health} for f in migrate_crit[:3]]}
        actions.sort(key=lambda a: (a.priority, a.payload["tech_health"]))
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.78)
