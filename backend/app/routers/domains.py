"""Domain views: portfolio, AI governance, application architecture, enterprise architecture, data architecture.

Views combine source records with the latest agent run outputs and the approval state of each proposal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.agents.common import cloud_cost_by_app, contract_index, tco
from app.db.session import Repo
from app.kg.queries import get_kg
from app.routers.deps import tenant_dep
from app.services.metrics import savings

router = APIRouter()


def latest(repo: Repo, agent_id: str, params: dict | None = None) -> dict | None:
    runs = [r for r in repo.all("agent_runs") if r["agent_id"] == agent_id and r["status"] == "completed"]
    if params is not None:
        runs = [r for r in runs if all((r["input_json"] or {}).get(k) == v for k, v in params.items())]
    if not runs:
        return None
    r = max(runs, key=lambda r: r["started_at"])
    return r["output_json"]


def run_meta(out: dict | None) -> dict | None:
    if not out:
        return None
    return {k: out.get(k) for k in ("run_id", "agent_id", "agent_name", "summary", "started_at", "duration_ms", "mode",
                                     "autonomy_level", "llm_mode", "confidence", "cost", "approvals_created", "flagged")}


def approval_index(repo: Repo) -> dict[tuple[str, str], dict]:
    idx: dict[tuple[str, str], dict] = {}
    for a in sorted(repo.all("approvals"), key=lambda a: a["created_at"] or ""):
        idx[(a["action_type"], a["target_id"])] = {"id": a["id"], "status": a["status"], "approver_role": a["approver_role"],
                                                   "decided_by_user_id": a["decided_by_user_id"], "decided_at": a["decided_at"]}
    return idx


def by_target(repo: Repo) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for (at, t), v in approval_index(repo).items():
        idx.setdefault(t, []).append({**v, "action_type": at})
    return idx


# ---- Portfolio --------------------------------------------------------------------------------

@router.get("/portfolio/applications")
def applications(tenant: str = Depends(tenant_dep), quadrant: str | None = None, flag: str | None = None,
                 capability: str | None = None, q: str | None = None) -> dict:
    repo = Repo(tenant)
    kg = get_kg(tenant)
    caps = repo.by_id("capabilities")
    users = repo.by_id("users")
    time_out = latest(repo, "pf.time_classifier")
    time_by = {f["app_id"]: f for f in (time_out or {}).get("findings", [])}
    debt_out = latest(repo, "app.tech_debt_radar")
    debt_by = {f["app_id"]: f for f in (debt_out or {}).get("findings", [])}
    flags: dict[str, list[str]] = {}
    for agent in ("pf.cost_license_optimizer", "pf.lifecycle_watcher"):
        out = latest(repo, agent)
        for f in (out or {}).get("findings", []):
            if f.get("app_id"):
                flags.setdefault(f["app_id"], []).append(f["type"])
    appr = by_target(repo)
    rows = []
    for a in repo.all("applications"):
        n = kg.node(a["id"]) or {"props_json": {}, "confidence": 0.9}
        t = time_by.get(a["id"], {})
        row = {
            "id": a["id"], "name": a["name"], "vendor": a["vendor"], "category": a["category"], "hosting": a["hosting"],
            "criticality": a["criticality"], "capability_ids": a["capability_ids"],
            "capabilities": [caps[c]["name"] for c in a["capability_ids"]], "owner_user_id": a["owner_user_id"],
            "owner": users.get(a["owner_user_id"], {}).get("name"), "annual_cost_usd": a["annual_cost_usd"],
            "user_count_90d": a["user_count_90d"], "confidence": n["confidence"], "in_cmdb": a["in_cmdb"],
            "discovered_via": a["discovered_via"], "owner_confirmed": n["props_json"].get("owner_confirmed"),
            "disposition": n["props_json"].get("disposition"), "proposed_disposition": t.get("quadrant"),
            "business_fit": t.get("business_fit"), "tech_health": t.get("tech_health"),
            "debt_score": debt_by.get(a["id"], {}).get("score"), "flags": sorted(set(flags.get(a["id"], []))),
            "vendor_eos_date": a["vendor_eos_date"], "lifecycle_status": a["lifecycle_status"], "zone": a["zone"],
            "approvals": appr.get(a["id"], []), "shadow_it": False,
        }
        rows.append(row)
    for n in kg.by_type("Application"):
        if n["props_json"].get("shadow_it") and n["status"] == "approved":
            rows.append({"id": n["id"], "name": n["name"], "vendor": n["props_json"].get("vendor"), "category": "Shadow IT (confirmed)",
                         "hosting": "saas", "criticality": 4, "capability_ids": [], "capabilities": [], "owner_user_id": n["props_json"].get("owner_user_id"),
                         "owner": users.get(n["props_json"].get("owner_user_id"), {}).get("name"),
                         "annual_cost_usd": n["props_json"].get("annual_cost_usd", 0), "user_count_90d": None, "confidence": n["confidence"],
                         "in_cmdb": False, "discovered_via": n["props_json"].get("discovered_via", []), "owner_confirmed": True,
                         "disposition": None, "proposed_disposition": None, "business_fit": None, "tech_health": None, "debt_score": None,
                         "flags": ["shadow_it"], "vendor_eos_date": None, "lifecycle_status": "active", "zone": "it",
                         "approvals": appr.get(n["id"], []), "shadow_it": True})
    if quadrant:
        rows = [r for r in rows if (r["disposition"] or r["proposed_disposition"]) == quadrant]
    if flag:
        rows = [r for r in rows if flag in r["flags"]]
    if capability:
        rows = [r for r in rows if capability in r["capability_ids"]]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["name"].lower() or ql in (r["vendor"] or "").lower() or ql in r["category"].lower()]
    return {"items": rows, "total": len(rows), "time_run": run_meta(time_out)}


@router.get("/portfolio/applications/{app_id}")
def application(app_id: str, tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    a = repo.get("applications", app_id)
    kg = get_kg(tenant)
    if not a:
        n = kg.node(app_id)
        if not n:
            raise HTTPException(404, "application not found")
        return {"application": {"id": n["id"], "name": n["name"], **n["props_json"]}, "kg_node": n, "tco": None, "contracts": [],
                "cloud": [], "integrations": [], "repos": [], "incidents": [], "evidence": [], "approvals": by_target(repo).get(app_id, [])}
    cidx = contract_index(ctx := _Ctx(tenant))  # type: ignore[name-defined]
    t = tco(ctx, a, cidx, cloud_cost_by_app(ctx))
    contracts = cidx.get(app_id, [])
    cloud = [repo.get("cloud_resources", e["to_id"]) for e in kg.out_edges(app_id, "RUNS_ON")]
    ints = [i for i in repo.all("integrations") if app_id in (i["from_app_id"], i["to_app_id"])]
    apps = repo.by_id("applications")
    for i in ints:
        i["from_name"] = apps[i["from_app_id"]]["name"]
        i["to_name"] = apps[i["to_app_id"]]["name"]
    evidence = []
    for inv in [x for x in repo.all("invoice_lines") if x["matched_app_id"] == app_id][:3]:
        evidence.append({"record_id": inv["id"], "table": "invoice_lines", "excerpt": f"{inv['vendor']} ${inv['amount_usd']:,.0f} on {inv['invoice_date']}"})
    for ci in [c for c in repo.all("cmdb_cis") if c["app_id"] == app_id][:2]:
        evidence.append({"record_id": ci["id"], "table": "cmdb_cis", "excerpt": f"CMDB CI '{ci['ci_name']}'"})
    for c in contracts[:2]:
        evidence.append({"record_id": c["id"], "table": "contracts", "excerpt": f"{c['vendor']} ${c['annual_value_usd']:,.0f}/yr"})
    return {"application": a, "kg_node": kg.node(app_id), "tco": t, "contracts": contracts, "cloud": cloud[:30],
            "integrations": ints, "repos": [r for r in repo.all("repos") if r["app_id"] == app_id],
            "incidents": sorted([i for i in repo.all("incidents") if i["app_id"] == app_id], key=lambda i: i["date"], reverse=True)[:20],
            "evidence": evidence, "approvals": by_target(repo).get(app_id, [])}


class _Ctx:
    """Minimal AgentContext stand-in for helpers that need repo/kg."""

    def __init__(self, tenant: str):
        from app.agents.base import AgentContext

        self._c = AgentContext(tenant)
        self.repo = self._c.repo
        self.kg = self._c.kg
        self.today = self._c.today


def _with_status(out: dict | None, action_type: str, key: str, repo: Repo) -> list[dict]:
    idx = approval_index(repo)
    items = []
    for f in (out or {}).get("findings", []):
        items.append({**f, "approval": idx.get((action_type, f.get(key)))})
    return items


@router.get("/portfolio/discovery")
def discovery(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "pf.app_discovery")
    idx = approval_index(repo)
    items = []
    for f in (out or {}).get("findings", []):
        tgt = f.get("ci_id") or f.get("app_id")
        at = {"new_app": "confirm_app", "alias_merge": "confirm_app", "cmdb_duplicate": "merge_cmdb_ci", "cmdb_stale": "retire_cmdb_ci"}[f["type"]]
        items.append({**f, "approval": idx.get((at, tgt))})
    return {"run": run_meta(out), "items": items, "proposed_actions": (out or {}).get("proposed_actions", [])}


@router.get("/portfolio/overlaps")
def overlaps(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "pf.overlap_finder")
    items = _with_status(out, "propose_consolidation", "cluster_id", repo)
    idx = approval_index(repo)
    for it in items:
        it["business_case"] = idx.get(("approve_business_case", it["cluster_id"]))
    return {"run": run_meta(out), "items": items}


@router.get("/portfolio/lifecycle")
def lifecycle(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "pf.lifecycle_watcher")
    return {"run": run_meta(out), "items": (out or {}).get("findings", [])}


@router.get("/portfolio/time")
def time_view(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "pf.time_classifier")
    kg = get_kg(tenant)
    items = []
    for f in (out or {}).get("findings", []):
        n = kg.node(f["app_id"])
        items.append({**f, "disposition": n["props_json"].get("disposition") if n else None})
    return {"run": run_meta(out), "items": items}


@router.get("/portfolio/savings")
def savings_view(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    cost = latest(repo, "pf.cost_license_optimizer")
    ovl = latest(repo, "pf.overlap_finder")
    levers: dict[str, float] = {}
    labels = {"auto_renew_soon": "Cancel low-use auto-renewals", "low_seat_utilization": "Right-size licences",
              "untagged_cloud": "Cloud tagging & clean-up", "zombie_app": "Retire unused apps", "above_market_price": "Price to market"}
    for f in (cost or {}).get("findings", []):
        levers[labels.get(f["type"], f["type"])] = levers.get(labels.get(f["type"], f["type"]), 0) + f["est_savings_usd"]
    if ovl:
        levers["Consolidate overlaps"] = sum(f["est_savings_usd"] for f in ovl["findings"])
    return {"levers": [{"lever": k, "usd": round(v, -2)} for k, v in sorted(levers.items(), key=lambda kv: -kv[1])],
            "totals": savings(repo), "cost_run": run_meta(cost), "overlap_run": run_meta(ovl),
            "findings": (cost or {}).get("findings", [])}


# ---- AI governance ---------------------------------------------------------------------------

def _usecase_rows(repo: Repo) -> list[dict]:
    kg = get_kg(repo.tenant_id)
    intake = {f["usecase_id"]: f for f in (latest(repo, "dai.ai_usecase_intake") or {}).get("findings", [])}
    risk: dict[str, dict] = {}
    for r in sorted([r for r in repo.all("agent_runs") if r["agent_id"] == "dai.ai_risk_classifier" and r["status"] == "completed"],
                    key=lambda r: r["started_at"]):
        for f in r["output_json"]["findings"]:
            risk[f["usecase_id"]] = {**f, "run_id": r["id"]}
    idx = approval_index(repo)
    rows = []
    for u in repo.all("ai_usecases"):
        n = kg.node(u["id"])
        rows.append({**u, "intake": intake.get(u["id"]), "risk": risk.get(u["id"]),
                     "risk_tier": n["props_json"].get("risk_tier") if n else None,
                     "proposed_risk_tier": (risk.get(u["id"]) or {}).get("tier"),
                     "tier_approval": idx.get(("set_risk_tier", u["id"]))})
    rows.sort(key=lambda r: (r["intake"] or {}).get("rank", 999))
    return rows


@router.get("/ai/usecases")
def usecases(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    return {"items": _usecase_rows(repo), "intake_run": run_meta(latest(repo, "dai.ai_usecase_intake")),
            "risk_run": run_meta(latest(repo, "dai.ai_risk_classifier"))}


@router.get("/ai/usecases/{uc_id}")
def usecase(uc_id: str, tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    row = next((r for r in _usecase_rows(repo) if r["id"] == uc_id), None)
    if not row:
        raise HTTPException(404, "use case not found")
    ds = repo.by_id("datasets")
    row["datasets"] = [ds[d] for d in row["dataset_ids"]]
    row["assets"] = [a for a in repo.all("ai_assets") if a["usecase_id"] == uc_id]
    row["reference_architecture"] = latest(repo, "dai.ai_ref_arch_generator", {"usecase_id": uc_id})
    return row


@router.get("/ai/assets")
def ai_assets(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "dai.model_agent_registry_steward")
    flags = {f["asset_id"]: f for f in (out or {}).get("findings", [])}
    kg = get_kg(tenant)
    idx = by_target(repo)
    items = []
    for a in repo.all("ai_assets"):
        n = kg.node(a["id"])
        fl = [f for f in flags.get(a["id"], {}).get("flags", []) if not (f == "unregistered" and a["registered"])]
        items.append({**a, "flags": fl, "risk_tier": flags.get(a["id"], {}).get("risk_tier"),
                      "suspended": bool(n and n["props_json"].get("suspended")), "approvals": idx.get(a["id"], [])})
    spend: dict[str, float] = {}
    for a in items:
        key = a["department"]
        spend.setdefault(key, 0)
        spend[key] += a["monthly_cost_usd"]
    return {"run": run_meta(out), "items": items, "spend_by_department": spend,
            "registered": sum(1 for a in items if a["registered"]), "unregistered": sum(1 for a in items if not a["registered"])}


@router.get("/ai/risk-summary")
def risk_summary(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    rows = _usecase_rows(repo)
    tiers = {t: {"approved": 0, "proposed": 0} for t in ("unacceptable", "high", "limited", "minimal")}
    for r in rows:
        if r["risk_tier"]:
            tiers[r["risk_tier"]]["approved"] += 1
        elif r["proposed_risk_tier"]:
            tiers[r["proposed_risk_tier"]]["proposed"] += 1
    return {"tiers": tiers, "total": len(rows)}


# ---- Application architecture ---------------------------------------------------------------

def _review_index(repo: Repo) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for r in sorted([r for r in repo.all("agent_runs") if r["agent_id"] == "app.design_review" and r["status"] == "completed"],
                    key=lambda r: r["started_at"]):
        for f in r["output_json"]["findings"]:
            idx[f["design_id"]] = {**f, "run_id": r["id"], "run_started_at": r["started_at"]}
    return idx


@router.get("/app/designs")
def designs(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    rev = _review_index(repo)
    idx = approval_index(repo)
    items = [{**{k: v for k, v in d.items() if k != "body_md"}, "review": rev.get(d["id"]),
              "approval": idx.get(("publish_review", d["id"]))} for d in repo.all("design_docs")]
    items.sort(key=lambda d: (d["status"] != "submitted", d["submitted_at"]), reverse=False)
    return {"items": items}


@router.get("/app/designs/{design_id}")
def design(design_id: str, tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    d = repo.get("design_docs", design_id)
    if not d:
        raise HTTPException(404, "design not found")
    threat = latest(repo, "app.threat_model_assistant", {"design_id": design_id})
    if not threat:
        base = latest(repo, "app.threat_model_assistant")
        threat = base if base and base["findings"] and base["findings"][0]["subject_id"] == design_id else None
    idx = by_target(repo)
    return {**d, "review": _review_index(repo).get(design_id), "threat_model": threat, "approvals": idx.get(design_id, [])}


@router.get("/app/adrs")
def adrs(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "app.adr_writer")
    idx = approval_index(repo)
    drafts = [{**f, "approval": idx.get(("publish_adr", f["source_discussion_id"]))} for f in (out or {}).get("findings", [])]
    return {"run": run_meta(out), "drafts": drafts, "published": sorted(repo.all("adrs"), key=lambda a: a["date"], reverse=True),
            "discussions": [{k: v for k, v in d.items() if k != "extracted"} for d in repo.all("discussions")]}


@router.get("/app/drift")
def drift(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "app.drift_detector")
    idx = approval_index(repo)
    items = []
    for f in (out or {}).get("findings", []):
        items.append({**f, "approval": idx.get(("create_remediation_ticket", f.get("integration_id"))) or idx.get(("approve_exception", f.get("integration_id")))})
    apps = repo.by_id("applications")
    for it in items:
        it["app_name"] = apps[it["app_id"]]["name"]
        it["to_app_name"] = apps.get(it.get("to_app_id"), {}).get("name")
    return {"run": run_meta(out), "items": items, "diagrams": (out or {}).get("artifacts", {}),
            "tickets": [t for t in repo.all("tickets") if t["key"].startswith("SEC")]}


@router.get("/app/debt")
def debt(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "app.tech_debt_radar")
    return {"run": run_meta(out), "items": _with_status(out, "add_to_debt_register", "app_id", repo)}


@router.get("/app/apis")
def apis(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "app.integration_api_architect")
    apps = repo.by_id("applications")
    kg = get_kg(tenant)
    rows = []
    for a in repo.all("apis"):
        n = kg.node(a["id"])
        rows.append({**a, "owner_app": apps[a["owner_app_id"]]["name"], "consumer_names": [apps[c]["name"] for c in a["consumers"]],
                     "canonical": bool(n and n["props_json"].get("canonical")), "deprecated": bool(n and n["props_json"].get("deprecated"))})
    idx = approval_index(repo)
    findings = []
    for f in (out or {}).get("findings", []):
        findings.append({**f, "approval": idx.get(("designate_canonical_api", f.get("canonical_api_id")))})
    return {"run": run_meta(out), "findings": findings, "apis": rows}


# ---- Enterprise architecture -----------------------------------------------------------------

@router.get("/ea/capabilities")
def capabilities(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "ea.capability_curator")
    by = {f["capability_id"]: f for f in (out or {}).get("findings", [])}
    users = repo.by_id("users")
    items = []
    for c in repo.all("capabilities"):
        f = by.get(c["id"], {})
        items.append({**c, "heat_score": f.get("heat_score", c["strategic_importance"] * (5 - c["maturity"])),
                      "app_count": f.get("app_count"), "flags": f.get("flags", []), "annual_cost_usd": f.get("annual_cost_usd"),
                      "app_ids": f.get("app_ids", []), "owner": users.get(c["owner_user_id"], {}).get("name")})
    return {"run": run_meta(out), "items": items}


@router.get("/ea/goals")
def goals(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    mapper = latest(repo, "ea.strategy_capability_mapper")
    links = {f["goal_id"]: f for f in (mapper or {}).get("findings", [])}
    kg = get_kg(tenant)
    docs = repo.by_id("strategy_docs")
    projects = repo.all("projects")
    aidx = approval_index(repo)
    items = []
    for g in repo.all("goals"):
        sup = [e for e in kg.in_edges(g["id"], "SUPPORTS")]
        items.append({**g, "source_doc": docs[g["source_doc_id"]]["title"], "link": links.get(g["id"]),
                      "approval": aidx.get(("link_goal_capability", g["id"])),
                      "capability_links": [{"capability_id": e["from_id"], "name": kg.node(e["from_id"])["name"], "status": e["status"],
                                            "strength": e["props_json"].get("strength")} for e in sup],
                      "projects": [{"id": p["id"], "name": p["name"], "budget_usd": p["budget_usd"]} for p in projects if g["id"] in p["goal_ids"]]})
    return {"run": run_meta(mapper), "items": items, "documents": [{k: v for k, v in d.items()} for d in repo.all("strategy_docs")]}


@router.get("/ea/investment-alignment")
def investment(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "ea.investment_traceability")
    caps = repo.by_id("capabilities")
    projects = [{**p, "capabilities": [caps[c]["name"] for c in p["capability_ids"]]} for p in repo.all("projects")]
    idx = approval_index(repo)
    items = []
    for f in (out or {}).get("findings", []):
        key = ("propose_funding_review", f["goal_id"]) if f["status"] == "unfunded" else ("flag_orphan_project", f["project_ids"][0]) \
            if f["status"] == "orphan" else None
        items.append({**f, "approval": idx.get(key) if key else None})
    total = sum(p["budget_usd"] for p in projects)
    orphan = sum(p["budget_usd"] for p in projects if not p["goal_ids"])
    return {"run": run_meta(out), "items": items, "projects": projects,
            "facts": {"total_budget": total, "orphan_budget": orphan, "aligned_pct": round(100 * (1 - orphan / total), 1) if total else 0}}


@router.get("/ea/roadmaps")
def roadmaps(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "ea.roadmap_drafter")
    idx = approval_index(repo)
    items = []
    for f in (out or {}).get("findings", []):
        tid = f"ROADMAP-{f['name'].split('-')[0].upper()}"
        items.append({**f, "target_id": tid, "approval": idx.get(("adopt_roadmap_scenario", tid))})
    return {"run": run_meta(out), "items": items}


@router.get("/ea/impact-triggers")
def impact_triggers(tenant: str = Depends(tenant_dep)) -> list[dict]:
    return Repo(tenant).get_meta("impact_triggers", [])


@router.get("/ea/board-pack")
def board_pack(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "ea.board_assistant")
    return {"run": run_meta(out), "pack": (out or {}).get("findings", [None])[0], "body_md": (out or {}).get("artifacts", {}).get("body_md")}


# ---- Data architecture ------------------------------------------------------------------------

@router.get("/data/datasets")
def datasets(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    users = repo.by_id("users")
    apps = repo.by_id("applications")
    items = [{**d, "owner": users.get(d["owner_user_id"], {}).get("name"), "system": apps[d["system_app_id"]]["name"]}
             for d in repo.all("datasets")]
    return {"items": items}


@router.get("/data/policy-findings")
def policy_findings(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "dai.governance_policy_checker")
    by_t = by_target(repo)
    items = []
    for f in (out or {}).get("findings", []):
        apprs = [a for a in by_t.get(f["subject_id"], []) if a["action_type"] in ("apply_masking", "set_retention", "assign_owner", "block_pipeline")]
        items.append({**f, "approval": apprs[-1] if apprs else None})
    return {"run": run_meta(out), "items": items, "policies": repo.all("data_policies")}


@router.get("/data/products")
def products(tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    out = latest(repo, "dai.data_product_designer")
    idx = approval_index(repo)
    items = []
    for f in (out or {}).get("findings", []):
        tid = f"DP-{f['domain'].upper().replace(' ', '_').replace('&', 'AND')}"
        items.append({**f, "target_id": tid, "approval": idx.get(("approve_data_contract", tid))})
    return {"run": run_meta(out), "items": items}
