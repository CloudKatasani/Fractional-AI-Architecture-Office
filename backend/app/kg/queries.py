"""Knowledge graph queries over an in-memory NetworkX view of kg_nodes / kg_edges (cached per tenant version)."""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime

import networkx as nx
from sqlalchemy import delete, insert, select, update

from app.db import models
from app.db.session import Repo, bump_version, get_engine, version

_cache: dict[str, tuple[int, KG]] = {}
_lock = threading.Lock()

# Edge types followed by impact analysis, with the direction that propagates impact.
# "out": impact flows from edge source to target when the *target* changes? We define impact as
# "things that would be affected if node X changed/disappeared", i.e. dependents of X.
IMPACT_EDGES = {
    # edge_type: which endpoint is the dependent when the other endpoint is impacted
    "REALIZES": "to",            # app change affects the capability it realises
    "DEPENDS_ON": "from",        # app depends on app: if target changes, source is affected
    "INTEGRATES_WITH": "both",
    "CONSUMES": "from",          # app consumes api
    "EXPOSES": "to",             # app exposes api: api affected if app changes
    "STORED_IN": "from",         # dataset stored in app
    "CONSUMES_DATA": "from",     # pipeline/bi/ai consumes dataset
    "PRODUCES": "to",            # pipeline produces dataset
    "USES_DATA": "from",         # use case uses dataset
    "IMPLEMENTS": "both",        # ai asset implements use case
    "OWNS": "from",              # owner affected
    "SOLD_BY": "from",           # vendor -> apps
    "LICENSED_UNDER": "both",
    "CHANGES": "from",           # project changes app
    "FUNDS": "from",
    "RUNS_ON": "from",
    "GOVERNED_BY": "from",
}


