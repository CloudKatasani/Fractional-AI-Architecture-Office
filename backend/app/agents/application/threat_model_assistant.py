"""app.threat_model_assistant — STRIDE threat model for a design or application."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev

RULES = [
    # (component keywords, STRIDE, description, likelihood, impact, mitigation, standard)
    (["portal", "app", "widget", "ui", "channel", "desktop"], "Spoofing", "Attacker impersonates a user or channel session",
     "medium", "high", "Authenticate via the enterprise identity platform with MFA for privileged actions", "STD-SEC-01"),
    (["api", "service", "gateway", "bff", "worker", "engine"], "Denial of service", "Unthrottled calls exhaust the service",
     "medium", "medium", "Rate limiting and quotas at the API gateway", "STD-API-02"),
    (["database", "db", "store", "tables", "replica", "lake", "bucket"], "Tampering", "Direct write access alters system-of-record data",
     "medium", "high", "No direct DB access; publish APIs/events and restrict service accounts", "STD-INT-02"),
    (["database", "db", "store", "lake", "bucket", "crm", "cis", "billing"], "Information disclosure",
     "Confidential or personal data exposed through over-broad queries or copies", "high", "high",
     "Classify flows, encrypt, mask in non-production, least-privilege access", "STD-DATA-01"),
    (["llm", "genai", "openmind", "chatassist", "promptforge", "agent", "assistant", "bot", "azure openai"], "Information disclosure",
     "Prompt injection or data leakage to an AI vendor", "high", "high",
     "Use an approved GenAI platform, guardrails, no PII in prompts without DPIA", "STD-AI-01"),
    (["agent", "orchestrator", "autoheal", "job", "batch"], "Elevation of privilege", "Automated component acts beyond intended scope",
     "medium", "high", "Scoped credentials, approval gate for high-impact actions", "STD-AI-03"),
    (["service", "api", "worker", "agent", "job"], "Repudiation", "Actions cannot be traced to an actor",
     "low", "medium", "Structured audit logging to the observability platform", "STD-OBS-01"),
    (["scada", "historian", "ems", "adms", "ot", "inventory", "oss", "ran"], "Tampering",
     "Change to operational technology / network elements from a less trusted zone", "medium", "critical",
     "Enforce zone boundary (DMZ / TMF APIs); change control", "STD-OT-01"),
]


class ThreatModel(Finding):
    subject_id: str
    threats: list[dict]


class ThreatModelAssistant(Agent):
    id = "app.threat_model_assistant"
    name = "Threat Model Assistant"
    domain = "application"
    description = ("Builds a STRIDE table over a design's components and data flows, pulls data classification and maps "
                   "mitigations to standards.")
    inputs = ["design_docs", "applications", "standards"]
    outputs = "ThreatModel"
    finding_model = ThreatModel
    approver_role = "security_architect"
    default_autonomy = 2
    demo_trigger = "Model threats"
    action_types = ["publish_threat_model"]
    params_spec = [{"name": "design_id", "label": "Design submission", "kind": "select", "source": "designs"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        docs = ctx.repo.by_id("design_docs")
        did = ctx.params.get("design_id") or next(d["id"] for d in ctx.repo.all("design_docs") if d["components"])
        doc = docs[did]
        stds = ctx.repo.by_id("standards")
        apps = ctx.repo.by_id("applications")
        comps = doc["components"] or [apps[a]["name"] for a in doc["app_ids"]]
        threats = []
        for comp in comps:
            cl = comp.lower()
            for kws, stride, desc, lik, imp, mit, std in RULES:
                if any(k in cl for k in kws):
                    threats.append({"component": comp, "stride_category": stride, "description": desc, "likelihood": lik,
                                    "impact": imp, "mitigation": mit, "standard_id": std if std in stds else None})
        classes = sorted({apps[a]["data_classification"] for a in doc["app_ids"]})
        refs = [ev(did, "design_docs", f"{doc['title']}: components {', '.join(comps)}")]
        refs += [ev(a, "applications", f"{apps[a]['name']} ({apps[a]['data_classification']})") for a in doc["app_ids"][:3]]
        tm = ThreatModel(subject_id=did, threats=threats, source_refs=refs, title=doc["title"], data_classifications=classes)
        action = ProposedAction(action_type="publish_threat_model", target_id=did, target_type="Design",
                                payload={"threats": len(threats), "title": doc["title"]},
                                rationale=f"STRIDE model for {doc['title']}: {len(threats)} threats across {len(comps)} components.",
                                source_refs=refs, approver_role="security_architect", priority=3)
        facts = {"title": doc["title"], "ref": did, "n": len(threats), "components": len(comps),
                 "high": sum(1 for t in threats if t["impact"] in ("high", "critical") and t["likelihood"] in ("medium", "high"))}
        return AnalysisResult(findings=[tm], actions=[action], facts=facts, confidence=0.7)

    def narrative_key(self, ctx: AgentContext) -> str:
        return ctx.params.get("design_id") or "default"
