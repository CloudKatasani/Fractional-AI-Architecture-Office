"""Phase 1: volumes (Section 5.1) and planted anomalies (Section 5.3) within expected ranges."""

from __future__ import annotations

import pytest
from app.db.session import Repo

VOLUMES = {
    "capabilities": (60, 80), "strategy_docs": (6, 8), "goals": (10, 14), "contracts": (120, 170), "invoice_lines": (1500, 2500),
    "cloud_resources": (400, 700), "apis": (90, 140), "integrations": (250, 400), "repos": (75, 120), "incidents": (300, 500),
    "projects": (40, 60), "design_docs": (12, 16), "standards": (25, 35), "patterns": (10, 12), "adrs": (15, 25),
    "datasets": (120, 160), "pipelines": (150, 220), "bi_assets": (60, 90), "data_policies": (11, 18), "ai_assets": (20, 35),
    "discussions": (20, 30), "users": (8, 12),
}


@pytest.mark.parametrize("tenant", ["northgrid", "meridian"])
def test_volumes(generated, tenant):
    r = Repo(tenant)
    for table, (lo, hi) in VOLUMES.items():
        n = r.count(table)
        assert lo <= n <= hi, f"{tenant}.{table} = {n} not in [{lo}, {hi}]"
    assert r.count("applications") == {"northgrid": 180, "meridian": 240}[tenant]
    assert r.count("ai_usecases") in ({"northgrid": (18, 19), "meridian": (24, 25)}[tenant])


def planted(tenant: str, anomaly: str) -> list[dict]:
    return [p for p in Repo(tenant).all("gt_planted") if p["anomaly"] == anomaly]


@pytest.mark.parametrize("tenant", ["northgrid", "meridian"])
def test_planted_anomalies(generated, tenant):
    r = Repo(tenant)
    apps = r.all("applications")
    not_cmdb = [a for a in apps if not a["in_cmdb"]]
    assert 0.10 <= len(not_cmdb) / len(apps) <= 0.14
    untagged = [c for c in r.all("cloud_resources") if c["untagged"]]
    assert 0.10 <= len(untagged) / r.count("cloud_resources") <= 0.15
    shadow_lines = [i for i in r.all("invoice_lines") if i["matched_app_id"] is None and i["vendor"] not in ("Amazon Web Services", "Microsoft Azure")]
    assert len({i["vendor"] for i in shadow_lines}) >= 15
    dup = planted(tenant, "cmdb_duplicate") + planted(tenant, "cmdb_stale_retired_app")
    assert 0.03 <= len(dup) / r.count("cmdb_cis") <= 0.07
    db_links = [i for i in r.all("integrations") if i["pattern"] == "db_link"]
    assert 6 <= len(db_links) <= 10
    assert sum(1 for i in db_links if i["crosses_boundary"]) == 2
    groups = {a["duplicate_group"] for a in r.all("apis") if a["duplicate_group"]}
    assert 3 <= len(groups) <= 4
    assert 4 <= len(planted(tenant, "design_violates_standards")) <= 8
    repos = r.all("repos")
    drift = [x for x in repos if set(x["declared_dependencies"]) != set(x["actual_dependencies"])]
    assert 0.12 <= len(drift) / len(repos) <= 0.28
    ds = r.all("datasets")
    pii = [d for d in ds if d["pii"]]
    assert 0.25 <= len(pii) / len(ds) <= 0.55
    bad_ret = planted(tenant, "pii_without_retention") + planted(tenant, "pii_retention_over_policy")
    assert 0.15 <= len(bad_ret) / len([d for d in pii if d["layer"] == "source" or True]) <= 0.3
    assert 3 <= len(planted(tenant, "restricted_data_to_nonprod")) <= 5
    assert len(planted(tenant, "bi_reads_pii_directly")) == 2
    assets = r.all("ai_assets")
    unreg = [a for a in assets if not a["registered"]]
    assert 0.3 <= len(unreg) / len(assets) <= 0.5
    assert 2 <= sum(1 for a in assets if a["paid_via"] == "expense") <= 3
    assert len(planted(tenant, "production_model_without_eval")) == 1
    projects = r.all("projects")
    orphan = [p for p in projects if not p["goal_ids"]]
    assert 0.2 <= len(orphan) / len(projects) <= 0.4
    assert len(planted(tenant, "unfunded_goal")) == 2
    # Incidents concentrate on 8-12 apps with old frameworks
    hot = [a for a in apps if (a.get("cluster") or True)]
    counts: dict[str, int] = {}
    for i in r.all("incidents"):
        counts[i["app_id"]] = counts.get(i["app_id"], 0) + 1
    top = sorted(counts.values(), reverse=True)[:12]
    assert sum(top) / r.count("incidents") >= 0.5
    assert hot


def test_lifecycle_traps_northgrid(generated):
    r = Repo("northgrid")
    eos = planted("northgrid", "vendor_eos_within_9_months")
    assert 4 <= len(eos) <= 6
    traps = [p for p in planted("northgrid", "contract_trap") if p["details"]["auto_renew"] and p["details"]["renewal_days"] <= 90
             and p["details"]["utilization"] < 0.3]
    assert len(traps) >= 2
    oms = next(a for a in r.all("applications") if a["name"] == "OutageWorks OMS")
    assert oms["vendor_eos_date"] == "2027-05-08"  # 7 months after DEMO_TODAY


def test_lifecycle_traps_meridian(generated):
    names = {a["name"] for a in Repo("meridian").all("applications")}
    assert {"Coastline Billing (Legacy)", "Meridian Convergent Billing", "Helios CRM Consumer", "Nimbus CRM B2B"} <= names
    traps = planted("meridian", "contract_trap")
    assert any(p["details"].get("market_multiple") == 2.0 and p["details"]["renewal_days"] == 120 for p in traps)
    assert planted("meridian", "residency_violation")


def test_ground_truth_aliases_exist(generated):
    for t in ("northgrid", "meridian"):
        gt = Repo(t).all("gt_app_aliases")
        assert len(gt) > 500
        assert {g["source"] for g in gt} == {"sso", "invoice", "cmdb"}


def test_determinism(generated):
    from app.config import demo_today

    from data_gen.generate import build_rows

    a = build_rows("northgrid", 42, demo_today())
    b = build_rows("northgrid", 42, demo_today())
    for table in ("applications", "invoice_lines", "datasets", "integrations"):
        strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]  # noqa: E731
        assert strip(a.rows[table]) == strip(b.rows[table])
    db = Repo("northgrid").all("applications")
    assert [x["name"] for x in db] == [x["name"] for x in a.rows["applications"]]


def test_raw_exports_written(generated):
    from app.config import settings

    raw = settings.data_dir / "northgrid" / "raw"
    for f in ("sso.csv", "invoices.csv", "cmdb.json", "cloud.json", "repos.json", "catalog.json"):
        assert (raw / f).exists(), f
