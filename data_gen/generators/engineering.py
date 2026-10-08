"""APIs, integrations, repositories, incidents, standards, patterns, ADRs, design submissions, discussions."""

from __future__ import annotations

import re

from data_gen.generators.core import GenContext, slug

EOL_FRAMEWORKS = {
    "Struts 1.3": 2008, "Struts 2.3": 2012, "Spring 3.2": 2012, "Spring 4": 2014, "J2EE": 2006, "EJB 3": 2009,
    "AngularJS 1.5": 2016, "AngularJS 1.6": 2016, "WinForms": 2008, "WebForms": 2012, "Django 1.8": 2015,
    "Custom": 2007, "Express 4 (Node 14)": 2020, "Spring Boot 2.7": 2022, "SAS 9.2": 2009,
}
SUPPORTED = {
    "Spring Boot 3": 2023, "FastAPI": 2023, "Express 4": 2022, "ASP.NET Core": 2023, "MVC": 2019, "PySpark": 2023,
    "MLflow": 2023, "Next.js 14": 2023, "React Native 0.72": 2023, "Spring 5": 2019,
}


def _parse_fw(fw: str) -> tuple[str, str, str]:
    lang, _, framework = fw.partition(" / ")
    m = re.match(r"(.+?) ([\d.]+)$", framework)
    if m:
        return lang, m.group(1), m.group(2)
    return lang, framework or lang, ""


def gen_apis(ctx: GenContext) -> None:
    domain = ctx.tenant["email_domain"]
    for spec in ctx.catalog.get("apis", []):
        owner = ctx.app(spec["owner"])
        row = ctx.add("apis", {
            "id": ctx.next_id("API", 3), "name": spec["name"], "owner_app_id": owner["id"], "style": spec["style"],
            "consumers": [ctx.app(n)["id"] for n in spec.get("consumers", [])],
            "spec_url": f"https://apis.{domain}/specs/{slug(spec['name'])}.yaml", "duplicate_group": spec.get("dup"),
            "auth": spec["auth"], "data_classification": spec["cls"], "via_gateway": spec.get("gateway", False),
            "resource": spec.get("resource"),
        }, "api_catalog")
        if spec.get("dup"):
            ctx.plant("duplicate_api", row["id"], group=spec["dup"], name=spec["name"])
        if spec["auth"] in ("none", "apikey") and spec["cls"] in ("confidential", "restricted"):
            ctx.plant("insecure_api", row["id"], auth=spec["auth"], cls=spec["cls"])
    planted_owners = {a["owner_app_id"] for a in ctx.rows["apis"]}
    apps = [a for a in ctx.rows["applications"] if (a["criticality"] <= 2 or not a["_spec"]["filler"]) and not a["ot_system"]]
    others = [a for a in ctx.rows["applications"] if not a["ot_system"]]
    for a in apps:
        n = 1 if a["id"] in planted_owners else (ctx.rng.choice([1, 2, 2]) if a["criticality"] <= 2 else 1)
        for i in range(n):
            res = (a["features"][i % len(a["features"])] if a["features"] else "data").replace("_", " ")
            old = any(x in " ".join(a["tech_stack"]) for x in ("Java 6", "Java 7", "COBOL", "VBA", "Perl"))
            style = "soap" if old else ctx.rng.choices(["rest", "rest", "rest", "event", "graphql"])[0]
            auth = ctx.rng.choices(["oauth2", "mtls", "apikey"], [0.75, 0.1, 0.15])[0]
            ctx.add("apis", {
                "id": ctx.next_id("API", 3), "name": f"{a['name']} {res.title()} API", "owner_app_id": a["id"],
                "style": style, "consumers": [c["id"] for c in ctx.pick(others, ctx.rng.randint(0, 4)) if c["id"] != a["id"]],
                "spec_url": f"https://apis.{domain}/specs/{slug(a['name'])}-{slug(res)}.yaml", "duplicate_group": None,
                "auth": auth if a["data_classification"] != "public" else "oauth2",
                "data_classification": "internal" if auth == "apikey" else a["data_classification"],
                "via_gateway": ctx.rng.random() < 0.6, "resource": slug(res),
            }, "api_catalog")


def _cls_max(a: str, b: str) -> str:
    order = ["public", "internal", "confidential", "restricted"]
    return order[max(order.index(a or "internal"), order.index(b or "internal"))]


