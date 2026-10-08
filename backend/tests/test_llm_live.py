"""Live-mode narrative path with a fake Anthropic client: validation, one retry, fallback (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.agents.base import AgentContext
from app.agents.registry import get_agent
from app.llm.client import AnthropicLLM


def _resp(text: str):  # noqa: ANN202
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0,
                                                 cache_read_input_tokens=800))


def _llm(responses: list[str]) -> AnthropicLLM:
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "claude-sonnet-4-5"
    from app.llm.client import MockLLM

    llm.mock = MockLLM()
    calls = []

    def fake_call(system, messages, max_tokens):  # noqa: ANN001, ANN202
        calls.append(messages)
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        return _resp(responses[min(len(calls) - 1, len(responses) - 1)])

    llm._call = fake_call  # type: ignore[method-assign]
    llm.calls = calls  # type: ignore[attr-defined]
    return llm


def test_live_valid_narrative(generated):
    agent = get_agent("pf.lifecycle_watcher")
    ctx = AgentContext("northgrid")
    res = agent.mock_run(ctx)
    findings, _ = agent.validate_findings(res.findings)
    ref = findings[0]["source_refs"][0]["record_id"]
    llm = _llm([json.dumps({"summary": f"OMS support ends soon [{ref}].", "order": [1, 0],
                            "notes": [{"index": 0, "note": "plan now", "source_refs": [ref]}]})])
    n = llm.narrate(agent, ctx, res, findings)
    assert n.mode == "live" and n.order == [1, 0] and n.cost.usd > 0 and len(llm.calls) == 1


def test_live_invented_id_is_retried_then_falls_back(generated):
    agent = get_agent("pf.lifecycle_watcher")
    ctx = AgentContext("northgrid")
    res = agent.mock_run(ctx)
    findings, _ = agent.validate_findings(res.findings)
    bad = json.dumps({"summary": "Retire APP-9999 now [APP-9999].", "order": [], "notes": []})
    llm = _llm([bad, bad])
    n = llm.narrate(agent, ctx, res, findings)
    assert len(llm.calls) == 2  # one retry with the validation error appended
    assert "Validation error" in llm.calls[1][-1]["content"]
    assert n.mode == "live-fallback" and "fell back" in n.summary


def test_live_retry_succeeds(generated):
    agent = get_agent("dai.ai_risk_classifier")
    ctx = AgentContext("northgrid", params={"usecase_id": "AIU-013"})
    res = agent.mock_run(ctx)
    findings, _ = agent.validate_findings(res.findings)
    good = json.dumps({"summary": "Dynamic pricing is high risk [AIU-013] under AIR-H4.", "order": [0], "notes": []})
    llm = _llm(["not json at all", good])
    n = llm.narrate(agent, ctx, res, findings)
    assert n.mode == "live" and len(llm.calls) == 2
