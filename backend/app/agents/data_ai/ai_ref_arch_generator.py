"""dai.ai_ref_arch_generator — reference architecture for a use case's AI pattern."""

from __future__ import annotations

from app.agents.base import Agent, AgentContext, AnalysisResult, Finding, ProposedAction, ev
from app.agents.data_ai.ai_risk_classifier import classify

TEMPLATES = {
    "rag": {
        "components": ["Channel / UI", "Orchestrator", "Retriever", "Vector index", "{platform}", "Guardrails", "Eval harness", "Audit log"],
        "mermaid": "flowchart LR\n  U[Channel / UI] --> O[Orchestrator]\n  O --> R[Retriever] --> V[(Vector index)]\n"
                   "  V -.-> D[(\"{data}\")]\n  O --> L[\"{platform}\"]\n  O --> G[Guardrails]\n  O -.-> A[(Audit log)]\n  E[Eval harness] -.-> O",
        "eval": ["Groundedness on a reviewed Q&A set (>= 90%)", "PII leakage red-team", "Answer refusal accuracy", "Latency p95 < 3s"],
        "cost": "$2k-$10k / month",
    },
    "agent_tools": {
        "components": ["Agent runtime", "{platform}", "Tool registry", "Approval gate", "Target systems", "Audit log", "Kill switch"],
        "mermaid": "flowchart LR\n  T[Trigger] --> A[Agent runtime]\n  A --> L[\"{platform}\"]\n  A --> TR[Tool registry]\n"
                   "  TR --> G{{Approval gate}}\n  G -->|approved| S[Target systems]\n  G -.-> AU[(Audit log)]\n  K[Kill switch] -.-> A\n  D[(\"{data}\")] -.-> A",
        "eval": ["Action accuracy on replayed incidents", "Blast-radius limits enforced", "Rollback tested", "Human override rate tracked"],
        "cost": "$5k-$20k / month",
    },
    "fine_tune": {
        "components": ["Training data store", "Labelling", "Fine-tune job", "Model registry", "Serving endpoint", "Monitoring"],
        "mermaid": "flowchart LR\n  D[(\"{data}\")] --> LB[Labelling] --> FT[Fine-tune job] --> MR[Model registry] --> S[Serving] --> M[Monitoring]",
        "eval": ["Holdout accuracy vs baseline", "Bias by segment", "Drift monitoring"],
        "cost": "$10k-$40k one-off + serving",
    },
    "classic_ml": {
        "components": ["Feature store", "Training pipeline", "Model registry", "Batch / online scoring", "Consuming application", "Monitoring"],
        "mermaid": "flowchart LR\n  D[(\"{data}\")] --> FS[(Feature store)] --> TR[Training] --> MR[Model registry]\n"
                   "  MR --> SC[Scoring] --> APP[Consuming app]\n  SC -.-> MON[Monitoring]",
        "eval": ["Backtest on 12 months", "Calibration", "Feature drift alerts", "Champion / challenger"],
        "cost": "$1k-$5k / month",
    },
    "vision": {
        "components": ["Image capture", "Image store", "Labelling", "Vision model", "Model registry", "Review queue", "Work management"],
        "mermaid": "flowchart LR\n  C[Capture] --> IS[(Image store)] --> VM[Vision model] --> RQ[Review queue] --> WM[Work management]\n"
                   "  LB[Labelling] --> VM\n  VM -.-> MR[Model registry]\n  D[(\"{data}\")] -.-> VM",
        "eval": ["Precision / recall on labelled set", "False-negative review", "Throughput per inspection season"],
        "cost": "$3k-$15k / month",
    },
}


class ReferenceArchitecture(Finding):
    usecase_id: str
    pattern: str
    components: list[str]
    diagram_mermaid: str
    controls: list[dict]
    eval_plan: list[str]
    cost_band: str


