"""Users, capabilities, applications, contracts, invoices, SSO usage, cloud resources and CMDB."""

from __future__ import annotations

from data_gen.generators.core import GenContext, name_variants, slug, vendor_variants

OLD_STACKS = [
    ("Java 7 / Struts 1.3", ["Java 7", "Struts 1.3", "Oracle 11g"]),
    (".NET Framework 3.5 / WinForms", [".NET Framework 3.5", "SQL Server 2008"]),
    ("AngularJS 1.5 / Java 8", ["AngularJS 1.5", "Java 8"]),
    ("Python 2.7 / Django 1.8", ["Python 2.7", "Django 1.8"]),
]
NEW_STACKS = [
    ("Java 17 / Spring Boot 3", ["Java 17", "Spring Boot 3", "PostgreSQL 15"]),
    ("Python 3.11 / FastAPI", ["Python 3.11", "FastAPI", "PostgreSQL 15"]),
    ("Node.js 20 / Express 4", ["Node.js 20", "React 18"]),
    (".NET 8 / ASP.NET Core", [".NET 8", "SQL Server 2022"]),
    ("Java 11 / Spring Boot 2.7", ["Java 11", "Spring Boot 2.7", "Oracle 19c"]),
    (".NET Framework 4.8 / MVC", [".NET Framework 4.8", "SQL Server 2016"]),
]
SMALL_VENDORS = [
    "Brightline Software", "Cobalt Apps", "Fieldnote Systems", "Gridwise Labs", "Harbor Software", "Insignia Tools",
    "Juniper Bay Software", "Kinetic Forms", "Lattice Apps", "Meridian-agnostic Tools", "Northstar Solutions",
    "Orbit Data", "Pinecrest Software", "Quarry Systems", "Redwood Apps", "Summit Analytics", "Tidewater Software",
    "Upland Utilities Software", "Vantage Point Apps", "Willow Systems",
]


def gen_tenant_and_users(ctx: GenContext) -> None:
    t = ctx.tenant
    ctx.rows["tenants"] = [{
        "id": t["id"], "name": t["name"], "industry": t["industry"], "employees": t["employees"],
        "it_spend_usd": t["it_spend_usd"], "notes": t["notes"], "boundary_label": t["boundary_label"],
        "home_region": t["home_region"],
    }]
    for u in ctx.catalog["users"]:
        first, last = u["name"].split(" ", 1)
        row = ctx.add("users", {
            "id": ctx.next_id("USR", 3), "name": u["name"], "role": u["role"], "title": u["title"],
            "email": f"{first.lower()}.{last.lower().replace(' ', '')}@{t['email_domain']}",
        }, "hris")
        ctx.users_by_key[u["key"]] = row


def gen_capabilities(ctx: GenContext) -> None:
    def add_cap(name: str, level: int, parent: dict | None, importance: int, maturity: int, keywords: list[str]) -> dict:
        l1_name = parent and ctx.l1_of(parent)["name"] or name
        row = ctx.add("capabilities", {
            "id": ctx.next_id("CAP", 3), "name": name, "level": level, "parent_id": parent["id"] if parent else None,
            "strategic_importance": importance, "maturity": maturity, "owner_user_id": ctx.owner_for_l1(l1_name),
            "keywords": sorted(set(keywords + [w.lower() for w in name.replace("&", " ").split() if len(w) > 2])),
            "description": f"{name} capability" + (f" within {l1_name}" if parent else ""),
        }, "ea_repository")
        ctx.caps_by_name[name] = row
        return row

    for l1 in ctx.catalog["capabilities"]:
        c1 = add_cap(l1["name"], 1, None, l1["importance"], l1["maturity"], l1.get("keywords", []))
        for l2 in l1.get("children", []):
            imp2 = l2.get("importance", l1["importance"])
            mat2 = l2.get("maturity", l1["maturity"])
            c2 = add_cap(l2["name"], 2, c1, imp2, mat2, [])
            for l3 in l2.get("children", []):
                add_cap(l3, 3, c2, imp2, max(1, mat2 - (1 if ctx.rng.random() < 0.4 else 0)), [])


