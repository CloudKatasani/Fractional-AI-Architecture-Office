"""shared.orchestrator — routes a natural-language request to one or more agents and merges their outputs.

Mock: keyword router over the registry. Live: Claude picks agents from the registry descriptions (ids validated).
"""

from __future__ import annotations

import json
import re

from app.agents.base import Agent, AgentContext
from app.config import settings

ROUTES = [
    (r"shadow|discover|cmdb|inventory", ["pf.app_discovery"]),
    (r"saving|cost|licen|renew|spend", ["pf.cost_license_optimizer", "pf.lifecycle_watcher"]),
    (r"overlap|duplicate app|consolidat|rationali", ["pf.overlap_finder"]),
    (r"business case", ["pf.business_case_builder"]),
    (r"time|disposition|tolerate|eliminate", ["pf.time_classifier"]),
    (r"end of support|eos|lifecycle", ["pf.lifecycle_watcher"]),
    (r"risk tier|ai risk|classify.*ai|ai act", ["dai.ai_risk_classifier"]),
    (r"use case|backlog|intake", ["dai.ai_usecase_intake"]),
    (r"registry|unregistered|shadow ai|copilot spend", ["dai.model_agent_registry_steward"]),
    (r"lineage|upstream|downstream", ["dai.lineage_mapper"]),
    (r"policy|privacy|retention|residency|pii|masking", ["dai.governance_policy_checker"]),
    (r"data product|data contract", ["dai.data_product_designer"]),
    (r"reference architecture|reference design", ["dai.ai_ref_arch_generator"]),
    (r"design review|review (the )?design", ["app.design_review"]),
    (r"adr|decision record", ["app.adr_writer"]),
    (r"drift|boundary|db link|ot/it|bss/oss", ["app.drift_detector"]),
    (r"\bapi", ["app.integration_api_architect"]),
    (r"debt|eol framework|vulnerab", ["app.tech_debt_radar"]),
    (r"threat|stride", ["app.threat_model_assistant"]),
    (r"pattern", ["app.pattern_advisor"]),
    (r"strategy|goal", ["ea.strategy_capability_mapper", "ea.investment_traceability"]),
    (r"capabilit|heat ?map", ["ea.capability_curator"]),
    (r"invest|orphan|unfunded|budget", ["ea.investment_traceability"]),
    (r"roadmap", ["ea.roadmap_drafter"]),
    (r"impact|what if|exit|merger|acquisi", ["ea.impact_analyst"]),
    (r"board", ["ea.board_assistant"]),
    (r"briefing|summary for (the )?(cio|board|exec)", ["shared.exec_briefing"]),
    (r"evidence|audit pack", ["shared.evidence_audit"]),
]


class Orchestrator(Agent):
    id = "shared.orchestrator"
    name = "Orchestrator"
    domain = "shared"
    description = ("Routes a natural-language request or UI trigger to one or more agents, merges their outputs, creates "
                   "approvals and enforces autonomy gating.")
    inputs = ["agent registry"]
    outputs = "Combined AgentOutputs"
    approver_role = None
    default_autonomy = 2
    demo_trigger = "Ask the office"
    runnable = False


def route(request_text: str) -> tuple[list[str], str]:
    from app.agents.registry import AGENTS

    text = request_text.lower()
    if settings.llm_mode == "live":
        try:
            from app.llm.client import AnthropicLLM

            llm = AnthropicLLM()
            catalog = "\n".join(f"- {a.id}: {a.description}" for a in AGENTS.values() if a.runnable)
            resp = llm.complete("Pick the 1-3 agents best suited to this request. Reply with JSON {\"agent_ids\": [...], "
                                f"\"why\": str}}.\nAgents:\n{catalog}\n\nRequest: {request_text}")
            data = json.loads(re.search(r"\{.*\}", resp["text"], re.S).group(0))
            ids = [i for i in data.get("agent_ids", []) if i in AGENTS and AGENTS[i].runnable][:3]
            if ids:
                return ids, "live: " + data.get("why", "")
        except Exception:  # noqa: BLE001 - fall back to keyword routing
            pass
    picked: list[str] = []
    for pat, ids in ROUTES:
        if re.search(pat, text):
            for i in ids:
                if i not in picked:
                    picked.append(i)
    return picked[:3] or ["shared.exec_briefing"], "keyword router"


def orchestrate(tenant_id: str, request_text: str, user_id: str | None = None) -> dict:
    from app.agents.registry import get_agent

    ids, how = route(request_text)
    outputs = []
    for aid in ids:
        ctx = AgentContext(tenant_id=tenant_id, user_id=user_id, trigger="orchestrator")
        outputs.append(get_agent(aid).run(ctx).model_dump())
    summary = " ".join(o["summary"] for o in outputs)
    return {"request": request_text, "routed_to": ids, "routing": how, "summary": summary, "outputs": outputs}
