"""dai.ai_usecase_intake — value / feasibility / data-readiness scoring and backlog ranking."""

from __future__ import annotations

import math

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev

PATTERN_MATURITY = {"classic_ml": 0.9, "rag": 0.8, "vision": 0.7, "fine_tune": 0.6, "agent_tools": 0.5}


class UseCaseScore(Finding):
    usecase_id: str
    value_score: float
    feasibility_score: float
    data_readiness: float
    blockers: list[str]
    rank: int


class AIUseCaseIntake(Agent):
    id = "dai.ai_usecase_intake"
    name = "AI Use-Case Intake"
    domain = "data_ai"
    description = ("Scores AI use cases on value (estimate, sponsor priority) and feasibility (data exists, quality, "
                   "ownership, pattern maturity), checks data readiness and ranks the backlog.")
    inputs = ["ai_usecases", "datasets"]
    outputs = "UseCaseScore"
    finding_model = UseCaseScore
    approver_role = "principal_architect"
    default_autonomy = 2
    demo_trigger = "Rank backlog"
    action_types = ["prioritize_usecase"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        ucs = ctx.repo.all("ai_usecases")
        ds = ctx.repo.by_id("datasets")
        max_v = max(u["value_estimate_usd"] for u in ucs)
        rows = []
        for u in ucs:
            value = round(0.7 * math.log1p(u["value_estimate_usd"]) / math.log1p(max_v) * 5 + 0.3 * u["sponsor_priority"], 2)
            dsets = [ds[d] for d in u["dataset_ids"]]
            blockers = []
            if not dsets:
                blockers.append("no candidate datasets identified")
            q = sum(d["quality_score"] for d in dsets) / len(dsets) if dsets else 0
            for d in dsets:
                if d["quality_score"] < 0.6:
                    blockers.append(f"low quality data: {d['name']} ({d['quality_score']})")
                if d["pii"] and d["retention_days"] is None:
                    blockers.append(f"PII without retention: {d['name']}")
                if not d["owner_user_id"]:
                    blockers.append(f"dataset without owner: {d['name']}")
            if u["uses_personal_data"] and not all(d["has_contract"] for d in dsets):
                blockers.append("personal data used without a data contract")
            if "covert_surveillance" in (u["tags"] or []):
                blockers.append("prohibited practice — will be blocked at risk classification")
            readiness = round((sum(1 for d in dsets if d["quality_score"] >= 0.7 and d["owner_user_id"]) / len(dsets)) if dsets else 0, 2)
            feas = round(5 * (0.35 * q + 0.25 * readiness + 0.25 * PATTERN_MATURITY.get(u["pattern"], 0.6)
                              + 0.15 * (1 if u["status"] != "idea" else 0.5)), 2)
            if "covert_surveillance" in (u["tags"] or []):
                feas = 0.0
            refs = [ev(u["id"], "ai_usecases", f"{u['title']}: value ${u['value_estimate_usd']:,.0f}, priority {u['sponsor_priority']}, "
                                               f"pattern {u['pattern']}")]
            refs += [ev(d["id"], "datasets", f"{d['name']} quality {d['quality_score']}") for d in dsets[:3]]
            rows.append({"u": u, "value": value, "feas": feas, "ready": readiness, "blockers": blockers, "refs": refs,
                         "score": round(value * 0.55 + feas * 0.45, 2)})
        rows.sort(key=lambda r: (-r["score"], r["u"]["id"]))
        findings, actions = [], []
        for rank, r in enumerate(rows, 1):
            u = r["u"]
            findings.append(UseCaseScore(usecase_id=u["id"], value_score=r["value"], feasibility_score=r["feas"],
                                         data_readiness=r["ready"], blockers=r["blockers"], rank=rank, source_refs=r["refs"],
                                         title=u["title"], status=u["status"], pattern=u["pattern"],
                                         value_estimate_usd=u["value_estimate_usd"], score=r["score"], sponsor_dept=u["sponsor_dept"]))
            if rank <= 5 and not any("prohibited" in b for b in r["blockers"]):
                actions.append(ProposedAction(action_type="prioritize_usecase", target_id=u["id"], target_type="AIUseCase",
                                              payload={"rank": rank, "score": r["score"], "title": u["title"]},
                                              rationale=f"Rank {rank}: value {r['value']}, feasibility {r['feas']}, readiness {r['ready']:.0%}.",
                                              source_refs=r["refs"], approver_role="principal_architect", priority=3))
        facts = {"n": len(findings), "top": [{"title": f.title, "ref": f.usecase_id, "score": f.score} for f in findings[:3]],
                 "blocked": sum(1 for f in findings if f.blockers)}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.8)