def _zone(ctx: GenContext, spec: dict, l1_name: str) -> str:
    if spec.get("z"):
        return spec["z"]
    zone_map = ctx.catalog.get("zone_by_l1")
    if zone_map:
        return zone_map.get(l1_name, "corp")
    return "it"


def _add_app(ctx: GenContext, spec: dict, filler: bool = False) -> dict:
    cap = ctx.cap(spec["cap"])
    caps = [cap] + [ctx.cap(n) for n in spec.get("caps", [])]
    l1 = ctx.l1_of(cap)
    inhouse = bool(spec.get("inhouse"))
    st = spec.get("st") or []
    eos = spec.get("eos")
    vendor = "In-house" if inhouse else spec["v"]
    row = ctx.add("applications", {
        "id": ctx.next_id("APP"), "name": spec["n"], "vendor": vendor, "category": spec["cat"],
        "hosting": spec.get("h", "saas"), "criticality": spec.get("c", 3), "owner_user_id": ctx.owner_for_l1(l1["name"]),
        "capability_ids": [c["id"] for c in caps], "lifecycle_status": "active", "in_cmdb": True, "discovered_via": [],
        "tech_stack": st, "annual_cost_usd": 0.0, "user_count_90d": spec.get("u", 50), "last_login_days": 0,
        "version": spec.get("ver") or f"{ctx.rng.randint(3, 12)}.{ctx.rng.randint(0, 9)}",
        "vendor_eos_date": ctx.days_ahead(eos) if eos else None, "contract_renewal_date": None,
        "data_classification": spec.get("cls", "internal"), "ot_system": spec.get("z") == "ot",
        "regulatory_scope": spec.get("reg", []), "features": spec.get("f") or [slug(spec["n"] if filler else spec["cat"]).replace("-", "_")],
        "zone": _zone(ctx, spec, l1["name"]), "cluster": spec.get("cl"), "description": spec.get("desc") or f"{spec['cat']} supporting {cap['name']}.",
    }, "ea_repository")
    row["_spec"] = {**spec, "inhouse": inhouse, "filler": filler}
    if eos:
        row["lifecycle_status"] = "sunset"
        ctx.plant("vendor_eos_within_9_months" if eos <= 270 else "vendor_eos_within_12_months", row["id"], days=eos, name=row["name"])
    elif not inhouse and ctx.rng.random() < 0.5:
        row["vendor_eos_date"] = ctx.days_ahead(ctx.rng.randint(500, 2200))
    ctx.apps_by_name[row["name"]] = row
    return row


def gen_applications(ctx: GenContext) -> None:
    for spec in ctx.catalog["applications"]:
        _add_app(ctx, spec)

    # Long tail: combine capability nouns with suffixes until the target volume is reached.
    filler = ctx.catalog["filler"]
    target = filler["target_total"]
    combos: list[tuple[str, str]] = []
    for cap_name, nouns in filler["nouns"].items():
        for noun in nouns:
            for suffix in filler["suffixes"]:
                combos.append((cap_name, f"{noun} {suffix}"))
    ctx.rng.shuffle(combos)
    used_nouns: dict[str, int] = {}
    ordered = combos * 3  # later passes allow a noun to appear with additional suffixes
    for idx, (cap_name, name) in enumerate(ordered):
        if len(ctx.rows["applications"]) >= target:
            break
        noun = " ".join(name.split()[:-1]) if not name.endswith("Reporting Tool") else name[: -len(" Reporting Tool")]
        limit = idx // len(combos) + 1
        if used_nouns.get(noun, 0) >= limit or name in ctx.apps_by_name:
            continue
        used_nouns[noun] = used_nouns.get(noun, 0) + 1
        inhouse = ctx.rng.random() < 0.5
        hosting = ctx.rng.choices(["saas", "on_prem", "iaas", "paas"], [0.45, 0.35, 0.1, 0.1])[0]
        if inhouse and hosting == "saas":
            hosting = "on_prem"
        old = ctx.rng.random() < 0.35
        fw, stack = ctx.pick(OLD_STACKS if old else NEW_STACKS)
        spec = {
            "n": name, "cap": cap_name, "cat": f"Departmental {name.split()[-1].lower()}", "h": hosting,
            "c": ctx.rng.choice([3, 3, 4, 4, 4]), "cost": ctx.rng.randrange(15000, 180000, 500),
            "u": ctx.rng.randint(4, 380), "inhouse": inhouse, "v": None if inhouse else ctx.pick(SMALL_VENDORS),
            "st": stack if (inhouse or hosting != "saas") else ["SaaS"], "fw": fw if inhouse else None,
            "cls": ctx.rng.choice(["internal", "internal", "confidential"]),
        }
        _add_app(ctx, spec, filler=True)

    apps = ctx.rows["applications"]
    fillers = [a for a in apps if a["_spec"]["filler"]]
    # Zombie apps: cost > 0 and nobody logged in for 90 days.
    for a in ctx.pick(fillers, 5):
        a["user_count_90d"] = 0
        a["last_login_days"] = ctx.rng.randint(120, 420)
        ctx.plant("zombie_app_no_users", a["id"], name=a["name"])
    for a in apps:
        if a["user_count_90d"] and a["last_login_days"] == 0:
            a["last_login_days"] = ctx.rng.randint(0, 6)

    # ~12% of applications are not in the CMDB (mostly SaaS long tail, some named SaaS).
    saas = [a for a in apps if a["hosting"] == "saas" and not a["ot_system"]]
    not_in_cmdb = ctx.pick(saas, round(len(apps) * 0.12))
    for a in not_in_cmdb:
        a["in_cmdb"] = False
        ctx.plant("app_not_in_cmdb", a["id"], name=a["name"])


