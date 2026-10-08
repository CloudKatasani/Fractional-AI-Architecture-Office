"""Datasets, pipelines, BI assets, data policies, AI use cases and AI assets."""

from __future__ import annotations

from data_gen.generators.core import GenContext

RETENTION_DEFAULT = {"meter_data": 2555, "sox": 2555, "lawful_intercept": 365, "mnp": 1095}


def _lake(ctx: GenContext) -> dict:
    return next(a for a in ctx.rows["applications"] if a["category"] == "Data lake")


def _edw(ctx: GenContext) -> dict:
    return next(a for a in ctx.rows["applications"] if a["category"] == "Enterprise data warehouse")


def gen_datasets(ctx: GenContext) -> None:
    home = ctx.tenant["home_region"]
    lake, edw = _lake(ctx), _edw(ctx)
    pii_rows: list[dict] = []
    stage_specs: list[tuple[dict, dict]] = []

    def add_ds(name: str, domain: dict, spec: dict, system: dict, layer: str, pii: bool, cls: str, zone: str) -> dict:
        tags = list(spec.get("tags", []))
        retention = None
        for t in tags:
            if t in RETENTION_DEFAULT:
                retention = RETENTION_DEFAULT[t]
        if retention is None:
            retention = 1825 if pii else ctx.pick([730, 1095, 1825, 2555])
        row = ctx.add("datasets", {
            "id": ctx.next_id("DS", 4), "name": name, "domain": domain["name"],
            "owner_user_id": ctx.owner_for_l1(domain["l1"]), "classification": cls, "system_app_id": system["id"],
            "pii": pii, "retention_days": retention, "quality_score": round(ctx.rng.uniform(0.66, 0.98), 2),
            "has_contract": ctx.rng.random() < 0.2, "environment": "prod", "region": home, "zone": zone,
            "layer": layer, "tags": tags, "base_name": spec["n"],
        }, "data_catalog")
        ctx.datasets_by_name[name] = row
        if pii:
            pii_rows.append(row)
        return row

    for domain in ctx.catalog["data_domains"]:
        system = ctx.app(domain["system"])
        zone = domain.get("zone", system.get("zone", "it"))
        for spec in domain["datasets"]:
            pii = bool(spec.get("pii"))
            cls = spec.get("cls", "internal")
            src = add_ds(spec["n"], domain, spec, system, "source", pii, cls, zone)
            stage_specs.append((src, {"domain": domain, "spec": spec}))

    # Derived lake / warehouse layers
    ctx.lineage_edges = []  # (inputs, output, layer)
    for src, info in stage_specs:
        domain, spec = info["domain"], info["spec"]
        if "lawful_intercept" in spec.get("tags", []):
            continue  # LI data never leaves the LI system
        r = ctx.rng.random()
        if r > 0.7 and not spec.get("consumers"):
            continue
        raw = add_ds(f"{spec['n']} (raw)", domain, spec, lake, "raw", src["pii"], src["classification"], "it")
        ctx.lineage_edges.append(([src["id"]], raw["id"], "raw"))
        if ctx.rng.random() < 0.55 or spec.get("consumers"):
            deid = src["pii"] and ctx.rng.random() < 0.8
            cur = add_ds(f"{spec['n']} (curated)", domain, spec, lake, "curated", src["pii"] and not deid,
                         "internal" if deid else src["classification"], "it")
            ctx.lineage_edges.append(([raw["id"]], cur["id"], "curated"))
            if ctx.rng.random() < 0.33:
                mart = add_ds(f"{spec['n']} Mart", domain, spec, edw, "mart", False, "internal", "it")
                ctx.lineage_edges.append(([cur["id"]], mart["id"], "mart"))

    ds = ctx.rows["datasets"]
    # PII without retention (~20% of PII datasets get no retention or over-policy retention)
    pii_sorted = [d for d in pii_rows]
    chosen = ctx.pick(pii_sorted, max(4, round(len(pii_sorted) * 0.2)))
    for i, d in enumerate(chosen):
        if i % 2 == 0:
            d["retention_days"] = None
            ctx.plant("pii_without_retention", d["id"], name=d["name"])
        else:
            d["retention_days"] = 3650
            ctx.plant("pii_retention_over_policy", d["id"], name=d["name"], days=3650)
    # Datasets without owner
    for d in ctx.pick([d for d in ds if d["layer"] in ("raw", "curated")], 5):
        d["owner_user_id"] = None
        ctx.plant("dataset_without_owner", d["id"], name=d["name"])
    # Low-quality datasets that feed AI
    for name in ctx.catalog.get("low_quality_datasets", []):
        if name in ctx.datasets_by_name:
            ctx.datasets_by_name[name]["quality_score"] = round(ctx.rng.uniform(0.42, 0.58), 2)
    # Non-production copies of restricted / PII data (policy violation)
    restricted = [d for d in ds if d["layer"] == "source" and (d["classification"] == "restricted" or d["pii"])
                  and "lawful_intercept" not in d["tags"]]
    for src in ctx.pick(restricted, 4):
        test = ctx.add("datasets", {
            **{k: v for k, v in src.items() if k not in ("id", "created_at")},
            "id": ctx.next_id("DS", 4), "name": f"{src['base_name']} (test copy)", "environment": "nonprod",
            "system_app_id": lake["id"], "layer": "raw", "has_contract": False,
        }, "data_catalog")
        ctx.datasets_by_name[test["name"]] = test
        ctx.lineage_edges.append(([src["id"]], test["id"], "nonprod"))
    # Telecom residency: vendor copies outside the home region
    for vendor_copy in ctx.catalog.get("residency_copies", []):
        src = ctx.datasets_by_name[vendor_copy["source"]]
        sys_app = ctx.app(vendor_copy["system"])
        row = ctx.add("datasets", {
            **{k: v for k, v in src.items() if k not in ("id", "created_at")},
            "id": ctx.next_id("DS", 4), "name": vendor_copy["name"], "system_app_id": sys_app["id"],
            "region": vendor_copy["region"], "layer": "mart", "has_contract": False,
        }, "data_catalog")
        ctx.datasets_by_name[row["name"]] = row
        ctx.lineage_edges.append(([src["id"]], row["id"], "export"))
        ctx.plant("residency_violation", row["id"], region=vendor_copy["region"], name=row["name"])


