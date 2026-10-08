"""Strategy documents, strategic goals and projects."""

from __future__ import annotations

from data_gen.generators.core import GenContext


def gen_strategy(ctx: GenContext) -> None:
    doc_ids: dict[str, str] = {}
    goals_by_doc: dict[str, list[dict]] = {}
    for g in ctx.catalog["goals"]:
        goals_by_doc.setdefault(g["doc"], []).append(g)
    for d in ctx.catalog["strategy_docs"]:
        body = [f"# {d['title']}", "", f"*{ctx.tenant['name']} — {d['type'].replace('_', ' ')} ({d['year']})*", ""]
        body += [p + "\n" for p in d["paragraphs"]]
        doc_goals = goals_by_doc.get(d["key"], [])
        if doc_goals:
            body.append("## Commitments")
            for g in doc_goals:
                body.append(f"- **{g['statement']}** by {g['horizon']} (measured by {g['kpi']}).")
            body.append("")
            body.append("## Capabilities required")
            caps = sorted({c for g in doc_goals for c in g["caps"]})
            body.append("Delivering these commitments depends on the following business capabilities: " + ", ".join(caps) + ".")
            body.append("")
        body.append("## Governance")
        body.append(
            f"Progress is reported quarterly to the executive committee. The architecture office maintains traceability "
            f"from this document to funded projects and the application portfolio. Owner: {ctx.users_by_key['cio']['name']}."
        )
        row = ctx.add("strategy_docs", {
            "id": ctx.next_id("DOC", 3), "title": d["title"], "type": d["type"], "body_md": "\n".join(body), "year": d["year"],
        }, "document_management")
        doc_ids[d["key"]] = row["id"]
    ctx.goal_ids = {}
    for g in ctx.catalog["goals"]:
        caps = [ctx.cap(c) for c in g["caps"]]
        row = ctx.add("goals", {
            "id": ctx.next_id("GOAL", 3), "statement": g["statement"], "source_doc_id": doc_ids[g["doc"]],
            "horizon_year": g["horizon"], "kpi": g["kpi"],
            "keywords": sorted({k for c in caps for k in c["keywords"]} | {c["name"].lower() for c in caps}),
        }, "strategy_extraction")
        row["_cap_ids"] = [c["id"] for c in caps]
        ctx.goal_ids[g["key"]] = row["id"]


def gen_projects(ctx: GenContext) -> None:
    funded: set[str] = set()
    for p in ctx.catalog["projects"]:
        goal_ids = [ctx.goal_ids[k] for k in p.get("goals", [])]
        funded |= set(goal_ids)
        start = ctx.rng.randint(-300, 60)
        row = ctx.add("projects", {
            "id": ctx.next_id("PRJ", 3), "name": p["n"], "budget_usd": float(p["budget"]), "status": p["status"],
            "capability_ids": [ctx.cap(c)["id"] for c in p.get("caps", [])], "goal_ids": goal_ids,
            "app_ids": [ctx.app(a)["id"] for a in p.get("apps", [])],
            "start": ctx.days_ahead(start), "end": ctx.days_ahead(start + ctx.rng.randint(180, 720)),
            "sponsor_user_id": ctx.user_id("cio"),
        }, "ppm")
        if not goal_ids:
            ctx.plant("orphan_project", row["id"], budget=p["budget"], name=p["n"])
    for g in ctx.rows["goals"]:
        if g["id"] not in funded:
            ctx.plant("unfunded_goal", g["id"], statement=g["statement"])