def gen_contracts(ctx: GenContext) -> None:
    apps = ctx.rows["applications"]
    for a in apps:
        spec = a["_spec"]
        if spec["inhouse"]:
            continue
        ren = spec.get("ren") or {}
        seats = None
        utilization = ren.get("utilization") or round(ctx.rng.uniform(0.55, 0.97), 2)
        if a["user_count_90d"] and a["user_count_90d"] < 10000:
            seats = max(5, round(a["user_count_90d"] / utilization)) if a["user_count_90d"] else ctx.rng.randint(20, 200)
        elif a["user_count_90d"] == 0:
            seats = ctx.rng.randint(25, 150)
        renewal_days = ren.get("renewal_days") or ctx.rng.randint(95, 720)
        auto = ren.get("auto_renew", ctx.rng.random() < 0.4)
        value = float(spec["cost"])
        multiple = ren.get("market_multiple")
        row = ctx.add("contracts", {
            "id": ctx.next_id("CON", 3), "vendor": a["vendor"], "app_ids": [a["id"]], "annual_value_usd": value,
            "licensed_seats": seats, "renewal_date": ctx.days_ahead(renewal_days), "auto_renew": auto,
            "term_months": ctx.rng.choice([12, 24, 36]),
            "market_benchmark_usd": round(value / multiple if multiple else value * ctx.rng.uniform(0.9, 1.1), -2),
        }, "contract_management")
        a["contract_renewal_date"] = row["renewal_date"]
        if ren:
            ctx.plant("contract_trap", row["id"], app=a["name"], renewal_days=renewal_days, utilization=utilization,
                      auto_renew=auto, market_multiple=multiple)
        # Separate support & maintenance contract for big on-prem vendor platforms
        if a["hosting"] == "on_prem" and a["criticality"] <= 2 and spec["cost"] >= 400000:
            ctx.add("contracts", {
                "id": ctx.next_id("CON", 3), "vendor": a["vendor"], "app_ids": [a["id"]],
                "annual_value_usd": round(value * 0.18, -2), "licensed_seats": None,
                "renewal_date": ctx.days_ahead(ctx.rng.randint(120, 700)), "auto_renew": True, "term_months": 12,
                "market_benchmark_usd": round(value * 0.18, -2),
            }, "contract_management")
    # A handful of long-tail SaaS with poor (but not trap-level) utilisation
    candidates = [c for c in ctx.rows["contracts"] if c["licensed_seats"] and c["app_ids"] and c["auto_renew"] is not None]
    for c in ctx.pick([c for c in candidates if ctx.apps_by_id(c["app_ids"][0])["_spec"]["filler"]], 6):
        app = ctx.apps_by_id(c["app_ids"][0])
        if app["user_count_90d"]:
            c["licensed_seats"] = max(c["licensed_seats"], round(app["user_count_90d"] / ctx.rng.uniform(0.3, 0.45)))
            c["auto_renew"] = False
            ctx.plant("low_seat_utilization", c["id"], app=app["name"])
    # Hyperscaler enterprise agreements (not tied to an app; cost allocated via tags)
    for provider in ("Amazon Web Services", "Microsoft Azure"):
        ctx.add("contracts", {
            "id": ctx.next_id("CON", 3), "vendor": provider, "app_ids": [], "annual_value_usd": 0.0, "licensed_seats": None,
            "renewal_date": ctx.days_ahead(ctx.rng.randint(200, 500)), "auto_renew": False, "term_months": 36,
            "market_benchmark_usd": 0.0,
        }, "contract_management")


