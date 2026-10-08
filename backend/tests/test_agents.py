"""Phases 2-4: agent behaviour and acceptance criteria (Section 14)."""

from __future__ import annotations

from collections import Counter

import pytest
from app.agents.registry import AGENTS
from app.db.session import Repo

from tests.conftest import analyze, run_agent

RUNNABLE = [a.id for a in AGENTS.values() if a.runnable]


# ---- Portfolio --------------------------------------------------------------------------------

def test_discovery_recall_on_ground_truth(generated):
    from app.agents.base import AgentContext
    from app.agents.portfolio.app_discovery import AppDiscovery

    for t in ("northgrid", "meridian"):
        rec = AppDiscovery().reconcile(AgentContext(t))
        m = {((x["raw"] if not x["hint"] else f"{x['raw']} | {x['hint']}"), x["source"]): x["app_id"] for x in rec["matches"]}
        gt = Repo(t).all("gt_app_aliases")
        ok = sum(1 for g in gt if m.get((g["raw_name"], g["source"])) == g["app_id"])
        assert ok / len(gt) >= 0.90, f"{t} recall {ok / len(gt):.3f}"


def test_discovery_shadow_it(generated):
    res = analyze("northgrid", "pf.app_discovery")
    new = [f for f in res.findings if f.type == "new_app"]
    assert len(new) >= 18
    assert sum(1 for f in new if f.genai and f.paid_via_expense) == 3
    truth = {g["canonical"].lower() for g in Repo("northgrid").all("gt_shadow_it")}
    found = " ".join(n.lower() for f in new for n in f.raw_names)
    hits = sum(1 for name in truth if name.split()[0].lower() in found)
    assert hits / len(truth) >= 0.9
    assert {f.type for f in res.findings} >= {"cmdb_duplicate", "cmdb_stale", "alias_merge"}


def test_time_quadrants_non_empty(generated):
    for t in ("northgrid", "meridian"):
        res = analyze(t, "pf.time_classifier")
        q = Counter(f.quadrant for f in res.findings)
        assert all(q[x] > 0 for x in ("Tolerate", "Invest", "Migrate", "Eliminate")), (t, q)


def test_cost_optimizer_finds_traps(generated):
    res = analyze("northgrid", "pf.cost_license_optimizer")
    types = Counter(f.type for f in res.findings)
    assert types["auto_renew_soon"] >= 2 and types["untagged_cloud"] >= 1 and types["zombie_app"] >= 3
    res = analyze("meridian", "pf.cost_license_optimizer")
    assert any(f.type == "above_market_price" for f in res.findings)


def test_overlaps_include_headline_clusters(generated):
    res = analyze("northgrid", "pf.overlap_finder")
    docs = next(f for f in res.findings if "TeamSpace Docs" in f.app_names)
    assert len(docs.app_ids) == 3 and docs.survivor_name == "TeamSpace Docs"
    res = analyze("meridian", "pf.overlap_finder")
    billing = next(f for f in res.findings if "Coastline Billing (Legacy)" in f.app_names)
    assert billing.survivor_name == "Meridian Convergent Billing"
    assert any({"Helios CRM Consumer", "Nimbus CRM B2B"} <= set(f.app_names) for f in res.findings)


def test_business_case(generated):
    res = analyze("northgrid", "pf.business_case_builder")
    bc = res.findings[0]
    assert bc.savings_3y_usd > 0 and bc.one_time_cost_usd > 0 and bc.payback_months > 0 and "# " in bc.body_md


# ---- Data & AI ---------------------------------------------------------------------------------

def test_risk_tier_distribution_and_block(generated):
    for t in ("northgrid", "meridian"):
        res = analyze(t, "dai.ai_risk_classifier")
        tiers = Counter(f.tier for f in res.findings)
        n = len(res.findings)
        assert tiers["unacceptable"] >= 1
        assert 0.1 <= tiers["high"] / n <= 0.25
        assert 0.25 <= tiers["limited"] / n <= 0.45
        assert 0.35 <= tiers["minimal"] / n <= 0.6


def test_risk_classifications_cite_rules_and_controls_have_sources(generated):
    for t in ("northgrid", "meridian"):
        res = analyze(t, "dai.ai_risk_classifier")
        for f in res.findings:
            assert f.triggers and all(tr["rule_id"].startswith("AIR-") for tr in f.triggers)
            assert all(c["source"] for c in f.required_controls)
            assert f.documentation_checklist


def test_specific_tiers(generated):
    res = {f.title: f.tier for f in analyze("northgrid", "dai.ai_risk_classifier").findings}
    assert res["Dynamic pricing recommendation"] == "high"
    assert res["Grid operator GenAI knowledge assistant"] == "high"
    assert res["Covert employee sentiment monitoring"] == "unacceptable"
    assert res["Vegetation encroachment detection from imagery"] == "minimal"
    res = {f.title: f.tier for f in analyze("meridian", "dai.ai_risk_classifier").findings}
    assert res["Next-best-offer"] == "high"
    assert res["Credit scoring at activation"] == "high"