def gen_pipelines(ctx: GenContext) -> None:
    tools_by_layer = {"raw": ["airflow", "informatica", "ssis"], "curated": ["dbt", "spark"], "mart": ["informatica", "dbt"],
                      "nonprod": ["ssis", "airflow"], "export": ["airflow"]}
    ds_by_id = {d["id"]: d for d in ctx.rows["datasets"]}
    cross_zone_unapproved = 0
    for inputs, output, layer in ctx.lineage_edges:
        out = ds_by_id[output]
        src = ds_by_id[inputs[0]]
        tool = ctx.pick(tools_by_layer[layer])
        cross = src["zone"] != out["zone"]
        approved_cross = True
        if cross and src["zone"] == "ot":
            # most OT exports go through the DMZ historian replica; two are planted direct extracts
            approved_cross = cross_zone_unapproved >= 2
            if not approved_cross:
                cross_zone_unapproved += 1
                tool = "informatica"
        variants = ["load"] if layer != "raw" else (["cdc", "backfill"] if ctx.rng.random() < 0.7 else ["ingest"])
        for v in variants:
            row = ctx.add("pipelines", {
                "id": ctx.next_id("PL", 4), "name": f"{out['base_name'].lower().replace(' ', '_')}_{layer}_{v}",
                "tool": tool, "inputs": list(inputs), "outputs": [output], "owner": ctx.users_by_id(out["owner_user_id"] or ctx.user_id("pa"))["name"],
                "schedule": ctx.pick(["hourly", "daily", "daily", "weekly", "streaming"]),
                "target_env": out["environment"], "approved_cross_zone": approved_cross if cross else True,
            }, "orchestrator")
            if out["environment"] == "nonprod":
                ctx.plant("restricted_data_to_nonprod", row["id"], dataset=out["name"])
            if cross and not approved_cross:
                ctx.plant("bcsi_cross_zone_unapproved", row["id"], dataset=src["name"])
    # Join pipelines: curated datasets enriched with another domain's curated data
    curated = [d for d in ctx.rows["datasets"] if d["layer"] == "curated"]
    pool = curated + [d for d in ctx.rows["datasets"] if d["layer"] == "mart"]
    target_total = ctx.rng.randint(165, 195)
    guard = 0
    while len(ctx.rows["pipelines"]) < target_total and guard < 1000:
        guard += 1
        d = ctx.pick(pool)
        same = [x for x in pool if x["domain"] == d["domain"] and x["id"] != d["id"] and x["layer"] == "curated"]
        if not same:
            continue
        other = ctx.pick(same)
        ctx.add("pipelines", {
            "id": ctx.next_id("PL", 4), "name": f"{d['base_name'].lower().replace(' ', '_')}_enrich",
            "tool": ctx.pick(["dbt", "spark"]), "inputs": [d["id"], other["id"]], "outputs": [d["id"]],
            "owner": ctx.users_by_key["own_data"]["name"], "schedule": "daily", "target_env": "prod", "approved_cross_zone": True,
        }, "orchestrator")
    # CPNI fed to marketing without consent (telecom)
    for spec in ctx.catalog.get("cpni_marketing_feeds", []):
        src = ctx.datasets_by_name[spec["dataset"]]
        tgt = ctx.datasets_by_name[spec["target"]]
        row = ctx.add("pipelines", {
            "id": ctx.next_id("PL", 4), "name": spec["name"], "tool": "airflow", "inputs": [src["id"]], "outputs": [tgt["id"]],
            "owner": ctx.users_by_key["own_digital"]["name"], "schedule": "daily", "target_env": "prod", "approved_cross_zone": True,
        }, "orchestrator")
        ctx.plant("cpni_to_marketing_without_consent", row["id"], dataset=src["name"])