def gen_integrations(ctx: GenContext) -> None:
    seen: set[tuple[str, str]] = set()

    def add(frm: dict, to: dict, pattern: str, approved: bool, desc: str, source: str = "integration_catalog") -> dict | None:
        if frm["id"] == to["id"] or (frm["id"], to["id"]) in seen:
            return None
        seen.add((frm["id"], to["id"]))
        return ctx.add("integrations", {
            "id": ctx.next_id("INT"), "from_app_id": frm["id"], "to_app_id": to["id"], "pattern": pattern,
            "frequency": {"event": "real-time", "api": "on-demand", "file": "daily", "db_link": "hourly", "manual": "weekly"}[pattern],
            "approved": approved, "data_classification": _cls_max(frm["data_classification"], to["data_classification"]),
            "description": desc, "crosses_boundary": _crosses(frm, to),
        }, source)

    for frm, to, pattern in ctx.catalog.get("core_integrations", []):
        a, b = ctx.app(frm), ctx.app(to)
        add(a, b, pattern, True, f"{a['name']} sends data to {b['name']} via {pattern}")
    for link in ctx.catalog.get("db_links", []):
        a, b = ctx.app(link["from"]), ctx.app(link["to"])
        row = add(a, b, "db_link", False, link["desc"], source="network_flow_logs")
        if row:
            row["crosses_boundary"] = bool(link.get("cross")) or row["crosses_boundary"]
            ctx.plant("direct_db_link", row["id"], crosses_boundary=row["crosses_boundary"], desc=link["desc"],
                      from_app=a["name"], to_app=b["name"])
    apps = ctx.rows["applications"]
    by_l1: dict[str, list[dict]] = {}
    for a in apps:
        by_l1.setdefault(ctx.l1_name_of_app(a), []).append(a)
    hubs = [a for a in apps if a["criticality"] == 1]
    for a in apps:
        k = ctx.rng.choice([0, 1, 1, 2]) if a["criticality"] >= 3 else ctx.rng.choice([2, 3, 4])
        for _ in range(k):
            same = by_l1[ctx.l1_name_of_app(a)]
            target = ctx.pick(same) if ctx.rng.random() < 0.55 else ctx.pick(hubs)
            if a["ot_system"] != target["ot_system"]:
                pattern = "file"  # via DMZ historian / MFT
            else:
                pattern = ctx.rng.choices(["api", "file", "event", "manual"], [0.45, 0.28, 0.17, 0.10])[0]
            approved = ctx.rng.random() > 0.07
            row = add(a, target, pattern, approved, f"{a['name']} -> {target['name']} ({pattern})")
            if row and not approved:
                ctx.plant("unapproved_integration", row["id"])


def _crosses(a: dict, b: dict) -> bool:
    za, zb = a.get("zone"), b.get("zone")
    if {za, zb} == {"it", "ot"}:
        return True
    return {za, zb} == {"bss", "oss"}


def gen_repos(ctx: GenContext) -> None:
    deps: dict[str, list[str]] = {}
    for i in ctx.rows["integrations"]:
        if i["pattern"] != "db_link":
            deps.setdefault(i["from_app_id"], []).append(i["to_app_id"])
    db_link_targets: dict[str, list[str]] = {}
    for i in ctx.rows["integrations"]:
        if i["pattern"] == "db_link":
            db_link_targets.setdefault(i["from_app_id"], []).append(i["to_app_id"])
    all_ids = [a["id"] for a in ctx.rows["applications"]]
    for a in ctx.rows["applications"]:
        spec = a["_spec"]
        fw = spec.get("fw")
        if not spec["inhouse"] and not (fw or (a["hosting"] == "on_prem" and ctx.rng.random() < 0.06)):
            continue
        if not fw:
            fw = ctx.pick(["Java 11 / Spring 5", ".NET Framework 4.8 / MVC", "Python 3.11 / FastAPI"])
        lang, framework, version = _parse_fw(fw)
        fw_key = f"{framework} {version}".strip()
        if lang.startswith("Node.js 14"):
            fw_key = "Express 4 (Node 14)"
        eol = fw_key in EOL_FRAMEWORKS or any(x in lang for x in ("Java 6", "Java 7", "Python 2", ".NET Framework 3.5"))
        year = EOL_FRAMEWORKS.get(fw_key) or SUPPORTED.get(fw_key) or ctx.rng.randint(2016, 2023)
        n = 1 if a["criticality"] >= 3 else ctx.rng.choice([1, 2, 3])
        if not spec["inhouse"]:
            n = 1
        for r in range(n):
            suffix = ["", "-api", "-batch"][r] if spec["inhouse"] else "-customizations"
            declared = sorted(set(deps.get(a["id"], [])))
            actual = list(declared)
            # db links are always undeclared runtime dependencies (drift)
            for t in db_link_targets.get(a["id"], []):
                if t not in actual:
                    actual.append(t)
            if not db_link_targets.get(a["id"]) and ctx.rng.random() < 0.14:
                extra = ctx.pick(all_ids)
                if extra != a["id"] and extra not in actual:
                    actual.append(extra)
                elif actual:
                    actual.pop()
            hot = spec.get("hot")
            row = ctx.add("repos", {
                "id": ctx.next_id("REPO", 3), "name": f"{slug(a['name'])}{suffix}", "app_id": a["id"], "language": lang,
                "framework": framework, "framework_version": version, "eol": eol,
                "last_commit_days": ctx.rng.randint(1, 40) if not eol else ctx.rng.randint(20, 400),
                "open_critical_vulns": ctx.rng.randint(3, 12) if hot else ctx.rng.choice([0, 0, 0, 1, 2]),
                "has_iac": a["hosting"] in ("iaas", "paas") and ctx.rng.random() < 0.8,
                "declared_dependencies": declared, "actual_dependencies": sorted(set(actual)),
                "loc_k": ctx.rng.randint(8, 60) if a["criticality"] >= 3 else ctx.rng.randint(40, 420),
                "framework_release_year": year,
            }, "git")
            if set(row["actual_dependencies"]) != set(row["declared_dependencies"]):
                ctx.plant("dependency_drift", row["id"], app_id=a["id"])


