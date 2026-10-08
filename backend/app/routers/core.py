"""Tenants, users, metrics, records, raw sources, config, admin."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.config import TENANTS, demo_today, settings
from app.db.session import Repo
from app.routers.deps import PREFIX_TABLE, agents_using, find_record, tenant_dep
from app.services import metrics

router = APIRouter()

RAW_SOURCES = {
    "sso": ("sso_usage", "SSO identity provider", "Monthly login aggregates per application (24 months)."),
    "invoices": ("invoice_lines", "Accounts payable & expense reports", "Invoice lines and expense claims (24 months)."),
    "cmdb": ("cmdb_cis", "CMDB", "Configuration items of type application."),
    "cloud": ("cloud_resources", "Cloud billing (AWS / Azure)", "Resources with tags and monthly cost."),
    "repos": ("repos", "Source code (Git)", "Repositories with frameworks, vulnerabilities and dependencies."),
    "catalog": ("applications", "EA repository / app catalogue", "Existing application list (partial, unverified)."),
    "contracts": ("contracts", "Contract management", "Vendor contracts, seats, renewal terms."),
    "data_catalog": ("datasets", "Data catalogue", "Datasets with owners, classification and retention."),
    "pipelines": ("pipelines", "Pipeline orchestrators", "dbt / Airflow / Informatica / SSIS / Spark jobs."),
    "ai_assets": ("ai_assets", "Model registry + expense discovery", "Models, prompt apps, agents and vendor copilots."),
    "apis": ("apis", "API catalogue", "Published APIs with auth and consumers."),
    "itsm": ("incidents", "ITSM", "Incidents with severity and root cause (24 months)."),
    "documents": ("strategy_docs", "Document management", "Strategy papers, OKRs, board papers, mandates."),
    "discussions": ("discussions", "Slack / meeting notes", "Design discussions and decisions."),
    "design_intake": ("design_docs", "Design intake", "Design submissions for architecture review."),
}
PLANTED_BY_SOURCE = {
    "sso": ["app_not_in_cmdb", "shadow_it_tool"], "invoices": ["shadow_it_tool", "contract_trap", "low_seat_utilization"],
    "cmdb": ["cmdb_duplicate", "cmdb_stale_retired_app", "app_not_in_cmdb"], "cloud": ["untagged_cloud_resource"],
    "repos": ["dependency_drift"], "catalog": ["vendor_eos_within_9_months", "vendor_eos_within_12_months", "zombie_app_no_users"],
    "contracts": ["contract_trap", "low_seat_utilization"],
    "data_catalog": ["pii_without_retention", "pii_retention_over_policy", "dataset_without_owner", "residency_violation"],
    "pipelines": ["restricted_data_to_nonprod", "bcsi_cross_zone_unapproved", "cpni_to_marketing_without_consent"],
    "ai_assets": ["unregistered_ai_asset", "production_model_without_eval"], "apis": ["duplicate_api", "insecure_api"],
    "itsm": [], "documents": ["unfunded_goal", "orphan_project"], "discussions": [], "design_intake": ["design_violates_standards"],
}


@router.get("/tenants")
def tenants() -> list[dict]:
    out = []
    for t in TENANTS:
        if not settings.db_path(t).exists():
            out.append({"id": t, "name": t, "ready": False})
            continue
        r = Repo(t)
        row = r.all("tenants")[0]
        out.append({**row, "ready": True, "stats": {
            "applications": r.count("applications"), "datasets": r.count("datasets"), "ai_usecases": r.count("ai_usecases"),
            "pending_approvals": sum(1 for a in r.all("approvals") if a["status"] == "pending")}})
    return out


@router.get("/users")
def users(tenant: str = Depends(tenant_dep)) -> list[dict]:
    return Repo(tenant).all("users")


@router.get("/config")
def get_config() -> dict:
    return {"llm_mode": settings.llm_mode, "model": settings.anthropic_model, "live_available": bool(settings.anthropic_api_key),
            "demo_today": demo_today().isoformat(), "seed": settings.seed}


class ConfigPatch(BaseModel):
    llm_mode: str


@router.patch("/config")
def patch_config(body: ConfigPatch) -> dict:
    from app.llm.client import set_mode

    if body.llm_mode not in ("mock", "live"):
        raise HTTPException(400, "llm_mode must be mock or live")
    if body.llm_mode == "live" and not settings.anthropic_api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set in the environment; live mode unavailable")
    set_mode(body.llm_mode)
    return get_config()


@router.get("/metrics/dashboard")
def dashboard(tenant: str = Depends(tenant_dep)) -> dict:
    return metrics.dashboard(tenant)


@router.get("/records/{record_id}")
def record(record_id: str, tenant: str = Depends(tenant_dep)) -> dict:
    repo = Repo(tenant)
    table, row = find_record(repo, record_id)
    if not row:
        raise HTTPException(404, f"record {record_id} not found")
    from app.kg.queries import get_kg

    node = get_kg(tenant).node(record_id)
    return {"id": record_id, "table": table, "record": row, "kg_node": node, "used_by": agents_using(repo, record_id)}


@router.get("/raw")
def raw_index(tenant: str = Depends(tenant_dep), planted: bool = False) -> list[dict]:
    repo = Repo(tenant)
    gt = repo.all("gt_planted") if planted else []
    out = []
    for key, (table, label, desc) in RAW_SOURCES.items():
        notes = {}
        for p in gt:
            if p["anomaly"] in PLANTED_BY_SOURCE.get(key, []):
                notes[p["anomaly"]] = notes.get(p["anomaly"], 0) + 1
        out.append({"source": key, "table": table, "label": label, "description": desc, "rows": repo.count(table),
                    "planted": notes if planted else None})
    return out


@router.get("/raw/{source}")
def raw(source: str, tenant: str = Depends(tenant_dep), planted: bool = False, limit: int = Query(200, le=500)) -> dict:
    if source not in RAW_SOURCES:
        raise HTTPException(404, "unknown source")
    table, label, desc = RAW_SOURCES[source]
    repo = Repo(tenant)
    rows = repo.all(table)[:limit]
    if source == "documents":
        rows = [{**r, "body_md": r["body_md"][:600] + "…"} for r in rows]
    gt = [p for p in repo.all("gt_planted") if p["anomaly"] in PLANTED_BY_SOURCE.get(source, [])] if planted else []
    return {"source": source, "label": label, "description": desc, "rows": rows, "total": repo.count(table), "planted": gt}


@router.post("/admin/reset")
def reset(tenant: str = Query(...)) -> dict:
    if tenant not in TENANTS:
        raise HTTPException(404, "unknown tenant")
    from data_gen.generate import generate

    generate(tenant, settings.seed, quiet=True)
    return {"status": "regenerated", "tenant": tenant}


@router.get("/tickets")
def tickets(tenant: str = Depends(tenant_dep)) -> list[dict]:
    return sorted(Repo(tenant).all("tickets"), key=lambda t: t["created_at"], reverse=True)


@router.get("/prefixes")
def prefixes() -> dict:
    return PREFIX_TABLE
