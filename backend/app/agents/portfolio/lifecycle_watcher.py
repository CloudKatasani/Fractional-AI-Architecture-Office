"""pf.lifecycle_watcher — vendor end-of-support, contract renewals and EOL frameworks."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev


class LifecycleAlert(Finding):
    type: str  # vendor_eos | contract_renewal | eol_framework
    app_id: str | None = None
    contract_id: str | None = None
    days_remaining: int | None = None
    severity: str
    recommended_action: str


def _sev(days: int, criticality: int) -> str:
    if days <= 90 or (criticality == 1 and days <= 240):
        return "critical"
    if days <= 180 or criticality <= 2 and days <= 300:
        return "high"
    if days <= 270:
        return "medium"
    return "low"


class LifecycleWatcher(Agent):
    id = "pf.lifecycle_watcher"
    name = "Lifecycle Watcher"
    domain = "portfolio"
    description = ("Watches vendor end-of-support dates (12 months), contract renewals (180 days) and end-of-life "
                   "frameworks; severity by days remaining and business criticality.")
    inputs = ["applications", "contracts", "repos"]
    outputs = "LifecycleAlert"
    finding_model = LifecycleAlert
    approver_role = "principal_architect"
    default_autonomy = 2
    demo_trigger = "Check lifecycle"
    action_types = ["create_renewal_task", "plan_upgrade"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        apps = ctx.repo.by_id("applications")
        findings, actions = [], []
        for a in apps.values():
            days = ctx.days_until(a["vendor_eos_date"])
            if days is not None and 0 <= days <= 365:
                sev = _sev(days, a["criticality"])
                rec = f"Plan upgrade or replacement of {a['name']} before {a['vendor_eos_date']}"
                refs = [ev(a["id"], "applications", f"{a['name']} vendor EOS {a['vendor_eos_date']} (criticality {a['criticality']})")]
                findings.append(LifecycleAlert(type="vendor_eos", app_id=a["id"], days_remaining=days, severity=sev,
                                               recommended_action=rec, source_refs=refs, name=a["name"],
                                               date=a["vendor_eos_date"], criticality=a["criticality"]))
                if sev in ("critical", "high", "medium"):
                    actions.append(ProposedAction(action_type="plan_upgrade", target_id=a["id"], target_type="Application",
                                                  payload={"eos_date": a["vendor_eos_date"], "days_remaining": days, "severity": sev},
                                                  rationale=rec + f" ({days} days left).", source_refs=refs,
                                                  approver_role="principal_architect", priority=1 if sev == "critical" else 2))
        for c in ctx.repo.all("contracts"):
            days = ctx.days_until(c["renewal_date"])
            if not c["app_ids"] or days is None or not 0 <= days <= 180:
                continue
            a = apps[c["app_ids"][0]]
            seats = c["licensed_seats"]
            util = a["user_count_90d"] / seats if seats else None
            sev = _sev(days + (0 if c["auto_renew"] else 60), a["criticality"])
            if util is not None and util < 0.3 and c["auto_renew"]:
                sev = "critical" if days <= 90 else "high"
            rec = ("Decide renew / renegotiate / exit before the notice window" +
                   (f"; only {util:.0%} of seats used" if util is not None and util < 0.5 else ""))
            refs = [ev(c["id"], "contracts", f"{c['vendor']} renews {c['renewal_date']}{' (auto-renew)' if c['auto_renew'] else ''}, "
                                              f"${c['annual_value_usd']:,.0f}/yr"),
                    ev(a["id"], "applications", f"{a['name']}: {a['user_count_90d']} users")]
            findings.append(LifecycleAlert(type="contract_renewal", app_id=a["id"], contract_id=c["id"], days_remaining=days,
                                           severity=sev, recommended_action=rec, source_refs=refs, name=a["name"],
                                           date=c["renewal_date"], auto_renew=c["auto_renew"],
                                           utilization=round(util, 2) if util is not None else None,
                                           annual_value_usd=c["annual_value_usd"]))
            if sev in ("critical", "high") and (c["auto_renew"] or c["annual_value_usd"] >= 200000):
                actions.append(ProposedAction(action_type="create_renewal_task", target_id=c["id"], target_type="Contract",
                                              payload={"renewal_date": c["renewal_date"], "days_remaining": days, "app_id": a["id"]},
                                              rationale=f"{a['name']} contract renews in {days} days. {rec}.", source_refs=refs,
                                              approver_role="principal_architect", priority=1 if sev == "critical" else 2))
        repos_by_app: dict[str, list[dict]] = {}
        for r in ctx.repo.all("repos"):
            if r["eol"]:
                repos_by_app.setdefault(r["app_id"], []).append(r)
        for app_id, rs in sorted(repos_by_app.items()):
            a = apps[app_id]
            if a["criticality"] > 2:
                continue
            r = rs[0]
            refs = [ev(r["id"], "repos", f"{r['name']}: {r['language']} / {r['framework']} {r['framework_version']} (EOL)"),
                    ev(a["id"], "applications", a["name"])]
            findings.append(LifecycleAlert(type="eol_framework", app_id=app_id, days_remaining=None, severity="high",
                                           recommended_action=f"Upgrade {r['framework']} {r['framework_version']} in {a['name']}",
                                           source_refs=refs, name=a["name"], criticality=a["criticality"]))
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        findings.sort(key=lambda f: (order[f.severity], f.days_remaining if f.days_remaining is not None else 9999))
        eos = [f for f in findings if f.type == "vendor_eos"]
        ren = [f for f in findings if f.type == "contract_renewal"]
        facts = {"eos": len(eos), "renewals": len(ren), "eol": len(findings) - len(eos) - len(ren),
                 "critical": sum(1 for f in findings if f.severity == "critical"),
                 "first_eos": eos[0].model_dump() if eos else None,
                 "trap": next((f.model_dump() for f in ren if f.auto_renew and (f.utilization or 1) < 0.3), None)}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.95)