def gen_incidents(ctx: GenContext) -> None:
    apps = ctx.rows["applications"]
    hot = [a for a in apps if a["_spec"].get("hot")]
    causes = ["software_defect", "capacity", "change_failure", "integration_failure", "infrastructure", "data_quality",
              "security", "vendor_defect"]
    total = ctx.rng.randint(340, 460)
    for _ in range(total):
        a = ctx.pick(hot) if ctx.rng.random() < 0.62 else ctx.pick(apps)
        sev = ctx.rng.choices([1, 2, 3, 4], [0.05, 0.18, 0.42, 0.35])[0]
        if a in hot and ctx.rng.random() < 0.25:
            sev = max(1, sev - 1)
        cause = ctx.pick(causes)
        ctx.add("incidents", {
            "id": ctx.next_id("INC", 5), "app_id": a["id"], "severity": sev, "date": ctx.days_ago(ctx.rng.randint(0, 729)),
            "root_cause_category": cause, "minutes_to_resolve": int({1: 240, 2: 150, 3: 90, 4: 45}[sev] * ctx.rng.uniform(0.3, 2.5)),
            "title": f"{a['name']}: {cause.replace('_', ' ')}",
        }, "itsm")


def gen_standards_patterns(ctx: GenContext) -> None:
    for s in ctx.common["standards"] + ctx.catalog.get("extra_standards", []):
        ctx.add("standards", {
            "id": s["id"], "title": s["title"], "rule_text": s["rule_text"], "domain": s["domain"],
            "severity": s["severity"], "checks": s.get("checks", []),
        }, "architecture_standards")
    std_ids = {s["id"] for s in ctx.rows["standards"]}
    for p in ctx.common["patterns"] + ctx.catalog.get("extra_patterns", []):
        ctx.add("patterns", {
            "id": p["id"], "name": p["name"], "when_to_use": p["when_to_use"], "components": p["components"],
            "diagram_mermaid": p["diagram_mermaid"].strip(), "standard_ids": [s for s in p["standard_ids"] if s in std_ids],
            "keywords": p.get("keywords", []), "nfrs": p.get("nfrs", []),
        }, "architecture_standards")
    ctx.rows["patterns"].sort(key=lambda r: r["id"])


def gen_adrs(ctx: GenContext) -> None:
    for i, (title, app_names) in enumerate(ctx.catalog.get("adr_titles", [])):
        ids = [ctx.app(n)["id"] for n in app_names]
        status = "superseded" if i in (3, 11) else ("proposed" if i == 7 else "accepted")
        names = ", ".join(app_names)
        ctx.add("adrs", {
            "id": ctx.next_id("ADR", 3), "title": title, "status": status,
            "context": f"Teams working on {names} needed a consistent approach; options were discussed at the architecture forum.",
            "decision": f"{title}.", "consequences": f"Applies to {names}. Exceptions require architecture board approval.",
            "app_ids": ids, "date": ctx.days_ago(ctx.rng.randint(60, 1100)), "options": [], "source_discussion_id": None,
        }, "adr_repository")


