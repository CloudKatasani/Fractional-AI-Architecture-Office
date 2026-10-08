"""Deterministic analysis helpers shared by several agents (the "tool layer")."""

from __future__ import annotations

import math
import re
from datetime import date, timedelta

from app.agents.base import AgentContext, ev

SEVERITY_WEIGHT = {1: 8, 2: 4, 3: 2, 4: 1}
INCIDENT_COST_PER_MIN = {1: 900, 2: 250, 3: 60, 4: 15}  # USD per minute of disruption (synthetic)


def l2_of(ctx: AgentContext, cap_id: str) -> dict:
    caps = ctx.repo.by_id("capabilities")
    c = caps[cap_id]
    while c["level"] > 2:
        c = caps[c["parent_id"]]
    return c


def l1_of(ctx: AgentContext, cap_id: str) -> dict:
    caps = ctx.repo.by_id("capabilities")
    c = caps[cap_id]
    while c["parent_id"]:
        c = caps[c["parent_id"]]
    return c


def contract_index(ctx: AgentContext) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for c in ctx.repo.all("contracts"):
        for a in c["app_ids"]:
            idx.setdefault(a, []).append(c)
    return idx


def tco(ctx: AgentContext, app: dict, contracts: dict[str, list[dict]] | None = None,
        cloud_by_app: dict[str, float] | None = None) -> dict:
    """TCO = contract share + tagged cloud + 15% support overhead (in-house: internal run cost instead of contract)."""
    contracts = contracts if contracts is not None else contract_index(ctx)
    share = sum(c["annual_value_usd"] / max(1, len(c["app_ids"])) for c in contracts.get(app["id"], []))
    if cloud_by_app is None:
        cloud_by_app = cloud_cost_by_app(ctx)
    cloud = cloud_by_app.get(app["id"], 0.0)
    if app["vendor"] == "In-house":
        base = app["annual_cost_usd"] / 1.15 - cloud
        share = max(0.0, base)
    overhead = 0.15 * (share + cloud)
    return {"contract_share": round(share, 2), "cloud": round(cloud, 2), "overhead": round(overhead, 2),
            "total": round(share + cloud + overhead, 2)}


def cloud_cost_by_app(ctx: AgentContext) -> dict[str, float]:
    kg = ctx.kg
    out: dict[str, float] = {}
    for e in kg.edges_of_type("RUNS_ON"):
        n = kg.node(e["to_id"])
        out[e["from_id"]] = out.get(e["from_id"], 0.0) + n["props_json"]["monthly_cost_usd"] * 12
    return out


