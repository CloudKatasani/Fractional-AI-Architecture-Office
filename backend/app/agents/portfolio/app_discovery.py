"""pf.app_discovery — reconcile SSO, invoices, cloud tags and CMDB into the application inventory."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.config import settings

SUFFIX = re.compile(
    r"\b(inc|incorporated|ltd|llc|corp|corporation|gmbh|co|plc|prod|production|subscr|subscription|monthly|premium|"
    r"pro monthly|app|com|io|ai subscr|sw|software|systems|sys)\b"
)
COMMON = {"online", "api", "app", "cloud", "pro", "the", "and", "portal", "tool", "software", "systems", "data"}


def normalize(raw: str) -> str:
    s = raw.lower().replace("*", " ").replace(".com", " ").replace(".io", " ").replace(".ai", " ai")
    s = re.sub(r"\(([^)]*)\)", r" \1 ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(ng|mt)\b", " ", s)  # tenant CMDB prefixes
    s = re.sub(r"\blegacy ci\b|\b\d{1,2}\b", " ", s)  # CMDB duplicate markers
    s = SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


class DiscoveryFinding(Finding):
    type: str  # new_app | alias_merge | cmdb_duplicate | cmdb_stale
    app_id: str | None = None
    raw_names: list[str]
    evidence: str
    confidence: float


class Matcher:
    """normalisation + exact / fuzzy (rapidfuzz, threshold 85) / distinctive-acronym / vendor matching."""

    def __init__(self, apps: list[dict], threshold: int):
        self.apps = apps
        self.threshold = threshold
        self.by_norm: dict[str, str] = {}
        self.vendor_apps: dict[str, list[dict]] = {}
        self.vendor_tokens: dict[str, list[str]] = {}
        token_count: dict[str, int] = {}
        for a in apps:
            self.by_norm[normalize(a["name"])] = a["id"]
            self.by_norm[re.sub(r"\s+", "", normalize(a["name"]))] = a["id"]
            if a["vendor"] != "In-house":
                self.vendor_apps.setdefault(normalize(a["vendor"]), []).append(a)
                self.vendor_tokens[normalize(a["vendor"])] = re.sub(r"[^a-z0-9]+", " ", a["vendor"].lower()).split()
            for t in set(re.findall(r"\b[A-Z]{2,5}\b", a["name"])):
                token_count[t.lower()] = token_count.get(t.lower(), 0) + 1
        self.acronyms = {t: next(a["id"] for a in apps if re.search(rf"\b{t.upper()}\b", a["name"]))
                         for t, n in token_count.items() if n == 1}
        self.norm_items = list(self.by_norm.items())

    def match(self, raw: str, hint: str | None = None) -> tuple[str | None, float, str]:
        n = normalize(raw)
        if not n:
            return None, 0.0, "empty"
        if n in self.by_norm:
            return self.by_norm[n], 0.95, "exact normalised name"
        compact = n.replace(" ", "")
        if compact in self.by_norm:
            return self.by_norm[compact], 0.92, "exact normalised name (no spaces)"
        if hint:
            app_id, conf, how = self.match(hint)
            if app_id:
                return app_id, conf, f"product hint: {how}"
        # vendor match (fuzzy, or abbreviated: every raw token is a prefix of the vendor's tokens in order)
        for vnorm, vapps in self.vendor_apps.items():
            vt = self.vendor_tokens.get(vnorm, vnorm.split())
            nt = re.sub(r"[^a-z0-9]+", " ", raw.lower()).split()
            abbrev = 1 < len(nt) <= len(vt) and all(v.startswith(t) and len(t) >= 3 for t, v in zip(nt, vt, strict=False))
            if fuzz.token_sort_ratio(n, vnorm) >= self.threshold or n == vnorm or abbrev:
                if len(vapps) == 1:
                    return vapps[0]["id"], 0.85, "vendor name match (single product)"
                toks = set(n.split()) - set(vnorm.split())
                for a in vapps:
                    if toks and toks & set(normalize(a["name"]).split()):
                        return a["id"], 0.8, "vendor name + product token"
        best, best_score = None, 0.0
        for key, app_id in self.norm_items:
            sc = fuzz.token_sort_ratio(n, key)
            if sc > best_score:
                best, best_score = app_id, sc
        if best and best_score >= self.threshold:
            return best, round(0.6 + (best_score - self.threshold) / 100, 2), f"fuzzy match ({best_score:.0f})"
        for tok in n.split():
            if tok in self.acronyms and tok not in COMMON:
                return self.acronyms[tok], 0.72, f"distinctive token '{tok.upper()}'"
        return None, 0.0, "no match"


class AppDiscovery(Agent):
    id = "pf.app_discovery"
    name = "Application Discovery"
    domain = "portfolio"
    description = ("Reconciles SSO logs, invoices, expense reports, cloud tags and CMDB records into one application "
                   "inventory; surfaces shadow IT, CMDB duplicates and stale CIs with confidence per match.")
    inputs = ["sso_usage", "invoice_lines", "cloud_resources", "cmdb_cis", "applications"]
    outputs = "DiscoveryFinding"
    finding_model = DiscoveryFinding
    approver_role = "app_owner"
    default_autonomy = 1
    demo_trigger = "Run discovery"
    action_types = ["confirm_app", "merge_cmdb_ci", "retire_cmdb_ci", "assign_owner"]
    max_actions = 120

    def reconcile(self, ctx: AgentContext) -> dict:
        apps = ctx.repo.all("applications")
        m = Matcher(apps, settings.discovery_threshold)
        seen: dict[tuple[str, str], dict] = {}

        def consider(raw: str, source: str, rec: dict, table: str, hint: str | None = None) -> None:
            key = (raw if not hint else f"{raw} | {hint}", source)
            if key in seen:
                seen[key]["records"].append(rec["id"])
                return
            app_id, conf, how = m.match(raw, hint)
            seen[key] = {"raw": raw, "hint": hint, "source": source, "app_id": app_id, "confidence": conf, "method": how,
                         "records": [rec["id"]], "table": table, "row": rec}

        multi_vendor = {v for v, vs in m.vendor_apps.items() if len(vs) > 1}
        for r in ctx.repo.all("sso_usage"):
            consider(r["app_name_raw"], "sso", r, "sso_usage")
        for r in ctx.repo.all("invoice_lines"):
            if r["vendor"] in ("Amazon Web Services", "Microsoft Azure"):
                continue
            hint = None
            desc = r["description"] or ""
            for pre in ("Subscription", "License & support", "Expense claim -", "Subscription -"):
                if desc.startswith(pre):
                    hint = desc[len(pre):].strip(" -") or None
            if hint and normalize(hint) == normalize(r["vendor"]):
                hint = None
            if hint and not any(normalize(r["vendor"]).startswith(v.split()[0]) for v in multi_vendor):
                hint = hint if normalize(hint) in m.by_norm or normalize(hint).replace(" ", "") in m.by_norm else hint
            consider(r["vendor"], "invoice", r, "invoice_lines", hint)
        for r in ctx.repo.all("cloud_resources"):
            tag = (r["tags"] or {}).get("app")
            if tag:
                consider(tag, "cloud", r, "cloud_resources")
        for r in ctx.repo.all("cmdb_cis"):
            consider(r["ci_name"], "cmdb", r, "cmdb_cis")
        return {"matches": list(seen.values()), "apps": apps}

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        rec = self.reconcile(ctx)
        matches, apps = rec["matches"], rec["apps"]
        apps_by_id = {a["id"]: a for a in apps}
        findings: list[DiscoveryFinding] = []
        actions: list[ProposedAction] = []

        # ---- new_app: unmatched raw names from invoices / SSO, clustered by normalised name ----------
        unmatched = [x for x in matches if not x["app_id"] and x["source"] in ("sso", "invoice")]
        clusters: list[dict] = []
        for x in sorted(unmatched, key=lambda x: (x["source"], x["raw"])):
            n = normalize(x["raw"])
            target = None
            for c in clusters:
                if fuzz.token_sort_ratio(n, c["norm"]) >= 80 or n.split()[0] == c["norm"].split()[0]:
                    target = c
                    break
            if not target:
                target = {"norm": n, "items": []}
                clusters.append(target)
            target["items"].append(x)
        genai_known = {v.lower() for v in ctx.common["genai_vendors_known"]}
        genai_count, expense_refs = 0, []
        for i, c in enumerate(clusters):
            items = c["items"]
            sources = sorted({x["source"] for x in items})
            inv = [x for x in items if x["source"] == "invoice"]
            inv_rows = [x["row"] for x in inv]
            all_inv_ids = [rid for x in inv for rid in x["records"]]
            amount = 0.0
            inv_by_id = {r["id"]: r for r in ctx.repo.all("invoice_lines")}
            for rid in all_inv_ids:
                amount += inv_by_id[rid]["amount_usd"]
            expense = any(r["payment_channel"] == "expense" for r in inv_rows)
            mixed = sorted((x["raw"] for x in items if re.search("[a-z]", x["raw"]) and re.search("[A-Z]", x["raw"])), key=len)
            name = mixed[0] if mixed else c["norm"].title()
            genai_first = {normalize(k).split()[0] for k in genai_known}
            genai = any(normalize(x["raw"]).split()[:1] and normalize(x["raw"]).split()[0] in genai_first for x in items)
            if genai:
                genai_count += 1
            sso_users = sum(x["row"]["unique_users"] for x in items if x["source"] == "sso")
            refs = [ev(rid, "invoice_lines", f"{inv_by_id[rid]['vendor']} ${inv_by_id[rid]['amount_usd']:,.0f} "
                       f"({inv_by_id[rid]['payment_channel']}, {inv_by_id[rid]['cost_center']})") for rid in all_inv_ids[:3]]
            refs += [ev(x["records"][0], "sso_usage", f"SSO app '{x['raw']}'") for x in items if x["source"] == "sso"][:2]
            if expense:
                expense_refs += [r.record_id for r in refs if r.table == "invoice_lines"][:1]
            conf = 0.85 if len(sources) > 1 else 0.6
            cand_id = f"CAND-{ctx.tenant_id[:2].upper()}-{i + 1:03d}"
            annual = round(amount / max(1, len({inv_by_id[r]['invoice_date'][:7] for r in all_inv_ids})) * 12, 2) if all_inv_ids else 0
            evidence = (f"Seen in {', '.join(sources)}; {len(all_inv_ids)} invoice lines totalling ${amount:,.0f}"
                        + (" paid through expense reports" if expense else "") + (f"; {sso_users} SSO user-months" if sso_users else ""))
            findings.append(DiscoveryFinding(type="new_app", app_id=cand_id, raw_names=sorted({x["raw"] for x in items}),
                                             evidence=evidence, confidence=conf, source_refs=refs or [ev(items[0]["records"][0], items[0]["table"])],
                                             candidate_name=name, genai=genai, paid_via_expense=expense,
                                             annual_cost_usd=annual, sources=sources))
            actions.append(ProposedAction(
                action_type="confirm_app", target_id=cand_id, target_type="Application",
                payload={"candidate_name": name, "raw_names": sorted({x["raw"] for x in items}), "annual_cost_usd": annual,
                         "genai": genai, "paid_via_expense": expense, "sources": sources, "new": True},
                rationale=f"'{name}' appears in {', '.join(sources)} but in no inventory or CMDB record. "
                          f"Confirm it as an application (and name an owner) or reject it.",
                source_refs=refs[:4] or [ev(items[0]["records"][0], items[0]["table"])], approver_role="app_owner",
                priority=2 if genai else 3))

        # ---- alias_merge: inferred (lower confidence) reconciliations, grouped per app -----------
        inferred: dict[str, list[dict]] = {}
        for x in matches:
            if x["app_id"] and x["confidence"] < 0.9 and x["source"] != "cmdb":
                inferred.setdefault(x["app_id"], []).append(x)
        for app_id, xs in sorted(inferred.items()):
            a = apps_by_id[app_id]
            conf = round(min(x["confidence"] for x in xs), 2)
            raws = sorted({x["raw"] for x in xs})
            refs = [ev(x["records"][0], x["table"], f"'{x['raw']}' -> {a['name']} ({x['method']})") for x in xs[:4]]
            findings.append(DiscoveryFinding(type="alias_merge", app_id=app_id, raw_names=raws, confidence=conf,
                                             evidence=f"{len(raws)} raw names reconciled to {a['name']} by "
                                                      + ", ".join(sorted({x['method'].split(' (')[0] for x in xs})),
                                             source_refs=[ev(app_id, "applications", a["name"])] + refs))
            if conf < 0.7:
                actions.append(ProposedAction(
                    action_type="confirm_app", target_id=app_id, target_type="Application",
                    payload={"aliases": raws, "new": False}, rationale=f"Low-confidence alias match for {a['name']}; owner to confirm.",
                    source_refs=refs, approver_role="app_owner", priority=4))

        # ---- CMDB duplicates and stale CIs -------------------------------------------------------
        cis = ctx.repo.all("cmdb_cis")
        ci_matches = {x["row"]["id"]: x for x in matches if x["source"] == "cmdb"}
        by_app: dict[str, list[dict]] = {}
        for ci in cis:
            x = ci_matches.get(ci["id"])
            resolved = ci["app_id"] or (x["app_id"] if x else None)
            if resolved:
                by_app.setdefault(resolved, []).append(ci)
            else:
                age = (ctx.today - __import__("datetime").date.fromisoformat(ci["last_updated"])).days
                findings.append(DiscoveryFinding(
                    type="cmdb_stale", app_id=None, raw_names=[ci["ci_name"]], confidence=0.8 if age > 700 else 0.65,
                    evidence=f"CI '{ci['ci_name']}' is 'operational' but matches no application, SSO, invoice or cloud "
                             f"record; last updated {age} days ago.",
                    source_refs=[ev(ci["id"], "cmdb_cis", f"{ci['ci_name']} ({ci['ci_status']}, updated {ci['last_updated']})")],
                    ci_id=ci["id"]))
                actions.append(ProposedAction(
                    action_type="retire_cmdb_ci", target_id=ci["id"], target_type="ConfigItem",
                    payload={"ci_name": ci["ci_name"], "last_updated": ci["last_updated"]},
                    rationale=f"No evidence of '{ci['ci_name']}' in any live source for {age} days.",
                    source_refs=[ev(ci["id"], "cmdb_cis", ci["ci_name"])], approver_role="principal_architect", priority=4))
        for app_id, group in sorted(by_app.items()):
            if len(group) < 2:
                continue
            group.sort(key=lambda c: (c["app_id"] is None, c["last_updated"]), reverse=False)
            keep = next((c for c in group if c["app_id"]), group[0])
            for dup in group:
                if dup["id"] == keep["id"]:
                    continue
                a = apps_by_id[app_id]
                findings.append(DiscoveryFinding(
                    type="cmdb_duplicate", app_id=app_id, raw_names=[keep["ci_name"], dup["ci_name"]], confidence=0.88,
                    evidence=f"CIs '{keep['ci_name']}' and '{dup['ci_name']}' both describe {a['name']}.",
                    source_refs=[ev(dup["id"], "cmdb_cis", dup["ci_name"]), ev(keep["id"], "cmdb_cis", keep["ci_name"]),
                                 ev(app_id, "applications", a["name"])], ci_id=dup["id"], keep_ci_id=keep["id"]))
                actions.append(ProposedAction(
                    action_type="merge_cmdb_ci", target_id=dup["id"], target_type="ConfigItem",
                    payload={"merge_into": keep["id"], "app_id": app_id},
                    rationale=f"Duplicate CI for {a['name']}; merge into {keep['id']}.",
                    source_refs=[ev(dup["id"], "cmdb_cis", dup["ci_name"]), ev(keep["id"], "cmdb_cis", keep["ci_name"])],
                    approver_role="principal_architect", priority=4))

        new_apps = [f for f in findings if f.type == "new_app"]
        missing_cmdb = [a for a in apps if not a["in_cmdb"]]
        facts = {
            "new_apps": len(new_apps), "genai": genai_count, "expense_refs": expense_refs[:3],
            "expense_genai": sum(1 for f in new_apps if f.genai and f.paid_via_expense),
            "cmdb_duplicates": sum(1 for f in findings if f.type == "cmdb_duplicate"),
            "cmdb_stale": sum(1 for f in findings if f.type == "cmdb_stale"),
            "alias_merges": sum(1 for f in findings if f.type == "alias_merge"),
            "raw_names": len(matches), "matched": sum(1 for x in matches if x["app_id"]),
            "missing_from_cmdb": len(missing_cmdb),
            "shadow_annual_cost": round(sum(f.annual_cost_usd for f in new_apps), 0),
        }
        return AnalysisResult(findings=findings, actions=actions, facts=facts,
                              confidence=round(facts["matched"] / max(1, facts["raw_names"]), 2),
                              artifacts={"match_table": [{k: v for k, v in x.items() if k != "row"} for x in matches]})