def gen_cloud(ctx: GenContext) -> None:
    regions = ctx.tenant["approved_regions"]
    types_aws = ["ec2.instance", "rds.instance", "s3.bucket", "eks.cluster", "lambda.function", "elasticache.cluster"]
    types_az = ["vm", "sql.database", "storage.account", "aks.cluster", "function.app"]
    for a in ctx.rows["applications"]:
        if a["hosting"] not in ("iaas", "paas"):
            continue
        n = ctx.rng.randint(26, 50) if a["criticality"] <= 2 else ctx.rng.randint(3, 8)
        provider = "aws" if ctx.rng.random() < 0.7 else "azure"
        tag_variant = ctx.pick([slug(a["name"]), f"{slug(a['name'])}-prod", a["name"], a["name"].lower()])
        for _ in range(n):
            env = ctx.rng.choices(["prod", "nonprod"], [0.7, 0.3])[0]
            row = ctx.add("cloud_resources", {
                "id": ctx.next_id("CLD"), "provider": provider,
                "account": f"{ctx.tenant['cost_center_prefix'].lower()}-{provider}-{env}",
                "resource_type": ctx.pick(types_aws if provider == "aws" else types_az),
                "tags": {"app": tag_variant, "env": env, "owner": ctx.users_by_id(a["owner_user_id"])["email"]},
                "monthly_cost_usd": round(ctx.rng.uniform(40, 6500) * 1.4 if a["criticality"] <= 2 else ctx.rng.uniform(20, 900), 2),
                "utilization_pct": round(ctx.rng.uniform(4, 88), 1), "untagged": False, "region": ctx.pick(regions),
            }, "cloud_billing")
            row["_app_id"] = a["id"]
    # 10-15% untagged (ground truth app kept for tests only)
    res = ctx.rows["cloud_resources"]
    for r in ctx.pick(res, round(len(res) * 0.13)):
        r["tags"] = {"env": r["tags"]["env"]} if ctx.rng.random() < 0.4 else {}
        r["untagged"] = True
        ctx.plant("untagged_cloud_resource", r["id"], monthly_cost_usd=r["monthly_cost_usd"], true_app_id=r["_app_id"])


def _invoice_vendor(ctx: GenContext, vendor: str) -> str:
    return ctx.pick(vendor_variants(vendor)) if ctx.rng.random() < 0.55 else vendor