def debt_scores(ctx: AgentContext) -> dict[str, dict]:
    """Tech Debt Radar scoring per app with repos: EOL framework (30) + framework age (0-20) +
    critical vulns (0-25) + severity-weighted incidents in the last 90 days (0-25)."""
    repos_by_app: dict[str, list[dict]] = {}
    for r in ctx.repo.all("repos"):
        repos_by_app.setdefault(r["app_id"], []).append(r)
    cutoff = (ctx.today - timedelta(days=90)).isoformat()
    inc_by_app: dict[str, list[dict]] = {}
    for i in ctx.repo.all("incidents"):
        if i["date"] >= cutoff:
            inc_by_app.setdefault(i["app_id"], []).append(i)
    out = {}
    for app_id, repos in repos_by_app.items():
        eol = any(r["eol"] for r in repos)
        oldest = min(r["framework_release_year"] or ctx.today.year for r in repos)
        age_pts = min(20, max(0, (ctx.today.year - oldest - 2) * 2))
        vulns = sum(r["open_critical_vulns"] for r in repos)
        vuln_pts = min(25, vulns * 2.5)
        incs = inc_by_app.get(app_id, [])
        inc_pts = min(25, sum(SEVERITY_WEIGHT[i["severity"]] for i in incs))
        score = (30 if eol else 0) + age_pts + vuln_pts + inc_pts
        drivers = []
        refs = []
        if eol:
            r = next(r for r in repos if r["eol"])
            drivers.append(f"EOL framework {r['framework']} {r['framework_version']}".strip())
            refs.append(ev(r["id"], "repos", f"{r['language']} / {r['framework']} {r['framework_version']} (eol)"))
        if age_pts:
            drivers.append(f"framework released {oldest}")
        if vulns:
            drivers.append(f"{vulns} open critical vulnerabilities")
            refs.append(ev(max(repos, key=lambda r: r["open_critical_vulns"])["id"], "repos", f"{vulns} critical vulns"))
        if incs:
            drivers.append(f"{len(incs)} incidents in 90 days")
            for i in sorted(incs, key=lambda i: i["severity"])[:3]:
                refs.append(ev(i["id"], "incidents", f"sev{i['severity']} {i['root_cause_category']} on {i['date']}"))
        if not refs:
            refs.append(ev(repos[0]["id"], "repos", f"{repos[0]['framework']} {repos[0]['framework_version']}"))
        loc = sum(r["loc_k"] for r in repos)
        band = "S" if loc < 60 and len(repos) == 1 else ("M" if loc < 250 else "L")
        cost = sum(i["minutes_to_resolve"] * INCIDENT_COST_PER_MIN[i["severity"]] for i in incs)
        out[app_id] = {"score": round(score, 1), "drivers": drivers, "effort_band": band, "incident_cost_est": cost,
                       "refs": refs, "eol": eol, "repo_ids": [r["id"] for r in repos]}
    return out


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a or []), set(b or [])
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def overlap_clusters(ctx: AgentContext, threshold: float = 0.3) -> list[dict]:
    """Cluster apps realizing the same L2 capability (or same category) with overlapping feature tags."""
    apps = [a for a in ctx.repo.all("applications") if a["lifecycle_status"] != "retired"]
    l2_by_app = {a["id"]: {l2_of(ctx, c)["id"] for c in a["capability_ids"]} for a in apps}
    parent = {a["id"]: a["id"] for a in apps}
    pair_sim: dict[tuple[str, str], float] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(apps):
        for b in apps[i + 1:]:
            if not (l2_by_app[a["id"]] & l2_by_app[b["id"]] or a["category"] == b["category"]):
                continue
            sim = jaccard(a["features"], b["features"])
            if sim >= threshold:
                pair_sim[(a["id"], b["id"])] = sim
                parent[find(a["id"])] = find(b["id"])
    groups: dict[str, list[dict]] = {}
    for a in apps:
        groups.setdefault(find(a["id"]), []).append(a)
    debt = debt_scores(ctx)
    caps = ctx.repo.by_id("capabilities")
    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda a: a["id"])
        max_users = max(m["user_count_90d"] for m in members) or 1
        max_cost = max(m["annual_cost_usd"] for m in members) or 1
        scored = []
        for m in members:
            usage = math.log1p(m["user_count_90d"]) / math.log1p(max_users)
            cost = 1 - m["annual_cost_usd"] / max_cost
            d = 1 - (debt.get(m["id"], {}).get("score", 20) / 100)
            fit = 0.5 if m["lifecycle_status"] == "sunset" else 1.0
            breadth = len(m["features"]) / max(len(x["features"]) for x in members)
            sor = (4 - m["criticality"]) / 3  # systems of record are preferred survivors
            s = 0.3 * usage + 0.1 * cost + 0.15 * d + 0.1 * fit + 0.15 * breadth + 0.2 * sor
            scored.append((round(s, 3), m))
        scored.sort(key=lambda t: (-t[0], t[1]["id"]))
        survivor = scored[0][1]
        retire = [m for _, m in scored[1:]]
        savings = round(sum(m["annual_cost_usd"] for m in retire) * 0.7, -2)
        cap_counts: dict[str, int] = {}
        for m in members:
            for c in l2_by_app[m["id"]]:
                cap_counts[c] = cap_counts.get(c, 0) + 1
        cap_id = max(cap_counts, key=lambda c: (cap_counts[c], c))
        sims = [v for (x, y), v in pair_sim.items() if x in {m["id"] for m in members}]
        clusters.append({
            "cluster_id": "OVL-" + survivor["id"].split("-")[1], "capability_id": cap_id,
            "capability_name": caps[cap_id]["name"], "app_ids": [m["id"] for m in members],
            "app_names": [m["name"] for m in members], "survivor_app_id": survivor["id"], "survivor_name": survivor["name"],
            "scores": {m["id"]: s for s, m in scored}, "similarity": round(sum(sims) / len(sims), 2) if sims else threshold,
            "est_savings_usd": savings, "retire_app_ids": [m["id"] for m in retire],
            "category": survivor["category"],
        })
    clusters.sort(key=lambda c: -c["est_savings_usd"])
    return clusters


