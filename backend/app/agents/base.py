"""Common agent contract (Section 7.1).

Every agent:
  * gathers data via ctx.repo / ctx.kg,
  * computes findings deterministically in `mock_run` (also the "tool layer" in live mode),
  * asks ctx.llm for the narrative (mock: Jinja template; live: Anthropic, which may only rank / explain),
  * validates every finding against its typed schema with non-empty source_refs (retry once, then flag),
  * persists agent_runs + audit_events and, at autonomy >= L2, approval rows for each proposed action.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import cached_property
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import TENANT_CATALOG, demo_today
from app.db.session import Repo

log = logging.getLogger("arch_office.agents")


class Evidence(BaseModel):
    record_id: str
    table: str
    excerpt: str | None = None


class Finding(BaseModel):
    """Base finding: every agent-specific finding schema extends this and must cite at least one record."""

    model_config = ConfigDict(extra="allow")
    source_refs: list[Evidence] = Field(min_length=1)


class ProposedAction(BaseModel):
    action_type: str
    target_id: str
    target_type: str = ""
    payload: dict = Field(default_factory=dict)
    rationale: str
    source_refs: list[Evidence] = Field(min_length=1)
    approver_role: str
    priority: int = 3  # 1 = most urgent; used for "decisions needed this week"


class LLMCost(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    model: str | None = None


class AgentOutput(BaseModel):
    agent_id: str
    tenant_id: str
    run_id: str
    summary: str
    findings: list[dict]
    proposed_actions: list[ProposedAction]
    confidence: float
    cost: LLMCost | None = None
    duration_ms: int
    # extras (not in the minimal contract but useful to the UI)
    agent_name: str = ""
    autonomy_level: int = 2
    mode: str = "observe"  # observe (L1) | propose (L2+)
    llm_mode: str = "mock"
    flagged: list[dict] = Field(default_factory=list)
    artifacts: dict = Field(default_factory=dict)  # e.g. mermaid diagrams, markdown bodies
    approvals_created: list[str] = Field(default_factory=list)
    narrative_notes: list[dict] = Field(default_factory=list)
    started_at: str = ""


@dataclass
class AnalysisResult:
    findings: list[Finding]
    actions: list[ProposedAction] = field(default_factory=list)
    facts: dict = field(default_factory=dict)  # inputs to the narrative template / LLM
    confidence: float = 0.9
    artifacts: dict = field(default_factory=dict)


def ev(record_id: str, table: str, excerpt: Any = None) -> Evidence:
    return Evidence(record_id=str(record_id), table=table, excerpt=None if excerpt is None else str(excerpt)[:240])


@dataclass
class AgentContext:
    tenant_id: str
    params: dict = field(default_factory=dict)
    user_id: str | None = None
    trigger: str = "ui"
    run_id: str = field(default_factory=lambda: "RUN-" + uuid.uuid4().hex[:10].upper())
    llm: Any = None

    @cached_property
    def repo(self) -> Repo:
        return Repo(self.tenant_id)

    @property
    def kg(self):  # noqa: ANN201
        from app.kg.queries import get_kg

        return get_kg(self.tenant_id)

    @property
    def today(self) -> date:
        return demo_today()

    @cached_property
    def catalog(self) -> dict:
        from data_gen.generators.core import load_yaml

        return load_yaml(TENANT_CATALOG[self.tenant_id])

    @cached_property
    def common(self) -> dict:
        from data_gen.generators.core import load_yaml

        return load_yaml("common")

    @cached_property
    def risk_rules(self) -> dict:
        from data_gen.generators.core import load_yaml

        return load_yaml("ai_risk_rules")

    @cached_property
    def tenant(self) -> dict:
        return self.repo.all("tenants")[0]

    def user_name(self, user_id: str | None) -> str:
        if not user_id:
            return "unassigned"
        u = self.repo.get("users", user_id)
        return u["name"] if u else user_id

    def days_until(self, iso: str | None) -> int | None:
        if not iso:
            return None
        return (date.fromisoformat(iso[:10]) - self.today).days

    def latest_output(self, agent_id: str) -> dict | None:
        runs = [r for r in self.repo.all("agent_runs") if r["agent_id"] == agent_id and r["status"] == "completed"]
        if not runs:
            return None
        return max(runs, key=lambda r: r["started_at"])["output_json"]


class Agent:
    id: ClassVar[str]
    name: ClassVar[str]
    domain: ClassVar[str]  # enterprise | application | portfolio | data_ai | shared
    description: ClassVar[str]
    inputs: ClassVar[list[str]] = []
    outputs: ClassVar[str] = ""
    finding_model: ClassVar[type[Finding]] = Finding
    approver_role: ClassVar[str | None] = None
    default_autonomy: ClassVar[int] = 2
    demo_trigger: ClassVar[str] = "Run"
    action_types: ClassVar[list[str]] = []
    params_spec: ClassVar[list[dict]] = []  # [{name, label, kind: select|text, source: designs|usecases|...}]
    runnable: ClassVar[bool] = True
    max_actions: ClassVar[int] = 60

    # ---- to implement --------------------------------------------------------------------
    def mock_run(self, ctx: AgentContext) -> AnalysisResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def narrative_key(self, ctx: AgentContext) -> str:
        """Key for llm/mock_responses/{agent_id}/{key}.json overrides."""
        return "_".join(str(v) for v in ctx.params.values()) or "default"

    # ---- framework -----------------------------------------------------------------------
    def meta(self) -> dict:
        return {
            "id": self.id, "name": self.name, "domain": self.domain, "description": self.description,
            "inputs": self.inputs, "outputs": self.outputs, "approver_role": self.approver_role,
            "default_autonomy": self.default_autonomy, "demo_trigger": self.demo_trigger, "action_types": self.action_types,
            "params_spec": self.params_spec, "runnable": self.runnable,
            "finding_schema": self.finding_model.model_json_schema() if self.finding_model is not Finding else None,
        }

    def validate_findings(self, raw: list[Finding | dict]) -> tuple[list[dict], list[dict]]:
        valid, invalid = [], []
        for f in raw:
            data = f.model_dump() if isinstance(f, BaseModel) else f
            if isinstance(data.get("source_refs"), list):  # de-duplicate citations, keep order
                seen: set[str] = set()
                data["source_refs"] = [r for r in data["source_refs"]
                                       if not (r.get("record_id") in seen or seen.add(r.get("record_id")))]
            try:
                valid.append(self.finding_model.model_validate(data).model_dump())
            except ValidationError as exc:
                invalid.append({"finding": data, "error": exc.errors(include_url=False)})
        return valid, invalid

    def run(self, ctx: AgentContext) -> AgentOutput:
        from app.llm.client import get_llm
        from app.orchestrator import approval_gate
        from app.services import audit, settings_service

        ctx.llm = ctx.llm or get_llm()
        started = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
        t0 = time.time()
        autonomy = settings_service.autonomy_for(ctx.tenant_id, self.id)
        audit.log(ctx.tenant_id, "agent", self.id, "agent_run_started", "agent_run", ctx.run_id,
                  {"params": ctx.params, "trigger": ctx.trigger, "autonomy_level": autonomy}, run_id=ctx.run_id)
        try:
            result = self.mock_run(ctx)
            valid, invalid = self.validate_findings(result.findings)
            flagged: list[dict] = []
            if invalid:
                # P1: retry once (deterministic re-computation), then flag what still fails.
                retry = self.mock_run(ctx)
                valid, invalid = self.validate_findings(retry.findings)
                result = retry
                flagged = [{"reason": "missing or invalid source_refs", **i} for i in invalid]
            actions = [a for a in result.actions if a.source_refs][: self.max_actions]
            narrative = ctx.llm.narrate(self, ctx, result, valid)
            output = AgentOutput(
                agent_id=self.id, tenant_id=ctx.tenant_id, run_id=ctx.run_id, summary=narrative.summary,
                findings=_order(valid, narrative.order), proposed_actions=actions, confidence=round(result.confidence, 2),
                cost=narrative.cost, duration_ms=int((time.time() - t0) * 1000), agent_name=self.name,
                autonomy_level=autonomy, mode="observe" if autonomy <= 1 else "propose", llm_mode=narrative.mode,
                flagged=flagged, artifacts=_jsonable(result.artifacts), narrative_notes=narrative.notes, started_at=started,
            )
            if autonomy >= 2 and actions:
                output.approvals_created = approval_gate.create_approvals(ctx, self, actions)
            status = "completed"
        except Exception as exc:  # noqa: BLE001
            log.exception("agent %s failed", self.id)
            audit.log(ctx.tenant_id, "agent", self.id, "agent_run_failed", "agent_run", ctx.run_id, {"error": str(exc)},
                      run_id=ctx.run_id)
            _persist_run(ctx, self, started, None, "failed", autonomy, {"error": str(exc)})
            raise
        _persist_run(ctx, self, started, output, status, autonomy)
        settings_service.touch_last_run(ctx.tenant_id, self.id, started)
        audit.log(ctx.tenant_id, "agent", self.id, "agent_run_completed", "agent_run", ctx.run_id, {
            "findings": len(output.findings), "proposed_actions": len(actions), "approvals_created": len(output.approvals_created),
            "duration_ms": output.duration_ms, "llm_mode": output.llm_mode, "flagged": len(flagged),
        }, run_id=ctx.run_id)
        log.info(json.dumps({"event": "agent_run", "run_id": ctx.run_id, "tenant": ctx.tenant_id, "agent": self.id,
                             "findings": len(output.findings), "ms": output.duration_ms}))
        return output


def _order(findings: list[dict], order: list[int] | None) -> list[dict]:
    if not order:
        return findings
    seen = [i for i in order if 0 <= i < len(findings)]
    rest = [i for i in range(len(findings)) if i not in seen]
    return [findings[i] for i in dict.fromkeys(seen + rest)]


def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def _persist_run(ctx: AgentContext, agent: Agent, started: str, output: AgentOutput | None, status: str, autonomy: int,
                 error: dict | None = None) -> None:
    ctx.repo.insert("agent_runs", {
        "id": ctx.run_id, "tenant_id": ctx.tenant_id, "agent_id": agent.id, "trigger": ctx.trigger,
        "input_json": ctx.params, "output_json": output.model_dump() if output else error, "status": status,
        "started_at": started, "finished_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "cost_json": output.cost.model_dump() if output and output.cost else None, "autonomy_level": autonomy,
        "user_id": ctx.user_id,
    })
