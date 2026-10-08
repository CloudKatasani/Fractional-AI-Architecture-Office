"""ea.roadmap_drafter — three sequenced roadmap scenarios (cost-first, risk-first, speed-first)."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.agents.common import overlap_clusters, quarter_labels


class RoadmapScenario(Finding):
    name: str
    quarters: list[dict]
    tradeoffs: str


class RoadmapDrafter(Agent):
    id = "ea.roadmap_drafter"
    name = "Roadmap Drafter"
    domain = "enterprise"
    description = ("Sequences end-of-support remediation, portfolio consolidations, boundary-violation fixes and "
                   "unfunded strategic capabilities into three 6-quarter scenarios with dependencies and trade-offs.")
    inputs = ["applications", "integrations", "goals", "projects", "capabilities"]
    outputs = "RoadmapScenario"
    finding_model = RoadmapScenario
    approver_role = "cio"
    default_autonomy = 2
    demo_trigger = "Draft roadmaps"
    action_types = ["adopt_roadmap_scenario"]

    def items(self, ctx: AgentContext) -> list[dict]:
        apps = ctx.repo.by_id("applications")
        out = []
        for a in apps.values():
            d = ctx.days_until(a["vendor_eos_date"])
            if d is not None and d <= 365:
                out.append({"id": f"EOS-{a['id']}", "title": f"Replace / upgrade {a['name']} (EOS {a['vendor_eos_date']})",
                            "type": "eos", "ref_ids": [a["id"]], "risk": 5 if a["criticality"] <= 2 else 3,
                            "savings": 0, "effort": 3 if a["criticality"] <= 2 else 1, "deadline_days": d})
        for c in overlap_clusters(ctx)[:5]:
            out.append({"id": f"CONS-{c['cluster_id']}", "title": f"Consolidate {c['capability_name']} on {c['survivor_name']}",
                        "type": "consolidation", "ref_ids": c["app_ids"], "risk": 2, "savings": c["est_savings_usd"],
                        "effort": 2 if len(c["app_ids"]) <= 2 else 3,
                        "depends_on": [f"EOS-{a}" for a in c["retire_app_ids"] if f"EOS-{a}" in {x["id"] for x in out}]})
        for i in ctx.repo.all("integrations"):
            if i["pattern"] == "db_link" and i["crosses_boundary"]:
                out.append({"id": f"FIX-{i['id']}", "title": f"Remove boundary DB link {apps[i['from_app_id']]['name']} -> "
                                                          f"{apps[i['to_app_id']]['name']}", "type": "risk_fix", "ref_ids": [i["id"]],
                            "risk": 5, "savings": 0, "effort": 1})
        funded = {g for p in ctx.repo.all("projects") for g in p["goal_ids"]}
        for g in ctx.repo.all("goals"):
            if g["id"] not in funded:
                out.append({"id": f"GOAL-{g['id']}", "title": f"Stand up programme: {g['statement']}", "type": "strategic",
                            "ref_ids": [g["id"]], "risk": 3, "savings": 0, "effort": 3})
        return out

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        items = self.items(ctx)
        q = quarter_labels(ctx.today, 6)
        orders = {
            "Cost-first": sorted(items, key=lambda x: (-x["savings"], -x["risk"], x["id"])),
            "Risk-first": sorted(items, key=lambda x: (-x["risk"], x.get("deadline_days", 999), x["id"])),
            "Speed-first": sorted(items, key=lambda x: (x["effort"], -x["risk"], x["id"])),
        }
        tradeoffs = {
            "Cost-first": "Releases savings earliest to self-fund later work; leaves boundary and EOS risks open for 2-3 quarters.",
            "Risk-first": "Closes compliance and end-of-support exposure first; savings arrive 2-3 quarters later.",
            "Speed-first": "Delivers visible quick wins early; large migrations bunch up in the back half and need more capacity.",
        }
        findings, actions = [], []
        for name, ordered in orders.items():
            quarters = [{"label": lbl, "items": []} for lbl in q]
            capacity = [4] * 6
            placed: dict[str, int] = {}
            by_id = {x["id"]: x for x in ordered}

            def place(it: dict) -> None:
                if it["id"] in placed:
                    return
                for d in it.get("depends_on", []):  # dependencies first
                    if d in by_id:
                        place(by_id[d])
                start = max([placed[d] + 1 for d in it.get("depends_on", []) if d in placed] or [0])
                last = 5
                if it.get("deadline_days") is not None:  # must land before end of support
                    last = max(start, min(5, it["deadline_days"] // 92 - 1))
                    if name == "Risk-first":
                        start = min(start, last)
                qi = next((i for i in range(start, last + 1) if capacity[i] >= it["effort"]), last)
                capacity[qi] -= it["effort"]
                placed[it["id"]] = qi
                quarters[qi]["items"].append({"id": it["id"], "title": it["title"], "type": it["type"],
                                              "ref_ids": it["ref_ids"], "depends_on": it.get("depends_on", [])})

            for it in ordered:
                place(it)
            savings_by_q4 = sum(it["savings"] for it in items if placed.get(it["id"], 9) <= 3)
            risk_closed = sum(1 for it in items if it["risk"] >= 5 and placed.get(it["id"], 9) <= 1)
            refs = [ev(r, "applications" if r.startswith("APP") else ("integrations" if r.startswith("INT") else "goals"), None)
                    for it in ordered[:3] for r in it["ref_ids"][:1]]
            findings.append(RoadmapScenario(name=name, quarters=quarters, tradeoffs=tradeoffs[name], source_refs=refs,
                                            savings_in_year_1=savings_by_q4, high_risks_closed_in_2q=risk_closed))
            actions.append(ProposedAction(action_type="adopt_roadmap_scenario", target_id=f"ROADMAP-{name.split('-')[0].upper()}",
                                          target_type="Roadmap", payload={"scenario": name, "quarters": quarters},
                                          rationale=f"{name}: {tradeoffs[name]} Year-1 savings ${savings_by_q4:,.0f}; "
                                                    f"{risk_closed} high risks closed in 2 quarters.",
                                          source_refs=refs, approver_role="cio", priority=2))
        facts = {"n_items": len(items), "scenarios": [{"name": f.name, "savings": f.savings_in_year_1,
                                                     "risks": f.high_risks_closed_in_2q} for f in findings]}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.7)
