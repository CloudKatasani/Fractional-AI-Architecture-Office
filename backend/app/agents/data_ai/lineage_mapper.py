"""dai.lineage_mapper — upstream/downstream lineage and AI-consumed low-quality data."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ev
from app.kg.export import data_flow


class LineageReport(Finding):
    root_id: str
    upstream: list[dict]
    downstream: list[dict]
    quality_flags: list[dict]


def default_dataset(ctx: AgentContext) -> str:
    names = {"northgrid": "Customer Usage Daily", "meridian": "Subscriber Usage Daily"}
    ds = [d for d in ctx.repo.all("datasets") if d["name"] == names.get(ctx.tenant_id)]
    return ds[0]["id"] if ds else ctx.repo.all("datasets")[0]["id"]


class LineageMapper(Agent):
    id = "dai.lineage_mapper"
    name = "Lineage Mapper"
    domain = "data_ai"
    description = ("Builds lineage from pipelines, BI assets and AI assets; answers upstream/downstream questions and "
                   "flags datasets feeding AI with a quality score below 0.6.")
    inputs = ["datasets", "pipelines", "bi_assets", "ai_assets"]
    outputs = "LineageReport"
    finding_model = LineageReport
    approver_role = None
    default_autonomy = 1
    demo_trigger = "Trace lineage"
    params_spec = [{"name": "dataset_id", "label": "Dataset", "kind": "select", "source": "datasets"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        kg = ctx.kg
        root = ctx.params.get("dataset_id") or default_dataset(ctx)
        ds = ctx.repo.by_id("datasets")
        up = kg.lineage_upstream(root)
        down = kg.lineage_downstream(root)

        def item(nid: str) -> dict:
            n = kg.node(nid)
            return {"id": nid, "type": n["type"], "name": n["name"]}

        upstream = [item(i) for i in up["datasets"] + up["pipelines"] + up["systems"]]
        downstream = [item(i) for i in down["datasets"] + down["pipelines"] + down["bi_assets"] + down["ai"]]
        flags = []
        scope = {root} | set(up["datasets"]) | set(down["datasets"])
        for a in ctx.repo.all("ai_assets"):
            for d in a["data_used"]:
                if d in scope and d in ds and ds[d]["quality_score"] < 0.6:
                    flags.append({"dataset_id": d, "dataset": ds[d]["name"], "quality_score": ds[d]["quality_score"],
                                  "ai_asset_id": a["id"], "ai_asset": a["name"]})
        refs = [ev(root, "datasets", f"{ds[root]['name']} ({ds[root]['classification']}, owner {ctx.user_name(ds[root]['owner_user_id'])})")]
        refs += [ev(p, "pipelines", kg.node(p)["name"]) for p in up["pipelines"][:2]]
        refs += [ev(f["dataset_id"], "datasets", f"quality {f['quality_score']} used by {f['ai_asset']}") for f in flags[:3]]
        refs += [ev(f["ai_asset_id"], "ai_assets", f["ai_asset"]) for f in flags[:2]]
        report = LineageReport(root_id=root, upstream=upstream, downstream=downstream, quality_flags=flags, source_refs=refs,
                               root_name=ds[root]["name"])
        facts = {"root": ds[root]["name"], "root_id": root, "up": len(upstream), "down": len(downstream),
                 "ai": [item(i)["name"] for i in down["ai"]], "bi": len(down["bi_assets"]),
                 "systems": [kg.node(s)["name"] for s in up["systems"]], "flags": flags[:4], "n_flags": len(flags)}
        return AnalysisResult(findings=[report], facts=facts, confidence=0.92,
                              artifacts={"diagram_mermaid": data_flow(kg, root)})

    def narrative_key(self, ctx: AgentContext) -> str:
        return ctx.params.get("dataset_id") or "default"