def test_governance_policy_checker(generated):
    for t in ("northgrid", "meridian"):
        res = analyze(t, "dai.governance_policy_checker")
        checks = {f.check for f in res.findings}
        assert {"pii_requires_retention", "no_bi_direct_pii", "owner_required"} <= checks
        assert "no_restricted_nonprod" in checks or "masking_nonprod" in checks
    checks = {f.check for f in analyze("meridian", "dai.governance_policy_checker").findings}
    assert {"residency", "cpni_marketing"} <= checks
    checks = {f.check for f in analyze("northgrid", "dai.governance_policy_checker").findings}
    assert "cross_zone" in checks


def test_registry_steward(generated):
    res = analyze("northgrid", "dai.model_agent_registry_steward")
    assert res.facts["unregistered"] >= 6 and res.facts["no_eval_prod"]


def test_evidence_pack(generated):
    out = run_agent("northgrid", "shared.evidence_audit", regulation_or_policy_id="State PUC customer data privacy rule")
    assert out.findings and "# Evidence pack" in out.artifacts["body_md"] and out.artifacts["json"]["controls"]


# ---- Application & Enterprise ------------------------------------------------------------------

@pytest.mark.parametrize("tenant", ["northgrid", "meridian"])
def test_design_review_flags_planted_violations(generated, tenant):
    res = analyze(tenant, "app.design_review")
    by_title = {f.title: f for f in res.findings}
    from data_gen.generators.core import TENANT_CATALOG, load_yaml

    for d in load_yaml(TENANT_CATALOG[tenant])["design_docs"]:
        got = {c["standard_id"] for c in by_title[d["title"]].concerns}
        assert got == set(d["violations"]), (d["title"], got, d["violations"])
        if d["violations"]:
            assert by_title[d["title"]].verdict != "pass"


def test_design_review_suggests_reuse(generated):
    f = analyze("northgrid", "app.design_review", design_id="DES-001").findings[0]
    names = [Repo("northgrid").get("apis", a)["name"] for a in f.reuse_suggestions]
    assert "Customer Lookup API" in names


@pytest.mark.parametrize("tenant", ["northgrid", "meridian"])
def test_drift_detector_finds_boundary_violations(generated, tenant):
    res = analyze(tenant, "app.drift_detector")
    found = {f.integration_id for f in res.findings if f.type == "boundary_violation"}
    planted = {p["subject_id"] for p in Repo(tenant).all("gt_planted") if p["anomaly"] == "direct_db_link" and p["details"]["crosses_boundary"]}
    assert planted and planted == found
    assert "linkStyle" in res.artifacts["actual"]


def test_tech_debt_correlates_with_incidents(generated):
    res = analyze("northgrid", "app.tech_debt_radar")
    assert res.facts["eol_incident_share"] >= 0.5
    assert res.findings[0].score >= 60


def test_adr_writer_and_pattern_advisor(generated):
    res = analyze("northgrid", "app.adr_writer")
    assert len(res.findings) == 8 and res.facts["skipped"] >= 10
    res = analyze("northgrid", "app.pattern_advisor", text="stream meter events to analytics in real time")
    assert res.findings[0].pattern_id == "PAT-02"


def test_enterprise_agents(generated):
    inv = analyze("northgrid", "ea.investment_traceability")
    assert 20 <= inv.facts["orphan_pct"] <= 35
    assert any("wildfire" in u["statement"].lower() for u in inv.facts["unfunded"])
    cur = analyze("northgrid", "ea.capability_curator")
    om = next(f for f in cur.findings if f.name == "Outage Management")
    assert om.heat_score >= 12 and om.app_count >= 4
    rm = analyze("northgrid", "ea.roadmap_drafter")
    assert {f.name for f in rm.findings} == {"Cost-first", "Risk-first", "Speed-first"}
    for trig in ("gis_exit", "puc_mandate", "coop_acquisition", "oms_eos"):
        imp = analyze("northgrid", "ea.impact_analyst", trigger_id=trig).findings[0]
        assert imp.affected["applications"], trig
    mp = analyze("northgrid", "ea.strategy_capability_mapper")
    assert all(f.capability_ids for f in mp.findings)


# ---- Contract: every agent output is grounded --------------------------------------------------

@pytest.mark.parametrize("agent_id", RUNNABLE)
def test_every_agent_runs_and_cites(generated, agent_id):
    for t in ("northgrid", "meridian"):
        out = run_agent(t, agent_id)
        assert out.summary
        assert not out.flagged
        for f in out.findings:
            assert f["source_refs"], f"{agent_id} finding without source_refs"
        for a in out.proposed_actions:
            assert a.source_refs
        assert out.duration_ms < 2000, f"{agent_id} took {out.duration_ms} ms"


def test_validation_flags_uncited_findings(generated):
    from app.agents.base import AgentContext, AnalysisResult, Finding
    from app.agents.portfolio.lifecycle_watcher import LifecycleWatcher

    class Broken(LifecycleWatcher):
        id = "pf.lifecycle_watcher"

        def mock_run(self, ctx):  # noqa: ANN001, ANN201
            res = super().mock_run(ctx)
            res.findings.append(Finding.model_construct(source_refs=[]))
            return AnalysisResult(findings=res.findings, facts=res.facts)

    out = Broken().run(AgentContext("northgrid"))
    assert len(out.flagged) == 1
    assert all(f["source_refs"] for f in out.findings)
