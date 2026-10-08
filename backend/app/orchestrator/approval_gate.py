"""Approval gate (P2 draft-first, Section 8.2). Only a human decision moves anything to approved/rejected."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.session import Repo
from app.services import audit

# Roles allowed to decide each approver_role's items (Section 4). principal_architect may approve
# everything except budget (cio) and AI risk sign-off (risk_officer).
ROLE_CAN_APPROVE = {
    "principal_architect": {"principal_architect", "app_owner", "tech_lead", "security_architect", "data_governance_lead"},
    "cio": {"cio"},
    "app_owner": {"app_owner"},
    "security_architect": {"security_architect"},
    "data_governance_lead": {"data_governance_lead"},
    "risk_officer": {"risk_officer"},
    "tech_lead": {"tech_lead"},
}
LOW_RISK_BULK = {"tag_resources", "assign_owner"}


class ApprovalError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def can_decide(user_role: str, approver_role: str) -> bool:
    return approver_role in ROLE_CAN_APPROVE.get(user_role, set())


def create_approvals(ctx, agent, actions, force: bool = False) -> list[str]:  # noqa: ANN001
    """Create pending approval rows; re-runs update the existing pending row instead of duplicating it.
    An action already approved/rejected for the same target is not re-proposed unless its payload changed."""
    repo: Repo = ctx.repo
    existing = repo.all("approvals")
    created: list[str] = []
    for a in actions:
        same = [e for e in existing if e["action_type"] == a.action_type and e["target_id"] == a.target_id]
        pending = [e for e in same if e["status"] == "pending"]
        decided = [e for e in same if e["status"] != "pending"]
        payload = a.payload
        if pending:
            repo.update("approvals", pending[0]["id"], {
                "run_id": ctx.run_id, "payload_json": payload, "rationale": a.rationale,
                "source_refs_json": [r.model_dump() for r in a.source_refs], "priority": a.priority,
            })
            created.append(pending[0]["id"])
            continue
        if decided and not force and _same_payload(decided[-1]["payload_json"], payload):
            continue
        aid = "APR-" + uuid.uuid4().hex[:8].upper()
        repo.insert("approvals", {
            "id": aid, "tenant_id": ctx.tenant_id, "run_id": ctx.run_id, "agent_id": agent.id, "action_type": a.action_type,
            "target_id": a.target_id, "target_type": a.target_type, "payload_json": payload, "rationale": a.rationale,
            "source_refs_json": [r.model_dump() for r in a.source_refs], "approver_role": a.approver_role,
            "status": "pending", "decided_by_user_id": None, "decided_at": None, "decision_note": None,
            "edited_payload_json": None, "created_at": _now(), "applied": False, "side_effects_json": None,
            "priority": a.priority,
        })
        audit.log(ctx.tenant_id, "agent", agent.id, "approval_created", a.target_type or "record", a.target_id,
                  {"action_type": a.action_type, "approver_role": a.approver_role, "priority": a.priority,
                   "payload": payload}, run_id=ctx.run_id, approval_id=aid)
        existing.append({"action_type": a.action_type, "target_id": a.target_id, "status": "pending", "id": aid,
                         "payload_json": payload})
        created.append(aid)
    return created


def _same_payload(a: dict | None, b: dict | None) -> bool:
    keys = ("quadrant", "tier", "disposition", "survivor_app_id", "scenario")
    a, b = a or {}, b or {}
    return all(a.get(k) == b.get(k) for k in keys)


def decide(tenant_id: str, approval_id: str, user_id: str, decision: str, note: str | None = None,
           edited_payload: dict | None = None, ts: str | None = None) -> dict:
    from app.agents.shared.graph_curator import apply_approval
    from app.services import settings_service

    repo = Repo(tenant_id)
    appr = repo.get("approvals", approval_id)
    if not appr:
        raise ApprovalError("approval not found")
    if appr["status"] != "pending":
        raise ApprovalError(f"approval already {appr['status']}")
    user = repo.get("users", user_id)
    if not user:
        raise ApprovalError("unknown user")
    if not can_decide(user["role"], appr["approver_role"]):
        raise ApprovalError(f"role {user['role']} cannot decide items for {appr['approver_role']}")
    if decision not in ("approve", "reject", "edit"):
        raise ApprovalError("decision must be approve | edit | reject")
    status = {"approve": "approved", "reject": "rejected", "edit": "edited"}[decision]
    when = ts or _now()
    repo.update("approvals", approval_id, {
        "status": status, "decided_by_user_id": user_id, "decided_at": when, "decision_note": note,
        "edited_payload_json": edited_payload if decision == "edit" else None,
    })
    audit.log(tenant_id, "user", user_id, "approval_decided", appr["target_type"] or "record", appr["target_id"], {
        "decision": status, "note": note, "action_type": appr["action_type"], "agent_id": appr["agent_id"],
        "edited_payload": edited_payload if decision == "edit" else None,
    }, run_id=appr["run_id"], approval_id=approval_id, ts=when)
    appr = repo.get("approvals", approval_id)
    effects = apply_approval(tenant_id, appr, user, ts=when)
    repo.update("approvals", approval_id, {"applied": status != "rejected", "side_effects_json": effects})
    settings_service.recompute_acceptance(tenant_id, appr["agent_id"])
    return repo.get("approvals", approval_id)


def bulk_decide(tenant_id: str, ids: list[str], user_id: str, decision: str, note: str | None = None) -> list[dict]:
    repo = Repo(tenant_id)
    out = []
    for i in ids:
        a = repo.get("approvals", i)
        if not a or a["action_type"] not in LOW_RISK_BULK:
            raise ApprovalError(f"{i} is not a low-risk type eligible for bulk approval")
    for i in ids:
        out.append(decide(tenant_id, i, user_id, decision, note))
    return out
