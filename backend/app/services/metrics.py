"""Dashboard KPIs (Section 10.1). Every number carries the record / approval ids it was computed from."""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from app.config import demo_today
from app.db.session import Repo
from app.kg.queries import get_kg

SAVINGS_ACTIONS = {"renegotiate_contract", "cancel_renewal", "propose_consolidation", "approve_business_case", "tag_resources"}
REALIZABLE = {"renegotiate_contract", "cancel_renewal"}


def latest_output(repo: Repo, agent_id: str) -> dict | None:
    runs = [r for r in repo.all("agent_runs") if r["agent_id"] == agent_id and r["status"] == "completed"]
    return max(runs, key=lambda r: r["started_at"])["output_json"] if runs else None


def savings(repo: Repo) -> dict:
    identified, id_refs = 0.0, []
    for agent in ("pf.cost_license_optimizer", "pf.overlap_finder"):
        out = latest_output(repo, agent)
        if out:
            for f in out["findings"]:
                identified += f.get("est_savings_usd", 0) or 0
            id_refs.append(out["run_id"])
    approved_by_key: dict[str, tuple[float, str, dict]] = {}
    realized, real_refs = 0.0, []
    today = demo_today()
    for a in repo.all("approvals"):
        if a["status"] not in ("approved", "edited") or a["action_type"] not in SAVINGS_ACTIONS:
            continue
        p = a["edited_payload_json"] or a["payload_json"] or {}
        amt = p.get("annual_savings_usd") or p.get("est_savings_usd") or 0
        key = p.get("cluster_id") or a["target_id"]
        if key not in approved_by_key or amt > approved_by_key[key][0]:
            approved_by_key[key] = (amt, a["id"], a)
    approved = sum(v[0] for v in approved_by_key.values())
    for amt, aid, a in approved_by_key.values():
        p = a["edited_payload_json"] or a["payload_json"] or {}
        decided = date.fromisoformat(a["decided_at"][:10]) if a["decided_at"] else today
        if p.get("realized_usd") is not None:
            realized += p["realized_usd"]
            real_refs.append(aid)
        elif a["action_type"] in REALIZABLE and (today - decided).days >= 30:
            realized += amt
            real_refs.append(aid)
    return {"identified": round(identified, -2), "approved": round(approved, -2), "realized": round(realized, -2),
            "source_refs": {"identified": id_refs, "approved": [v[1] for v in approved_by_key.values()], "realized": real_refs}}


