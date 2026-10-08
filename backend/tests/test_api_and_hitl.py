"""API, human-in-the-loop flow (Section 8) and tenant isolation (P5)."""

from __future__ import annotations

H = {"X-Tenant-Id": "northgrid"}
HM = {"X-Tenant-Id": "meridian"}


def users(client, headers=H):  # noqa: ANN001, ANN201
    return {u["role"]: u for u in client.get("/api/v1/users", headers=headers).json()}


def test_tenant_required(client):
    assert client.get("/api/v1/users").status_code == 400
    assert client.get("/api/v1/users", headers={"X-Tenant-Id": "nope"}).status_code == 404


def test_tenant_isolation(client):
    a = client.get("/api/v1/portfolio/applications", headers=H).json()["items"]
    b = client.get("/api/v1/portfolio/applications", headers=HM).json()["items"]
    assert {x["name"] for x in a}.isdisjoint({"Coastline Billing (Legacy)"})
    assert any(x["name"] == "Coastline Billing (Legacy)" for x in b)
    assert len(a) != len(b)


def test_get_endpoints(client):
    for p in ["/tenants", "/metrics/dashboard", "/kg/nodes?type=Application", "/kg/graph", "/kg/impact?node_id=APP-0021",
              "/kg/lineage?dataset_id=DS-0001", "/kg/diagram?kind=capability_map", "/portfolio/applications", "/portfolio/overlaps",
              "/portfolio/lifecycle", "/portfolio/savings", "/portfolio/discovery", "/ai/usecases", "/ai/assets", "/ai/risk-summary",
              "/app/designs", "/app/adrs", "/app/drift", "/app/debt", "/app/apis", "/ea/capabilities", "/ea/goals",
              "/ea/investment-alignment", "/ea/roadmaps", "/data/datasets", "/data/policy-findings", "/data/products", "/agents",
              "/runs", "/approvals", "/audit", "/raw", "/raw/sso", "/records/APP-0001", "/copilot/suggestions"]:
        r = client.get("/api/v1" + p, headers=H)
        assert r.status_code == 200, (p, r.text[:200])


def test_l1_observe_then_promote_and_owner_decides(client):
    u = users(client)
    out = client.post("/api/v1/agents/run", headers=H, json={"agent_id": "pf.app_discovery", "user_id": u["principal_architect"]["id"]}).json()
    assert out["mode"] == "observe" and out["approvals_created"] == []
    prom = client.post(f"/api/v1/runs/{out['run_id']}/propose", headers=H,
                       json={"user_id": u["principal_architect"]["id"], "action_types": ["confirm_app"]}).json()
    assert len(prom["approvals_created"]) >= 18
    owner = u["app_owner"]
    inbox = client.get("/api/v1/approvals", headers=H, params={"status": "pending", "role": "app_owner", "user_id": owner["id"]}).json()["items"]
    cand = next(a for a in inbox if a["action_type"] == "confirm_app" and a["payload_json"].get("new"))
    r = client.post(f"/api/v1/approvals/{cand['id']}/decide", headers=H, json={"decision": "approve", "user_id": owner["id"]}).json()
    assert r["status"] == "approved"
    node = client.get(f"/api/v1/kg/nodes/{cand['target_id']}", headers=H).json()
    assert node["status"] == "approved" and node["props_json"]["owner_confirmed"]
    audit = client.get("/api/v1/audit", headers=H, params={"subject": cand["target_id"]}).json()["items"]
    assert {"approval_decided", "graph_updated"} <= {e["event_type"] for e in audit}


def test_role_enforcement_and_double_decide(client):
    u = users(client)
    pend = client.get("/api/v1/approvals", headers=H, params={"status": "pending"}).json()["items"]
    tier = next(a for a in pend if a["action_type"] == "set_risk_tier")
    r = client.post(f"/api/v1/approvals/{tier['id']}/decide", headers=H, json={"decision": "approve", "user_id": u["principal_architect"]["id"]})
    assert r.status_code == 400  # AI risk sign-off is reserved for the risk officer
    r = client.post(f"/api/v1/approvals/{tier['id']}/decide", headers=H, json={"decision": "approve", "user_id": u["risk_officer"]["id"]})
    assert r.status_code == 200
    r = client.post(f"/api/v1/approvals/{tier['id']}/decide", headers=H, json={"decision": "approve", "user_id": u["risk_officer"]["id"]})
    assert r.status_code == 400
    risk = client.get("/api/v1/ai/risk-summary", headers=H).json()
    assert sum(v["approved"] for v in risk["tiers"].values()) >= 1


