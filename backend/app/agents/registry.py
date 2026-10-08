"""Agent registry — the single source of truth for agent metadata (generates docs/AGENT_CATALOG.md)."""

from __future__ import annotations

from app.agents.application.adr_writer import ADRWriter
from app.agents.application.design_review import DesignReviewAgent
from app.agents.application.drift_detector import DriftDetector
from app.agents.application.integration_api_architect import IntegrationAPIArchitect
from app.agents.application.pattern_advisor import PatternAdvisor
from app.agents.application.tech_debt_radar import TechDebtRadar
from app.agents.application.threat_model_assistant import ThreatModelAssistant
from app.agents.base import Agent
from app.agents.data_ai.ai_ref_arch_generator import AIRefArchGenerator
from app.agents.data_ai.ai_risk_classifier import AIRiskClassifier
from app.agents.data_ai.ai_usecase_intake import AIUseCaseIntake
from app.agents.data_ai.data_product_designer import DataProductDesigner
from app.agents.data_ai.governance_policy_checker import GovernancePolicyChecker
from app.agents.data_ai.lineage_mapper import LineageMapper
from app.agents.data_ai.model_agent_registry_steward import ModelAgentRegistrySteward
from app.agents.enterprise.board_assistant import BoardAssistant
from app.agents.enterprise.capability_curator import CapabilityCurator
from app.agents.enterprise.impact_analyst import ImpactAnalyst
from app.agents.enterprise.investment_traceability import InvestmentTraceability
from app.agents.enterprise.roadmap_drafter import RoadmapDrafter
from app.agents.enterprise.strategy_capability_mapper import StrategyCapabilityMapper
from app.agents.portfolio.app_discovery import AppDiscovery
from app.agents.portfolio.business_case_builder import BusinessCaseBuilder
from app.agents.portfolio.cost_license_optimizer import CostLicenseOptimizer
from app.agents.portfolio.lifecycle_watcher import LifecycleWatcher
from app.agents.portfolio.overlap_finder import OverlapFinder
from app.agents.portfolio.time_classifier import TimeClassifier
from app.agents.shared.copilot import Copilot
from app.agents.shared.evidence_audit import EvidenceAudit
from app.agents.shared.exec_briefing import ExecBriefing
from app.agents.shared.graph_curator import GraphCurator
from app.agents.shared.orchestrator import Orchestrator


class DiagramGenerator(Agent):
    id = "shared.diagram_generator"
    name = "Diagram Generator"
    domain = "shared"
    description = ("Produces Mermaid diagrams from the knowledge graph: capability map, C4-style context for an "
                   "application, data flow for a dataset, integration map for a capability.")
    inputs = ["kg_nodes", "kg_edges"]
    outputs = "Mermaid text"
    default_autonomy = 1
    demo_trigger = "Render diagram"
    runnable = False


_CLASSES: list[type[Agent]] = [
    # Enterprise
    StrategyCapabilityMapper, CapabilityCurator, InvestmentTraceability, RoadmapDrafter, ImpactAnalyst, BoardAssistant,
    # Application
    DesignReviewAgent, ADRWriter, PatternAdvisor, DriftDetector, IntegrationAPIArchitect, TechDebtRadar, ThreatModelAssistant,
    # Portfolio
    AppDiscovery, CostLicenseOptimizer, OverlapFinder, TimeClassifier, LifecycleWatcher, BusinessCaseBuilder,
    # Data & AI
    LineageMapper, DataProductDesigner, GovernancePolicyChecker, AIUseCaseIntake, AIRiskClassifier, AIRefArchGenerator,
    ModelAgentRegistrySteward,
    # Shared
    Orchestrator, GraphCurator, Copilot, DiagramGenerator, EvidenceAudit, ExecBriefing,
]

AGENTS: dict[str, Agent] = {cls.id: cls() for cls in _CLASSES}

DOMAIN_LABELS = {"enterprise": "Enterprise Architecture", "application": "Application Architecture",
                 "portfolio": "Portfolio Architecture", "data_ai": "Data & AI Architecture", "shared": "Shared"}

# Seeded acceptance history so the Agents page can show promotion guidance (80%/4 weeks -> L2; 90%/8 weeks -> L3).
SEED_ACCEPTANCE = {
    "pf.app_discovery": (37, 41), "pf.cost_license_optimizer": (22, 27), "pf.overlap_finder": (9, 11),
    "pf.time_classifier": (31, 40), "pf.lifecycle_watcher": (18, 19), "pf.business_case_builder": (4, 5),
    "dai.governance_policy_checker": (44, 48), "dai.ai_risk_classifier": (15, 17), "dai.ai_usecase_intake": (8, 11),
    "dai.model_agent_registry_steward": (12, 14), "dai.data_product_designer": (3, 5), "dai.ai_ref_arch_generator": (4, 5),
    "app.design_review": (26, 29), "app.adr_writer": (19, 20), "app.drift_detector": (23, 25),
    "app.integration_api_architect": (7, 9), "app.tech_debt_radar": (11, 15), "app.threat_model_assistant": (5, 7),
    "ea.strategy_capability_mapper": (13, 18), "ea.capability_curator": (10, 12), "ea.investment_traceability": (9, 10),
    "ea.roadmap_drafter": (2, 3), "ea.board_assistant": (6, 6),
}


def get_agent(agent_id: str) -> Agent:
    try:
        return AGENTS[agent_id]
    except KeyError as exc:
        raise KeyError(f"unknown agent {agent_id}") from exc


def catalog_markdown() -> str:
    lines = ["# Agent Catalog", "", "Generated from `backend/app/agents/registry.py` (single source of truth). "
             "Regenerate with `make docs`.", ""]
    for dom, label in DOMAIN_LABELS.items():
        lines += [f"## {label}", "", "| id | Name | Inputs | Output | Actions | Approver | Default autonomy | Demo trigger |",
                  "|---|---|---|---|---|---|---|---|"]
        for a in AGENTS.values():
            if a.domain != dom:
                continue
            lines.append(f"| `{a.id}` | {a.name} | {', '.join(a.inputs)} | {a.outputs} | {', '.join(a.action_types) or '—'} | "
                         f"{a.approver_role or '—'} | L{a.default_autonomy} | {a.demo_trigger} |")
        lines.append("")
        for a in AGENTS.values():
            if a.domain == dom:
                lines.append(f"- **{a.name}** — {a.description}")
        lines.append("")
    return "\n".join(lines)
