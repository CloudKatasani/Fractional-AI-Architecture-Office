"""Knowledge graph browsing, impact, lineage, diagrams."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.session import Repo
from app.kg import export
from app.kg.queries import get_kg
from app.routers.deps import tenant_dep

router = APIRouter(prefix="/kg")


@router.get("/nodes")
def nodes(tenant: str = Depends(tenant_dep), type: str | None = None, q: str | None = None, limit: int = Query(300, le=3000)) -> list[dict]:
    return get_kg(tenant).search(q, type, limit)


@router.get("/stats")
def stats(tenant: str = Depends(tenant_dep)) -> dict:
    kg = get_kg(tenant)
    nt: dict[str, int] = {}
    for n in kg.nodes.values():
        nt[n["type"]] = nt.get(n["type"], 0) + 1
    et: dict[str, int] = {}
    for e in kg.edges.values():
        et[e["type"]] = et.get(e["type"], 0) + 1
    return {"node_types": nt, "edge_types": et, "nodes": len(kg.nodes), "edges": len(kg.edges),
            "drafts": sum(1 for e in kg.edges.values() if e["status"] == "draft") + sum(1 for n in kg.nodes.values() if n["status"] == "draft"),
            "low_confidence": sum(1 for n in kg.nodes.values() if n["confidence"] < 0.7)}


@router.get("/graph")
def graph(tenant: str = Depends(tenant_dep), types: str = "Application,Capability,Dataset,AIUseCase,Goal", limit: int = 600,
          focus: str | None = None, depth: int = 1) -> dict:
    """Subgraph for the force-directed explorer."""
    kg = get_kg(tenant)
    if focus:
        sub = kg.neighbors(focus, depth=min(depth, 2), max_nodes=limit)
        ns, es = sub["nodes"], sub["edges"]
    else:
        tset = set(types.split(","))
        ns = [n for n in kg.nodes.values() if n["type"] in tset][:limit]
        ids = {n["id"] for n in ns}
        es = [e for e in kg.edges.values() if e["from_id"] in ids and e["to_id"] in ids]
    return {"nodes": [{"id": n["id"], "name": n["name"], "type": n["type"], "confidence": n["confidence"], "status": n["status"]} for n in ns],
            "links": [{"id": e["id"], "source": e["from_id"], "target": e["to_id"], "type": e["type"], "status": e["status"]} for e in es]}


@router.get("/nodes/{node_id}")
def node(node_id: str, tenant: str = Depends(tenant_dep)) -> dict:
    kg = get_kg(tenant)
    n = kg.node(node_id)
    if not n:
        raise HTTPException(404, "node not found")
    out_e = kg.out_edges(node_id)
    in_e = kg.in_edges(node_id)

    def brief(e: dict, other: str) -> dict:
        o = kg.node(other)
        return {**e, "other": {"id": other, "name": o["name"] if o else other, "type": o["type"] if o else None}}

    return {**n, "out_edges": [brief(e, e["to_id"]) for e in out_e[:200]], "in_edges": [brief(e, e["from_id"]) for e in in_e[:200]]}


@router.get("/nodes/{node_id}/neighbors")
def neighbors(node_id: str, tenant: str = Depends(tenant_dep), depth: int = Query(1, le=3)) -> dict:
    return get_kg(tenant).neighbors(node_id, depth)


@router.get("/impact")
def impact(node_id: str, tenant: str = Depends(tenant_dep), depth: int = Query(3, le=4)) -> dict:
    kg = get_kg(tenant)
    if not kg.node(node_id):
        raise HTTPException(404, "node not found")
    return {"node_id": node_id, "affected": kg.impact(node_id, depth)}


@router.get("/lineage")
def lineage(dataset_id: str, tenant: str = Depends(tenant_dep), direction: str = "both") -> dict:
    kg = get_kg(tenant)
    if not kg.node(dataset_id):
        raise HTTPException(404, "dataset not found")
    out: dict = {"dataset_id": dataset_id}
    if direction in ("both", "upstream"):
        out["upstream"] = kg.lineage_upstream(dataset_id)
    if direction in ("both", "downstream"):
        out["downstream"] = kg.lineage_downstream(dataset_id)
    out["mermaid"] = export.data_flow(kg, dataset_id)
    names = {}
    for part in ("upstream", "downstream"):
        for k, v in out.get(part, {}).items():
            if isinstance(v, list) and k != "edges":
                for i in v:
                    if isinstance(i, str) and kg.node(i):
                        names[i] = {"name": kg.node(i)["name"], "type": kg.node(i)["type"]}
    out["names"] = names
    return out


@router.get("/violations")
def violations(tenant: str = Depends(tenant_dep)) -> list[dict]:
    return get_kg(tenant).violations()


@router.get("/orphans")
def orphans(tenant: str = Depends(tenant_dep)) -> dict:
    return get_kg(tenant).orphans()


@router.get("/diagram")
def diagram(kind: str, tenant: str = Depends(tenant_dep), id: str | None = None) -> dict:
    kg = get_kg(tenant)
    if kind == "capability_map":
        text = export.capability_map(kg, Repo(tenant).all("tenants")[0]["name"])
    elif kind == "c4_context":
        text = export.c4_context(kg, id or "")
    elif kind == "data_flow":
        text = export.data_flow(kg, id or "")
    elif kind == "integration_map":
        text = export.integration_map(kg, id or "")
    else:
        raise HTTPException(400, "kind must be capability_map | c4_context | data_flow | integration_map")
    return {"kind": kind, "id": id, "mermaid": text}