def test_l3_side_effect_ticket(client):
    u = users(client)
    pend = client.get("/api/v1/approvals", headers=H, params={"status": "pending"}).json()["items"]
    t = next(a for a in pend if a["action_type"] == "create_remediation_ticket")
    r = client.post(f"/api/v1/approvals/{t['id']}/decide", headers=H, json={"decision": "approve", "user_id": u["security_architect"]["id"]}).json()
    assert r["side_effects_json"]["ticket"].startswith("SEC-")
    assert any(x["approval_id"] == t["id"] for x in client.get("/api/v1/tickets", headers=H).json())


def test_edit_and_approve_and_savings(client):
    u = users(client)
    before = client.get("/api/v1/metrics/dashboard", headers=H).json()["savings"]["approved"]
    pend = client.get("/api/v1/approvals", headers=H, params={"status": "pending", "role": "cio"}).json()["items"]
    bc = next(a for a in pend if a["action_type"] == "approve_business_case")
    edited = {**bc["payload_json"], "annual_savings_usd": bc["payload_json"]["annual_savings_usd"] - 1000}
    r = client.post(f"/api/v1/approvals/{bc['id']}/decide", headers=H,
                    json={"decision": "edit", "user_id": u["cio"]["id"], "edited_payload": edited, "note": "conservative"}).json()
    assert r["status"] == "edited"
    after = client.get("/api/v1/metrics/dashboard", headers=H).json()["savings"]["approved"]
    assert after > before


def test_autonomy_settings(client):
    u = users(client)
    r = client.patch("/api/v1/agents/pf.overlap_finder/settings", headers=H, json={"autonomy_level": 1, "user_id": u["cio"]["id"]})
    assert r.status_code == 403
    r = client.patch("/api/v1/agents/pf.overlap_finder/settings", headers=H, json={"autonomy_level": 4, "user_id": u["principal_architect"]["id"]})
    assert r.status_code == 400
    r = client.patch("/api/v1/agents/pf.overlap_finder/settings", headers=H, json={"autonomy_level": 1, "user_id": u["principal_architect"]["id"]})
    assert r.json()["autonomy_level"] == 1
    out = client.post("/api/v1/agents/run", headers=H, json={"agent_id": "pf.overlap_finder"}).json()
    assert out["mode"] == "observe" and not out["approvals_created"]
    client.patch("/api/v1/agents/pf.overlap_finder/settings", headers=H, json={"autonomy_level": 2, "user_id": u["principal_architect"]["id"]})


def test_bulk_only_low_risk(client):
    u = users(client)
    pend = client.get("/api/v1/approvals", headers=H, params={"status": "pending"}).json()["items"]
    risky = next(a for a in pend if a["action_type"] == "set_disposition")
    r = client.post("/api/v1/approvals/bulk", headers=H, json={"ids": [risky["id"]], "user_id": u["principal_architect"]["id"]})
    assert r.status_code == 400


def test_copilot_answers_cite(client):
    for q in client.get("/api/v1/copilot/suggestions", headers=H).json():
        a = client.post("/api/v1/copilot/ask", headers=H, json={"question": q}).json()
        assert a["citations"], q
    a = client.post("/api/v1/copilot/ask", headers=H, json={"question": "tell me a joke"}).json()
    assert "Try:" in a["answer"]


def test_briefing_evidence_orchestrate(client):
    b = client.post("/api/v1/briefing/generate", headers=H, json={}).json()
    assert "Executive briefing" in b["markdown"] and b["findings"]
    e = client.post("/api/v1/evidence/pack", headers=H, json={"regulation_or_policy_id": "NERC CIP"}).json()
    assert e["json"]["controls"]
    o = client.post("/api/v1/orchestrate", headers=H, json={"request_text": "show me lineage and AI risk"}).json()
    assert "dai.lineage_mapper" in o["routed_to"] and "dai.ai_risk_classifier" in o["routed_to"]


def test_audit_export(client):
    r = client.get("/api/v1/audit/export", headers=H, params={"format": "csv"})
    assert r.status_code == 200 and r.text.startswith("id,ts")
    r = client.get("/api/v1/audit/export", headers=H, params={"format": "json"})
    assert r.json()