def dashboard(tenant_id: str) -> dict:
    repo = Repo(tenant_id)
    kg = get_kg(tenant_id)
    today = demo_today()
    apps = [n for n in kg.by_type("Application") if n["status"] != "retired"]
    confirmed = [n for n in apps if n["props_json"].get("owner_confirmed")]
    inv = {"value": round(100 * len(confirmed) / max(1, len(apps)), 1), "confirmed": len(confirmed), "total": len(apps),
           "source_refs": [n["id"] for n in confirmed[:20]]}

    tiers = {t: {"approved": 0, "proposed": 0} for t in ("unacceptable", "high", "limited", "minimal")}
    tier_refs: dict[str, list[str]] = {t: [] for t in tiers}
    for u in kg.by_type("AIUseCase"):
        if u["props_json"].get("risk_tier"):
            tiers[u["props_json"]["risk_tier"]]["approved"] += 1
            tier_refs[u["props_json"]["risk_tier"]].append(u["id"])
        elif u["props_json"].get("proposed_risk_tier"):
            tiers[u["props_json"]["proposed_risk_tier"]]["proposed"] += 1
            tier_refs[u["props_json"]["proposed_risk_tier"]].append(u["id"])

    hours = []
    reviewed = []
    for d in repo.all("design_docs"):
        if d["reviewed_at"]:
            h = (datetime.fromisoformat(d["reviewed_at"]) - datetime.fromisoformat(d["submitted_at"])).total_seconds() / 3600
            hours.append(max(0.0, h))
            reviewed.append(d["id"])
    turnaround = {"median_hours": round(statistics.median(hours), 1) if hours else None, "reviewed": len(hours),
                  "pending": sum(1 for d in repo.all("design_docs") if d["status"] == "submitted"), "source_refs": reviewed}

    pol = latest_output(repo, "dai.governance_policy_checker")
    fixed = {a["target_id"] for a in repo.all("approvals") if a["agent_id"] == "dai.governance_policy_checker"
             and a["status"] in ("approved", "edited")}
    pol_open = [f for f in (pol["findings"] if pol else []) if f["subject_id"] not in fixed]
    kg_viol = [v for v in kg.violations() if v["status"] != "retired"]
    violations = {"value": len(pol_open) + len(kg_viol), "policy": len(pol_open), "standards": len(kg_viol),
                  "source_refs": [f["subject_id"] for f in pol_open[:10]] + [v["subject_id"] for v in kg_viol[:10]]}

    debt = latest_output(repo, "app.tech_debt_radar")
    avg = round(sum(f["score"] for f in debt["findings"]) / max(1, len(debt["findings"])), 1) if debt else None
    trend = []
    if avg is not None:
        factors = [1.12, 1.10, 1.08, 1.05, 1.03, 1.0]  # synthetic history (Section 10.2: "6 months synthetic")
        for i, f in enumerate(factors):
            m = (today.replace(day=1) - timedelta(days=30 * (5 - i))).strftime("%Y-%m")
            trend.append({"month": m, "score": round(avg * f, 1)})

    upcoming = []
    for a in repo.all("applications"):
        if a["vendor_eos_date"]:
            d = (date.fromisoformat(a["vendor_eos_date"]) - today).days
            if 0 <= d <= 180:
                upcoming.append({"type": "vendor_eos", "id": a["id"], "name": a["name"], "date": a["vendor_eos_date"], "days": d})
    apps_by_id = repo.by_id("applications")
    for c in repo.all("contracts"):
        d = (date.fromisoformat(c["renewal_date"]) - today).days
        if 0 <= d <= 180 and c["app_ids"]:
            upcoming.append({"type": "renewal", "id": c["id"], "name": apps_by_id[c["app_ids"][0]]["name"], "date": c["renewal_date"],
                             "days": d, "auto_renew": c["auto_renew"], "annual_value_usd": c["annual_value_usd"]})
    upcoming.sort(key=lambda x: x["days"])

    st = repo.all("agent_settings")
    num = sum((s["acceptance_rate_30d"] or 0) * max(1, s["seed_decided"] or 0) for s in st if s["acceptance_rate_30d"] is not None)
    den = sum(max(1, s["seed_decided"] or 0) for s in st if s["acceptance_rate_30d"] is not None)
    decided = [a for a in repo.all("approvals") if a["status"] != "pending"]
    acceptance = {"value": round(100 * num / den, 1) if den else None, "decided": len(decided),
                  "source_refs": [a["id"] for a in decided[-10:]]}

    pending = [a for a in repo.all("approvals") if a["status"] == "pending"]
    pending.sort(key=lambda a: (a["priority"] or 3, -((a["payload_json"] or {}).get("est_savings_usd") or 0), a["created_at"] or ""))
    decisions = [{"id": a["id"], "action_type": a["action_type"], "target_id": a["target_id"], "approver_role": a["approver_role"],
                  "rationale": a["rationale"], "priority": a["priority"], "agent_id": a["agent_id"]} for a in pending[:5]]
    return {
        "tenant_id": tenant_id, "as_of": today.isoformat(), "inventory_accuracy": inv, "savings": savings(repo),
        "ai_tiers": tiers, "ai_tier_refs": tier_refs, "design_review": turnaround, "violations": violations,
        "debt_trend": {"current": avg, "points": trend, "source_refs": [debt["run_id"]] if debt else []},
        "upcoming": {"count": len(upcoming), "items": upcoming[:12]}, "acceptance": acceptance,
        "decisions_needed": decisions, "pending_approvals": len(pending),
        "counts": {"applications": len(apps), "datasets": repo.count("datasets"), "ai_usecases": repo.count("ai_usecases"),
                   "integrations": repo.count("integrations"), "apis": repo.count("apis")},
    }
