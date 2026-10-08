"""pf.business_case_builder — one-page rationalisation business case for a cluster or a set of apps."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.agents.common import debt_scores, overlap_clusters, quarter_labels

EFFORT_COST = {"S": 60000, "M": 180000, "L": 450000}
DISCOUNT = 0.08


class BusinessCase(Finding):
    title: str
    scope_app_ids: list[str]
    savings_3y_usd: float
    one_time_cost_usd: float
    payback_months: float
    risks: list[str]
    timeline: list[dict]
    body_md: str


class BusinessCaseBuilder(Agent):
    id = "pf.business_case_builder"
    name = "Rationalization Business Case Builder"
    domain = "portfolio"
    description = ("Builds a one-page business case for an overlap cluster or disposition set: 3-year savings, "
                   "one-time migration cost, payback, simple NPV, risks and a timeline.")
    inputs = ["applications", "contracts", "integrations", "repos"]
    outputs = "BusinessCase"
    finding_model = BusinessCase
    approver_role = "cio"
    default_autonomy = 2
    demo_trigger = "Build business case"
    action_types = ["approve_business_case"]
    params_spec = [{"name": "cluster_id", "label": "Overlap cluster", "kind": "select", "source": "overlaps"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        apps = ctx.repo.by_id("applications")
        clusters = overlap_clusters(ctx)
        cluster = None
        cid = ctx.params.get("cluster_id")
        if cid:
            cluster = next((c for c in clusters if c["cluster_id"] == cid), None)
        app_ids = ctx.params.get("app_ids")
        if not cluster and not app_ids:
            pref = {"northgrid": "Document management", "meridian": "Billing"}.get(ctx.tenant_id)
            cluster = next((c for c in clusters if c["category"] == pref), clusters[0] if clusters else None)
        if cluster:
            scope = cluster["app_ids"]
            retire = cluster["retire_app_ids"]
            survivor = cluster["survivor_app_id"]
            title = f"Consolidate {cluster['capability_name']} on {cluster['survivor_name']}"
        else:
            scope = list(app_ids)
            retire = scope
            survivor = None
            title = f"Retire {len(scope)} applications"
        debt = debt_scores(ctx)
        annual = round(sum(apps[a]["annual_cost_usd"] for a in retire) * 0.7, -2)
        savings_3y = round(annual * (0.5 + 1 + 1), -2)  # year-1 ramp at 50%
        integ = ctx.repo.all("integrations")
        one_time = 0.0
        risks = []
        for a in retire:
            app = apps[a]
            band = debt.get(a, {}).get("effort_band") or ("L" if app["criticality"] <= 2 else ("M" if app["criticality"] == 3 else "S"))
            n_int = sum(1 for i in integ if a in (i["from_app_id"], i["to_app_id"]))
            one_time += EFFORT_COST[band] + n_int * 15000
            if n_int >= 4:
                risks.append(f"{app['name']} has {n_int} integrations to re-point")
            if app["data_classification"] in ("confidential", "restricted"):
                risks.append(f"{app['name']} holds {app['data_classification']} data — migration needs a data-handling plan")
            if app["vendor_eos_date"] and (ctx.days_until(app["vendor_eos_date"]) or 999) < 270:
                risks.append(f"{app['name']} reaches vendor EOS on {app['vendor_eos_date']} — sequence it first")
        one_time = round(one_time, -3)
        payback = round(one_time / (annual / 12), 1) if annual else 0.0
        cash = [annual * 0.5 - one_time, annual, annual]
        npv = round(sum(cf / (1 + DISCOUNT) ** (i + 1) for i, cf in enumerate(cash)), -2)
        q = quarter_labels(ctx.today, 6)
        timeline = [{"quarter": q[0], "step": "Confirm scope with owners; freeze changes on retiring apps"},
                    {"quarter": q[1], "step": "Migrate content/users" + (f" to {apps[survivor]['name']}" if survivor else "")},
                    {"quarter": q[2], "step": "Re-point integrations; parallel run"},
                    {"quarter": q[3], "step": "Decommission and cancel contracts at renewal"}]
        refs = [ev(a, "applications", f"{apps[a]['name']}: ${apps[a]['annual_cost_usd']:,.0f}/yr, {apps[a]['user_count_90d']} users")
                for a in scope]
        lines = [f"# {title}", "", f"**Scope:** {', '.join(apps[a]['name'] for a in scope)}  ",
                 f"**Survivor:** {apps[survivor]['name'] if survivor else 'n/a'}  ", "",
                 "| Metric | Value |", "|---|---|",
                 f"| Annual run-cost reduction | ${annual:,.0f} |", f"| 3-year savings (year-1 at 50%) | ${savings_3y:,.0f} |",
                 f"| One-time migration cost | ${one_time:,.0f} |", f"| Payback | {payback} months |",
                 f"| NPV (3 yrs, {DISCOUNT:.0%}) | ${npv:,.0f} |", "", "## Why",
                 "Overlapping applications serve the same capability; consolidating reduces licences, support effort and "
                 "integration points. Figures are computed from contract, cloud and usage records cited below.", "",
                 "## Risks"] + [f"- {r}" for r in (risks or ["Low — limited integrations and data exposure"])] + \
                ["", "## Timeline"] + [f"- **{t['quarter']}** — {t['step']}" for t in timeline] + \
                ["", "## Evidence", ", ".join(f"[{r.record_id}]" for r in refs)]
        body = "\n".join(lines)
        bc = BusinessCase(title=title, scope_app_ids=scope, savings_3y_usd=savings_3y, one_time_cost_usd=one_time,
                          payback_months=payback, risks=risks, timeline=timeline, body_md=body, source_refs=refs,
                          npv_usd=npv, annual_savings_usd=annual, cluster_id=cluster["cluster_id"] if cluster else None,
                          survivor_app_id=survivor)
        target = cluster["cluster_id"] if cluster else "BC-" + "-".join(sorted(scope))[:40]
        action = ProposedAction(action_type="approve_business_case", target_id=target, target_type="BusinessCase",
                                payload={"title": title, "annual_savings_usd": annual, "est_savings_usd": annual,
                                         "savings_3y_usd": savings_3y, "one_time_cost_usd": one_time, "payback_months": payback,
                                         "npv_usd": npv, "scope_app_ids": scope, "survivor_app_id": survivor,
                                         "cluster_id": cluster["cluster_id"] if cluster else None},
                                rationale=f"{title}: ${annual:,.0f}/yr savings, payback {payback} months.", source_refs=refs,
                                approver_role="cio", priority=1)
        facts = {"title": title, "annual": annual, "savings_3y": savings_3y, "one_time": one_time, "payback": payback,
                 "npv": npv, "refs": [r.record_id for r in refs]}
        return AnalysisResult(findings=[bc], actions=[action], facts=facts, confidence=0.75, artifacts={"body_md": body})

    def narrative_key(self, ctx: AgentContext) -> str:
        return ctx.params.get("cluster_id") or "default"