def gen_invoices(ctx: GenContext) -> None:
    apps_by_id = ctx.apps_by_id
    vendor_app_count: dict[str, int] = {}
    for a in ctx.rows["applications"]:
        vendor_app_count[a["vendor"]] = vendor_app_count.get(a["vendor"], 0) + 1
    cc_prefix = ctx.tenant["cost_center_prefix"]
    for c in ctx.rows["contracts"]:
        if not c["app_ids"]:
            # hyperscaler monthly bills: sum of tagged + untagged resources
            prov = "aws" if "Amazon" in c["vendor"] else "azure"
            monthly = sum(r["monthly_cost_usd"] for r in ctx.rows["cloud_resources"] if r["provider"] == prov)
            for m in range(24):
                ctx.add("invoice_lines", {
                    "id": ctx.next_id("INV", 5), "vendor": c["vendor"], "amount_usd": round(monthly * ctx.rng.uniform(0.93, 1.05), 2),
                    "invoice_date": ctx.days_ago(30 * m + 3), "cost_center": f"{cc_prefix}-IT-CLOUD", "matched_app_id": None,
                    "description": "Monthly cloud consumption", "payment_channel": "ap",
                }, "ap_invoices")
            continue
        app = apps_by_id(c["app_ids"][0])
        cadence = 1 if app["hosting"] == "saas" else (3 if c["annual_value_usd"] > 200000 else 12)
        periods = 24 // cadence
        product_hint = app["name"] if vendor_app_count.get(c["vendor"], 0) > 1 else ""
        for p in range(periods):
            amount = c["annual_value_usd"] * cadence / 12 * ctx.rng.uniform(0.97, 1.03)
            raw_vendor = _invoice_vendor(ctx, c["vendor"])
            desc_hint = product_hint
            if product_hint and ctx.rng.random() < 0.3:
                desc_hint = ctx.pick(name_variants(product_hint))
            ctx.add("invoice_lines", {
                "id": ctx.next_id("INV", 5), "vendor": raw_vendor, "amount_usd": round(amount, 2),
                "invoice_date": ctx.days_ago(30 * cadence * p + ctx.rng.randint(0, 9)),
                "cost_center": f"{cc_prefix}-{slug(ctx.l1_name_of_app(app))[:12].upper()}",
                "matched_app_id": app["id"],
                "description": f"{'Subscription' if cadence == 1 else 'License & support'} {desc_hint}".strip(),
                "payment_channel": "ap",
            }, "ap_invoices")
            ctx.alias(raw_vendor, app["id"], "invoice", desc_hint or None)

    # Shadow IT: invoices / expense claims that match no application
    for s in ctx.catalog["shadow_it"]:
        months = ctx.rng.randint(5, 16)
        start = ctx.rng.randint(0, 4)
        for m in range(start, start + months):
            raw = ctx.pick(s["vendor_raw"])
            row = ctx.add("invoice_lines", {
                "id": ctx.next_id("INV", 5), "vendor": raw, "amount_usd": round(s["monthly"] * ctx.rng.uniform(0.9, 1.1), 2),
                "invoice_date": ctx.days_ago(30 * m + ctx.rng.randint(0, 20)),
                "cost_center": s["cost_center"] if s["channel"] == "expense" else f"{cc_prefix}-{slug(s['cost_center'])[:12].upper()}",
                "matched_app_id": None,
                "description": ("Expense claim - " if s["channel"] == "expense" else "Subscription - ") + raw,
                "payment_channel": s["channel"],
            }, "expense_reports" if s["channel"] == "expense" else "ap_invoices")
            s.setdefault("_invoice_ids", []).append(row["id"])


def gen_sso(ctx: GenContext) -> None:
    for a in ctx.rows["applications"]:
        if a["ot_system"] or a["hosting"] == "on_prem" and a["user_count_90d"] < 20:
            continue
        if a["hosting"] == "on_prem" and ctx.rng.random() < 0.5:
            continue
        variants = name_variants(a["name"])
        primary = a["name"] if ctx.rng.random() < 0.6 else ctx.pick(variants)
        secondary = ctx.pick(variants) if ctx.rng.random() < 0.35 else primary
        switch = ctx.rng.randint(6, 18)
        base = a["user_count_90d"]
        for m in range(24):
            raw = secondary if m < switch else primary
            if a["user_count_90d"] == 0 and m < 4:
                users = 0
            else:
                users = max(0, int(base * ctx.rng.uniform(0.75, 1.05) * (1 - 0.006 * m)))
            month = ctx.days_ago(30 * m)[:7]
            ctx.add("sso_usage", {
                "id": ctx.next_id("SSO", 5), "app_name_raw": raw, "month": month, "unique_users": users,
                "logins": users * ctx.rng.randint(4, 40),
            }, "sso_idp")
            ctx.alias(raw, a["id"], "sso")
        a["discovered_via"].append("sso")
    for s in ctx.catalog["shadow_it"]:
        for raw in s.get("sso_raw", []):
            users = ctx.rng.randint(3, 60)
            for m in range(ctx.rng.randint(4, 14)):
                ctx.add("sso_usage", {
                    "id": ctx.next_id("SSO", 5), "app_name_raw": raw, "month": ctx.days_ago(30 * m)[:7],
                    "unique_users": max(1, int(users * ctx.rng.uniform(0.6, 1.2))), "logins": users * ctx.rng.randint(3, 20),
                }, "sso_idp")


