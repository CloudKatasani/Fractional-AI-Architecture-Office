"""shared.exec_briefing — monthly executive briefing over the dashboard metrics."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ev
from app.services.metrics import dashboard


class BriefingPoint(Finding):
    topic: str
    statement: str


def _usd(v: float | None) -> str:
    return f"${(v or 0):,.0f}"


class ExecBriefing(Agent):
    id = "shared.exec_briefing"
    name = "Executive Briefing Agent"
    domain = "shared"
    description = ("Writes the monthly executive summary: inventory accuracy, savings identified / approved / realised, AI "
                   "use cases by tier, design review SLA, debt trend, upcoming renewals and the top decisions needed.")
    inputs = ["metrics", "approvals", "agent_runs"]
    outputs = "BriefingPoint"
    finding_model = BriefingPoint
    approver_role = None
    default_autonomy = 1
    demo_trigger = "Generate briefing"

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        m = dashboard(ctx.tenant_id)
        s = m["savings"]
        pts: list[BriefingPoint] = []

        def add(topic: str, statement: str, refs: list[str], table: str) -> None:
            refs = [r for r in refs if r][:5] or [ctx.run_id]
            pts.append(BriefingPoint(topic=topic, statement=statement, source_refs=[ev(r, table) for r in refs]))

        inv = m["inventory_accuracy"]
        add("Inventory", f"Inventory accuracy is {inv['value']}% ({inv['confirmed']} of {inv['total']} applications confirmed by owners).",
            inv["source_refs"], "kg_nodes")
        add("Savings", f"Savings identified {_usd(s['identified'])}/yr; approved {_usd(s['approved'])}; realised {_usd(s['realized'])}.",
            s["source_refs"]["approved"] + s["source_refs"]["identified"], "approvals")
        t = m["ai_tiers"]
        add("AI governance", "AI use cases by tier — " + ", ".join(
            f"{k}: {v['approved'] + v['proposed']} ({v['approved']} signed off)" for k, v in t.items()) + ".",
            [r for refs in m["ai_tier_refs"].values() for r in refs], "ai_usecases")
        d = m["design_review"]
        add("Design reviews", f"Median design review turnaround {d['median_hours']} hours over {d['reviewed']} reviews; {d['pending']} pending.",
            d["source_refs"], "design_docs")
        dt = m["debt_trend"]
        if dt["current"] is not None:
            first = dt["points"][0]["score"]
            add("Technical debt", f"Average debt score {dt['current']} (from {first} six months ago).", dt["source_refs"], "agent_runs")
        up = m["upcoming"]["items"]
        if up:
            add("Lifecycle", f"{m['upcoming']['count']} end-of-support dates or renewals in the next 180 days; nearest: "
                             f"{up[0]['name']} in {up[0]['days']} days.", [u["id"] for u in up[:4]], "contracts")
        add("Risk", f"{m['violations']['value']} open policy / standard violations ({m['violations']['policy']} data-policy, "
                    f"{m['violations']['standards']} architecture).", m["violations"]["source_refs"], "kg_edges")
        dec = m["decisions_needed"][:3]
        if dec:
            add("Decisions needed", "Top decisions: " + "; ".join(f"{x['action_type'].replace('_', ' ')} on {x['target_id']} ({x['approver_role']})"
                                                                for x in dec) + ".", [x["id"] for x in dec], "approvals")
        md = [f"# Executive briefing — {ctx.tenant['name']}", f"*{ctx.today.strftime('%B %Y')} · Fractional AI Architecture Office*", ""]
        for p in pts:
            md.append(f"**{p.topic}.** {p.statement} " + " ".join(f"[{r.record_id}]" for r in p.source_refs[:3]))
            md.append("")
        facts = {"inv": inv["value"], "identified": s["identified"], "approved": s["approved"], "realized": s["realized"],
                 "high": t["high"]["approved"] + t["high"]["proposed"], "pending": m["pending_approvals"],
                 "tenant": ctx.tenant["name"]}
        return AnalysisResult(findings=pts, facts=facts, confidence=0.9, artifacts={"body_md": "\n".join(md), "metrics": m})
