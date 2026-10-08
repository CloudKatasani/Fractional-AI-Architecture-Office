"""ea.impact_analyst — what is affected by a vendor exit, regulation, M&A or retirement (graph depth 3)."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ev


class ImpactReport(Finding):
    trigger: str
    affected: dict  # capabilities, applications, datasets, ai_assets, people
    est_cost_usd: float
    hotspots: list[dict]


def _name_to_id(ctx: AgentContext, table: str, name: str, field: str = "name") -> str | None:
    return next((r["id"] for r in ctx.repo.all(table) if r[field] == name), None)


class ImpactAnalyst(Agent):
    id = "ea.impact_analyst"
    name = "Impact Analyst"
    domain = "enterprise"
    description = ("Given a trigger (vendor exit, regulation, M&A, application retirement or any graph node) traverses the "
                   "knowledge graph to depth 3 and lists affected capabilities, applications, datasets, AI and people.")
    inputs = ["kg_nodes", "kg_edges", "applications"]
    outputs = "ImpactReport"
    finding_model = ImpactReport
    approver_role = None
    default_autonomy = 1
    demo_trigger = "Analyse impact"
    params_spec = [{"name": "trigger_id", "label": "Preset trigger", "kind": "select", "source": "impact_triggers"},
                   {"name": "node_id", "label": "...or any node id", "kind": "text"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        kg = ctx.kg
        presets = {t["id"]: t for t in ctx.catalog.get("impact_triggers", [])}
        tid = ctx.params.get("trigger_id")
        node_id = ctx.params.get("node_id")
        if not tid and not node_id:
            tid = next(iter(presets))
        roots: list[str] = []
        growth = None
        if node_id:
            label = f"Change to {kg.node(node_id)['name'] if kg.node(node_id) else node_id}"
            roots = [node_id]
            kind = "node"
        else:
            t = presets[tid]
            label, kind = t["label"], t["type"]
            if kind == "vendor_exit":
                vid = next(n["id"] for n in kg.by_type("Vendor") if n["name"] == t["vendor"])
                roots = [e["from_id"] for e in kg.in_edges(vid, "SOLD_BY")]
            elif kind == "app_retirement":
                roots = [_name_to_id(ctx, "applications", t["app"])]
            else:
                cap_ids = [_name_to_id(ctx, "capabilities", c) for c in t.get("capabilities", [])]
                roots = [c for c in cap_ids if c]
                for c in list(roots):  # capability triggers affect the applications that realise them
                    roots += kg.apps_for_capability(c)
                for tag in t.get("dataset_tags", []):
                    roots += [d["id"] for d in ctx.repo.all("datasets") if tag in (d["tags"] or []) and d["layer"] == "source"]
                for tag in t.get("usecase_tags", []):
                    roots += [u["id"] for u in ctx.repo.all("ai_usecases") if tag in (u["tags"] or [])]
                growth = t.get("growth")
        affected: dict[str, dict] = {}
        for r in roots:
            if not r:
                continue
            affected.setdefault(kg.node(r)["type"], {})[r] = {"id": r, "name": kg.node(r)["name"], "depth": 0}
            for typ, items in kg.impact(r, depth=3).items():
                for it in items:
                    cur = affected.setdefault(typ, {}).get(it["id"])
                    if not cur or it["depth"] < cur["depth"]:
                        affected[typ][it["id"]] = it
        groups = {
            "capabilities": sorted(affected.get("Capability", {}).values(), key=lambda x: (x["depth"], x["name"])),
            "applications": sorted(affected.get("Application", {}).values(), key=lambda x: (x["depth"], x["name"])),
            "datasets": sorted(affected.get("Dataset", {}).values(), key=lambda x: (x["depth"], x["name"])),
            "ai_assets": sorted(list(affected.get("AIAsset", {}).values()) + list(affected.get("AIUseCase", {}).values()),
                                key=lambda x: (x["depth"], x["name"])),
            "people": sorted(list(affected.get("Person", {}).values()) + list(affected.get("Team", {}).values()),
                             key=lambda x: (x["depth"], x["name"])),
            "projects": sorted(affected.get("Project", {}).values(), key=lambda x: (x["depth"], x["name"])),
        }
        apps = ctx.repo.by_id("applications")
        root_apps = [a for a in groups["applications"] if a["depth"] == 0]
        dependents = [a for a in groups["applications"] if a["depth"] >= 1]
        base = sum(apps[a["id"]]["annual_cost_usd"] for a in root_apps if a["id"] in apps)
        # replacement / change cost of the triggering apps + rework per dependent integration (synthetic $40k each)
        mult = {"vendor_exit": 1.5, "app_retirement": 1.2, "regulation": 0.25, "m_and_a": growth or 0.15, "node": 0.5}.get(kind, 0.5)
        est = round(base * mult + 40000 * len(dependents), -3)
        hotspots = []
        for a in groups["applications"][:40]:
            deg = len(kg.in_edges(a["id"], "INTEGRATES_WITH")) + len(kg.out_edges(a["id"], "INTEGRATES_WITH")) + \
                len(kg.in_edges(a["id"], "STORED_IN"))
            hotspots.append({"id": a["id"], "name": a["name"], "dependents": deg})
        hotspots.sort(key=lambda h: (-h["dependents"], h["id"]))
        refs = [ev(r, kg.node(r)["type"].lower(), kg.node(r)["name"]) for r in roots[:4] if r]
        refs += [ev(h["id"], "applications", f"{h['name']}: {h['dependents']} dependents") for h in hotspots[:2]]
        report = ImpactReport(trigger=label, affected=groups, est_cost_usd=est, hotspots=hotspots[:5], source_refs=refs,
                              trigger_id=tid or node_id, root_ids=[r for r in roots if r], kind=kind)
        facts = {"label": label, "counts": {k: len(v) for k, v in groups.items()}, "est": est,
                 "hot": hotspots[0] if hotspots else None, "roots": [r for r in roots if r][:3]}
        return AnalysisResult(findings=[report], facts=facts, confidence=0.75)

    def narrative_key(self, ctx: AgentContext) -> str:
        return ctx.params.get("trigger_id") or ctx.params.get("node_id") or "default"