def gen_cmdb(ctx: GenContext) -> None:
    prefix = ctx.tenant["cost_center_prefix"]
    for a in ctx.rows["applications"]:
        if not a["in_cmdb"]:
            continue
        style = ctx.rng.random()
        if style < 0.5:
            ci_name = a["name"]
        elif style < 0.75:
            ci_name = a["name"].upper()
        else:
            ci_name = f"{prefix}-{slug(a['name'])}"
        ci = ctx.add("cmdb_cis", {
            "id": ctx.next_id("CI", 4), "ci_name": ci_name, "ci_type": ctx.pick(["application", "business_application", "application_service"]),
            "app_id": a["id"], "last_updated": ctx.days_ago(ctx.rng.randint(5, 600)), "ci_status": "operational",
        }, "cmdb")
        ctx.alias(ci_name, a["id"], "cmdb")
        a["discovered_via"].append("cmdb")
        a["_ci"] = ci["id"]
    # Duplicates: same application registered twice under different names
    in_cmdb = [a for a in ctx.rows["applications"] if a["in_cmdb"] and a["criticality"] <= 3]
    for a in ctx.pick(in_cmdb, 6):
        dup_name = ctx.pick([f"{a['name']} Prod", f"{prefix}-{slug(a['name'])}-01", f"{a['name']} (Legacy CI)"])
        ci = ctx.add("cmdb_cis", {
            "id": ctx.next_id("CI", 4), "ci_name": dup_name, "ci_type": "application",
            "app_id": None, "last_updated": ctx.days_ago(ctx.rng.randint(400, 1100)), "ci_status": "operational",
        }, "cmdb")
        ctx.alias(dup_name, a["id"], "cmdb")
        ctx.plant("cmdb_duplicate", ci["id"], duplicate_of=a["_ci"], app_id=a["id"], ci_name=dup_name)
    # Retired applications still listed as operational
    for name in ctx.catalog.get("retired_cis", []):
        ci = ctx.add("cmdb_cis", {
            "id": ctx.next_id("CI", 4), "ci_name": name, "ci_type": "application", "app_id": None,
            "last_updated": ctx.days_ago(ctx.rng.randint(800, 1600)), "ci_status": "operational",
        }, "cmdb")
        ctx.plant("cmdb_stale_retired_app", ci["id"], ci_name=name)


def finalize_costs(ctx: GenContext) -> None:
    """annual_cost_usd = contract share + tagged cloud + 15% support overhead (Section 5.3)."""
    contract_share: dict[str, float] = {}
    for c in ctx.rows["contracts"]:
        for app_id in c["app_ids"]:
            contract_share[app_id] = contract_share.get(app_id, 0.0) + c["annual_value_usd"] / len(c["app_ids"])
    cloud: dict[str, float] = {}
    for r in ctx.rows.get("cloud_resources", []):
        if not r["untagged"]:
            cloud[r["_app_id"]] = cloud.get(r["_app_id"], 0.0) + r["monthly_cost_usd"] * 12
    for a in ctx.rows["applications"]:
        base = contract_share.get(a["id"], 0.0)
        if a["_spec"]["inhouse"]:
            base = float(a["_spec"]["cost"])  # internal run cost (labour, licences bundled) stands in for contract share
        cloud_cost = cloud.get(a["id"], 0.0)
        a["annual_cost_usd"] = round((base + cloud_cost) * 1.15, 2)
        if a["id"] in contract_share:
            a["discovered_via"].append("invoice")
        if cloud_cost:
            a["discovered_via"].append("cloud")
        a["discovered_via"] = sorted(set(a["discovered_via"]))