def gen_bi(ctx: GenContext) -> None:
    bi_tools = [a for a in ctx.rows["applications"] if a["category"] in ("BI", "Hosted analytics")]
    marts = [d for d in ctx.rows["datasets"] if d["layer"] in ("curated", "mart") and d["environment"] == "prod"]
    depts = sorted({d["domain"] for d in ctx.rows["datasets"]})
    target = ctx.rng.randint(62, 80)
    for i in range(target):
        tool = bi_tools[i % len(bi_tools)]
        dsets = ctx.pick(marts, ctx.rng.randint(1, 3))
        low_usage = tool["_spec"].get("ren", {}).get("utilization", 1) < 0.3
        ctx.add("bi_assets", {
            "id": ctx.next_id("BI", 3), "name": f"{dsets[0]['base_name']} {ctx.pick(['Dashboard', 'Report', 'Scorecard', 'Explorer'])}",
            "tool": tool["name"], "dataset_ids": [d["id"] for d in dsets], "consumers": ctx.pick(depts),
            "last_viewed_days": ctx.rng.randint(60, 300) if low_usage else ctx.rng.randint(0, 45),
        }, "bi_catalog")
    # Two dashboards read PII source datasets directly
    pii_sources = [d for d in ctx.rows["datasets"] if d["layer"] == "source" and d["pii"]]
    for d in ctx.pick(pii_sources, 2):
        row = ctx.add("bi_assets", {
            "id": ctx.next_id("BI", 3), "name": f"{d['base_name']} Detail (direct)", "tool": bi_tools[-1]["name"],
            "dataset_ids": [d["id"]], "consumers": d["domain"], "last_viewed_days": ctx.rng.randint(0, 20),
        }, "bi_catalog")
        ctx.plant("bi_reads_pii_directly", row["id"], dataset=d["name"])


def gen_policies(ctx: GenContext) -> None:
    for p in ctx.common["policies"] + ctx.catalog.get("extra_policies", []):
        ctx.add("data_policies", {
            "id": p["id"], "title": p["title"], "rule": p["rule"], "regulation": p["regulation"],
            "severity": p["severity"], "check": p["check"],
        }, "governance_policies")


def _ds_ids(ctx: GenContext, names: list[str]) -> list[str]:
    ids = []
    for n in names:
        d = ctx.datasets_by_name.get(f"{n} (curated)") or ctx.datasets_by_name.get(n)
        if d is None:
            raise KeyError(f"[{ctx.tenant_id}] unknown dataset '{n}'")
        ids.append(d["id"])
    return ids


def gen_ai(ctx: GenContext) -> None:
    uc_ids: dict[str, str] = {}
    for u in ctx.catalog["ai_usecases"]:
        row = ctx.add("ai_usecases", {
            "id": ctx.next_id("AIU", 3), "title": u["t"], "sponsor_dept": u["dept"],
            "description": u.get("desc") or f"{u['t']} for {u['dept']}.", "status": u["status"],
            "dataset_ids": _ds_ids(ctx, u.get("ds", [])), "value_estimate_usd": float(u["value"]),
            "feasibility_notes": f"Pattern {u['pattern']}; {len(u.get('ds', []))} candidate datasets identified.",
            "uses_personal_data": bool(u.get("personal")), "affects_individuals": bool(u.get("individuals")),
            "safety_relevant": bool(u.get("safety")), "automated_decision": bool(u.get("automated")),
            "pattern": u["pattern"], "tags": u.get("tags", []), "sponsor_priority": u.get("prio", 3),
            "owner_user_id": ctx.user_id("own_data"),
        }, "ai_intake")
        uc_ids[u["t"]] = row["id"]
    for a in ctx.catalog["ai_assets"]:
        row = ctx.add("ai_assets", {
            "id": ctx.next_id("AIA", 3), "name": a["n"], "type": a["type"], "owner": a["dept"],
            "vendor": a.get("vendor", "in-house"), "data_used": _ds_ids(ctx, a.get("ds", [])),
            "eval_status": a.get("eval", "none"), "monthly_cost_usd": float(a.get("monthly", 0)),
            "registered": bool(a.get("registered")), "usecase_id": uc_ids.get(a.get("uc")), "department": a["dept"],
            "paid_via": a.get("paid_via", "ap"), "lifecycle": a.get("lifecycle", "pilot"),
        }, "model_registry" if a.get("registered") else "expense_and_sso_discovery")
        if not row["registered"]:
            ctx.plant("unregistered_ai_asset", row["id"], name=row["name"], paid_via=row["paid_via"])
        if row["lifecycle"] == "production" and row["eval_status"] == "none":
            ctx.plant("production_model_without_eval", row["id"], name=row["name"])
