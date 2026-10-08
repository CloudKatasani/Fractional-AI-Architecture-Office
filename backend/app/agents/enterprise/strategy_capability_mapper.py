"""ea.strategy_capability_mapper — link strategic goals to business capabilities; flag gaps."""

from __future__ import annotations

import re

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.kg.queries import add_edge

STOP = {"and", "the", "for", "with", "management", "of", "to", "a", "by", "at", "on", "in", "our"}


class GoalCapabilityLink(Finding):
    goal_id: str
    capability_ids: list[str]
    strength: float
    gap_flag: bool


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP and len(t) > 2}


class StrategyCapabilityMapper(Agent):
    id = "ea.strategy_capability_mapper"
    name = "Strategy-to-Capability Mapper"
    domain = "enterprise"
    description = ("Extracts strategic goals from strategy documents and links each goal to the business capabilities "
                   "it depends on; flags goals with no capability and high-importance / low-maturity capabilities.")
    inputs = ["strategy_docs", "goals", "capabilities"]
    outputs = "GoalCapabilityLink"
    finding_model = GoalCapabilityLink
    approver_role = "principal_architect"
    default_autonomy = 2
    demo_trigger = "Map strategy"
    action_types = ["link_goal_capability"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        caps = ctx.repo.all("capabilities")
        docs = ctx.repo.by_id("strategy_docs")
        findings, actions = [], []
        for g in ctx.repo.all("goals"):
            kw = set(g["keywords"] or [])
            gtok = _tokens(g["statement"]) | {t for k in kw for t in _tokens(k)}
            scored = []
            for c in caps:
                if c["level"] == 1:
                    continue
                if c["name"].lower() in kw:
                    scored.append((1.0, c))
                    continue
                ctok = _tokens(c["name"])
                if not ctok:
                    continue
                ov = len(ctok & gtok) / len(ctok)
                if ov >= 0.67:
                    scored.append((round(0.5 + 0.3 * ov, 2), c))
            scored.sort(key=lambda t: (-t[0], t[1]["id"]))
            linked = scored[:4]
            weak = [c for _, c in linked if c["strategic_importance"] >= 4 and c["maturity"] <= 2]
            strength = round(sum(s for s, _ in linked) / len(linked), 2) if linked else 0.0
            gap = not linked or bool(weak)
            doc = docs[g["source_doc_id"]]
            refs = [ev(g["id"], "goals", g["statement"]), ev(doc["id"], "strategy_docs", doc["title"])]
            refs += [ev(c["id"], "capabilities", f"{c['name']} (importance {c['strategic_importance']}, maturity {c['maturity']})")
                     for _, c in linked[:3]]
            findings.append(GoalCapabilityLink(goal_id=g["id"], capability_ids=[c["id"] for _, c in linked], strength=strength,
                                               gap_flag=gap, source_refs=refs, statement=g["statement"],
                                               capability_names=[c["name"] for _, c in linked],
                                               weak_capabilities=[c["name"] for c in weak], source_doc=doc["title"]))
            for s, c in linked:
                add_edge(ctx.repo, "SUPPORTS", c["id"], g["id"], {"strength": s, "method": "keyword map"}, [g["id"], c["id"]],
                         self.id, status="draft", confidence=round(0.6 + 0.3 * s, 2))
            if linked:
                actions.append(ProposedAction(action_type="link_goal_capability", target_id=g["id"], target_type="Goal",
                                              payload={"capability_ids": [c["id"] for _, c in linked], "strength": strength},
                                              rationale=f"'{g['statement']}' depends on " + ", ".join(c["name"] for _, c in linked)
                                                        + (f"; gap: {', '.join(c['name'] for c in weak)} are high-importance, low-maturity." if weak else "."),
                                              source_refs=refs, approver_role="principal_architect", priority=3))
        hi_lo = [c for c in caps if c["strategic_importance"] >= 4 and c["maturity"] <= 2]
        facts = {"goals": len(findings), "links": sum(len(f.capability_ids) for f in findings),
                 "gaps": sum(1 for f in findings if f.gap_flag), "hi_lo": [c["name"] for c in hi_lo][:5], "n_hi_lo": len(hi_lo),
                 "no_caps": [f.goal_id for f in findings if not f.capability_ids]}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.72)
