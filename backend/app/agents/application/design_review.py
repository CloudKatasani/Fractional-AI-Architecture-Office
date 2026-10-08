"""app.design_review — rule-based review of design submissions against architecture standards."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.agents.common import design_concerns, reuse_apis


class DesignReview(Finding):
    design_id: str
    verdict: str  # pass | pass_with_conditions | changes_required
    concerns: list[dict]
    reuse_suggestions: list[str]


def verdict_for(concerns: list[dict]) -> str:
    sev = {c["severity"] for c in concerns}
    if sev & {"critical", "high"}:
        return "changes_required"
    if sev & {"medium"}:
        return "pass_with_conditions"
    return "pass"


def review(ctx: AgentContext, doc: dict) -> DesignReview:
    concerns = design_concerns(ctx, doc)
    reuse = reuse_apis(ctx, doc["body_md"])
    apps = ctx.repo.by_id("applications")
    refs = [ev(doc["id"], "design_docs", f"{doc['title']} ({doc['team']}, submitted {doc['submitted_at'][:10]})")]
    refs += [ev(c["standard_id"], "standards", c["standard_title"]) for c in concerns[:3]]
    refs += [ev(a["id"], "apis", f"{a['name']} (owner {apps[a['owner_app_id']]['name']}, {a['auth']}, via gateway)") for a in reuse]
    for c in concerns:
        if any(a["resource"] in ("customer", "usage") for a in reuse) and c["standard_id"] in ("STD-INT-02", "STD-BSS-01"):
            c["recommendation"] += " Reuse " + ", ".join(f"{a['name']} [{a['id']}]" for a in reuse[:2]) + " instead."
    return DesignReview(design_id=doc["id"], verdict=verdict_for(concerns), concerns=concerns,
                        reuse_suggestions=[a["id"] for a in reuse], source_refs=refs, title=doc["title"], team=doc["team"],
                        reuse_names=[a["name"] for a in reuse])


class DesignReviewAgent(Agent):
    id = "app.design_review"
    name = "Design Review Agent"
    domain = "application"
    description = ("Checks design submissions against architecture standards (integration, data classification, approved "
                   "GenAI platforms, NFRs, boundary rules); every concern maps to a standard id; suggests APIs to reuse.")
    inputs = ["design_docs", "standards", "apis"]
    outputs = "DesignReview"
    finding_model = DesignReview
    approver_role = "tech_lead"
    default_autonomy = 2
    demo_trigger = "Review design"
    action_types = ["publish_review", "request_exception"]
    params_spec = [{"name": "design_id", "label": "Design submission (blank = all pending)", "kind": "select", "source": "designs"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        docs = ctx.repo.all("design_docs")
        if ctx.params.get("design_id"):
            docs = [d for d in docs if d["id"] == ctx.params["design_id"]]
        else:
            docs = [d for d in docs if d["status"] == "submitted"]
        findings, actions = [], []
        for d in docs:
            r = review(ctx, d)
            findings.append(r)
            actions.append(ProposedAction(
                action_type="publish_review", target_id=d["id"], target_type="Design",
                payload={"verdict": r.verdict, "concerns": [c["standard_id"] for c in r.concerns], "title": d["title"]},
                rationale=f"{d['title']}: {r.verdict.replace('_', ' ')}" + (
                    " — " + ", ".join(c["standard_id"] for c in r.concerns) if r.concerns else ""),
                source_refs=r.source_refs, approver_role="tech_lead", priority=2 if r.verdict == "changes_required" else 3))
        single = findings[0].model_dump() if len(findings) == 1 else None
        facts = {"n": len(findings), "single": single,
                 "verdicts": {v: sum(1 for f in findings if f.verdict == v) for v in ("pass", "pass_with_conditions", "changes_required")},
                 "concerns": sum(len(f.concerns) for f in findings)}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.86)

    def narrative_key(self, ctx: AgentContext) -> str:
        return ctx.params.get("design_id") or "default"