class AIRefArchGenerator(Agent):
    id = "dai.ai_ref_arch_generator"
    name = "AI Reference Architecture Generator"
    domain = "data_ai"
    description = ("Emits a reference design for a use case's pattern (RAG, agent with tools, fine-tune, classic ML, "
                   "vision): components on approved platforms, data-flow diagram, security controls, eval plan, cost band.")
    inputs = ["ai_usecases", "patterns", "standards", "datasets"]
    outputs = "ReferenceArchitecture"
    finding_model = ReferenceArchitecture
    approver_role = "principal_architect"
    default_autonomy = 2
    demo_trigger = "Generate reference design"
    action_types = ["approve_reference_design"]
    params_spec = [{"name": "usecase_id", "label": "Use case", "kind": "select", "source": "usecases"}]

    def mock_run(self, ctx: AgentContext) -> AnalysisResult:
        ucs = ctx.repo.by_id("ai_usecases")
        uid = ctx.params.get("usecase_id") or sorted(ucs)[0]
        u = ucs[uid]
        ds = ctx.repo.by_id("datasets")
        tpl = TEMPLATES[u["pattern"]]
        platform = ctx.common["approved_genai_platforms"][0] if u["pattern"] in ("rag", "agent_tools") else "ModelHub ML Platform"
        data = ", ".join(ds[d]["name"] for d in u["dataset_ids"][:2]) or "source data"
        risk = classify(ctx, u)
        controls = [{"id": c["id"], "title": c["title"], "source": c["source"]} for c in risk["controls"]]
        std_ids = {"rag": ["STD-AI-01", "STD-AI-02", "STD-DATA-01"], "agent_tools": ["STD-AI-01", "STD-AI-02", "STD-AI-03"],
                   "classic_ml": ["STD-AI-02", "STD-DATA-03"], "vision": ["STD-AI-02", "STD-DATA-01"],
                   "fine_tune": ["STD-AI-02", "STD-DATA-02"]}[u["pattern"]]
        stds = ctx.repo.by_id("standards")
        controls += [{"id": s, "title": stds[s]["title"], "source": s} for s in std_ids if s in stds]
        if any(ds[d]["pii"] for d in u["dataset_ids"]):
            controls.append({"id": "STD-DATA-02", "title": "PII masked in non-production", "source": "STD-DATA-02"})
        mermaid = tpl["mermaid"].replace("{platform}", platform).replace("{data}", data)
        refs = [ev(u["id"], "ai_usecases", f"{u['title']} (pattern {u['pattern']})")]
        refs += [ev(d, "datasets", ds[d]["name"]) for d in u["dataset_ids"][:2]]
        refs += [ev(s, "standards", stds[s]["title"]) for s in std_ids if s in stds][:2]
        ra = ReferenceArchitecture(usecase_id=uid, pattern=u["pattern"], components=[c.replace("{platform}", platform) for c in tpl["components"]],
                                   diagram_mermaid=mermaid, controls=controls, eval_plan=tpl["eval"], cost_band=tpl["cost"],
                                   source_refs=refs, title=u["title"], risk_tier=risk["tier"], platform=platform)
        action = ProposedAction(action_type="approve_reference_design", target_id=uid, target_type="AIUseCase",
                                payload={"pattern": u["pattern"], "platform": platform, "controls": [c["id"] for c in controls]},
                                rationale=f"Reference design for '{u['title']}' on {platform} with {len(controls)} controls.",
                                source_refs=refs, approver_role="principal_architect", priority=3)
        facts = {"title": u["title"], "ref": uid, "pattern": u["pattern"], "platform": platform, "n_controls": len(controls),
                 "tier": risk["tier"], "cost": tpl["cost"]}
        return AnalysisResult(findings=[ra], actions=[] if risk["tier"] == "unacceptable" else [action], facts=facts,
                              confidence=0.82, artifacts={"diagram_mermaid": mermaid})

    def narrative_key(self, ctx: AgentContext) -> str:
        return ctx.params.get("usecase_id") or "default"
