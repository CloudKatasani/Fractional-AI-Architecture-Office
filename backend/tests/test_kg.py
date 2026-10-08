"""Knowledge-graph build and queries (Section 6)."""

from __future__ import annotations

from app.db.session import Repo
from app.kg import export
from app.kg.queries import get_kg


def test_graph_nodes_and_edges(generated):
    kg = get_kg("northgrid")
    types = {n["type"] for n in kg.nodes.values()}
    for t in ("Goal", "Capability", "Application", "Vendor", "Contract", "API", "Integration", "Repo", "CloudResource", "Dataset",
              "Pipeline", "BIAsset", "AIUseCase", "AIAsset", "Project", "Standard", "Pattern", "ADR", "Policy", "Person", "Team",
              "Regulation"):
        assert t in types, t
    etypes = {e["type"] for e in kg.edges.values()}
    for t in ("REALIZES", "OWNS", "DEPENDS_ON", "EXPOSES", "CONSUMES", "INTEGRATES_WITH", "IMPLEMENTED_IN", "RUNS_ON",
              "LICENSED_UNDER", "SOLD_BY", "PRODUCES", "CONSUMES_DATA", "STORED_IN", "USES_DATA", "IMPLEMENTS", "FUNDS", "TARGETS",
              "CHANGES", "GOVERNED_BY", "VIOLATES", "AFFECTS", "DUPLICATES", "SUPPORTS", "OVERLAPS_WITH"):
        assert t in etypes, t
    # every node / edge has provenance
    assert all(n["source_refs_json"] for n in kg.nodes.values())
    assert all(e["source_refs_json"] for e in kg.edges.values())


def test_confidence_rules(generated):
    kg = get_kg("northgrid")
    apps = kg.by_type("Application")
    multi = [a for a in apps if len(a["props_json"]["discovered_via"] or []) >= 2 and a["status"] == "approved" and not a["props_json"].get("shadow_it")]
    assert all(a["confidence"] >= 0.95 for a in multi)
    inferred = [e for e in kg.edges_of_type("RUNS_ON") if e["props_json"].get("inference")]
    assert inferred and all(0.5 <= e["confidence"] <= 0.85 for e in inferred)


def test_lineage(generated):
    kg = get_kg("meridian")
    usage = next(d for d in Repo("meridian").all("datasets") if d["name"] == "Subscriber Usage Daily")
    down = kg.lineage_downstream(usage["id"])
    assert down["datasets"] and down["ai"]
    raw = next(d for d in Repo("meridian").all("datasets") if d["name"] == "Subscriber Usage Daily (raw)")
    up = kg.lineage_upstream(raw["id"])
    assert usage["id"] in up["datasets"]
    assert up["systems"]


def test_impact(generated):
    kg = get_kg("northgrid")
    oms = next(a for a in Repo("northgrid").all("applications") if a["name"] == "OutageWorks OMS")
    imp = kg.impact(oms["id"], depth=3)
    assert "Capability" in imp and "Application" in imp and "Dataset" in imp
    assert any(c["name"].startswith("Outage") for c in imp["Capability"])


def test_orphans_and_violations(generated):
    kg = get_kg("northgrid")
    o = kg.orphans()
    assert len(o["goals_without_project"]) == 2
    assert len(o["projects_without_goal"]) >= 8
    assert o["cloud_resources_without_app"]
    v = kg.violations()
    stds = {x["standard_id"] for x in v}
    assert {"STD-INT-02", "STD-OT-01", "STD-CLD-01"} <= stds
    assert sum(1 for x in v if x["standard_id"] == "STD-OT-01") == 2


def test_path_and_capability_subgraph(generated):
    kg = get_kg("northgrid")
    cap = next(c for c in Repo("northgrid").all("capabilities") if c["name"] == "Outage Management")
    sub = kg.subgraph_for_capability(cap["id"])
    assert len(sub["capabilities"]) > 1 and len(sub["applications"]) >= 4
    p = kg.path(sub["applications"][0], cap["id"])
    assert p and p[0] == sub["applications"][0]


def test_mermaid_export(generated):
    kg = get_kg("northgrid")
    apps = Repo("northgrid").all("applications")
    assert export.capability_map(kg, "NorthGrid").startswith("mindmap")
    assert "flowchart" in export.c4_context(kg, apps[0]["id"])
    ds = Repo("northgrid").all("datasets")[0]
    assert "flowchart" in export.data_flow(kg, ds["id"])
    cap = Repo("northgrid").all("capabilities")[0]
    assert "flowchart" in export.integration_map(kg, cap["id"])
