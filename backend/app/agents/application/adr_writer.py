"""app.adr_writer — turn design discussions (Slack / meeting notes) into draft ADRs."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class ADRDraft(Finding):
    title: str
    context: str
    options: list[str]
    decision: str
    consequences: str
    app_ids: list[str]
    source_discussion_id: str


class ADRWriter(Agent):
    id = "app.adr_writer"
    name = "ADR Writer"
    domain = "application"
    description = ("Extracts context, options, decision and consequences from design discussions and drafts "
                   "Architecture Decision Records linked to the applications mentioned.")
    inputs = ["discussions", "applications", "adrs"]
    outputs = "ADRDraft"
    finding_model = ADRDraft
    approver_role = "tech_lead"
    default_autonomy = 3
    demo_trigger = "Draft ADRs"
    action_types = ["publish_adr"]
    params_spec = [{"name": "discussion_id", "label": "Discussion (blank = all)", "kind": "select", "source": "discussions"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        discs = ctx.repo.all("discussions")
        if ctx.params.get("discussion_id"):
            discs = [d for d in discs if d["id"] == ctx.params["discussion_id"]]
        published = {a["source_discussion_id"] for a in ctx.repo.all("adrs") if a["source_discussion_id"]}
        apps = ctx.repo.all("applications")
        findings, actions, skipped = [], [], 0
        for d in discs:
            x = d["extracted"]
            if not x:
                skipped += 1
                continue
            if d["id"] in published and not ctx.params.get("discussion_id"):
                continue
            mentioned = [a for a in apps if a["name"] in d["body_md"] or a["name"] in x.get("apps", [])]
            app_ids = sorted({a["id"] for a in mentioned})
            refs = [ev(d["id"], "discussions", f"{d['channel']} {d['date']}: \"{x['decision']}\"")]
            refs += [ev(a["id"], "applications", a["name"]) for a in mentioned[:3]]
            draft = ADRDraft(title=x["title"], context=x["context"], options=x["options"], decision=x["decision"],
                             consequences=x["consequences"], app_ids=app_ids, source_discussion_id=d["id"], source_refs=refs,
                             participants=d["participants"], channel=d["channel"],
                             body_md=_adr_md(x, d, mentioned))
            findings.append(draft)
            actions.append(ProposedAction(action_type="publish_adr", target_id=d["id"], target_type="Discussion",
                                          payload={"title": x["title"], "context": x["context"], "options": x["options"],
                                                   "decision": x["decision"], "consequences": x["consequences"], "app_ids": app_ids},
                                          rationale=f"Decision reached in {d['channel']} on {d['date']}: {x['decision']}",
                                          source_refs=refs, approver_role="tech_lead", priority=3))
        facts = {"n": len(findings), "skipped": skipped, "titles": [f.title for f in findings][:3],
                 "first_ref": findings[0].source_discussion_id if findings else None}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.85)


def _adr_md(x: dict, d: dict, apps: list[dict]) -> str:
    opts = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(x["options"]))
    return (f"# ADR: {x['title']}\n\n**Status:** Proposed  \n**Source:** {d['channel']} ({d['date']}) [{d['id']}]  \n"
            f"**Affects:** {', '.join(a['name'] for a in apps) or 'n/a'}\n\n## Context\n{x['context']}\n\n## Options considered\n{opts}\n\n"
            f"## Decision\n{x['decision']}\n\n## Consequences\n{x['consequences']}\n")