class KG:
    def __init__(self, tenant_id: str, nodes: list[dict], edges: list[dict]):
        self.tenant_id = tenant_id
        self.g = nx.MultiDiGraph()
        self.nodes: dict[str, dict] = {}
        for n in nodes:
            self.nodes[n["id"]] = n
            self.g.add_node(n["id"])
        self.edges: dict[str, dict] = {}
        for e in edges:
            if e["status"] == "retired":
                continue
            self.edges[e["id"]] = e
            self.g.add_edge(e["from_id"], e["to_id"], key=e["id"], type=e["type"])

    # ---- basic ---------------------------------------------------------------------------
    def node(self, id_: str) -> dict | None:
        return self.nodes.get(id_)

    def by_type(self, type_: str) -> list[dict]:
        return [n for n in self.nodes.values() if n["type"] == type_]

    def out_edges(self, id_: str, type_: str | None = None) -> list[dict]:
        if id_ not in self.g:
            return []
        res = [self.edges[k] for _, _, k in self.g.out_edges(id_, keys=True)]
        return [e for e in res if type_ is None or e["type"] == type_]

    def in_edges(self, id_: str, type_: str | None = None) -> list[dict]:
        if id_ not in self.g:
            return []
        res = [self.edges[k] for _, _, k in self.g.in_edges(id_, keys=True)]
        return [e for e in res if type_ is None or e["type"] == type_]

    def edges_of_type(self, type_: str) -> list[dict]:
        return [e for e in self.edges.values() if e["type"] == type_]

    def search(self, q: str | None = None, type_: str | None = None, limit: int = 200) -> list[dict]:
        ql = (q or "").lower()
        out = []
        for n in self.nodes.values():
            if type_ and n["type"] != type_:
                continue
            if ql and ql not in n["name"].lower() and ql not in n["id"].lower():
                continue
            out.append(n)
            if len(out) >= limit:
                break
        return out

    def neighbors(self, id_: str, depth: int = 1, edge_types: set[str] | None = None, max_nodes: int = 400) -> dict:
        seen = {id_}
        frontier = [id_]
        used_edges: dict[str, dict] = {}
        for _ in range(depth):
            nxt = []
            for nid in frontier:
                for e in self.out_edges(nid) + self.in_edges(nid):
                    if edge_types and e["type"] not in edge_types:
                        continue
                    used_edges[e["id"]] = e
                    other = e["to_id"] if e["from_id"] == nid else e["from_id"]
                    if other not in seen and len(seen) < max_nodes:
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
        nodes = [self.nodes[n] for n in seen if n in self.nodes]
        edges = [e for e in used_edges.values() if e["from_id"] in seen and e["to_id"] in seen]
        return {"nodes": nodes, "edges": edges}

    # ---- lineage ---------------------------------------------------------------------------
    def lineage_upstream(self, dataset_id: str, max_depth: int = 8) -> dict:
        datasets, pipelines, systems = [], [], []
        seen = {dataset_id}
        q = deque([(dataset_id, 0)])
        edges = []
        while q:
            ds, d = q.popleft()
            for st in self.out_edges(ds, "STORED_IN"):
                systems.append(st["to_id"])
                edges.append(st)
            if d >= max_depth:
                continue
            for pe in self.in_edges(ds, "PRODUCES"):
                pl = pe["from_id"]
                edges.append(pe)
                if pl not in pipelines:
                    pipelines.append(pl)
                for ce in self.out_edges(pl, "CONSUMES_DATA"):
                    edges.append(ce)
                    src = ce["to_id"]
                    if src not in seen:
                        seen.add(src)
                        datasets.append(src)
                        q.append((src, d + 1))
        return {"root_id": dataset_id, "datasets": datasets, "pipelines": pipelines,
                "systems": sorted(set(systems)), "edges": _dedupe(edges)}

    def lineage_downstream(self, dataset_id: str, max_depth: int = 8) -> dict:
        datasets, pipelines, bi, ai = [], [], [], []
        seen = {dataset_id}
        q = deque([(dataset_id, 0)])
        edges = []
        while q:
            ds, d = q.popleft()
            for ce in self.in_edges(ds, "CONSUMES_DATA"):
                consumer = ce["from_id"]
                edges.append(ce)
                ctype = self.nodes[consumer]["type"]
                if ctype == "BIAsset":
                    if consumer not in bi:
                        bi.append(consumer)
                elif ctype == "AIAsset":
                    if consumer not in ai:
                        ai.append(consumer)
                elif ctype == "Pipeline" and d < max_depth:
                    if consumer not in pipelines:
                        pipelines.append(consumer)
                    for pe in self.out_edges(consumer, "PRODUCES"):
                        edges.append(pe)
                        out = pe["to_id"]
                        if out not in seen:
                            seen.add(out)
                            datasets.append(out)
                            q.append((out, d + 1))
            for ue in self.in_edges(ds, "USES_DATA"):
                edges.append(ue)
                if ue["from_id"] not in ai:
                    ai.append(ue["from_id"])
        return {"root_id": dataset_id, "datasets": datasets, "pipelines": pipelines, "bi_assets": bi, "ai": ai,
                "edges": _dedupe(edges)}

    # ---- impact ----------------------------------------------------------------------------
    def impact(self, node_id: str, depth: int = 3) -> dict:
        """Dependents of node_id up to `depth` hops, grouped by node type, with the hop distance."""
        dist = {node_id: 0}
        via: dict[str, str] = {}
        q = deque([node_id])
        while q:
            cur = q.popleft()
            if dist[cur] >= depth:
                continue
            cands = []
            for e in self.out_edges(cur) + self.in_edges(cur):
                rule = IMPACT_EDGES.get(e["type"])
                if not rule:
                    continue
                # dependent endpoint
                if e["from_id"] == cur:
                    other = e["to_id"]
                    ok = rule in ("both", "to")
                else:
                    other = e["from_id"]
                    ok = rule in ("both", "from")
                if ok:
                    cands.append((other, e))
            for other, e in cands:
                if other not in dist:
                    # avoid fanning out through hub-like nodes (persons, regulations, vendors) beyond the first hop
                    dist[other] = dist[cur] + 1
                    via[other] = e["id"]
                    otype = self.nodes[other]["type"]
                    terminal = e["type"] in ("INTEGRATES_WITH", "CONSUMES", "REALIZES")
                    if otype not in ("Person", "Regulation", "Vendor", "Team", "Contract", "CloudResource", "Capability") \
                            and not terminal:
                        q.append(other)
        grouped: dict[str, list[dict]] = {}
        for nid, d in dist.items():
            if nid == node_id:
                continue
            n = self.nodes[nid]
            grouped.setdefault(n["type"], []).append({"id": nid, "name": n["name"], "depth": d, "via_edge": via.get(nid)})
        for v in grouped.values():
            v.sort(key=lambda x: (x["depth"], x["name"]))
        return grouped

    def path(self, a: str, b: str) -> list[str]:
        try:
            return nx.shortest_path(self.g.to_undirected(as_view=True), a, b)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def subgraph_for_capability(self, cap_id: str) -> dict:
        caps = {cap_id}
        frontier = [cap_id]
        while frontier:
            nxt = []
            for c in frontier:
                for e in self.in_edges(c, "PART_OF"):
                    if e["from_id"] not in caps:
                        caps.add(e["from_id"])
                        nxt.append(e["from_id"])
            frontier = nxt
        apps = {e["from_id"] for c in caps for e in self.in_edges(c, "REALIZES")}
        integ = [e for a in apps for e in self.out_edges(a, "INTEGRATES_WITH")]
        return {"capabilities": sorted(caps), "applications": sorted(apps), "integrations": _dedupe(integ)}

    def orphans(self) -> dict:
        res = {
            "applications_without_capability": [a["id"] for a in self.by_type("Application") if not self.out_edges(a["id"], "REALIZES")],
            "cloud_resources_without_app": [c["id"] for c in self.by_type("CloudResource") if not self.in_edges(c["id"], "RUNS_ON")],
            "datasets_without_owner": [d["id"] for d in self.by_type("Dataset") if not self.in_edges(d["id"], "OWNS")],
            "projects_without_goal": [p["id"] for p in self.by_type("Project") if not self.out_edges(p["id"], "TARGETS")],
            "goals_without_project": [g["id"] for g in self.by_type("Goal") if not self.in_edges(g["id"], "TARGETS")],
            "apis_without_consumers": [a["id"] for a in self.by_type("API") if not self.in_edges(a["id"], "CONSUMES")],
        }
        return res

    def violations(self) -> list[dict]:
        out = []
        for e in self.edges_of_type("VIOLATES"):
            subj = self.nodes.get(e["from_id"])
            out.append({"edge_id": e["id"], "subject_id": e["from_id"], "subject_type": subj["type"] if subj else None,
                        "subject_name": subj["name"] if subj else None, "standard_id": e["to_id"],
                        "rule": e["props_json"].get("rule"), "status": e["status"], "source_refs": e["source_refs_json"]})
        return out

    def apps_for_capability(self, cap_id: str, include_children: bool = True) -> list[str]:
        if include_children:
            return self.subgraph_for_capability(cap_id)["applications"]
        return sorted({e["from_id"] for e in self.in_edges(cap_id, "REALIZES")})


