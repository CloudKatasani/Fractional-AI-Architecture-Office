"""shared.copilot — Architecture Copilot over the knowledge graph.

Mock mode: regex pattern handlers -> graph queries -> templated answers with citations (no network).
Live mode: Claude with tools (kg_search, kg_neighbors, kg_lineage, kg_impact, search_standards, search_patterns);
the answer must cite record ids returned by the tools.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date

from rapidfuzz import fuzz, process  # noqa: F401

from app.agents.base import Agent, AgentContext
from app.config import demo_today, settings
from app.db.session import Repo
from app.kg.export import data_flow
from app.kg.queries import KG, get_kg
from app.services import audit


class Copilot(Agent):
    id = "shared.copilot"
    name = "Architecture Copilot"
    domain = "shared"
    description = ("Answers questions over the knowledge graph (owners, dependencies, costs, lineage, policies, patterns) "
                   "with cited record ids and optional diagrams.")
    inputs = ["kg_nodes", "kg_edges", "standards", "patterns"]
    outputs = "Answer with citations"
    approver_role = None
    default_autonomy = 1
    demo_trigger = "Ask a question"
    runnable = False


def _cite(kg: KG, ids: list[str]) -> list[dict]:
    out, seen = [], set()
    for i in ids:
        n = kg.node(i)
        if n and i not in seen:
            seen.add(i)
            out.append({"id": i, "type": n["type"], "name": n["name"]})
    return out


STOPWORDS = {"the", "a", "an", "platform", "system", "systems", "tool", "tools", "app", "application", "our", "we", "of", "for",
             "dataset", "data set"}


def _tok(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOPWORDS]


def _find(kg: KG, text: str, types: list[str], cutoff: int = 62) -> dict | None:
    """Token-overlap match on name + category (prefix-tolerant), WRatio as tie-breaker; types are searched in order."""
    q = _tok(text)
    if not q:
        return None
    for t in types:
        best, best_score = None, 0.0
        for n in kg.by_type(t):
            if n["status"] == "retired":
                continue
            name_t = _tok(n["name"])
            cat_t = _tok(n["props_json"].get("category") or "")
            hits = 0.0
            for w in q:
                if w in name_t or any(x.startswith(w[:4]) and len(w) >= 4 for x in name_t):
                    hits += 1
                elif w in cat_t or any(x.startswith(w[:4]) and len(w) >= 4 for x in cat_t):
                    hits += 0.8
            score = 100 * hits / len(q) + fuzz.WRatio(text, n["name"]) / 100 - (0.6 if "(" in n["name"] or n["name"].endswith(" Mart") else 0)
            if score > best_score:
                best, best_score = n, score
        if best and best_score >= cutoff:
            return best
    return None


def _usd(v: float) -> str:
    return f"${v:,.0f}"


class MockCopilot:
    def __init__(self, tenant_id: str):
        self.t = tenant_id
        self.kg = get_kg(tenant_id)
        self.repo = Repo(tenant_id)
        self.handlers = [
            (r"who owns (.+?) and what ai uses it", self.owner_and_ai),
            (r"who owns (?:the )?(.+?)\??$", self.owner),
            (r"which (?:applications|systems|apps) (?:support|realize|realise|serve) (.+?)\??$", self.apps_for_cap),
            (r"what would break if we retired (?:the )?(.+?)\??$", self.impact),
            (r"what depends on (?:the )?(.+?)\??$", self.impact),
            (r"(?:ai use cases|ai).*(?:pii|personal data)", self.ai_pii),
            (r"(?:ai use cases|ai).*high risk", self.ai_high_risk),
            (r"pattern for (.+?)\??$", self.pattern),
            (r"contracts? renew.*?(\d+) days", self.renewals),
            (r"(?:integrations|what).*(?:cross|crosses) the (?:it/ot|ot|bss/oss|boundary)|bss and oss share", self.boundary),
            (r"(?:how much do we spend on|cost of) (?:the )?(.+?)\??$", self.spend),
            (r"projects.*(?:no|without).*goal", self.orphans),
            (r"lineage (?:for|of) (?:the )?(.+?)\??$", self.lineage),
            (r"apis? .*duplicat|duplicat.*apis?", self.dup_apis),
            (r"residency", self.residency),
            (r"design reviews? .*pending|pending design", self.pending_designs),
            (r"what does the (.+?) (?:strategy )?need that we don'?t have", self.strategy_gaps),
            (r"end of support|eos", self.eos),
            (r"unregistered|shadow ai", self.shadow_ai),
            (r"shadow it", self.shadow_it),
            (r"explain (?:node )?([A-Z]{2,5}-[A-Z0-9-]+)", self.explain),
            (r"\b([A-Z]{2,5}-\d{3,5})\b", self.explain),
            (r"how many applications", self.count_apps),
            (r"(?:what|which).*(?:violations|violate)", self.violations),
        ]

    def answer(self, q: str, history: list[dict] | None = None) -> dict:
        ql = q.strip()
        history = history or []
        follow = self.follow_up(ql, history)
        if follow:
            return follow
        res = self.dispatch(ql)
        if res:
            return res
        sugg = self.repo.get_meta("copilot_questions", [])[:4]
        return {"answer": "I can answer questions about owners, dependencies, costs, lineage, policies and patterns in the "
                          "knowledge graph. Try: " + "; ".join(f"“{s}”" for s in sugg), "citations": [], "mermaid": None}

    def dispatch(self, q: str) -> dict | None:
        for pat, fn in self.handlers:
            m = re.search(pat, q, re.I)
            if m:
                res = fn(*[g for g in m.groups()]) if m.groups() else fn()
                if res:
                    return res
        return None

    # ---- conversation history -------------------------------------------------------------
    PRONOUN = r"\b(those|these|them|they|it|its|that one|this one|that system|this system|that app|this app|the same)\b"

    def _context(self, history: list[dict]) -> tuple[str | None, list[dict]]:
        """Previous user question and the graph nodes cited in the previous assistant answer."""
        prev_q, focus, seen_answer = None, [], False
        for m in reversed(history):
            if m.get("role") == "assistant" and not seen_answer:
                seen_answer = True
                ids = list(dict.fromkeys(re.findall(r"\[([A-Z]{2,5}-[A-Za-z0-9-]+)\]", m.get("content") or "")))
                focus = [self.kg.node(i) for i in ids if self.kg.node(i)]
            elif m.get("role") == "user":
                prev_q = m.get("content")
                break
        return prev_q, focus

    def follow_up(self, q: str, history: list[dict]) -> dict | None:
        if not history:
            return None
        prev_q, focus = self._context(history)
        low = q.lower()
        refers = bool(re.search(self.PRONOUN, low)) or low.startswith(("and ", "which of", "of those", "only "))
        # "what about X?" / "and the CRM?" -> re-ask the previous question with a new subject
        m = re.match(r"^(?:and |what about |how about |same for |and what about )(?:the )?(.+?)\??$", low)
        if m and prev_q and not re.search(self.PRONOUN, m.group(1)):
            res = self._reask(prev_q, m.group(1))
            if res:
                res["answer"] = f"_Following up on “{prev_q}”:_\n\n" + res["answer"]
                return res
        if not refers or not focus:
            return None
        res = self._filter_focus(low, focus)
        if res is None:
            # substitute the pronoun with the main subject of the previous answer and dispatch normally
            subject = focus[0]["name"]
            res = self.dispatch(re.sub(self.PRONOUN, subject, q, count=1, flags=re.I))
        if res:
            names = ", ".join(n["name"] for n in focus[:3]) + (f" and {len(focus) - 3} more" if len(focus) > 3 else "")
            res["answer"] = f"_Using the previous answer ({names}):_\n\n" + res["answer"]
        return res

    def _reask(self, prev_q: str, subject: str) -> dict | None:
        for pat, _fn in self.handlers:
            m = re.search(pat, prev_q, re.I)
            if m and m.groups() and m.group(1):
                a, b = m.span(1)
                return self.dispatch(prev_q[:a] + subject + prev_q[b:])
        return None

    def _filter_focus(self, low: str, focus: list[dict]) -> dict | None:
        """Questions about the set of records cited in the previous answer."""
        from app.agents.base import AgentContext
        from app.agents.data_ai.ai_risk_classifier import classify

        by_type: dict[str, list[dict]] = {}
        for n in focus:
            by_type.setdefault(n["type"], []).append(n)
        apps = [self.repo.get("applications", n["id"]) for n in by_type.get("Application", []) if self.repo.get("applications", n["id"])]
        ucs = [self.repo.get("ai_usecases", n["id"]) for n in by_type.get("AIUseCase", [])]
        assets = [self.repo.get("ai_assets", n["id"]) for n in by_type.get("AIAsset", [])]
        ucs += [self.repo.get("ai_usecases", a["usecase_id"]) for a in assets if a and a["usecase_id"]]
        ucs = [u for u in {u["id"]: u for u in ucs if u}.values()]
        dsets = [self.repo.get("datasets", n["id"]) for n in by_type.get("Dataset", [])]
        if re.search(r"high[- ]risk|risk tier|risky|prohibited|blocked", low) and ucs:
            ctx = AgentContext(self.t)
            rows = [(u, classify(ctx, u)) for u in ucs]
            hi = [(u, c) for u, c in rows if c["tier"] in ("high", "unacceptable")]
            lines = [f"- **{u['title']}** [{u['id']}] — {c['tier']}: " + ", ".join(t["rule_id"] for t in c["triggers"]) for u, c in hi]
            rest = ", ".join(f"{u['title']} [{u['id']}] ({c['tier']})" for u, c in rows if (u, c) not in hi)
            txt = (f"{len(hi)} of the {len(rows)} AI use cases are high risk or prohibited:\n" + "\n".join(lines) if hi
                   else f"None of the {len(rows)} AI use cases is high risk.") + (f"\nThe others: {rest}." if rest else "")
            return {"answer": txt, "citations": _cite(self.kg, [u["id"] for u in ucs]), "mermaid": None}
        if re.search(r"how much|cost|spend|budget", low) and apps:
            total = sum(a["annual_cost_usd"] for a in apps)
            lines = [f"- {a['name']} [{a['id']}] — {_usd(a['annual_cost_usd'])}/yr" for a in sorted(apps, key=lambda a: -a["annual_cost_usd"])]
            return {"answer": f"Together they cost **{_usd(total)}** a year:\n" + "\n".join(lines),
                    "citations": _cite(self.kg, [a["id"] for a in apps]), "mermaid": None}
        if re.search(r"who owns|owner", low) and (apps or dsets or ucs):
            rows = []
            for r in apps + [d for d in dsets if d] + [{**u, "name": u["title"]} for u in ucs]:
                owner = self.kg.node(r["owner_user_id"]) if r.get("owner_user_id") else None
                rows.append(f"- {r['name']} [{r['id']}] — " + (f"{owner['name']} [{owner['id']}]" if owner else "no owner recorded"))
            ids = [r["id"] for r in apps + [d for d in dsets if d] + ucs]
            return {"answer": "Owners:\n" + "\n".join(rows), "citations": _cite(self.kg, ids), "mermaid": None}
        if re.search(r"renew|contract", low) and apps:
            cs = [c for c in self.repo.all("contracts") if set(c["app_ids"]) & {a["id"] for a in apps}]
            lines = [f"- {next(a['name'] for a in apps if a['id'] in c['app_ids'])} [{c['id']}] — renews {c['renewal_date']}"
                     f"{' (auto-renew)' if c['auto_renew'] else ''}, {_usd(c['annual_value_usd'])}/yr" for c in sorted(cs, key=lambda c: c["renewal_date"])]
            return {"answer": (f"{len(cs)} contracts cover them:\n" + "\n".join(lines)) if cs else "None of them has a vendor contract (in-house).",
                    "citations": _cite(self.kg, [c["id"] for c in cs] or [a["id"] for a in apps]), "mermaid": None}
        if re.search(r"pii|personal", low) and (dsets or ucs):
            if dsets:
                hit = [d for d in dsets if d and d["pii"]]
                lines = [f"- {d['name']} [{d['id']}] — {d['classification']}, retention {d['retention_days'] or 'not set'}" for d in hit]
                return {"answer": f"{len(hit)} of the {len(dsets)} datasets contain personal data:\n" + "\n".join(lines),
                        "citations": _cite(self.kg, [d["id"] for d in hit] or [d["id"] for d in dsets if d]), "mermaid": None}
            hit = [u for u in ucs if u["uses_personal_data"]]
            return {"answer": f"{len(hit)} of the {len(ucs)} use cases use personal data: " + ", ".join(f"{u['title']} [{u['id']}]" for u in hit) + ".",
                    "citations": _cite(self.kg, [u["id"] for u in ucs]), "mermaid": None}
        if re.search(r"end of support|eos|unsupported", low) and apps:
            eos = [a for a in apps if a["vendor_eos_date"]]
            lines = [f"- {a['name']} [{a['id']}] — vendor EOS {a['vendor_eos_date']}" for a in sorted(eos, key=lambda a: a["vendor_eos_date"])]
            return {"answer": (f"{len(eos)} of them have a vendor end-of-support date:\n" + "\n".join(lines)) if eos
                    else "None of them has a published vendor end-of-support date.",
                    "citations": _cite(self.kg, [a["id"] for a in (eos or apps)]), "mermaid": None}
        return None

    # ---- handlers --------------------------------------------------------------------------
    def owner(self, what: str) -> dict | None:
        n = _find(self.kg, what, ["Application", "Dataset", "Capability"], cutoff=75)
        if not n:
            return None
        owners = [e["from_id"] for e in self.kg.in_edges(n["id"], "OWNS")]
        if not owners:
            return {"answer": f"**{n['name']}** [{n['id']}] has no recorded owner — the Governance Policy Checker flags this.",
                    "citations": _cite(self.kg, [n["id"]]), "mermaid": None}
        p = self.kg.node(owners[0])
        conf = n["props_json"].get("owner_confirmed")
        return {"answer": f"**{n['name']}** [{n['id']}] is owned by **{p['name']}**, {p['props_json'].get('title')} [{p['id']}]"
                          + (" (confirmed by the owner)." if conf else ("." if conf is None else " — not yet confirmed by the owner.")),
                "citations": _cite(self.kg, [n["id"], p["id"]]), "mermaid": None}

    def owner_and_ai(self, what: str) -> dict | None:
        ds = [d for d in self.repo.all("datasets") if d["layer"] == "source"]
        words = what.lower().replace("data", "").strip()
        domain = None
        for d in ds:
            if words and (words in d["domain"].lower() or d["domain"].lower().startswith(words[:5])):
                domain = d["domain"]
                break
        if not domain:
            return self.owner(what)
        dsets = [d for d in self.repo.all("datasets") if d["domain"] == domain]
        owners = sorted({d["owner_user_id"] for d in dsets if d["owner_user_id"]})
        system = self.kg.node(dsets[0]["system_app_id"])
        ai_ids = set()
        for d in dsets:
            for e in self.kg.in_edges(d["id"], "CONSUMES_DATA") + self.kg.in_edges(d["id"], "USES_DATA"):
                if self.kg.node(e["from_id"])["type"] in ("AIAsset", "AIUseCase"):
                    ai_ids.add(e["from_id"])
        ai = sorted(ai_ids)
        key = max(dsets, key=lambda d: len(self.kg.in_edges(d["id"], "CONSUMES_DATA")))
        owner_txt = ", ".join(f"**{self.kg.node(o)['name']}** [{o}]" for o in owners)
        ai_txt = "; ".join(f"{self.kg.node(a)['name']} [{a}]" for a in ai) or "none recorded"
        return {"answer": f"{domain} data ({len(dsets)} datasets, system of record **{system['name']}** [{system['id']}]) is owned by "
                          f"{owner_txt}. AI that uses it: {ai_txt}. Lineage for the most-used dataset, {key['name']} [{key['id']}], is shown below.",
                "citations": _cite(self.kg, owners + [system["id"], key["id"]] + ai), "mermaid": data_flow(self.kg, key["id"])}

    def apps_for_cap(self, what: str) -> dict | None:
        c = _find(self.kg, what, ["Capability"])
        if not c:
            return None
        apps = self.kg.apps_for_capability(c["id"])
        rows = sorted((self.kg.node(a) for a in apps), key=lambda n: -n["props_json"].get("annual_cost_usd", 0))
        lines = [f"- {n['name']} [{n['id']}] — {n['props_json'].get('category')}, {_usd(n['props_json'].get('annual_cost_usd', 0))}/yr"
                 for n in rows[:12]]
        more = f"\n…and {len(rows) - 12} more." if len(rows) > 12 else ""
        return {"answer": f"**{c['name']}** [{c['id']}] is realised by {len(rows)} applications:\n" + "\n".join(lines) + more,
                "citations": _cite(self.kg, [c["id"]] + [n["id"] for n in rows[:12]]), "mermaid": None}

    def impact(self, what: str) -> dict | None:
        n = _find(self.kg, what, ["Application", "Vendor", "Dataset"], cutoff=70)
        if not n:
            return None
        imp = self.kg.impact(n["id"], depth=2)
        parts = []
        cites = [n["id"]]
        for typ in ("Application", "Capability", "Dataset", "AIAsset", "AIUseCase", "Project"):
            items = imp.get(typ, [])
            if items:
                parts.append(f"**{len(items)} {typ}{'s' if len(items) != 1 else ''}**: " + ", ".join(f"{i['name']} [{i['id']}]" for i in items[:6])
                             + ("…" if len(items) > 6 else ""))
                cites += [i["id"] for i in items[:6]]
        integ = len(self.kg.in_edges(n["id"], "INTEGRATES_WITH")) + len(self.kg.out_edges(n["id"], "INTEGRATES_WITH"))
        from app.kg.export import c4_context
        return {"answer": f"Changing or retiring **{n['name']}** [{n['id']}] affects ({integ} direct integrations):\n- " + "\n- ".join(parts),
                "citations": _cite(self.kg, cites), "mermaid": c4_context(self.kg, n["id"]) if n["type"] == "Application" else None}

    def ai_pii(self) -> dict:
        ucs = [u for u in self.repo.all("ai_usecases") if u["uses_personal_data"]]
        ds = self.repo.by_id("datasets")
        lines = [f"- {u['title']} [{u['id']}] — " + ", ".join(f"{ds[d]['name']} [{d}]" for d in u["dataset_ids"] if ds[d]["pii"]) for u in ucs]
        cites = [u["id"] for u in ucs] + [d for u in ucs for d in u["dataset_ids"] if ds[d]["pii"]][:10]
        return {"answer": f"{len(ucs)} AI use cases use personal data:\n" + "\n".join(lines), "citations": _cite(self.kg, cites), "mermaid": None}

    def ai_high_risk(self) -> dict:
        from app.agents.base import AgentContext
        from app.agents.data_ai.ai_risk_classifier import classify

        ctx = AgentContext(self.t)
        rows = []
        for u in self.repo.all("ai_usecases"):
            c = classify(ctx, u)
            if c["tier"] in ("high", "unacceptable"):
                rows.append((u, c))
        lines = [f"- **{u['title']}** [{u['id']}] — {c['tier']}: " + "; ".join(f"{t['rule_id']} {t['title'].lower()}" for t in c["triggers"])
                 for u, c in rows]
        return {"answer": "High-risk (and prohibited) AI use cases under the tiering rules:\n" + "\n".join(lines),
                "citations": _cite(self.kg, [u["id"] for u, _ in rows]), "mermaid": None}

    def pattern(self, what: str) -> dict | None:
        from app.agents.application.pattern_advisor import PatternAdvisor

        ctx = AgentContext(self.t, params={"text": what})
        res = PatternAdvisor().mock_run(ctx)
        if not res.findings:
            return {"answer": f"No reference pattern matches “{what}”. Ask the principal architect to add one.", "citations": [], "mermaid": None}
        f = res.findings[0]
        approved = "Yes" if f.fit_score >= 0.5 else "Partially"
        return {"answer": f"{approved} — **{f.name}** [{f.pattern_id}] fits ({f.why}) Applicable standards: "
                          + ", ".join(f"[{s}]" for s in f.standard_ids) + "."
                          + (" Reuse: " + ", ".join(f"[{a}]" for a in f.reuse_api_ids) if f.reuse_api_ids else ""),
                "citations": _cite(self.kg, [f.pattern_id] + f.standard_ids + f.reuse_api_ids), "mermaid": f.starter_diagram_mermaid}

    def renewals(self, days: str) -> dict:
        n = int(days)
        today = demo_today()
        apps = self.repo.by_id("applications")
        cs = [c for c in self.repo.all("contracts") if c["app_ids"] and 0 <= (date.fromisoformat(c["renewal_date"]) - today).days <= n]
        cs.sort(key=lambda c: c["renewal_date"])
        lines = [f"- {apps[c['app_ids'][0]]['name']} [{c['id']}] — {c['renewal_date']} ({(date.fromisoformat(c['renewal_date']) - today).days} days), "
                 f"{_usd(c['annual_value_usd'])}/yr{' **auto-renews**' if c['auto_renew'] else ''}" for c in cs]
        return {"answer": f"{len(cs)} contracts renew in the next {n} days:\n" + "\n".join(lines), "citations": _cite(self.kg, [c["id"] for c in cs]),
                "mermaid": None}

    def boundary(self) -> dict:
        label = self.repo.all("tenants")[0]["boundary_label"]
        apps = self.repo.by_id("applications")
        ints = [i for i in self.repo.all("integrations") if i["crosses_boundary"]]
        bad = [i for i in ints if i["pattern"] == "db_link"]
        lines = [f"- **{apps[i['from_app_id']]['name']} → {apps[i['to_app_id']]['name']}** [{i['id']}] — direct DB link: {i['description']}" for i in bad]
        ok = len(ints) - len(bad)
        return {"answer": f"{len(ints)} integrations cross the {label} boundary. {len(bad)} are direct database links that violate the "
                          f"boundary standard:\n" + "\n".join(lines) + f"\nThe other {ok} use approved file/event/API patterns.",
                "citations": _cite(self.kg, [i["id"] for i in bad]), "mermaid": None}

    def spend(self, what: str) -> dict | None:
        words = [re.sub(r"s$", "", w) for w in re.findall(r"[a-z]+", what.lower())
                 if w not in {"the", "two", "combined", "both", "all", "our", "tools", "tool", "of", "and", "on"}]
        apps = [a for a in self.repo.all("applications")
                if words and all(re.search(rf"\b{re.escape(w)}s?\b", f"{a['category']} {a['name']}".lower()) for w in words)]
        if not apps:
            n = _find(self.kg, what, ["Application"])
            if not n:
                return None
            apps = [self.repo.get("applications", n["id"])]
        total = sum(a["annual_cost_usd"] for a in apps)
        lines = [f"- {a['name']} [{a['id']}] — {_usd(a['annual_cost_usd'])}/yr, {a['user_count_90d']} users" for a in apps]
        return {"answer": f"Annual run cost for {what.strip()}: **{_usd(total)}** across {len(apps)} applications "
                          f"(contract share + tagged cloud + 15% overhead):\n" + "\n".join(lines),
                "citations": _cite(self.kg, [a["id"] for a in apps]), "mermaid": None}

    def orphans(self) -> dict:
        ps = [p for p in self.repo.all("projects") if not p["goal_ids"]]
        total = sum(p["budget_usd"] for p in ps)
        allb = sum(p["budget_usd"] for p in self.repo.all("projects"))
        lines = [f"- {p['name']} [{p['id']}] — {_usd(p['budget_usd'])}" for p in sorted(ps, key=lambda p: -p["budget_usd"])]
        return {"answer": f"{len(ps)} projects ({_usd(total)}, {100 * total / allb:.0f}% of project budget) have no strategic goal:\n" + "\n".join(lines),
                "citations": _cite(self.kg, [p["id"] for p in ps]), "mermaid": None}

    def lineage(self, what: str) -> dict | None:
        what = re.sub(r"\bdataset\b", "", what, flags=re.I).strip()
        n = _find(self.kg, what, ["Dataset"], cutoff=55)
        if not n:
            return None
        up = self.kg.lineage_upstream(n["id"])
        down = self.kg.lineage_downstream(n["id"])
        sys_names = ", ".join(f"{self.kg.node(s)['name']} [{s}]" for s in up["systems"])
        return {"answer": f"**{n['name']}** [{n['id']}] — upstream: {len(up['datasets'])} datasets via {len(up['pipelines'])} pipelines "
                          f"(stored in {sys_names}); downstream: {len(down['datasets'])} datasets, {len(down['bi_assets'])} BI assets, "
                          f"{len(down['ai'])} AI assets/use cases" + (": " + ", ".join(f"{self.kg.node(a)['name']} [{a}]" for a in down["ai"][:5]) if down["ai"] else "") + "."
                          + ("\n- Upstream datasets: " + ", ".join(f"{self.kg.node(d)['name']} [{d}]" for d in up["datasets"][:8]) if up["datasets"] else "")
                          + ("\n- Downstream datasets: " + ", ".join(f"{self.kg.node(d)['name']} [{d}]" for d in down["datasets"][:8]) if down["datasets"] else ""),
                "citations": _cite(self.kg, [n["id"]] + up["systems"] + down["ai"][:5] + down["bi_assets"][:3]), "mermaid": data_flow(self.kg, n["id"])}

    def dup_apis(self) -> dict:
        groups: dict[str, list[dict]] = {}
        apps = self.repo.by_id("applications")
        for a in self.repo.all("apis"):
            if a["duplicate_group"]:
                groups.setdefault(a["duplicate_group"], []).append(a)
        lines = [f"- **{g.split('-', 1)[1].lower()}**: " + " vs ".join(f"{a['name']} [{a['id']}] (owner {apps[a['owner_app_id']]['name']}, {a['auth']})"
                                                                        for a in items) for g, items in groups.items()]
        return {"answer": f"{len(groups)} duplicated API groups:\n" + "\n".join(lines),
                "citations": _cite(self.kg, [a["id"] for v in groups.values() for a in v]), "mermaid": None}

    def residency(self) -> dict:
        home = self.repo.all("tenants")[0]["home_region"]
        ds = [d for d in self.repo.all("datasets") if d["region"] != home]
        if not ds:
            return {"answer": f"All datasets are stored in the home region ({home}).", "citations": [], "mermaid": None}
        apps = self.repo.by_id("applications")
        lines = [f"- {d['name']} [{d['id']}] — {d['region']} via {apps[d['system_app_id']]['name']}" for d in ds]
        return {"answer": f"{len(ds)} datasets sit outside {home} and violate the residency policy:\n" + "\n".join(lines),
                "citations": _cite(self.kg, [d["id"] for d in ds]), "mermaid": None}

    def pending_designs(self) -> dict:
        ds = [d for d in self.repo.all("design_docs") if d["status"] == "submitted"]
        lines = [f"- {d['title']} [{d['id']}] — {d['team']}, submitted {d['submitted_at'][:10]}" for d in ds]
        return {"answer": f"{len(ds)} design reviews are pending:\n" + "\n".join(lines), "citations": _cite(self.kg, [d["id"] for d in ds]),
                "mermaid": None}

    def strategy_gaps(self, what: str) -> dict | None:
        docs = self.repo.all("strategy_docs")
        best = process.extractOne(what, {d["id"]: d["title"] for d in docs}, scorer=fuzz.WRatio, score_cutoff=50)
        if not best:
            return None
        doc = next(d for d in docs if d["id"] == best[2])
        goals = [g for g in self.repo.all("goals") if g["source_doc_id"] == doc["id"]]
        from app.agents.enterprise.strategy_capability_mapper import StrategyCapabilityMapper

        res = StrategyCapabilityMapper().mock_run(AgentContext(self.t))
        caps = self.repo.by_id("capabilities")
        lines, cites = [], [doc["id"]]
        for f in res.findings:
            if f.goal_id not in {g["id"] for g in goals}:
                continue
            weak = [c for c in f.capability_ids if caps[c]["maturity"] <= 2]
            cites += [f.goal_id] + weak
            lines.append(f"- **{f.statement}** [{f.goal_id}] needs " + (", ".join(
                f"{caps[c]['name']} [{c}] (maturity {caps[c]['maturity']}/5)" for c in weak) if weak else "capabilities that are already mature"))
        funded = {g for p in self.repo.all("projects") for g in p["goal_ids"]}
        unfunded = [g for g in goals if g["id"] not in funded]
        tail = ("\nUnfunded: " + "; ".join(f"{g['statement']} [{g['id']}]" for g in unfunded)) if unfunded else ""
        return {"answer": f"**{doc['title']}** [{doc['id']}] depends on capabilities we rate low-maturity:\n" + "\n".join(lines) + tail,
                "citations": _cite(self.kg, cites + [g["id"] for g in unfunded]), "mermaid": None}

    def eos(self) -> dict:
        today = demo_today()
        apps = [a for a in self.repo.all("applications") if a["vendor_eos_date"] and 0 <= (date.fromisoformat(a["vendor_eos_date"]) - today).days <= 365]
        apps.sort(key=lambda a: a["vendor_eos_date"])
        lines = [f"- {a['name']} [{a['id']}] — {a['vendor_eos_date']} ({(date.fromisoformat(a['vendor_eos_date']) - today).days} days)" for a in apps]
        return {"answer": f"{len(apps)} applications reach vendor end of support within 12 months:\n" + "\n".join(lines),
                "citations": _cite(self.kg, [a["id"] for a in apps]), "mermaid": None}

    def shadow_ai(self) -> dict:
        assets = [a for a in self.repo.all("ai_assets") if not a["registered"]]
        lines = [f"- {a['name']} [{a['id']}] — {a['vendor']}, {a['department']}, {_usd(a['monthly_cost_usd'])}/mo via {a['paid_via']}" for a in assets]
        return {"answer": f"{len(assets)} AI assets are not in the model registry:\n" + "\n".join(lines), "citations": _cite(self.kg, [a["id"] for a in assets]),
                "mermaid": None}

    def shadow_it(self) -> dict:
        out = None
        runs = [r for r in self.repo.all("agent_runs") if r["agent_id"] == "pf.app_discovery" and r["status"] == "completed"]
        if runs:
            out = max(runs, key=lambda r: r["started_at"])["output_json"]
        if not out:
            return {"answer": "Run Application Discovery first (Portfolio › Discovery).", "citations": [], "mermaid": None}
        new = [f for f in out["findings"] if f["type"] == "new_app"]
        refs = [r["record_id"] for f in new for r in f["source_refs"][:1]]
        return {"answer": f"Application Discovery found {len(new)} shadow IT candidates: " + ", ".join(f["candidate_name"] for f in new) + ".",
                "citations": [{"id": r, "type": "InvoiceLine", "name": r} for r in refs[:8]], "mermaid": None}

    def explain(self, node_id: str) -> dict | None:
        n = self.kg.node(node_id)
        if not n:
            return None
        nb = self.kg.neighbors(node_id, 1)
        rels: dict[str, int] = {}
        for e in nb["edges"]:
            rels[e["type"]] = rels.get(e["type"], 0) + 1
        props = ", ".join(f"{k}: {v}" for k, v in list(n["props_json"].items())[:8] if v not in (None, [], {}))
        return {"answer": f"**{n['name']}** [{node_id}] is a {n['type']} (status {n['status']}, confidence {n['confidence']}). "
                          f"{props}. Relationships: " + ", ".join(f"{k} ×{v}" for k, v in sorted(rels.items())) + ".",
                "citations": _cite(self.kg, [node_id] + [x["id"] for x in nb["nodes"][:6]]), "mermaid": None}

    def count_apps(self) -> dict:
        apps = [n for n in self.kg.by_type("Application") if n["status"] != "retired"]
        return {"answer": f"The inventory holds {len(apps)} applications.", "citations": _cite(self.kg, [a["id"] for a in apps[:5]]), "mermaid": None}

    def violations(self) -> dict:
        v = self.kg.violations()
        by: dict[str, int] = {}
        for x in v:
            by[x["standard_id"]] = by.get(x["standard_id"], 0) + 1
        return {"answer": f"{len(v)} open standard violations: " + ", ".join(f"[{k}] ×{n}" for k, n in sorted(by.items(), key=lambda kv: -kv[1])) + ".",
                "citations": _cite(self.kg, list(by)), "mermaid": None}


# ---- live mode --------------------------------------------------------------------------------

TOOLS = [
    {"name": "kg_search", "description": "Search knowledge-graph nodes by text and optional type (Application, Capability, Dataset, AIUseCase, AIAsset, API, Contract, Project, Goal, Person, Vendor, Standard, Pattern, Policy).",
     "input_schema": {"type": "object", "properties": {"q": {"type": "string"}, "type": {"type": "string"}}, "required": ["q"]}},
    {"name": "kg_neighbors", "description": "Nodes and edges around a node id (depth 1-2).",
     "input_schema": {"type": "object", "properties": {"id": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["id"]}},
    {"name": "kg_lineage", "description": "Upstream and downstream lineage of a dataset id.",
     "input_schema": {"type": "object", "properties": {"dataset_id": {"type": "string"}}, "required": ["dataset_id"]}},
    {"name": "kg_impact", "description": "Dependents of a node id up to depth 3, grouped by type.",
     "input_schema": {"type": "object", "properties": {"node_id": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["node_id"]}},
    {"name": "search_standards", "description": "Search architecture standards and data policies by keyword.",
     "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
    {"name": "search_patterns", "description": "Search reference patterns by keyword.",
     "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
]

LIVE_SYSTEM = """You are the Architecture Copilot of a fractional architecture office. Answer questions about the client's
application portfolio, capabilities, data, AI and standards using ONLY the tools provided. Every factual statement must
cite record ids in square brackets exactly as returned by the tools, e.g. [APP-0042]. If the tools do not return enough
evidence, say so. Plain language, short, no marketing tone. Use markdown lists for multiple items."""


def _slim(n: dict) -> dict:
    return {"id": n["id"], "type": n["type"], "name": n["name"], "props": {k: v for k, v in (n["props_json"] or {}).items()
                                                                           if not isinstance(v, (list, dict)) or k in ("tags",)}}


def _run_tool(tenant_id: str, name: str, args: dict) -> dict:
    kg = get_kg(tenant_id)
    repo = Repo(tenant_id)
    if name == "kg_search":
        res = kg.search(args.get("q"), args.get("type"), limit=15)
        if not res:
            n = _find(kg, args.get("q", ""), [args["type"]] if args.get("type") else ["Application", "Dataset", "Capability", "AIUseCase"])
            res = [n] if n else []
        return {"nodes": [_slim(n) for n in res]}
    if name == "kg_neighbors":
        nb = kg.neighbors(args["id"], min(2, args.get("depth", 1)), max_nodes=40)
        return {"nodes": [_slim(n) for n in nb["nodes"]], "edges": [{"type": e["type"], "from": e["from_id"], "to": e["to_id"]} for e in nb["edges"][:80]]}
    if name == "kg_lineage":
        up, down = kg.lineage_upstream(args["dataset_id"]), kg.lineage_downstream(args["dataset_id"])
        return {"upstream": {k: v for k, v in up.items() if k != "edges"}, "downstream": {k: v for k, v in down.items() if k != "edges"}}
    if name == "kg_impact":
        return kg.impact(args["node_id"], min(3, args.get("depth", 2)))
    if name == "search_standards":
        q = args["q"].lower()
        st = [s for s in repo.all("standards") if q in (s["title"] + s["rule_text"]).lower()]
        pol = [p for p in repo.all("data_policies") if q in (p["title"] + p["rule"] + p["regulation"]).lower()]
        return {"standards": [{"id": s["id"], "title": s["title"], "rule": s["rule_text"]} for s in st[:8]],
                "policies": [{"id": p["id"], "title": p["title"], "regulation": p["regulation"]} for p in pol[:8]]}
    if name == "search_patterns":
        q = args["q"].lower()
        ps = [p for p in repo.all("patterns") if q in (p["name"] + p["when_to_use"] + " ".join(p["keywords"])).lower()]
        return {"patterns": [{"id": p["id"], "name": p["name"], "when_to_use": p["when_to_use"], "standards": p["standard_ids"]} for p in ps[:5]]}
    return {"error": f"unknown tool {name}"}


def _ask_live(tenant_id: str, question: str, history: list[dict]) -> dict:
    from app.llm.client import AnthropicLLM, collect_ids  # noqa: F401

    llm = AnthropicLLM()
    messages = [{"role": m["role"], "content": m["content"]} for m in history[-6:] if m.get("role") in ("user", "assistant")]
    messages.append({"role": "user", "content": question})
    seen_ids: set[str] = set()
    cost = {"tokens_in": 0, "tokens_out": 0, "usd": 0.0, "model": llm.model}
    for _ in range(6):
        resp = llm.client.messages.create(model=llm.model, max_tokens=settings.max_output_tokens,
                                          system=[{"type": "text", "text": LIVE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                                          tools=TOOLS, messages=messages)
        c = llm.cost(resp.usage)
        for k in ("tokens_in", "tokens_out", "usd"):
            cost[k] += c[k]
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    out = _run_tool(tenant_id, b.name, b.input or {})
                    seen_ids |= set(re.findall(r'"([A-Z]{2,5}-[A-Za-z0-9-]+)"', json.dumps(out, default=str)))
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, default=str)[:20000]})
            messages.append({"role": "user", "content": results})
            continue
        text = "".join(b.text for b in resp.content if b.type == "text")
        cited = re.findall(r"\[([A-Z]{2,5}-[A-Za-z0-9-]+)\]", text)
        kg = get_kg(tenant_id)
        valid = [c for c in cited if c in seen_ids or kg.node(c)]
        return {"answer": text, "citations": _cite(kg, valid), "mermaid": None, "cost": cost,
                "uncited_warning": None if valid or not text else "Answer contains no verifiable citations."}
    return {"answer": "The live copilot did not finish within the tool-call budget.", "citations": [], "mermaid": None, "cost": cost}


def ask(tenant_id: str, question: str, history: list[dict] | None = None, user_id: str | None = None) -> dict:
    t0 = time.time()
    mode = "mock"
    if settings.llm_mode == "live":
        try:
            res = _ask_live(tenant_id, question, history or [])
            mode = "live"
        except Exception as exc:  # noqa: BLE001
            res = MockCopilot(tenant_id).answer(question, history)
            res["answer"] += f"\n\n_(Live copilot unavailable — answered deterministically: {exc})_"
            mode = "live-fallback"
    else:
        res = MockCopilot(tenant_id).answer(question, history)
    res["mode"] = mode
    res["duration_ms"] = int((time.time() - t0) * 1000)
    audit.log(tenant_id, "agent", "shared.copilot", "copilot_answered", "question", question[:80],
              {"user_id": user_id, "citations": [c["id"] for c in res["citations"]], "mode": mode})
    return res


def suggested(tenant_id: str) -> list[str]:
    return Repo(tenant_id).get_meta("copilot_questions", [])

