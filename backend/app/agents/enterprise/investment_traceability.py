"""ea.investment_traceability — project spend traced to goals; orphan spend and unfunded goals."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class InvestmentAlignment(Finding):
    goal_id: str | None = None
    project_ids: list[str]
    budget_usd: float
    status: str  # aligned | orphan | unfunded


class InvestmentTraceability(Agent):
    id = "ea.investment_traceability"
    name = "Investment Traceability"
    domain = "enterprise"
    description = ("Traces every project to strategic goals and capabilities; sums budget per goal, lists orphan projects "
                   "(no goal) and unfunded goals (no project), and computes the share of budget aligned to strategy.")
    inputs = ["projects", "goals", "capabilities"]
    outputs = "InvestmentAlignment"
    finding_model = InvestmentAlignment
    approver_role = "cio"
    default_autonomy = 2
    demo_trigger = "Trace investment"
    action_types = ["flag_orphan_project", "propose_funding_review"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        projects = ctx.repo.all("projects")
        goals = ctx.repo.all("goals")
        findings, actions = [], []
        total = sum(p["budget_usd"] for p in projects)
        for g in goals:
            ps = [p for p in projects if g["id"] in p["goal_ids"]]
            budget = sum(p["budget_usd"] / len(p["goal_ids"]) for p in ps)
            refs = [ev(g["id"], "goals", g["statement"])] + [ev(p["id"], "projects", f"{p['name']} ${p['budget_usd']:,.0f}") for p in ps[:3]]
            status = "aligned" if ps else "unfunded"
            findings.append(InvestmentAlignment(goal_id=g["id"], project_ids=[p["id"] for p in ps], budget_usd=round(budget, 0),
                                                status=status, source_refs=refs, statement=g["statement"]))
            if not ps:
                actions.append(ProposedAction(action_type="propose_funding_review", target_id=g["id"], target_type="Goal",
                                              payload={"statement": g["statement"]},
                                              rationale=f"Strategic goal '{g['statement']}' has no funded project.",
                                              source_refs=refs, approver_role="cio", priority=1))
        orphan_budget = 0.0
        for p in projects:
            if not p["goal_ids"]:
                orphan_budget += p["budget_usd"]
                refs = [ev(p["id"], "projects", f"{p['name']}: ${p['budget_usd']:,.0f}, {p['status']}, no strategic goal")]
                findings.append(InvestmentAlignment(goal_id=None, project_ids=[p["id"]], budget_usd=p["budget_usd"], status="orphan",
                                                    source_refs=refs, name=p["name"]))
                actions.append(ProposedAction(action_type="flag_orphan_project", target_id=p["id"], target_type="Project",
                                              payload={"budget_usd": p["budget_usd"], "name": p["name"]},
                                              rationale=f"{p['name']} (${p['budget_usd']:,.0f}) is not linked to any strategic goal.",
                                              source_refs=refs, approver_role="cio", priority=3))
        unfunded = [f for f in findings if f.status == "unfunded"]
        facts = {"total": total, "aligned_pct": round(100 * (1 - orphan_budget / total), 1) if total else 0,
                 "orphan_pct": round(100 * orphan_budget / total, 1) if total else 0, "orphan_budget": orphan_budget,
                 "orphans": sum(1 for f in findings if f.status == "orphan"), "unfunded": [{"statement": f.statement, "ref": f.goal_id} for f in unfunded],
                 "n_projects": len(projects)}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.95)
