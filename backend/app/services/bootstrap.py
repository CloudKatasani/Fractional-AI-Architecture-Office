"""Tenant bootstrap after data generation: knowledge graph, agent settings, baseline runs, decision history.

Deterministic given the generated data: baseline runs use fixed parameters and history decisions are picked by rule.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from app.agents.base import AgentContext
from app.agents.registry import AGENTS, SEED_ACCEPTANCE
from app.config import demo_today
from app.db.session import Repo
from app.kg.build import build_graph
from app.services import audit

BASELINE_ORDER = [
    "pf.app_discovery", "pf.cost_license_optimizer", "pf.overlap_finder", "pf.time_classifier", "pf.lifecycle_watcher",
    "pf.business_case_builder", "app.tech_debt_radar", "app.drift_detector", "app.integration_api_architect",
    "app.design_review", "app.adr_writer", "app.pattern_advisor", "app.threat_model_assistant",
    "dai.governance_policy_checker", "dai.ai_usecase_intake", "dai.ai_risk_classifier", "dai.model_agent_registry_steward",
    "dai.lineage_mapper", "dai.data_product_designer", "dai.ai_ref_arch_generator",
    "ea.strategy_capability_mapper", "ea.capability_curator", "ea.investment_traceability", "ea.roadmap_drafter",
    "ea.impact_analyst", "ea.board_assistant",
]


def seed_settings(tenant_id: str) -> None:
    repo = Repo(tenant_id)
    repo.delete_all("agent_settings")
    rows = []
    for a in AGENTS.values():
        acc, dec = SEED_ACCEPTANCE.get(a.id, (0, 0))
        rows.append({"tenant_id": tenant_id, "agent_id": a.id, "autonomy_level": a.default_autonomy, "enabled": True,
                     "acceptance_rate_30d": round(acc / dec, 3) if dec else None, "last_run_at": None,
                     "seed_accepted": acc, "seed_decided": dec})
    repo.insert("agent_settings", rows)


def _hist_ts(days_ago: int, hour: int = 10) -> str:
    d = demo_today() - timedelta(days=days_ago)
    return datetime(d.year, d.month, d.day, hour, 15).isoformat(timespec="seconds")


def seed_history(tenant_id: str) -> int:
    """Decide a few baseline approvals 'last month' so the dashboard, audit trail and acceptance rates have history.
    Picks low-stakes items only, never the ones the demo script walks through."""
    from app.orchestrator.approval_gate import decide

    repo = Repo(tenant_id)
    users = repo.all("users")
    by_role = {}
    for u in users:
        by_role.setdefault(u["role"], u)
    pending = [a for a in repo.all("approvals") if a["status"] == "pending"]
    picks: list[tuple[dict, str, str, int]] = []

    def take(action_type: str, n: int, decision: str = "approve", note: str = "Reviewed in monthly cycle",
             pred=lambda a: True, days: int = 24) -> None:  # noqa: ANN001
        for a in [x for x in pending if x["action_type"] == action_type and pred(x)][:n]:
            picks.append((a, decision, note, days))
            days -= 3

    demo_names = ("Vizora", "ChatWave", "ChargeCore", "PulseAnalytics", "EngageFlow")
    take("tag_resources", 2, days=33)
    take("renegotiate_contract", 1, note="Procurement confirmed lower seat count at renewal",
         pred=lambda a: not any(n in a["rationale"] for n in demo_names) and "Right-size" in a["rationale"], days=45)
    take("set_disposition", 2, pred=lambda a: a["payload_json"].get("quadrant") == "Eliminate", days=28)
    take("publish_review", 0)
    take("register_asset", 1, days=20)
    take("set_retention", 1, days=18)
    take("approve_exception", 1, decision="reject", note="Integration must be registered first", days=16)
    take("add_to_debt_register", 2, days=14)
    take("create_renewal_task", 1, days=12, pred=lambda a: not any(n in a["rationale"] for n in demo_names))
    n = 0
    for a, decision, note, days in picks:
        role = a["approver_role"]
        user = by_role.get(role) or by_role["principal_architect"]
        if role in ("app_owner",):
            owner = (a["payload_json"] or {}).get("owner_user_id")
            user = repo.get("users", owner) if owner else user
        if role in ("tech_lead", "security_architect", "data_governance_lead") and role not in by_role:
            user = by_role["principal_architect"]
        decide(tenant_id, a["id"], user["id"], decision, note, ts=_hist_ts(days))
        n += 1
    return n


def bootstrap_tenant(tenant_id: str, quiet: bool = False) -> dict:
    from data_gen.generators.core import TENANT_CATALOG, load_yaml

    t0 = time.time()
    nodes, edges = build_graph(tenant_id)
    repo = Repo(tenant_id)
    seed_settings(tenant_id)
    cat = load_yaml(TENANT_CATALOG[tenant_id])
    repo.set_meta("copilot_questions", cat.get("copilot_questions", []))
    repo.set_meta("impact_triggers", cat.get("impact_triggers", []))
    repo.set_meta("evidence_regulations", cat.get("evidence_regulations", []))
    audit.log(tenant_id, "system", "data_gen", "graph_built", "knowledge_graph", tenant_id, {"nodes": nodes, "edges": edges},
              ts=_hist_ts(40, 8))
    for aid in BASELINE_ORDER:
        AGENTS[aid].run(AgentContext(tenant_id=tenant_id, trigger="scheduled"))
    decided = seed_history(tenant_id)
    res = {"nodes": nodes, "edges": edges, "baseline_runs": len(BASELINE_ORDER), "history_decisions": decided,
           "seconds": round(time.time() - t0, 1)}
    if not quiet:
        print(f"[{tenant_id}] bootstrap: {res}")
    return res
