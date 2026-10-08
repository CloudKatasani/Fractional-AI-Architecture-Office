"""pf.cost_license_optimizer — TCO per app and savings levers (seats, renewals, untagged cloud, zombie apps, price)."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.agents.common import cloud_cost_by_app, contract_index, tco


class CostFinding(Finding):
    app_id: str | None = None
    type: str  # low_seat_utilization | auto_renew_soon | untagged_cloud | zombie_app | above_market_price
    current_cost_usd: float
    est_savings_usd: float
    evidence: str


class CostLicenseOptimizer(Agent):
    id = "pf.cost_license_optimizer"
    name = "Cost and License Optimizer"
    domain = "portfolio"
    description = ("Computes TCO per application (contract share + tagged cloud + 15% overhead) and flags low seat "
                   "utilisation, auto-renewals within 90 days, untagged cloud spend, unused apps and above-market pricing.")
    inputs = ["applications", "contracts", "cloud_resources", "invoice_lines", "sso_usage"]
    outputs = "CostFinding"
    finding_model = CostFinding
    approver_role = "cio"
    default_autonomy = 2
    demo_trigger = "Find savings"
    action_types = ["renegotiate_contract", "cancel_renewal", "tag_resources"]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        apps = ctx.repo.by_id("applications")
        cidx = contract_index(ctx)
        cloud = cloud_cost_by_app(ctx)
        findings: list[CostFinding] = []
        actions: list[ProposedAction] = []
        tcos = {}
        for a in apps.values():
            tcos[a["id"]] = tco(ctx, a, cidx, cloud)

        for c in ctx.repo.all("contracts"):
            if not c["app_ids"]:
                continue
            a = apps[c["app_ids"][0]]
            days = ctx.days_until(c["renewal_date"])
            seats = c["licensed_seats"]
            util = (a["user_count_90d"] / seats) if seats else None
            refs = [ev(c["id"], "contracts", f"{c['vendor']}: ${c['annual_value_usd']:,.0f}/yr, {seats or 'n/a'} seats, "
                                              f"renews {c['renewal_date']}{' (auto-renew)' if c['auto_renew'] else ''}"),
                    ev(a["id"], "applications", f"{a['name']}: {a['user_count_90d']} users in last 90 days")]
            if c["auto_renew"] and days is not None and 0 <= days <= 90:
                if util is not None and util < 0.3:
                    sav = round(c["annual_value_usd"] * (1 - util) * 0.9, -2)
                    findings.append(CostFinding(app_id=a["id"], type="auto_renew_soon", current_cost_usd=c["annual_value_usd"],
                                                est_savings_usd=sav, source_refs=refs, contract_id=c["id"], days_to_renewal=days,
                                                utilization=round(util, 2),
                                                evidence=f"Auto-renews in {days} days at {util:.0%} seat utilisation."))
                    actions.append(ProposedAction(
                        action_type="cancel_renewal", target_id=c["id"], target_type="Contract",
                        payload={"app_id": a["id"], "est_savings_usd": sav, "renewal_date": c["renewal_date"],
                                 "notice_deadline_days": max(0, days - 30), "utilization": round(util, 2)},
                        rationale=f"{a['name']} auto-renews in {days} days with only {util:.0%} of {seats} seats used. "
                                  f"Send non-renewal notice and right-size or retire.",
                        source_refs=refs, approver_role="cio", priority=1))
                    continue
            if util is not None and util < 0.5 and a["user_count_90d"] > 0:
                sav = round(c["annual_value_usd"] * (0.5 - util) * 0.8 + c["annual_value_usd"] * 0.1, -2)
                findings.append(CostFinding(app_id=a["id"], type="low_seat_utilization", current_cost_usd=c["annual_value_usd"],
                                            est_savings_usd=sav, source_refs=refs, contract_id=c["id"], utilization=round(util, 2),
                                            days_to_renewal=days, evidence=f"{a['user_count_90d']} of {seats} seats used ({util:.0%})."))
                actions.append(ProposedAction(
                    action_type="renegotiate_contract", target_id=c["id"], target_type="Contract",
                    payload={"app_id": a["id"], "est_savings_usd": sav, "target_seats": max(5, int(a["user_count_90d"] * 1.15)),
                             "lever": "right-size seats"},
                    rationale=f"Right-size {a['name']} from {seats} to ~{int(a['user_count_90d'] * 1.15)} seats at renewal.",
                    source_refs=refs, approver_role="cio", priority=3))
            if c["market_benchmark_usd"] and c["annual_value_usd"] > c["market_benchmark_usd"] * 1.4:
                sav = round(c["annual_value_usd"] - c["market_benchmark_usd"] * 1.1, -2)
                refs2 = refs + [ev(c["id"], "contracts", f"market benchmark ${c['market_benchmark_usd']:,.0f}/yr")]
                findings.append(CostFinding(app_id=a["id"], type="above_market_price", current_cost_usd=c["annual_value_usd"],
                                            est_savings_usd=sav, source_refs=refs2, contract_id=c["id"], days_to_renewal=days,
                                            evidence=f"Priced at {c['annual_value_usd'] / c['market_benchmark_usd']:.1f}x the "
                                                     f"market benchmark; renews in {days} days."))
                actions.append(ProposedAction(
                    action_type="renegotiate_contract", target_id=c["id"], target_type="Contract",
                    payload={"app_id": a["id"], "est_savings_usd": sav, "lever": "price to market",
                             "benchmark_usd": c["market_benchmark_usd"]},
                    rationale=f"{a['name']} renewal is {c['annual_value_usd'] / c['market_benchmark_usd']:.1f}x market. "
                              f"Open renegotiation before the renewal window.",
                    source_refs=refs2, approver_role="cio", priority=1 if (days or 999) < 150 else 2))

        for a in apps.values():
            if a["user_count_90d"] == 0 and a["annual_cost_usd"] > 0:
                refs = [ev(a["id"], "applications", f"{a['name']}: 0 users in 90 days, last login {a['last_login_days']} days ago, "
                                                    f"${a['annual_cost_usd']:,.0f}/yr")]
                refs += [ev(c["id"], "contracts", f"{c['vendor']} ${c['annual_value_usd']:,.0f}") for c in cidx.get(a["id"], [])[:1]]
                sav = round(a["annual_cost_usd"] * 0.9, -2)
                findings.append(CostFinding(app_id=a["id"], type="zombie_app", current_cost_usd=a["annual_cost_usd"],
                                            est_savings_usd=sav, source_refs=refs,
                                            evidence=f"No logins for {a['last_login_days']} days but still costs "
                                                     f"${a['annual_cost_usd']:,.0f}/yr."))
                if cidx.get(a["id"]):
                    actions.append(ProposedAction(
                        action_type="cancel_renewal", target_id=cidx[a["id"]][0]["id"], target_type="Contract",
                        payload={"app_id": a["id"], "est_savings_usd": sav, "reason": "no usage"},
                        rationale=f"{a['name']} has had no users for {a['last_login_days']} days.", source_refs=refs,
                        approver_role="cio", priority=3))

        # Untagged cloud resources grouped by account
        by_acct: dict[str, list[dict]] = {}
        for r in ctx.repo.all("cloud_resources"):
            if r["untagged"]:
                by_acct.setdefault(r["account"], []).append(r)
        for acct, res in sorted(by_acct.items()):
            monthly = sum(r["monthly_cost_usd"] for r in res)
            sav = round(monthly * 12 * 0.2, -2)
            refs = [ev(r["id"], "cloud_resources", f"{r['resource_type']} ${r['monthly_cost_usd']:,.0f}/mo, tags {r['tags'] or '{}'}")
                    for r in sorted(res, key=lambda r: -r["monthly_cost_usd"])[:4]]
            findings.append(CostFinding(app_id=None, type="untagged_cloud", current_cost_usd=round(monthly * 12, 2),
                                        est_savings_usd=sav, source_refs=refs, account=acct, resource_ids=[r["id"] for r in res],
                                        evidence=f"{len(res)} resources in {acct} lack an app tag (${monthly * 12:,.0f}/yr unallocated)."))
            actions.append(ProposedAction(
                action_type="tag_resources", target_id=acct, target_type="CloudAccount",
                payload={"resource_ids": [r["id"] for r in res], "est_savings_usd": sav, "monthly_cost_usd": round(monthly, 2)},
                rationale=f"Tag {len(res)} resources in {acct} so spend is allocated (STD-CLD-01); idle ones can then be removed.",
                source_refs=refs, approver_role="principal_architect", priority=4))

        total = round(sum(f.est_savings_usd for f in findings), -2)
        by_type: dict[str, float] = {}
        for f in findings:
            by_type[f.type] = by_type.get(f.type, 0) + f.est_savings_usd
        top = sorted(findings, key=lambda f: -f.est_savings_usd)[:3]
        facts = {"total_savings": total, "by_type": by_type, "count": len(findings),
                 "auto_renew": [f.model_dump() for f in findings if f.type == "auto_renew_soon"],
                 "top": [{"evidence": f.evidence, "ref": f.source_refs[0].record_id, "savings": f.est_savings_usd,
                          "app": apps[f.app_id]["name"] if f.app_id else f.account} for f in top],
                 "portfolio_tco": round(sum(t["total"] for t in tcos.values()), -3)}
        return AnalysisResult(findings=findings, actions=actions, facts=facts, confidence=0.88,
                              artifacts={"tco": tcos})
