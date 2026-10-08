"""Agents registry, autonomy settings, runs, orchestration, approvals, audit, copilot, evidence, briefing."""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.agents.base import AgentContext
from app.agents.registry import AGENTS, DOMAIN_LABELS, get_agent
from app.agents.shared import copilot as copilot_mod
from app.agents.shared.orchestrator import orchestrate as do_orchestrate
from app.db.session import Repo
from app.orchestrator import approval_gate
from app.routers.deps import tenant_dep
from app.services import audit

router = APIRouter()


# ---- agents -----------------------------------------------------------------------------------

@router.get("/agents")
def list_agents(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    st = {s["agent_id"]: s for s in repo.all("agent_settings")}
    runs: dict[str, int] = {}
    for r in repo.all("agent_runs"):
        runs[r["agent_id"]] = runs.get(r["agent_id"], 0) + 1
    items = []
    for a in AGENTS.values():
        s = st.get(a.id, {})
        items.append({**a.meta(), "autonomy_level": s.get("autonomy_level", a.default_autonomy), "enabled": s.get("enabled", True),
                      "acceptance_rate_30d": s.get("acceptance_rate_30d"), "decided_30d": s.get("seed_decided"),
                      "last_run_at": s.get("last_run_at"), "run_count": runs.get(a.id, 0)})
    return {"items": items, "domains": DOMAIN_LABELS,
            "promotion_rules": {"L2": "acceptance >= 80% over 4 weeks", "L3": "acceptance >= 90% over 8 weeks",
                                "L4": "Act and notify — not enabled in prototype"}}


class SettingsPatch(BaseModel):
    autonomy_level: int | None = Field(default=None, ge=1, le=4)
    enabled: bool | None = None
    user_id: str | None = None


@router.patch("/agents/{agent_id}/settings")
def patch_settings(agent_id: str, body: SettingsPatch, tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    get_agent(agent_id)
    if not body.user_id:
        raise HTTPException(403, "user_id is required; only the principal architect can change autonomy levels")
    if body.user_id:
        u = repo.get("users", body.user_id)
        if not u or u["role"] != "principal_architect":
            raise HTTPException(403, "only the principal architect can change autonomy levels")
    vals = {k: v for k, v in body.model_dump().items() if v is not None and k != "user_id"}
    if vals.get("autonomy_level") == 4:
        raise HTTPException(400, "L4 (act and notify) is display-only in the prototype")
    repo.update_where("agent_settings", {"tenant_id": tenant, "agent_id": agent_id}, vals)
    audit.log(tenant, "user", body.user_id or "unknown", "agent_settings_changed", "agent", agent_id, vals)
    return next(s for s in repo.all("agent_settings") if s["agent_id"] == agent_id)


class RunRequest(BaseModel):
    agent_id: str
    params: dict = Field(default_factory=dict)
    user_id: str | None = None


@router.post("/agents/run")
def run_agent(body: RunRequest, tenant: str = Depends(tenant_dep)) -> dict:
    try:
        agent = get_agent(body.agent_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not agent.runnable:
        raise HTTPException(400, f"{agent.id} is not directly runnable")
    st = {s["agent_id"]: s for s in Repo(tenant).all("agent_settings")}
    if st.get(agent.id) and not st[agent.id]["enabled"]:
        raise HTTPException(400, f"{agent.id} is disabled for this tenant")
    params = {k: v for k, v in body.params.items() if v not in (None, "")}
    out = agent.run(AgentContext(tenant_id=tenant, params=params, user_id=body.user_id, trigger="ui"))
    return out.model_dump()


class OrchestrateRequest(BaseModel):
    request_text: str
    user_id: str | None = None


@router.post("/orchestrate")
def orchestrate(body: OrchestrateRequest, tenant: str = Depends(tenant_dep)) -> dict:
    return do_orchestrate(tenant, body.request_text, body.user_id)


@router.get("/runs")
def runs(tenant: str = Depends(tenant_dep), agent_id: str | None = None, limit: int = Query(100, le=500)) -> list[dict]:
    rs = [r for r in Repo(tenant).all("agent_runs") if not agent_id or r["agent_id"] == agent_id]
    rs.sort(key=lambda r: r["started_at"], reverse=True)
    out = []
    for r in rs[:limit]:
        o = r["output_json"] or {}
        out.append({k: r[k] for k in ("id", "agent_id", "trigger", "input_json", "status", "started_at", "finished_at", "cost_json",
                                     "autonomy_level", "user_id")} | {
            "summary": o.get("summary") or o.get("error"), "findings": len(o.get("findings", [])),
            "proposed_actions": len(o.get("proposed_actions", [])), "approvals_created": len(o.get("approvals_created", [])),
            "llm_mode": o.get("llm_mode"), "duration_ms": o.get("duration_ms")})
    return out


@router.get("/runs/{run_id}")
def run(run_id: str, tenant: str = Depends(tenant_dep)) -> dict:
    r = Repo(tenant).get("agent_runs", run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r


class ProposeRequest(BaseModel):
    user_id: str
    indices: list[int] | None = None
    action_types: list[str] | None = None


@router.post("/runs/{run_id}/propose")
def propose_from_run(run_id: str, body: ProposeRequest, tenant: str = Depends(tenant_dep)) -> dict:
    """Human-initiated promotion of L1 observations into approval items (e.g. 'Send to owners for confirmation')."""
    from app.agents.base import ProposedAction

    repo = Repo(tenant)
    r = repo.get("agent_runs", run_id)
    if not r:
        raise HTTPException(404, "run not found")
    acts = [ProposedAction(**a) for a in r["output_json"]["proposed_actions"]]
    if body.action_types:
        acts = [a for a in acts if a.action_type in body.action_types]
    if body.indices is not None:
        acts = [a for i, a in enumerate(acts) if i in set(body.indices)]
    ctx = AgentContext(tenant_id=tenant, user_id=body.user_id, trigger="ui")
    ctx.run_id = run_id
    ids = approval_gate.create_approvals(ctx, get_agent(r["agent_id"]), acts)
    audit.log(tenant, "user", body.user_id, "observations_promoted", "agent_run", run_id, {"approvals": len(ids)}, run_id=run_id)
    return {"approvals_created": ids}


# ---- approvals ----------------------------------------------------------------------------------

@router.get("/approvals")
def approvals(tenant: str = Depends(tenant_dep), status: str | None = None, role: str | None = None,
              user_id: str | None = None, agent_id: str | None = None) -> dict:
    repo = Repo(tenant)
    items = repo.all("approvals")
    if status:
        items = [a for a in items if a["status"] == status]
    if role:
        allowed = approval_gate.ROLE_CAN_APPROVE.get(role, {role})
        items = [a for a in items if a["approver_role"] in allowed]
    if agent_id:
        items = [a for a in items if a["agent_id"] == agent_id]
    if user_id:
        u = repo.get("users", user_id)
        if u and u["role"] == "app_owner":
            # app owners see owner items for their own apps, items addressed to them, and unowned shadow-IT candidates
            inventory = {a["id"]: a for a in repo.all("applications")}

            def visible(a: dict) -> bool:
                if a["approver_role"] != "app_owner":
                    return True
                if a["target_id"] in inventory:
                    return inventory[a["target_id"]]["owner_user_id"] == user_id
                owner = (a["payload_json"] or {}).get("owner_user_id")
                return owner in (None, user_id)

            items = [a for a in items if visible(a)]
    users = repo.by_id("users")
    for a in items:
        a["decided_by"] = users.get(a["decided_by_user_id"], {}).get("name") if a["decided_by_user_id"] else None
        a["agent_name"] = AGENTS[a["agent_id"]].name if a["agent_id"] in AGENTS else a["agent_id"]
    items.sort(key=lambda a: (a["status"] != "pending", a["priority"] or 3, a["created_at"] or ""), reverse=False)
    counts = {}
    for a in repo.all("approvals"):
        counts[a["status"]] = counts.get(a["status"], 0) + 1
    return {"items": items, "counts": counts, "bulk_types": sorted(approval_gate.LOW_RISK_BULK)}


class DecideRequest(BaseModel):
    decision: str  # approve | edit | reject
    user_id: str
    note: str | None = None
    edited_payload: dict | None = None


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: str, body: DecideRequest, tenant: str = Depends(tenant_dep)) -> dict:
    try:
        return approval_gate.decide(tenant, approval_id, body.user_id, body.decision, body.note, body.edited_payload)
    except approval_gate.ApprovalError as exc:
        raise HTTPException(400, str(exc)) from exc


class BulkRequest(BaseModel):
    ids: list[str]
    user_id: str
    decision: str = "approve"
    note: str | None = None


@router.post("/approvals/bulk")
def bulk(body: BulkRequest, tenant: str = Depends(tenant_dep)) -> list[dict]:
    try:
        return approval_gate.bulk_decide(tenant, body.ids, body.user_id, body.decision, body.note)
    except approval_gate.ApprovalError as exc:
        raise HTTPException(400, str(exc)) from exc


class ManualProposal(BaseModel):
    action_type: str
    target_id: str
    target_type: str = ""
    rationale: str
    source_refs: list[dict]
    approver_role: str
    payload: dict = Field(default_factory=dict)
    user_id: str
    agent_id: str = "app.design_review"


@router.post("/approvals")
def create_manual(body: ManualProposal, tenant: str = Depends(tenant_dep)) -> dict:
    """A human raises an item (e.g. 'Request exception' on a design concern)."""
    from app.agents.base import Evidence, ProposedAction

    ctx = AgentContext(tenant_id=tenant, user_id=body.user_id, trigger="ui")
    act = ProposedAction(action_type=body.action_type, target_id=body.target_id, target_type=body.target_type, payload=body.payload,
                         rationale=body.rationale, source_refs=[Evidence(**r) for r in body.source_refs], approver_role=body.approver_role)
    ids = approval_gate.create_approvals(ctx, get_agent(body.agent_id), [act], force=True)
    return {"approval_ids": ids}


# ---- audit ----------------------------------------------------------------------------------------

def _audit_rows(tenant: str, actor: str | None, agent: str | None, subject: str | None, frm: str | None, to: str | None,
                event_type: str | None = None) -> list[dict]:
    rows = Repo(tenant).all("audit_events")
    if actor:
        rows = [r for r in rows if r["actor_type"] == actor or r["actor_id"] == actor]
    if agent:
        rows = [r for r in rows if r["actor_id"] == agent or (r["details_json"] or {}).get("agent_id") == agent]
    if subject:
        rows = [r for r in rows if subject.lower() in (r["subject_id"] or "").lower()]
    if event_type:
        rows = [r for r in rows if r["event_type"] == event_type]
    if frm:
        rows = [r for r in rows if r["ts"] >= frm]
    if to:
        rows = [r for r in rows if r["ts"] <= to + "T23:59:59"]
    return sorted(rows, key=lambda r: r["ts"], reverse=True)


@router.get("/audit")
def audit_list(tenant: str = Depends(tenant_dep), actor: str | None = None, agent: str | None = None, subject: str | None = None,
               from_: str | None = Query(None, alias="from"), to: str | None = None, event_type: str | None = None,
               limit: int = Query(500, le=5000)) -> dict:
    rows = _audit_rows(tenant, actor, agent, subject, from_, to, event_type)
    return {"items": rows[:limit], "total": len(rows)}


@router.get("/audit/export")
def audit_export(tenant: str = Depends(tenant_dep), format: str = "json", actor: str | None = None, agent: str | None = None,
                 subject: str | None = None, from_: str | None = Query(None, alias="from"), to: str | None = None,
                 event_type: str | None = None):  # noqa: ANN201
    rows = _audit_rows(tenant, actor, agent, subject, from_, to, event_type)
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["id", "ts", "actor_type", "actor_id", "event_type", "subject_type", "subject_id",
                                            "run_id", "approval_id", "details_json"])
        w.writeheader()
        for r in rows:
            w.writerow({**{k: r[k] for k in w.fieldnames if k != "details_json"}, "details_json": json.dumps(r["details_json"])})
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": f"attachment; filename=audit_{tenant}.csv"})
    return PlainTextResponse(json.dumps(rows, indent=1, default=str), media_type="application/json",
                             headers={"Content-Disposition": f"attachment; filename=audit_{tenant}.json"})


# ---- copilot / evidence / briefing ----------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    history: list[dict] = Field(default_factory=list)
    user_id: str | None = None


@router.post("/copilot/ask")
def ask(body: AskRequest, tenant: str = Depends(tenant_dep)) -> dict:
    return copilot_mod.ask(tenant, body.question, body.history, body.user_id)


@router.get("/copilot/suggestions")
def suggestions(tenant: str = Depends(tenant_dep)) -> list[str]:
    return copilot_mod.suggested(tenant)


class EvidenceRequest(BaseModel):
    regulation_or_policy_id: str | None = None
    user_id: str | None = None


@router.post("/evidence/pack")
def evidence(body: EvidenceRequest, tenant: str = Depends(tenant_dep)) -> dict:
    out = get_agent("shared.evidence_audit").run(AgentContext(
        tenant_id=tenant, params={"regulation_or_policy_id": body.regulation_or_policy_id} if body.regulation_or_policy_id else {},
        user_id=body.user_id))
    return {"run_id": out.run_id, "summary": out.summary, "markdown": out.artifacts.get("body_md"), "json": out.artifacts.get("json"),
            "findings": out.findings}


@router.get("/evidence/regulations")
def regulations(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    return {"regulations": repo.get_meta("evidence_regulations", []), "policies": [{"id": p["id"], "title": p["title"],
                                                                                  "regulation": p["regulation"]} for p in repo.all("data_policies")]}


class BriefingRequest(BaseModel):
    user_id: str | None = None


@router.post("/briefing/generate")
def briefing(body: BriefingRequest | None = None, tenant: str = Depends(tenant_dep)) -> dict:
    out = get_agent("shared.exec_briefing").run(AgentContext(tenant_id=tenant, user_id=body.user_id if body else None))
    return {"run_id": out.run_id, "summary": out.summary, "markdown": out.artifacts.get("body_md"), "findings": out.findings,
            "llm_mode": out.llm_mode, "cost": out.cost.model_dump() if out.cost else None}
