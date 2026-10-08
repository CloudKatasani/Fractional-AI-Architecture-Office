"""app.integration_api_architect — duplicate / insecure / ungoverned APIs and canonical designation."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class APIFinding(Finding):
    type: str  # duplicate | insecure | missing_gateway
    api_ids: list[str]
    recommendation: str


def openapi_stub(name: str, resource: str) -> str:
    path = resource.lower().replace(" ", "-")
    return (f"openapi: 3.0.3\ninfo:\n  title: {name}\n  version: 0.1.0\nservers:\n  - url: https://api.example/{path}/v1\n"
            f"security:\n  - oauth2: [{path}.read]\npaths:\n  /{path}/{{id}}:\n    get:\n      summary: Get {resource} by id\n"
            f"      parameters:\n        - in: path\n          name: id\n          required: true\n          schema: {{type: string}}\n"
            f"      responses:\n        '200': {{description: OK}}\ncomponents:\n  securitySchemes:\n    oauth2:\n      type: oauth2\n"
            f"      flows:\n        clientCredentials:\n          tokenUrl: https://idp.example/oauth2/token\n          scopes: {{{path}.read: read}}\n")


class IntegrationAPIArchitect(Agent):
    id = "app.integration_api_architect"
    name = "Integration and API Architect"
    domain = "application"
    description = ("Finds duplicate APIs, APIs with weak authentication on confidential data and confidential APIs "
                   "bypassing the gateway; proposes a canonical API and the consumers to migrate; drafts OpenAPI stubs.")
    inputs = ["apis", "applications", "integrations"]
    outputs = "APIFinding"
    finding_model = APIFinding
    approver_role = "principal_architect"
    default_autonomy = 2
    demo_trigger = "Review APIs"
    action_types = ["designate_canonical_api", "deprecate_api"]
    params_spec = [{"name": "new_api_request", "label": "New API request (optional)", "kind": "text"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        apis = ctx.repo.all("apis")
        apps = ctx.repo.by_id("applications")
        findings, actions = [], []
        groups: dict[str, list[dict]] = {}
        for a in apis:
            if a["duplicate_group"]:
                groups.setdefault(a["duplicate_group"], []).append(a)
        for g, items in sorted(groups.items()):
            canon = sorted(items, key=lambda a: (not a["via_gateway"], a["auth"] not in ("oauth2", "mtls"),
                                                 -len(a["consumers"] or []), a["id"]))[0]
            others = [a for a in items if a["id"] != canon["id"]]
            migrate = sorted({c for o in others for c in o["consumers"]})
            rec = (f"Designate {canon['name']} [{canon['id']}] as canonical for '{canon['resource']}'; migrate "
                   + ", ".join(apps[c]["name"] for c in migrate[:5]) + " and deprecate " + ", ".join(o["name"] for o in others) + ".")
            refs = [ev(a["id"], "apis", f"{a['name']} (owner {apps[a['owner_app_id']]['name']}, {a['style']}, auth {a['auth']}, "
                                        f"{len(a['consumers'])} consumers)") for a in items]
            findings.append(APIFinding(type="duplicate", api_ids=[a["id"] for a in items], recommendation=rec, source_refs=refs,
                                       canonical_api_id=canon["id"], group=g, resource=canon["resource"],
                                       consumers_to_migrate=migrate))
            actions.append(ProposedAction(action_type="designate_canonical_api", target_id=canon["id"], target_type="API",
                                          payload={"group": g, "deprecate": [o["id"] for o in others], "migrate_consumers": migrate},
                                          rationale=rec, source_refs=refs, approver_role="principal_architect", priority=2))
            for o in others:
                actions.append(ProposedAction(action_type="deprecate_api", target_id=o["id"], target_type="API",
                                              payload={"replacement": canon["id"], "consumers": o["consumers"]},
                                              rationale=f"Duplicate of {canon['name']}; migrate {len(o['consumers'])} consumers.",
                                              source_refs=[refs[items.index(o)], refs[items.index(canon)]],
                                              approver_role="principal_architect", priority=3))
        for a in apis:
            if a["auth"] in ("none", "apikey") and a["data_classification"] in ("confidential", "restricted"):
                refs = [ev(a["id"], "apis", f"{a['name']}: auth={a['auth']} on {a['data_classification']} data")]
                findings.append(APIFinding(type="insecure", api_ids=[a["id"]], source_refs=refs,
                                           recommendation=f"Move {a['name']} to OAuth2 client credentials or mTLS (STD-API-03).",
                                           severity="high" if a["auth"] == "none" else "medium"))
            elif a["data_classification"] in ("confidential", "restricted") and not a["via_gateway"] and len(a["consumers"] or []) >= 2 \
                    and a["style"] != "event":
                refs = [ev(a["id"], "apis", f"{a['name']}: {a['data_classification']}, {len(a['consumers'])} consumers, not via gateway")]
                findings.append(APIFinding(type="missing_gateway", api_ids=[a["id"]], source_refs=refs,
                                           recommendation=f"Publish {a['name']} through the API gateway (STD-API-02).", severity="medium"))
        stub = None
        if ctx.params.get("new_api_request"):
            stub = openapi_stub(ctx.params["new_api_request"], ctx.params["new_api_request"].split()[0])
        facts = {"dups": len(groups), "insecure": sum(1 for f in findings if f.type == "insecure"),
                 "gateway": sum(1 for f in findings if f.type == "missing_gateway"),
                 "example": next((f.recommendation for f in findings if f.type == "duplicate"), None)}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.88,
                              artifacts={"openapi_stub": stub} if stub else {})