def gen_design_docs(ctx: GenContext) -> None:
    for d in ctx.catalog.get("design_docs", []):
        row = ctx.add("design_docs", {
            "id": ctx.next_id("DES", 3), "title": d["title"], "team": d["team"], "body_md": d["body"].strip(),
            "submitted_at": ctx.days_ago(ctx.rng.randint(0, 12)) + f"T{ctx.rng.randint(8, 17):02d}:00:00",
            "status": "submitted", "reviewed_at": None, "app_ids": [ctx.app(n)["id"] for n in d.get("apps", [])],
            "components": d.get("components", []),
        }, "design_intake")
        ctx.rows.setdefault("gt_planted_design", []).append({"design_id": row["id"], "violations": d.get("violations", [])})
        if d.get("violations"):
            ctx.plant("design_violates_standards", row["id"], standards=d["violations"], title=d["title"])
    # Historical, already-reviewed submissions (give the turnaround KPI a baseline)
    teams = sorted({d["team"] for d in ctx.catalog.get("design_docs", [])})
    hist_titles = ["Reporting API refresh", "Batch interface hardening", "Identity federation for partners"]
    for t in hist_titles:
        sub_days = ctx.rng.randint(30, 120)
        hours = ctx.rng.randint(20, 96)
        from datetime import datetime, timedelta

        submitted = ctx.days_ago(sub_days) + "T09:00:00"
        reviewed = (datetime.fromisoformat(submitted) + timedelta(hours=hours)).isoformat(timespec="seconds")
        ctx.add("design_docs", {
            "id": ctx.next_id("DES", 3), "title": t, "team": ctx.pick(teams),
            "body_md": f"## Summary\n{t}.\n\n## Design\nData classification: internal. All APIs published through the API gateway with OAuth2.",
            "submitted_at": submitted, "status": "approved", "reviewed_at": reviewed,
            "app_ids": [], "components": [],
        }, "design_intake")


def _best_option(d: dict) -> int:
    words = set(re.findall(r"[a-z]+", d["decision"].lower()))
    scores = [len(words & set(re.findall(r"[a-z]+", o.lower()))) for o in d["options"]]
    return scores.index(max(scores))


def gen_discussions(ctx: GenContext) -> None:
    users = ctx.rows["users"]
    for d in ctx.catalog.get("decisions", []):
        people = ctx.pick(users, 4)
        lines = [
            f"**{people[0]['name']}**: Raising this for a decision: {d['title'].lower()}. Context — {d['context']}",
            f"**{people[1]['name']}**: Options I see: " + "; ".join(f"({i + 1}) {o}" for i, o in enumerate(d["options"])) + ".",
            f"**{people[2]['name']}**: Option {_best_option(d) + 1} gets my vote; the others keep the problem alive.",
            f"**{people[0]['name']}**: Agreed. Decision: {d['decision']}",
            f"**{people[3]['name']}**: Noting the consequences: {d['consequences']}",
        ]
        ctx.add("discussions", {
            "id": ctx.next_id("DSC", 3), "channel": d["channel"], "participants": [p["name"] for p in people],
            "body_md": "\n\n".join(lines), "title": d["title"], "date": ctx.days_ago(ctx.rng.randint(1, 40)),
            "extracted": {"title": d["title"], "context": d["context"], "options": d["options"], "decision": d["decision"],
                          "consequences": d["consequences"], "apps": d.get("apps", [])},
        }, "slack")
    chatter = [
        ("#arch-forum", "Agenda for next architecture forum", "Please add items to the agenda by Thursday."),
        ("#platform-ops", "Patch window this weekend", "Reminder: patching window Saturday 22:00-02:00."),
        ("#data-platform", "Lake storage costs", "Storage grew 9% last month; mostly raw imagery and logs."),
        ("#digital-channels", "App store review", "Release 4.12 approved; rollout at 10%."),
        ("#arch-integration", "Gateway certificate rotation", "Certificates rotate on the 15th, no action needed."),
        ("#genai-cop", "Prompt library", "Sharing a few prompts that worked well for summarising tickets."),
        ("#security", "Phishing simulation results", "Click rate down to 4.1%."),
        ("#arch-forum", "Capability map refresh", "Owners: please confirm L2 maturity scores by month end."),
        ("#field-systems", "Tablet refresh", "New rugged tablets arrive in two weeks."),
        ("#finance-it", "Q3 run-cost forecast", "Forecast attached; licences are the main variance."),
        ("#data-governance", "Catalog onboarding", "Three more domains onboarded to the catalog this sprint."),
        ("#platform-ops", "DR test", "Annual DR test passed for tier-1 systems except one."),
        ("#arch-forum", "Lunch and learn", "Next session: event-driven patterns."),
        ("#digital-channels", "Accessibility audit", "Audit found 12 minor issues; fixes scheduled."),
    ]
    for ch, title, text in chatter:
        people = ctx.pick(users, 2)
        ctx.add("discussions", {
            "id": ctx.next_id("DSC", 3), "channel": ch, "participants": [p["name"] for p in people],
            "body_md": f"**{people[0]['name']}**: {text}\n\n**{people[1]['name']}**: Thanks, noted.",
            "title": title, "date": ctx.days_ago(ctx.rng.randint(1, 60)), "extracted": None,
        }, "slack")
