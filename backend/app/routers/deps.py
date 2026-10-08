"""Shared request dependencies: tenant scoping (P5) and record lookup helpers."""

from __future__ import annotations

import json

from fastapi import Header, HTTPException, Query

from app.config import TENANTS, settings
from app.db.session import Repo

PREFIX_TABLE = {
    "APP": "applications", "INV": "invoice_lines", "CON": "contracts", "SSO": "sso_usage", "CLD": "cloud_resources",
    "CI": "cmdb_cis", "API": "apis", "INT": "integrations", "REPO": "repos", "INC": "incidents", "PRJ": "projects",
    "DES": "design_docs", "STD": "standards", "PAT": "patterns", "ADR": "adrs", "DS": "datasets", "PL": "pipelines",
    "BI": "bi_assets", "POL": "data_policies", "AIU": "ai_usecases", "AIA": "ai_assets", "DSC": "discussions",
    "CAP": "capabilities", "DOC": "strategy_docs", "GOAL": "goals", "USR": "users", "APR": "approvals", "RUN": "agent_runs",
    "TCK": "tickets", "AUD": "audit_events",
}


def tenant_dep(x_tenant_id: str | None = Header(default=None), tenant_id: str | None = Query(default=None)) -> str:
    t = tenant_id or x_tenant_id
    if not t:
        raise HTTPException(400, "tenant_id header (X-Tenant-Id) or query parameter is required")
    if t not in TENANTS:
        raise HTTPException(404, f"unknown tenant {t}")
    if not settings.db_path(t).exists():
        raise HTTPException(503, f"tenant {t} has no data yet — run `make data`")
    return t


def find_record(repo: Repo, rid: str) -> tuple[str | None, dict | None]:
    prefix = rid.split("-")[0]
    table = PREFIX_TABLE.get(prefix)
    if table:
        row = repo.get(table, rid)
        if row:
            return table, row
    if prefix == "CAND" or table is None:
        from app.kg.queries import get_kg

        n = get_kg(repo.tenant_id).node(rid)
        if n:
            return "kg_nodes", n
    return None, None


def agents_using(repo: Repo, rid: str) -> list[dict]:
    needle = f'"{rid}"'
    out = []
    for r in repo.all("agent_runs"):
        if r["output_json"] and needle in json.dumps(r["output_json"]):
            out.append({"run_id": r["id"], "agent_id": r["agent_id"], "started_at": r["started_at"]})
    out.sort(key=lambda x: x["started_at"], reverse=True)
    seen, dedup = set(), []
    for x in out:
        if x["agent_id"] not in seen:
            seen.add(x["agent_id"])
            dedup.append(x)
    return dedup