# ---- design review rule engine --------------------------------------------------------------

def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _excerpt(text: str, match: re.Match) -> str:
    for s in _sentences(text):
        if match.group(0).lower() in s.lower():
            return s[:220]
    return match.group(0)


def design_concerns(ctx: AgentContext, doc: dict) -> list[dict]:
    text = doc["body_md"]
    low = text.lower()
    approved = set(ctx.common["approved_genai_platforms"])
    known = ctx.common["genai_vendors_known"]
    concerns = []
    for std in ctx.repo.all("standards"):
        for chk in std["checks"] or []:
            t = chk["type"]
            hit_excerpt = None
            if t == "pattern_any":
                for pat in chk["patterns"]:
                    m = re.search(pat, low)
                    if m:
                        hit_excerpt = _excerpt(text, m)
                        break
            elif t == "missing_all":
                if not any(re.search(p, low) for p in chk["patterns"]):
                    hit_excerpt = "No data classification stated for the data flows in this design."
            elif t == "unapproved_vendor":
                for v in known:
                    if v.lower() in low and v not in approved:
                        m = re.search(re.escape(v.lower()), low)
                        hit_excerpt = _excerpt(text, m)
                        break
            elif t == "sync_chain":
                if "synchronous" in low or "blocking" in low:
                    for line in text.splitlines():
                        hops = line.count("->")
                        if hops > chk.get("max_hops", 3):
                            hit_excerpt = line.strip()[:220] + f" ({hops} synchronous hops)"
                            break
            if hit_excerpt:
                concerns.append({
                    "standard_id": std["id"], "standard_title": std["title"], "severity": std["severity"],
                    "excerpt": hit_excerpt, "recommendation": std["rule_text"],
                })
                break
    return concerns


def reuse_apis(ctx: AgentContext, text: str, limit: int = 3) -> list[dict]:
    low = text.lower()
    keywords = {
        "customer": ["customer", "account"], "usage": ["usage", "interval", "consumption"], "outage": ["outage", "restoration"],
        "bill": ["bill", "invoice"], "product": ["offer", "catalog", "product"], "balance": ["balance"],
        "asset": ["asset", "work order"], "network_model": ["network model", "gis"], "order": ["order"],
        "payment": ["payment", "card"], "service_inventory": ["service status", "service instance", "inventory"],
        "ticket": ["ticket", "trouble"],
    }
    hits = [res for res, words in keywords.items() if any(w in low for w in words)]
    apis = [a for a in ctx.repo.all("apis") if a["resource"] in hits and a["via_gateway"] and a["auth"] in ("oauth2", "mtls")]
    apis.sort(key=lambda a: (-len(a["consumers"] or []), a["id"]))
    return apis[:limit]


def quarter_labels(today: date, n: int = 6) -> list[str]:
    q = (today.month - 1) // 3 + 1
    y = today.year
    out = []
    for _ in range(n):
        q += 1
        if q > 4:
            q, y = 1, y + 1
        out.append(f"Q{q} {y}")
    return out
