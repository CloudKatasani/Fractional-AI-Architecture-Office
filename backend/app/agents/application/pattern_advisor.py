"""app.pattern_advisor — recommend reference patterns and reusable APIs for a feature description."""

from __future__ import annotations

import re

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ev
from app.agents.common import reuse_apis

DEFAULT_TEXT = {
    "northgrid": "Stream smart meter events in real time to the customer app and the theft analytics team",
    "meridian": "Show service status from OSS in the care desktop without touching the inventory database",
}


class PatternRecommendation(Finding):
    pattern_id: str
    fit_score: float
    why: str
    starter_diagram_mermaid: str
    reuse_api_ids: list[str]


class PatternAdvisor(Agent):
    id = "app.pattern_advisor"
    name = "Pattern Advisor"
    domain = "application"
    description = ("Matches a short feature description to reference patterns by keywords and NFRs; returns the top two "
                   "with starter diagram, applicable standards and existing APIs to reuse.")
    inputs = ["patterns", "standards", "apis"]
    outputs = "PatternRecommendation"
    finding_model = PatternRecommendation
    approver_role = None
    default_autonomy = 1
    demo_trigger = "Recommend pattern"
    params_spec = [{"name": "text", "label": "Describe the feature", "kind": "text"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        text = ctx.params.get("text") or DEFAULT_TEXT.get(ctx.tenant_id, "")
        low = text.lower()
        words = set(re.findall(r"[a-z][a-z-]+", low))
        scored = []
        for p in ctx.repo.all("patterns"):
            kw_hits = [k for k in p["keywords"] if (k in low if " " in k else k in words)]
            nfr_hits = [n for n in p["nfrs"] if n in low]
            score = len(kw_hits) + 0.5 * len(nfr_hits)
            if score:
                scored.append((score, p, kw_hits, nfr_hits))
        scored.sort(key=lambda t: (-t[0], t[1]["id"]))
        reuse = reuse_apis(ctx, text)
        top = scored[0][0] if scored else 1
        findings = []
        for score, p, kw, nfr in scored[:2]:
            refs = [ev(p["id"], "patterns", p["name"])] + [ev(s, "standards", s) for s in p["standard_ids"][:2]]
            refs += [ev(a["id"], "apis", a["name"]) for a in reuse[:2]]
            findings.append(PatternRecommendation(
                pattern_id=p["id"], fit_score=round(min(1.0, score / max(top, 3)), 2),
                why=f"Matches {', '.join(kw)}" + (f"; NFRs {', '.join(nfr)}" if nfr else "") + f". {p['when_to_use']}",
                starter_diagram_mermaid=p["diagram_mermaid"], reuse_api_ids=[a["id"] for a in reuse], source_refs=refs,
                name=p["name"], standard_ids=p["standard_ids"], components=p["components"]))
        facts = {"text": text, "top": findings[0].name if findings else None, "ref": findings[0].pattern_id if findings else None,
                 "second": findings[1].name if len(findings) > 1 else None, "reuse": [a["name"] for a in reuse]}
        return AnalysisResult(findings=findings, facts=facts, confidence=0.7)

    def narrative_key(self, ctx: AgentContext) -> str:
        return "default" if not ctx.params.get("text") else "custom"
