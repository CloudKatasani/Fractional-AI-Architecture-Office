"""ea.board_assistant — architecture board pack: agenda, submissions with principle checks, pending decisions."""

from __future__ import annotations

from datetime import timedelta

from app.agents.application.design_review import review
from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class BoardPack(Finding):
    agenda: list[str]
    submissions: list[dict]
    decisions_pending: list[dict]


class BoardAssistant(Agent):
    id = "ea.board_assistant"
    name = "Architecture Board Assistant"
    domain = "enterprise"
    description = ("Prepares the architecture board pack: pending approvals, open violations, new ADRs since the last "
                   "board and each design submission checked against standards; records board decisions.")
    inputs = ["approvals", "kg_edges", "adrs", "design_docs", "standards"]
    outputs = "BoardPack"
    finding_model = BoardPack
    approver_role = "principal_architect"
    default_autonomy = 2
    demo_trigger = "Prepare board pack"
    action_types = ["record_board_decision"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        pending = [a for a in ctx.repo.all("approvals") if a["status"] == "pending"]
        by_type: dict[str, int] = {}
        for a in pending:
            by_type[a["action_type"]] = by_type.get(a["action_type"], 0) + 1
        violations = ctx.kg.violations()
        since = (ctx.today - timedelta(days=30)).isoformat()
        new_adrs = [a for a in ctx.repo.all("adrs") if a["date"] >= since]
        subs = []
        for d in ctx.repo.all("design_docs"):
            if d["status"] != "submitted":
                continue
            r = review(ctx, d)
            subs.append({"id": d["id"], "title": d["title"], "team": d["team"], "verdict": r.verdict,
                         "principle_checks": [{"standard_id": c["standard_id"], "result": "fail", "excerpt": c["excerpt"]}
                                              for c in r.concerns] or [{"standard_id": "all", "result": "pass"}]})
        top = sorted(pending, key=lambda a: (a["created_at"] or ""))[:8]
        decisions = [{"approval_id": a["id"], "action_type": a["action_type"], "target_id": a["target_id"],
                      "approver_role": a["approver_role"], "rationale": a["rationale"]} for a in top]
        agenda = [
            f"1. Decisions pending: {len(pending)} items (" + ", ".join(f"{k} {v}" for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])[:4]) + ")",
            f"2. Design submissions: {len(subs)} ({sum(1 for s in subs if s['verdict'] == 'changes_required')} need changes)",
            f"3. Open standard violations: {len(violations)}",
            f"4. ADRs since last board: {len(new_adrs)}",
            "5. AOB and exceptions",
        ]
        refs = [ev(s["id"], "design_docs", s["title"]) for s in subs[:4]] + [ev(a["id"], "approvals", a["action_type"]) for a in top[:3]]
        refs = refs or [ev("board", "meta_kv", "empty board")]
        pack = BoardPack(agenda=agenda, submissions=subs, decisions_pending=decisions, source_refs=refs,
                         violations=len(violations), new_adrs=[a["id"] for a in new_adrs])
        actions = [ProposedAction(action_type="record_board_decision", target_id=s["id"], target_type="Design",
                                  payload={"verdict": s["verdict"], "title": s["title"]},
                                  rationale=f"Board to record decision on {s['title']} (agent verdict: {s['verdict'].replace('_', ' ')}).",
                                  source_refs=[ev(s["id"], "design_docs", s["title"])], approver_role="principal_architect", priority=2)
                   for s in subs]
        facts = {"pending": len(pending), "subs": len(subs), "violations": len(violations), "adrs": len(new_adrs),
                 "changes": sum(1 for s in subs if s["verdict"] == "changes_required")}
        md = "# Architecture Board Pack\n\n## Agenda\n" + "\n".join(agenda) + "\n\n## Submissions\n" + "\n".join(
            f"- **{s['title']}** [{s['id']}] — {s['verdict'].replace('_', ' ')}: " + ", ".join(c["standard_id"] for c in s["principle_checks"])
            for s in subs)
        return AnalysisResult(findings=[pack], actions=actions, facts=facts, confidence=0.85, artifacts={"body_md": md})