def _dedupe(edges: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in edges:
        if e["id"] not in seen:
            seen.add(e["id"])
            out.append(e)
    return out


def get_kg(tenant_id: str) -> KG:
    v = version(tenant_id)
    with _lock:
        hit = _cache.get(tenant_id)
        if hit and hit[0] == v:
            return hit[1]
    eng = get_engine(tenant_id)
    with eng.connect() as conn:
        nodes = [dict(r._mapping) for r in conn.execute(select(models.kg_nodes).where(models.kg_nodes.c.tenant_id == tenant_id))]
        edges = [dict(r._mapping) for r in conn.execute(select(models.kg_edges).where(models.kg_edges.c.tenant_id == tenant_id))]
    kg = KG(tenant_id, nodes, edges)
    with _lock:
        _cache[tenant_id] = (v, kg)
    return kg


# ---- writes (used by agents for drafts and by the graph curator for approved changes) --------

def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def upsert_node(repo: Repo, id_: str, type_: str, name: str, props: dict, refs: list[str], created_by: str,
                status: str = "draft", confidence: float = 0.8) -> None:
    eng = repo.engine
    t = models.kg_nodes
    with eng.begin() as conn:
        existing = conn.execute(select(t).where(t.c.id == id_)).first()
        if existing:
            cur = dict(existing._mapping)
            merged = {**(cur["props_json"] or {}), **props}
            conn.execute(update(t).where(t.c.id == id_).values(
                props_json=merged, status=status if status != "draft" or cur["status"] == "draft" else cur["status"],
                updated_at=_now(), source_refs_json=sorted(set((cur["source_refs_json"] or []) + refs))))
        else:
            conn.execute(insert(t), [{
                "id": id_, "tenant_id": repo.tenant_id, "type": type_, "name": name, "props_json": props,
                "confidence": confidence, "source_refs_json": refs, "created_by": created_by, "status": status,
                "updated_at": _now(),
            }])
    bump_version(repo.tenant_id)


def update_node_props(repo: Repo, id_: str, props: dict, status: str | None = None) -> bool:
    t = models.kg_nodes
    with repo.engine.begin() as conn:
        row = conn.execute(select(t).where(t.c.id == id_)).first()
        if not row:
            return False
        cur = dict(row._mapping)
        vals = {"props_json": {**(cur["props_json"] or {}), **props}, "updated_at": _now()}
        if status:
            vals["status"] = status
        conn.execute(update(t).where(t.c.id == id_).values(**vals))
    bump_version(repo.tenant_id)
    return True


def add_edge(repo: Repo, type_: str, frm: str, to: str, props: dict, refs: list[str], created_by: str,
             status: str = "draft", confidence: float = 0.8) -> str:
    t = models.kg_edges
    with repo.engine.begin() as conn:
        existing = conn.execute(select(t).where(t.c.type == type_, t.c.from_id == frm, t.c.to_id == to)).first()
        if existing:
            cur = dict(existing._mapping)
            new_status = status if (status != "draft" or cur["status"] == "draft") else cur["status"]
            conn.execute(update(t).where(t.c.id == cur["id"]).values(
                props_json={**(cur["props_json"] or {}), **props}, status=new_status, updated_at=_now()))
            eid = cur["id"]
        else:
            n = conn.execute(select(t.c.id)).fetchall()
            eid = f"E-{len(n) + 1:06d}"
            while conn.execute(select(t.c.id).where(t.c.id == eid)).first():
                eid = f"E-{int(eid[2:]) + 1:06d}"
            conn.execute(insert(t), [{
                "id": eid, "tenant_id": repo.tenant_id, "type": type_, "from_id": frm, "to_id": to, "props_json": props,
                "confidence": confidence, "source_refs_json": refs, "created_by": created_by, "status": status,
                "updated_at": _now(),
            }])
    bump_version(repo.tenant_id)
    return eid


def set_edge_status(repo: Repo, type_: str, frm: str, to: str, status: str) -> None:
    t = models.kg_edges
    with repo.engine.begin() as conn:
        conn.execute(update(t).where(t.c.type == type_, t.c.from_id == frm, t.c.to_id == to).values(status=status, updated_at=_now()))
    bump_version(repo.tenant_id)


def delete_draft_edges(repo: Repo, type_: str, created_by: str) -> None:
    t = models.kg_edges
    with repo.engine.begin() as conn:
        conn.execute(delete(t).where(t.c.type == type_, t.c.created_by == created_by, t.c.status == "draft"))
    bump_version(repo.tenant_id)
