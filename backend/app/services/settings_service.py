"""Per-tenant agent settings: autonomy level (L1-L4), enabled flag, acceptance rate."""

from __future__ import annotations

from app.db.session import Repo


def _row(tenant_id: str, agent_id: str) -> dict | None:
    for r in Repo(tenant_id).all("agent_settings"):
        if r["agent_id"] == agent_id:
            return r
    return None


def autonomy_for(tenant_id: str, agent_id: str) -> int:
    row = _row(tenant_id, agent_id)
    if row:
        # L4 is display-only in the prototype: behaves as L3 (Section 8.4)
        return min(3, int(row["autonomy_level"]))
    from app.agents.registry import get_agent

    return get_agent(agent_id).default_autonomy


def touch_last_run(tenant_id: str, agent_id: str, ts: str) -> None:
    repo = Repo(tenant_id)
    if _row(tenant_id, agent_id):
        repo.update_where("agent_settings", {"tenant_id": tenant_id, "agent_id": agent_id}, {"last_run_at": ts})


def recompute_acceptance(tenant_id: str, agent_id: str) -> float | None:
    """acceptance = (seeded accepted + approved) / (seeded decided + decided) over the trailing window."""
    repo = Repo(tenant_id)
    row = _row(tenant_id, agent_id)
    if not row:
        return None
    decided = [a for a in repo.all("approvals") if a["agent_id"] == agent_id and a["status"] in ("approved", "edited", "rejected")]
    acc = sum(1 for a in decided if a["status"] in ("approved", "edited"))
    num = (row["seed_accepted"] or 0) + acc
    den = (row["seed_decided"] or 0) + len(decided)
    rate = round(num / den, 3) if den else None
    repo.update_where("agent_settings", {"tenant_id": tenant_id, "agent_id": agent_id}, {"acceptance_rate_30d": rate})
    return rate
