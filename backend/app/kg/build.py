"""Deterministic knowledge-graph build from the raw source tables (no LLM). Section 6.4.

Confidence (Section 6.5): single-system facts 0.9; facts reconciled across 2+ systems 0.95-1.0;
inferred links (e.g. normalised tag matching) 0.5-0.85 with the method recorded in props.inference.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from sqlalchemy import delete, insert

from app.db import models
from app.db.session import Repo, bump_version

SYSTEM = "system:kg_build"


def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\b(prod|production|inc|ltd|llc)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _stable_frac(key: str) -> float:
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


class GraphBuilder:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.tenant_id = repo.tenant_id
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
        self._edge_keys: set[tuple[str, str, str]] = set()

    def node(self, id_: str, type_: str, name: str, props: dict | None = None, refs: list[str] | None = None,
             confidence: float = 0.9, status: str = "approved") -> None:
        if id_ in self.nodes:
            return
        self.nodes[id_] = {
            "id": id_, "tenant_id": self.tenant_id, "type": type_, "name": name, "props_json": props or {},
            "confidence": confidence, "source_refs_json": refs or [id_], "created_by": SYSTEM, "status": status,
            "updated_at": self.now,
        }

    def edge(self, type_: str, frm: str, to: str, props: dict | None = None, refs: list[str] | None = None,
             confidence: float = 0.9) -> None:
        if frm not in self.nodes or to not in self.nodes:
            return
        key = (type_, frm, to)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append({
            "id": f"E-{len(self.edges) + 1:06d}", "tenant_id": self.tenant_id, "type": type_, "from_id": frm, "to_id": to,
            "props_json": props or {}, "confidence": confidence, "source_refs_json": refs or [frm, to],
            "created_by": SYSTEM, "status": "approved", "updated_at": self.now,
        })

    # ------------------------------------------------------------------------------------------
    def build(self) -> tuple[int, int]:
        r = self.repo
        users = r.all("users")
        for u in users:
            self.node(u["id"], "Person", u["name"], {"role": u["role"], "title": u["title"], "email": u["email"]})
        regulations: set[str] = set()

        for g in r.all("goals"):
            self.node(g["id"], "Goal", g["statement"], {"horizon_year": g["horizon_year"], "kpi": g["kpi"],
                                                        "source_doc_id": g["source_doc_id"]}, [g["id"], g["source_doc_id"]])
        for d in r.all("strategy_docs"):
            self.node(d["id"], "Document", d["title"], {"type": d["type"], "year": d["year"]})
        for c in r.all("capabilities"):
            self.node(c["id"], "Capability", c["name"], {
                "level": c["level"], "parent_id": c["parent_id"], "strategic_importance": c["strategic_importance"],
                "maturity": c["maturity"], "owner_user_id": c["owner_user_id"],
            })
        for c in r.all("capabilities"):
            if c["parent_id"]:
                self.edge("PART_OF", c["id"], c["parent_id"], refs=[c["id"]])
            if c["owner_user_id"]:
                self.edge("OWNS", c["owner_user_id"], c["id"], refs=[c["id"]])

        incidents_by_app: dict[str, int] = {}
        for i in r.all("incidents"):
            incidents_by_app[i["app_id"]] = incidents_by_app.get(i["app_id"], 0) + 1
        for a in r.all("applications"):
            sources = len(a["discovered_via"] or [])
            conf = 0.9 if sources <= 1 else min(1.0, 0.9 + 0.03 * sources)
            confirmed = a["criticality"] <= 2 and _stable_frac(a["id"] + "owner") < 0.85 or _stable_frac(a["id"]) < 0.55
            self.node(a["id"], "Application", a["name"], {
                "vendor": a["vendor"], "category": a["category"], "hosting": a["hosting"], "criticality": a["criticality"],
                "annual_cost_usd": a["annual_cost_usd"], "user_count_90d": a["user_count_90d"],
                "lifecycle_status": a["lifecycle_status"], "zone": a["zone"], "in_cmdb": a["in_cmdb"],
                "discovered_via": a["discovered_via"], "data_classification": a["data_classification"],
                "vendor_eos_date": a["vendor_eos_date"], "owner_user_id": a["owner_user_id"],
                "owner_confirmed": bool(confirmed), "incident_count_24m": incidents_by_app.get(a["id"], 0),
                "disposition": None,
            }, [a["id"]], conf)
            if a["vendor"] and a["vendor"] != "In-house":
                vid = "VEN-" + re.sub(r"[^a-z0-9]+", "-", a["vendor"].lower()).strip("-")
                self.node(vid, "Vendor", a["vendor"], {}, [a["id"]])
                self.edge("SOLD_BY", a["id"], vid, refs=[a["id"]])
            for reg in a["regulatory_scope"] or []:
                regulations.add(reg)
        apps = r.by_id("applications")
        for a in apps.values():
            for cid in a["capability_ids"]:
                self.edge("REALIZES", a["id"], cid, refs=[a["id"]])
            if a["owner_user_id"]:
                self.edge("OWNS", a["owner_user_id"], a["id"], refs=[a["id"]])
            for reg in a["regulatory_scope"] or []:
                rid = "REG-" + _norm(reg)[:24]
                self.node(rid, "Regulation", reg, {}, [a["id"]])
                self.edge("GOVERNED_BY", a["id"], rid, refs=[a["id"]])

        for c in r.all("contracts"):
            self.node(c["id"], "Contract", f"{c['vendor']} contract", {
                "vendor": c["vendor"], "annual_value_usd": c["annual_value_usd"], "licensed_seats": c["licensed_seats"],
                "renewal_date": c["renewal_date"], "auto_renew": c["auto_renew"], "term_months": c["term_months"],
            })
            for aid in c["app_ids"]:
                self.edge("LICENSED_UNDER", aid, c["id"], refs=[c["id"]])

        for ci in r.all("cmdb_cis"):
            self.node(ci["id"], "ConfigItem", ci["ci_name"], {"ci_type": ci["ci_type"], "app_id": ci["app_id"],
                                                             "last_updated": ci["last_updated"], "ci_status": ci["ci_status"]})
            if ci["app_id"]:
                self.edge("DESCRIBES", ci["id"], ci["app_id"], refs=[ci["id"]])

        for api in r.all("apis"):
            self.node(api["id"], "API", api["name"], {
                "style": api["style"], "auth": api["auth"], "data_classification": api["data_classification"],
                "via_gateway": api["via_gateway"], "duplicate_group": api["duplicate_group"], "resource": api["resource"],
                "owner_app_id": api["owner_app_id"],
            })
            self.edge("EXPOSES", api["owner_app_id"], api["id"], refs=[api["id"]])
            for cons in api["consumers"] or []:
                self.edge("CONSUMES", cons, api["id"], refs=[api["id"]])
        dup_groups: dict[str, list[str]] = {}
        for api in r.all("apis"):
            if api["duplicate_group"]:
                dup_groups.setdefault(api["duplicate_group"], []).append(api["id"])
        for grp, ids in dup_groups.items():
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    self.edge("DUPLICATES", a, b, {"group": grp}, refs=[a, b])

        for s in r.all("standards"):
            self.node(s["id"], "Standard", s["title"], {"domain": s["domain"], "severity": s["severity"]})
        for p in r.all("patterns"):
            self.node(p["id"], "Pattern", p["name"], {"when_to_use": p["when_to_use"], "standard_ids": p["standard_ids"]})
            for sid in p["standard_ids"]:
                self.edge("CONFORMS_TO", p["id"], sid, refs=[p["id"]])

        boundary_std = "STD-OT-01" if self.repo.get("standards", "STD-OT-01") else "STD-BSS-01"
        for i in r.all("integrations"):
            self.node(i["id"], "Integration", f"{apps[i['from_app_id']]['name']} -> {apps[i['to_app_id']]['name']}", {
                "pattern": i["pattern"], "approved": i["approved"], "frequency": i["frequency"],
                "crosses_boundary": i["crosses_boundary"], "data_classification": i["data_classification"],
                "from_app_id": i["from_app_id"], "to_app_id": i["to_app_id"],
            })
            self.edge("INTEGRATES_WITH", i["from_app_id"], i["to_app_id"],
                      {"pattern": i["pattern"], "approved": i["approved"], "integration_id": i["id"]}, refs=[i["id"]])
            if i["pattern"] == "db_link":
                self.edge("VIOLATES", i["id"], "STD-INT-02", {"rule": "pattern == db_link"}, refs=[i["id"]])
                if i["crosses_boundary"]:
                    self.edge("VIOLATES", i["id"], boundary_std, {"rule": "db_link across boundary"}, refs=[i["id"]])
            elif not i["approved"]:
                self.edge("VIOLATES", i["id"], "STD-INT-03", {"rule": "approved == false"}, refs=[i["id"]])

        for rp in r.all("repos"):
            self.node(rp["id"], "Repo", rp["name"], {
                "language": rp["language"], "framework": rp["framework"], "framework_version": rp["framework_version"],
                "eol": rp["eol"], "open_critical_vulns": rp["open_critical_vulns"], "app_id": rp["app_id"],
            })
            self.edge("IMPLEMENTED_IN", rp["app_id"], rp["id"], refs=[rp["id"]])
            declared, actual = set(rp["declared_dependencies"] or []), set(rp["actual_dependencies"] or [])
            for dep in sorted(declared | actual):
                self.edge("DEPENDS_ON", rp["app_id"], dep, {"declared": dep in declared, "actual": dep in actual},
                          refs=[rp["id"]])

        # Cloud resources: tag -> application by normalised name (inferred, 0.85)
        app_norm = {}
        for a in apps.values():
            app_norm[_norm(a["name"])] = a["id"]
        for cr in r.all("cloud_resources"):
            self.node(cr["id"], "CloudResource", f"{cr['resource_type']} {cr['id']}", {
                "provider": cr["provider"], "account": cr["account"], "monthly_cost_usd": cr["monthly_cost_usd"],
                "utilization_pct": cr["utilization_pct"], "untagged": cr["untagged"], "tags": cr["tags"], "region": cr["region"],
            })
            tag = (cr["tags"] or {}).get("app")
            if tag:
                aid = app_norm.get(_norm(tag))
                if aid:
                    exact = tag == apps[aid]["name"]
                    self.edge("RUNS_ON", aid, cr["id"], {"inference": None if exact else "normalised tag match"},
                              refs=[cr["id"]], confidence=0.9 if exact else 0.85)
            else:
                self.edge("VIOLATES", cr["id"], "STD-CLD-01", {"rule": "missing app tag"}, refs=[cr["id"]])

        for d in r.all("datasets"):
            self.node(d["id"], "Dataset", d["name"], {
                "domain": d["domain"], "classification": d["classification"], "pii": d["pii"], "layer": d["layer"],
                "retention_days": d["retention_days"], "quality_score": d["quality_score"], "environment": d["environment"],
                "region": d["region"], "has_contract": d["has_contract"], "owner_user_id": d["owner_user_id"], "tags": d["tags"],
            })
            self.edge("STORED_IN", d["id"], d["system_app_id"], refs=[d["id"]])
            if d["owner_user_id"]:
                self.edge("OWNS", d["owner_user_id"], d["id"], refs=[d["id"]])
        for pl in r.all("pipelines"):
            self.node(pl["id"], "Pipeline", pl["name"], {"tool": pl["tool"], "schedule": pl["schedule"], "target_env": pl["target_env"]})
            for i in pl["inputs"]:
                self.edge("CONSUMES_DATA", pl["id"], i, refs=[pl["id"]])
            for o in pl["outputs"]:
                self.edge("PRODUCES", pl["id"], o, refs=[pl["id"]])
        for b in r.all("bi_assets"):
            self.node(b["id"], "BIAsset", b["name"], {"tool": b["tool"], "consumers": b["consumers"], "last_viewed_days": b["last_viewed_days"]})
            for i in b["dataset_ids"]:
                self.edge("CONSUMES_DATA", b["id"], i, refs=[b["id"]])
        for p in r.all("data_policies"):
            self.node(p["id"], "Policy", p["title"], {"regulation": p["regulation"], "severity": p["severity"], "rule": p["rule"]})
            rid = "REG-" + _norm(p["regulation"])[:24]
            self.node(rid, "Regulation", p["regulation"], {}, [p["id"]])
            self.edge("GOVERNED_BY", p["id"], rid, refs=[p["id"]])

        teams: set[str] = set()
        for u in r.all("ai_usecases"):
            self.node(u["id"], "AIUseCase", u["title"], {
                "status": u["status"], "pattern": u["pattern"], "sponsor_dept": u["sponsor_dept"],
                "value_estimate_usd": u["value_estimate_usd"], "risk_tier": None, "uses_personal_data": u["uses_personal_data"],
            })
            for d in u["dataset_ids"]:
                self.edge("USES_DATA", u["id"], d, refs=[u["id"]])
        for a in r.all("ai_assets"):
            self.node(a["id"], "AIAsset", a["name"], {
                "type": a["type"], "vendor": a["vendor"], "registered": a["registered"], "eval_status": a["eval_status"],
                "monthly_cost_usd": a["monthly_cost_usd"], "department": a["department"], "paid_via": a["paid_via"],
            })
            team_id = "TEAM-" + _norm(a["department"])[:20]
            if team_id not in teams:
                teams.add(team_id)
                self.node(team_id, "Team", a["department"], {}, [a["id"]])
            self.edge("OWNS", team_id, a["id"], refs=[a["id"]])
            for d in a["data_used"]:
                self.edge("CONSUMES_DATA", a["id"], d, refs=[a["id"]])
            if a["usecase_id"]:
                self.edge("IMPLEMENTS", a["id"], a["usecase_id"], refs=[a["id"]])

        for p in r.all("projects"):
            self.node(p["id"], "Project", p["name"], {"budget_usd": p["budget_usd"], "status": p["status"],
                                                      "orphan": not p["goal_ids"]})
            for c in p["capability_ids"]:
                self.edge("FUNDS", p["id"], c, refs=[p["id"]])
            for g in p["goal_ids"]:
                self.edge("TARGETS", p["id"], g, refs=[p["id"]])
            for a in p["app_ids"]:
                self.edge("CHANGES", p["id"], a, refs=[p["id"]])

        for adr in r.all("adrs"):
            self.node(adr["id"], "ADR", adr["title"], {"status": adr["status"], "date": adr["date"]})
            for a in adr["app_ids"]:
                self.edge("AFFECTS", adr["id"], a, refs=[adr["id"]])
        for d in r.all("design_docs"):
            self.node(d["id"], "Design", d["title"], {"team": d["team"], "status": d["status"], "submitted_at": d["submitted_at"]})
            for a in d["app_ids"]:
                self.edge("AFFECTS", d["id"], a, refs=[d["id"]])

        # Regulation edges for datasets by tag / PII
        tag_regs = {"sox": "SOX", "bcsi": "NERC CIP", "pci": "PCI DSS", "lawful_intercept": "Lawful intercept data handling",
                    "cpni": "Telecom customer privacy law (CPNI)"}
        privacy = next((p["regulation"] for p in r.all("data_policies") if "privacy" in p["regulation"].lower()
                        and p["regulation"] != "Privacy (enterprise policy)"), "Privacy (enterprise policy)")
        for d in r.all("datasets"):
            regs = [tag_regs[t] for t in d["tags"] or [] if t in tag_regs]
            if d["pii"]:
                regs.append(privacy)
            for reg in regs:
                rid = "REG-" + _norm(reg)[:24]
                self.node(rid, "Regulation", reg, {}, [d["id"]])
                self.edge("GOVERNED_BY", d["id"], rid, refs=[d["id"]])
        return len(self.nodes), len(self.edges)

    def write(self) -> None:
        eng = self.repo.engine
        with eng.begin() as conn:
            conn.execute(delete(models.kg_edges))
            conn.execute(delete(models.kg_nodes))
            nodes = list(self.nodes.values())
            for i in range(0, len(nodes), 500):
                conn.execute(insert(models.kg_nodes), nodes[i:i + 500])
            for i in range(0, len(self.edges), 500):
                conn.execute(insert(models.kg_edges), self.edges[i:i + 500])
        bump_version(self.tenant_id)


def build_graph(tenant_id: str) -> tuple[int, int]:
    b = GraphBuilder(Repo(tenant_id))
    counts = b.build()
    b.write()
    return counts
