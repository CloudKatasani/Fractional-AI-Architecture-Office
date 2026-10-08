"""Render Mermaid text from the knowledge graph (Diagram Generator). Rendered client-side with Mermaid."""

from __future__ import annotations

import re

from app.kg.queries import KG


def _id(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", x)


def _label(text: str, max_len: int = 38) -> str:
    text = text.replace('"', "'").replace("[", "(").replace("]", ")")
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def capability_map(kg: KG, tenant_name: str) -> str:
    caps = kg.by_type("Capability")
    children: dict[str | None, list[dict]] = {}
    for c in caps:
        children.setdefault(c["props_json"].get("parent_id"), []).append(c)
    lines = ["mindmap", f"  root(({_label(tenant_name)}))"]

    def walk(parent: str | None, depth: int) -> None:
        for c in sorted(children.get(parent, []), key=lambda x: x["id"]):
            heat = c["props_json"]["strategic_importance"] * (5 - c["props_json"]["maturity"])
            marker = " 🔥" if heat >= 12 else ""
            name = _label(c["name"]).replace("(", "- ").replace(")", "").replace("&", "and")
            lines.append("  " * (depth + 1) + f"{name}{marker}")
            if depth < 2:
                walk(c["id"], depth + 1)

    walk(None, 1)
    return "\n".join(lines)


def c4_context(kg: KG, app_id: str) -> str:
    app = kg.node(app_id)
    if not app:
        return "flowchart LR\n  missing[Unknown application]"
    lines = ["flowchart LR", f'  {_id(app_id)}["<b>{_label(app["name"])}</b><br/>{app["props_json"].get("category", "")}"]',
             f"  style {_id(app_id)} fill:#1f6feb,color:#fff"]
    seen = set()
    for e in kg.out_edges(app_id, "INTEGRATES_WITH")[:14]:
        o = kg.node(e["to_id"])
        if o and o["id"] not in seen:
            seen.add(o["id"])
            lines.append(f'  {_id(o["id"])}["{_label(o["name"])}"]')
            arrow = "-.->" if not e["props_json"].get("approved", True) else "-->"
            lines.append(f'  {_id(app_id)} {arrow}|{e["props_json"].get("pattern")}| {_id(o["id"])}')
    for e in kg.in_edges(app_id, "INTEGRATES_WITH")[:14]:
        o = kg.node(e["from_id"])
        if o and o["id"] not in seen:
            seen.add(o["id"])
            lines.append(f'  {_id(o["id"])}["{_label(o["name"])}"]')
            arrow = "-.->" if not e["props_json"].get("approved", True) else "-->"
            lines.append(f'  {_id(o["id"])} {arrow}|{e["props_json"].get("pattern")}| {_id(app_id)}')
    for e in kg.in_edges(app_id, "OWNS")[:1]:
        p = kg.node(e["from_id"])
        lines.append(f'  {_id(p["id"])}(["👤 {_label(p["name"])}"])')
        lines.append(f"  {_id(p['id'])} -.owns.- {_id(app_id)}")
    for e in kg.in_edges(app_id, "STORED_IN")[:6]:
        d = kg.node(e["from_id"])
        lines.append(f'  {_id(d["id"])}[("{_label(d["name"], 28)}")]')
        lines.append(f"  {_id(app_id)} --- {_id(d['id'])}")
    return "\n".join(lines)


def data_flow(kg: KG, dataset_id: str) -> str:
    up = kg.lineage_upstream(dataset_id, max_depth=3)
    down = kg.lineage_downstream(dataset_id, max_depth=2)
    # keep diagrams readable: cap each list
    for d in (up, down):
        for k in ("datasets", "pipelines", "bi_assets", "ai"):
            if k in d:
                d[k] = d[k][:12]
    nodes = {dataset_id} | set(up["datasets"]) | set(up["pipelines"]) | set(up["systems"]) | set(down["datasets"]) \
        | set(down["pipelines"]) | set(down["bi_assets"]) | set(down["ai"])
    lines = ["flowchart LR"]
    for nid in sorted(nodes):
        n = kg.node(nid)
        if not n:
            continue
        lbl = _label(n["name"], 30)
        t = n["type"]
        if t == "Dataset":
            lines.append(f'  {_id(nid)}[("{lbl}")]')
        elif t == "Pipeline":
            lines.append(f'  {_id(nid)}{{{{"{lbl}"}}}}')
        elif t == "Application":
            lines.append(f'  {_id(nid)}["🖥 {lbl}"]')
        elif t in ("AIAsset", "AIUseCase"):
            lines.append(f'  {_id(nid)}(["🤖 {lbl}"])')
        else:
            lines.append(f'  {_id(nid)}["📊 {lbl}"]')
    for e in up["edges"] + down["edges"]:
        if e["from_id"] in nodes and e["to_id"] in nodes:
            if e["type"] == "STORED_IN":
                lines.append(f"  {_id(e['to_id'])} -.-> {_id(e['from_id'])}")
            elif e["type"] == "CONSUMES_DATA":
                lines.append(f"  {_id(e['to_id'])} --> {_id(e['from_id'])}")
            elif e["type"] == "USES_DATA":
                lines.append(f"  {_id(e['to_id'])} -.-> {_id(e['from_id'])}")
            else:
                lines.append(f"  {_id(e['from_id'])} --> {_id(e['to_id'])}")
    lines.append(f"  style {_id(dataset_id)} fill:#1f6feb,color:#fff")
    return "\n".join(dict.fromkeys(lines))


def integration_map(kg: KG, cap_id: str) -> str:
    sub = kg.subgraph_for_capability(cap_id)
    apps = set(sub["applications"])
    lines = ["flowchart LR"]
    for a in sorted(apps):
        n = kg.node(a)
        lines.append(f'  {_id(a)}["{_label(n["name"])}"]')
    bad = []
    for i, e in enumerate(sub["integrations"]):
        if e["to_id"] in apps:
            pattern = e["props_json"].get("pattern")
            arrow = "==>" if pattern == "db_link" else ("-.->" if not e["props_json"].get("approved", True) else "-->")
            lines.append(f"  {_id(e['from_id'])} {arrow}|{pattern}| {_id(e['to_id'])}")
            if pattern == "db_link":
                bad.append(i)
    return "\n".join(lines)


def drift_diagrams(kg: KG, app_ids: list[str], boundary_pairs: set[tuple[str, str]]) -> dict:
    """Intended (declared, approved) vs actual (runtime) dependency diagrams for a set of apps."""
    def zone_of(a: str) -> str:
        return (kg.node(a) or {}).get("props_json", {}).get("zone") or "it"

    def render(edges: list[tuple[str, str, str]], highlight: bool) -> str:
        lines = ["flowchart LR"]
        zones: dict[str, set[str]] = {}
        for f, t, _ in edges:
            zones.setdefault(zone_of(f), set()).add(f)
            zones.setdefault(zone_of(t), set()).add(t)
        for z, members in sorted(zones.items()):
            lines.append(f"  subgraph {z.upper()}[{z.upper()} zone]")
            for m in sorted(members):
                lines.append(f'    {_id(m)}["{_label(kg.node(m)["name"], 26)}"]')
            lines.append("  end")
        link_idx = 0
        red = []
        for f, t, kind in edges:
            arrow = "==>" if kind == "db_link" else ("-.->" if kind == "undeclared" else "-->")
            lines.append(f"  {_id(f)} {arrow}|{kind}| {_id(t)}")
            if highlight and (f, t) in boundary_pairs:
                red.append(link_idx)
            link_idx += 1
        for i in red:
            lines.append(f"  linkStyle {i} stroke:#d1242f,stroke-width:3px")
        return "\n".join(lines)

    intended, actual = [], []
    apps = set(app_ids)
    for a in sorted(apps):
        for e in kg.out_edges(a, "DEPENDS_ON"):
            if e["props_json"].get("declared"):
                intended.append((a, e["to_id"], "declared"))
            if e["props_json"].get("actual") and not e["props_json"].get("declared"):
                actual.append((a, e["to_id"], "undeclared"))
            elif e["props_json"].get("actual"):
                actual.append((a, e["to_id"], "declared"))
        for e in kg.out_edges(a, "INTEGRATES_WITH"):
            if e["props_json"].get("pattern") == "db_link":
                actual = [x for x in actual if not (x[0] == a and x[1] == e["to_id"])]
                actual.append((a, e["to_id"], "db_link"))
            elif e["props_json"].get("approved"):
                intended.append((a, e["to_id"], e["props_json"].get("pattern")))
    return {"intended": render(intended[:40], False), "actual": render(actual[:40], True)}
