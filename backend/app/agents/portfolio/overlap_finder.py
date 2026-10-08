"""pf.overlap_finder — clusters of applications that realise the same capability with overlapping features."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.agents.common import overlap_clusters
from app.kg.queries import add_edge


class OverlapCluster(Finding):
    cluster_id: str
    capability_id: str
    app_ids: list[str]
    survivor_app_id: str
    rationale: str
    est_savings_usd: float


class OverlapFinder(Agent):
    id = "pf.overlap_finder"
    name = "Overlap Finder"
    domain = "portfolio"
    description = ("Groups applications realising the same L2 capability (or category) with overlapping feature tags "
                   "and recommends a survivor by usage, cost, technical debt and strategic fit.")
    inputs = ["applications", "capabilities", "repos", "incidents"]
    outputs = "OverlapCluster"
    finding_model = OverlapCluster
    approver_role = "principal_architect"
    default_autonomy = 2
    demo_trigger = "Find overlaps"
    action_types = ["propose_consolidation"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        apps = ctx.repo.by_id("applications")
        findings, actions = [], []
        for c in overlap_clusters(ctx):
            surv = apps[c["survivor_app_id"]]
            others = [apps[i] for i in c["retire_app_ids"]]
            rationale = (f"{surv['name']} has the highest combined score (usage {surv['user_count_90d']} users, "
                         f"${surv['annual_cost_usd']:,.0f}/yr). Retiring " + ", ".join(o["name"] for o in others)
                         + f" saves about ${c['est_savings_usd']:,.0f}/yr after migration overlap.")
            refs = [ev(a, "applications", f"{apps[a]['name']}: {apps[a]['user_count_90d']} users, ${apps[a]['annual_cost_usd']:,.0f}/yr, "
                                        f"features {', '.join(apps[a]['features'])}") for a in c["app_ids"]]
            refs.append(ev(c["capability_id"], "capabilities", c["capability_name"]))
            findings.append(OverlapCluster(cluster_id=c["cluster_id"], capability_id=c["capability_id"], app_ids=c["app_ids"],
                                           survivor_app_id=c["survivor_app_id"], rationale=rationale,
                                           est_savings_usd=c["est_savings_usd"], source_refs=refs,
                                           capability_name=c["capability_name"], app_names=c["app_names"],
                                           survivor_name=c["survivor_name"], scores=c["scores"], similarity=c["similarity"],
                                           category=c["category"]))
            # Draft graph writes (P2): OVERLAPS_WITH edges between survivor and the others
            for o in others:
                add_edge(ctx.repo, "OVERLAPS_WITH", o["id"], surv["id"], {"capability_id": c["capability_id"],
                         "similarity": c["similarity"], "cluster_id": c["cluster_id"]}, [o["id"], surv["id"]], self.id,
                         status="draft", confidence=0.75)
            actions.append(ProposedAction(
                action_type="propose_consolidation", target_id=c["cluster_id"], target_type="OverlapCluster",
                payload={"cluster_id": c["cluster_id"], "survivor_app_id": c["survivor_app_id"],
                         "retire_app_ids": c["retire_app_ids"], "est_savings_usd": c["est_savings_usd"],
                         "capability_id": c["capability_id"], "app_names": c["app_names"]},
                rationale=rationale, source_refs=refs, approver_role="principal_architect", priority=2))
        facts = {"clusters": len(findings), "total": round(sum(f.est_savings_usd for f in findings), -2),
                 "top": [{"cap": f.capability_name, "n": len(f.app_ids), "survivor": f.survivor_name,
                          "savings": f.est_savings_usd, "ref": f.app_ids[0]} for f in findings[:3]]}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.8)
