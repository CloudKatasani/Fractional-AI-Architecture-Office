"""dai.data_product_designer — propose governed data products with draft data contracts."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class DataProductProposal(Finding):
    domain: str
    dataset_ids: list[str]
    owner_user_id: str | None
    contract_yaml: str
    consumers: list[str]


class DataProductDesigner(Agent):
    id = "dai.data_product_designer"
    name = "Data Product Designer"
    domain = "data_ai"
    description = ("Groups datasets by domain and proposes data products (owner, schema summary, SLAs, quality rules) "
                   "for domains with 3+ datasets and 2+ consuming teams, with a draft data contract.")
    inputs = ["datasets", "pipelines", "bi_assets", "ai_assets"]
    outputs = "DataProductProposal"
    finding_model = DataProductProposal
    approver_role = "data_governance_lead"
    default_autonomy = 2
    demo_trigger = "Propose data products"
    action_types = ["approve_data_contract"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        ds = ctx.repo.all("datasets")
        by_domain: dict[str, list[dict]] = {}
        for d in ds:
            if d["environment"] == "prod":
                by_domain.setdefault(d["domain"], []).append(d)
        consumers: dict[str, set[str]] = {}
        ids_domain = {d["id"]: d["domain"] for d in ds}
        for b in ctx.repo.all("bi_assets"):
            for i in b["dataset_ids"]:
                consumers.setdefault(ids_domain[i], set()).add(f"BI: {b['consumers']}")
        for a in ctx.repo.all("ai_assets"):
            for i in a["data_used"]:
                consumers.setdefault(ids_domain[i], set()).add(f"AI: {a['department']}")
        findings, actions = [], []
        eligible = [(dom, items) for dom, items in by_domain.items() if len(items) >= 3 and len(consumers.get(dom, set())) >= 2]
        eligible.sort(key=lambda kv: (-len(consumers.get(kv[0], set())), kv[0]))
        for dom, items in eligible[:6]:
            teams = sorted(consumers.get(dom, set()))
            curated = [d for d in items if d["layer"] in ("curated", "mart")]
            if len(curated) < 3:
                curated = items
            owner = max((d["owner_user_id"] for d in items if d["owner_user_id"]), key=lambda u: sum(1 for d in items if d["owner_user_id"] == u), default=None)
            pii = any(d["pii"] for d in curated)
            sla = "hourly" if dom in ("Metering", "Usage", "Network", "Grid Operations") else "daily by 06:00"
            yaml_lines = [f"dataProduct: {dom.lower().replace(' ', '-').replace('&', 'and')}", f"domain: {dom}",
                          f"owner: {ctx.user_name(owner)}", "outputPorts:"]
            for d in curated[:5]:
                yaml_lines += [f"  - name: {d['name']}", f"    datasetId: {d['id']}", f"    classification: {d['classification']}",
                               f"    pii: {str(d['pii']).lower()}", f"    retentionDays: {d['retention_days'] or 'TBD'}"]
            yaml_lines += ["sla:", f"  freshness: {sla}", "  availability: 99.5%", "quality:",
                           "  - rule: not_null(primary_key)", "  - rule: freshness_within_sla",
                           f"  - rule: quality_score >= 0.8  # current min {min(d['quality_score'] for d in curated):.2f}",
                           "access:", f"  masking: {'required for PII fields outside prod' if pii else 'none'}",
                           "consumers:"] + [f"  - {t}" for t in teams[:8]]
            contract = "\n".join(yaml_lines)
            refs = [ev(d["id"], "datasets", f"{d['name']} ({d['layer']}, quality {d['quality_score']})") for d in curated[:4]]
            findings.append(DataProductProposal(domain=dom, dataset_ids=[d["id"] for d in curated], owner_user_id=owner,
                                                contract_yaml=contract, consumers=teams, source_refs=refs,
                                                name=f"{dom} data product", pii=pii))
            actions.append(ProposedAction(action_type="approve_data_contract", target_id=f"DP-{dom.upper().replace(' ', '_').replace('&', 'AND')}",
                                          target_type="DataProduct",
                                          payload={"domain": dom, "dataset_ids": [d["id"] for d in curated], "owner_user_id": owner,
                                                   "contract_yaml": contract},
                                          rationale=f"{dom} has {len(items)} datasets used by {len(teams)} teams; a governed product "
                                                    "with a contract removes point-to-point copies.",
                                          source_refs=refs, approver_role="data_governance_lead", priority=3))
        facts = {"count": len(findings), "domains": [f.domain for f in findings][:6]}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.75)
