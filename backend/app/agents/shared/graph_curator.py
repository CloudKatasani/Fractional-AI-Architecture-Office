"""shared.graph_curator — applies approved actions to the knowledge graph (and, at L3, executes side effects).

Runs after every approval decision. Conflicts (two sources disagree) keep the higher-confidence value and are logged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.agents.base import Agent
from app.db.session import Repo
from app.kg.queries import add_edge, get_kg, set_edge_status, update_node_props, upsert_node
from app.services import audit, settings_service

CURATOR = "shared.graph_curator"

# Side effects (L3 only): action types that open a simulated Jira ticket.
TICKET_ACTIONS = {
    "create_remediation_ticket": "SEC", "create_renewal_task": "PROC", "plan_upgrade": "ARCH", "create_ticket": "ARCH",
    "add_to_debt_register": "DEBT", "flag_orphan_project": "PMO", "propose_funding_review": "PMO",
    "renegotiate_contract": "PROC", "cancel_renewal": "PROC", "apply_masking": "DATA", "set_retention": "DATA",
    "block_pipeline": "DATA", "tag_resources": "CLOUD", "require_eval": "AIGOV", "suspend_asset": "AIGOV",
    "register_asset": "AIGOV", "approve_exception": "SEC",
}


class GraphCurator(Agent):
    id = CURATOR
    name = "Knowledge Graph Curator"
    domain = "shared"
    description = ("Applies approved actions to the knowledge graph, resolves conflicts by confidence, recomputes derived "
                   "properties and (at autonomy L3) executes simulated side effects such as tickets and ADR publication.")
    inputs = ["approvals", "kg_nodes", "kg_edges"]
    outputs = "graph updates"
    approver_role = None
    default_autonomy = 3
    demo_trigger = "Runs after every decision"
    runnable = False


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _ticket(repo: Repo, appr: dict, prefix: str, title: str, assignee: str | None) -> dict:
    n = len(repo.all("tickets")) + 1
    t = {"id": "TCK-" + uuid.uuid4().hex[:8].upper(), "tenant_id": repo.tenant_id, "source_system": "jira_simulated",
         "created_at": _now(), "key": f"{prefix}-{100 + n}", "title": title, "description": appr["rationale"],
         "status": "open", "assignee": assignee, "approval_id": appr["id"], "target_id": appr["target_id"]}
    repo.insert("tickets", t)
    return t


def apply_approval(tenant_id: str, appr: dict, user: dict, ts: str | None = None) -> dict:
    repo = Repo(tenant_id)
    status = appr["status"]
    payload = appr["edited_payload_json"] or appr["payload_json"] or {}
    target = appr["target_id"]
    at = appr["action_type"]
    autonomy = settings_service.autonomy_for(tenant_id, appr["agent_id"])
    effects: dict = {"graph": [], "side_effects": [], "autonomy_level": autonomy}
    kg = get_kg(tenant_id)
    refs = [r["record_id"] for r in appr["source_refs_json"] or []]

    if status == "rejected":
        if at == "confirm_app" and payload.get("new"):
            upsert_node(repo, target, "Application", payload.get("candidate_name", target),
                        {"shadow_it": True, "rejected_reason": appr["decision_note"]}, refs, CURATOR, status="retired", confidence=0.6)
            effects["graph"].append(f"candidate {target} retired")
        for e in kg.edges_of_type("OVERLAPS_WITH"):
            if at == "propose_consolidation" and e["props_json"].get("cluster_id") == target:
                set_edge_status(repo, "OVERLAPS_WITH", e["from_id"], e["to_id"], "retired")
        _log(tenant_id, user, appr, effects, ts)
        return effects

    def graph(msg: str) -> None:
        effects["graph"].append(msg)

    if at == "confirm_app":
        if payload.get("new"):
            upsert_node(repo, target, "Application", payload["candidate_name"], {
                "shadow_it": True, "owner_confirmed": True, "owner_user_id": user["id"], "annual_cost_usd": payload.get("annual_cost_usd", 0),
                "aliases": payload.get("raw_names", []), "genai": payload.get("genai"), "discovered_via": payload.get("sources", []),
                "in_cmdb": False, "category": "Shadow IT (confirmed)", "user_count_90d": 0, "criticality": 4, "hosting": "saas",
                "vendor": payload["candidate_name"], "lifecycle_status": "active",
            }, refs, CURATOR, status="approved", confidence=0.9)
            add_edge(repo, "OWNS", user["id"], target, {}, refs, CURATOR, status="approved", confidence=0.95)
            graph(f"new application {target} '{payload['candidate_name']}' added, owner {user['name']}")
        else:
            update_node_props(repo, target, {"owner_confirmed": True, "aliases": payload.get("aliases", [])}, status="approved")
            graph(f"{target} aliases confirmed by owner")
    elif at in ("merge_cmdb_ci", "retire_cmdb_ci"):
        update_node_props(repo, target, {"merged_into": payload.get("merge_into"), "ci_status": "retired"}, status="retired")
        graph(f"CMDB CI {target} {'merged into ' + payload['merge_into'] if payload.get('merge_into') else 'retired'}")
    elif at == "assign_owner":
        owner = payload.get("owner_user_id") or user["id"]
        add_edge(repo, "OWNS", owner, target, {"assigned_via": appr["id"]}, refs, CURATOR, status="approved", confidence=0.95)
        update_node_props(repo, target, {"owner_user_id": owner})
        graph(f"owner {owner} assigned to {target}")
    elif at == "set_disposition":
        update_node_props(repo, target, {"disposition": payload["quadrant"], "disposition_approved_by": user["id"],
                                         "owner_confirmed": True})
        graph(f"{target} disposition = {payload['quadrant']}")
    elif at in ("renegotiate_contract", "cancel_renewal"):
        update_node_props(repo, target, {"decision": at, "est_savings_usd": payload.get("est_savings_usd")})
        graph(f"contract {target}: {at.replace('_', ' ')} approved")
    elif at == "tag_resources":
        for rid in payload.get("resource_ids", []):
            update_node_props(repo, rid, {"untagged": False, "tagging_requested": True})
            set_edge_status(repo, "VIOLATES", rid, "STD-CLD-01", "retired")
        graph(f"{len(payload.get('resource_ids', []))} resources queued for tagging")
    elif at == "propose_consolidation":
        for r in payload.get("retire_app_ids", []):
            set_edge_status(repo, "OVERLAPS_WITH", r, payload["survivor_app_id"], "approved")
            add_edge(repo, "SUCCEEDS", payload["survivor_app_id"], r, {"cluster_id": target}, refs, CURATOR, status="approved", confidence=0.9)
            update_node_props(repo, r, {"disposition": "Eliminate", "succeeded_by": payload["survivor_app_id"]})
        graph(f"consolidation {target} approved: survivor {payload['survivor_app_id']}")
    elif at == "set_risk_tier":
        update_node_props(repo, target, {"risk_tier": payload["tier"], "risk_rules": payload.get("rule_ids"),
                                         "blocked": payload["tier"] == "unacceptable"}, status="approved")
        if payload["tier"] == "unacceptable":
            repo.update("ai_usecases", target, {"status": "blocked"})
        graph(f"{target} risk tier = {payload['tier']}")
    elif at == "prioritize_usecase":
        update_node_props(repo, target, {"priority_rank": payload.get("rank")})
        graph(f"{target} prioritised rank {payload.get('rank')}")
    elif at in ("register_asset", "require_eval", "suspend_asset"):
        props = {"register_asset": {"registered": True}, "require_eval": {"eval_required": True},
                 "suspend_asset": {"suspended": True}}[at]
        update_node_props(repo, target, props)
        if at == "register_asset":
            repo.update("ai_assets", target, {"registered": True})
        graph(f"{target}: {at.replace('_', ' ')}")
    elif at == "publish_review":
        update_node_props(repo, target, {"review_verdict": payload.get("verdict"), "status": "reviewed"}, status="approved")
        repo.update("design_docs", target, {"status": "reviewed", "reviewed_at": ts or _now()})
        graph(f"design {target} review published ({payload.get('verdict')})")
    elif at == "publish_adr":
        adr_id = "ADR-D" + target.split("-")[-1]
        upsert_node(repo, adr_id, "ADR", payload["title"], {"status": "accepted", "source_discussion_id": target}, refs, CURATOR,
                    status="approved", confidence=0.9)
        for a in payload.get("app_ids", []):
            add_edge(repo, "AFFECTS", adr_id, a, {}, refs, CURATOR, status="approved")
        add_edge(repo, "DECIDED_BY", adr_id, user["id"], {}, refs, CURATOR, status="approved")
        graph(f"ADR {adr_id} recorded")
        if autonomy >= 3 and not repo.get("adrs", adr_id):
            repo.insert("adrs", {"id": adr_id, "tenant_id": tenant_id, "source_system": "adr_writer", "created_at": _now(),
                                 "title": payload["title"], "status": "accepted", "context": payload["context"],
                                 "decision": payload["decision"], "consequences": payload["consequences"],
                                 "app_ids": payload.get("app_ids", []), "date": (ts or _now())[:10],
                                 "options": payload.get("options", []), "source_discussion_id": target})
            effects["side_effects"].append(f"ADR {adr_id} published to the ADR repository")
    elif at in ("designate_canonical_api", "deprecate_api"):
        update_node_props(repo, target, {"canonical": at == "designate_canonical_api", "deprecated": at == "deprecate_api",
                                         "replacement": payload.get("replacement")})
        graph(f"API {target}: {at.replace('_', ' ')}")
    elif at == "link_goal_capability":
        for c in payload.get("capability_ids", []):
            set_edge_status(repo, "SUPPORTS", c, target, "approved")
        graph(f"{len(payload.get('capability_ids', []))} capability links to {target} approved")
    elif at == "update_capability_scores":
        update_node_props(repo, target, {"heat_score": payload.get("heat_score"), "app_count": payload.get("app_count")})
        graph(f"capability {target} scores updated")
    elif at == "approve_data_contract":
        for d in payload.get("dataset_ids", []):
            update_node_props(repo, d, {"has_contract": True, "data_product": target})
            repo.update("datasets", d, {"has_contract": True})
        upsert_node(repo, target, "DataProduct", f"{payload.get('domain')} data product", {"contract_yaml": payload.get("contract_yaml")},
                    refs, CURATOR, status="approved")
        graph(f"data product {target} approved")
    elif at in ("apply_masking", "set_retention", "block_pipeline"):
        props = {"apply_masking": {"masking_required": True}, "set_retention": {"retention_days": payload.get("retention_days")},
                 "block_pipeline": {"blocked": True}}[at]
        update_node_props(repo, target, {**props, "policy_fix": payload.get("policy_id")})
        graph(f"{target}: {at.replace('_', ' ')} ({payload.get('policy_id')})")
    elif at in ("request_exception", "approve_exception"):
        for e in kg.out_edges(target, "VIOLATES"):
            add_edge(repo, "VIOLATES", e["from_id"], e["to_id"], {"exception": True, "approved_by": user["id"]}, refs, CURATOR, status="approved")
        update_node_props(repo, target, {"exception_approved": True, "approved": True})
        graph(f"exception recorded for {target}")
    elif at == "adopt_roadmap_scenario":
        upsert_node(repo, target, "Roadmap", payload["scenario"], {"quarters": payload["quarters"], "adopted": True}, refs, CURATOR,
                    status="approved")
        graph(f"roadmap scenario '{payload['scenario']}' adopted")

    # Every approval leaves a Decision node linked to its target (traceability for the dashboard)
    dec_id = "DEC-" + appr["id"].split("-")[-1]
    upsert_node(repo, dec_id, "Decision", f"{at.replace('_', ' ')}: {target}", {
        "approval_id": appr["id"], "action_type": at, "payload": payload, "decided_by": user["id"],
        "est_savings_usd": payload.get("est_savings_usd") or payload.get("annual_savings_usd"),
    }, refs, CURATOR, status="approved", confidence=1.0)
    if get_kg(tenant_id).node(target):
        add_edge(repo, "AFFECTS", dec_id, target, {}, [appr["id"]], CURATOR, status="approved", confidence=1.0)

    if autonomy >= 3 and at in TICKET_ACTIONS:
        title = payload.get("title") or f"{at.replace('_', ' ').title()}: {target}"
        t = _ticket(repo, appr, TICKET_ACTIONS[at], title, user["name"])
        effects["side_effects"].append(f"Ticket {t['key']} created (Jira, simulated)")
        effects["ticket"] = t["key"]
    _log(tenant_id, user, appr, effects, ts)
    return effects


def _log(tenant_id: str, user: dict, appr: dict, effects: dict, ts: str | None) -> None:
    audit.log(tenant_id, "agent", CURATOR, "graph_updated", appr["target_type"] or "record", appr["target_id"],
              {"action_type": appr["action_type"], "decision": appr["status"], **effects}, run_id=appr["run_id"],
              approval_id=appr["id"], ts=ts)
    for s in effects.get("side_effects", []):
        audit.log(tenant_id, "system", "simulated_integrations", "side_effect_executed", appr["target_type"] or "record",
                  appr["target_id"], {"effect": s}, run_id=appr["run_id"], approval_id=appr["id"], ts=ts)
