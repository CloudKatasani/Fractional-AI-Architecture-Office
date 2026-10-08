"""LLM abstraction: MockLLM (deterministic, offline) and AnthropicLLM (live).

Both receive the same deterministic tool results (the agent's mock_run output). The LLM only writes the
narrative, ranks findings and adds explanatory notes; it never introduces facts. In live mode every note must
cite record ids that exist in the tool results - otherwise the response is rejected and retried once with the
validation error appended, then we fall back to the mock narrative (and say so).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.config import settings

log = logging.getLogger("arch_office.llm")
LLM_DIR = Path(__file__).resolve().parent
PROMPTS = LLM_DIR / "prompts"
TEMPLATES = LLM_DIR / "templates"
MOCK_RESPONSES = LLM_DIR / "mock_responses"

# USD per 1M tokens (input, output) for cost display; unknown models fall back to the first row.
PRICING = {
    "claude-sonnet-4-5": (3.0, 15.0), "claude-sonnet-4-6": (3.0, 15.0), "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0), "claude-haiku-5-5": (0.10, 0.50),
}


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape([]), undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["usd"] = lambda v: f"${(v or 0):,.0f}"
    env.filters["refs"] = lambda ids, n=3: ", ".join(f"[{i}]" for i in list(ids)[:n])
    env.filters["plural"] = lambda n, word, pl=None: f"{n} {word if n == 1 else (pl or word + 's')}"
    return env


@dataclass
class Narrative:
    summary: str
    order: list[int] | None = None
    notes: list[dict] = field(default_factory=list)
    cost: Any = None
    mode: str = "mock"


def collect_ids(obj: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "record_id" and isinstance(v, str):
                ids.add(v)
            else:
                ids |= collect_ids(v)
    elif isinstance(obj, list):
        for v in obj:
            ids |= collect_ids(v)
    return ids


class MockLLM:
    mode = "mock"

    def __init__(self) -> None:
        self.env = _env()

    def narrate(self, agent, ctx, result, findings: list[dict]) -> Narrative:  # noqa: ANN001
        key = agent.narrative_key(ctx)
        override = MOCK_RESPONSES / agent.id / f"{ctx.tenant_id}_{key}.json"
        if override.exists():
            data = json.loads(override.read_text())
            return Narrative(summary=data["summary"], notes=data.get("notes", []), mode="mock")
        return Narrative(summary=self.render(agent.id, result.facts, findings), mode="mock")

    def render(self, agent_id: str, facts: dict, findings: list[dict]) -> str:
        tpl_path = TEMPLATES / f"{agent_id}.jinja"
        if not tpl_path.exists():
            return f"{len(findings)} findings."
        text = self.env.get_template(f"{agent_id}.jinja").render(f=facts, findings=findings, n=len(findings))
        return re.sub(r"\s+", " ", text).strip()

    # Copilot mock is pattern-based and lives in agents/shared/copilot.py
    def complete(self, prompt: str, schema: dict | None = None) -> dict:
        return {"text": "", "mode": "mock"}


class AnthropicLLM:
    mode = "live"

    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
        self.model = settings.anthropic_model
        self.mock = MockLLM()

    def cost(self, usage) -> dict:  # noqa: ANN001
        pin, pout = PRICING.get(self.model, (3.0, 15.0))
        tin = (usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        usd = (tin * pin + cached * pin * 0.1 + (usage.output_tokens or 0) * pout) / 1_000_000
        return {"tokens_in": tin + cached, "tokens_out": usage.output_tokens or 0, "usd": round(usd, 5), "model": self.model}

    def _system(self, agent_id: str) -> list[dict]:
        p = PROMPTS / f"{agent_id}.md"
        text = p.read_text() if p.exists() else (PROMPTS / "_common.md").read_text()
        # Static prompt first and cached (prefix caching); tool results go in the user turn.
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    def _call(self, system: list[dict], messages: list[dict], max_tokens: int):  # noqa: ANN202
        return self.client.messages.create(model=self.model, max_tokens=max_tokens, system=system, messages=messages)

    @staticmethod
    def _text(resp) -> str:  # noqa: ANN001
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    @staticmethod
    def _parse_json(text: str) -> dict:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("no JSON object in response")
        return json.loads(m.group(0))

    def narrate(self, agent, ctx, result, findings: list[dict]) -> Narrative:  # noqa: ANN001
        from app.agents.base import LLMCost

        tool_results = {"agent": agent.id, "tenant": ctx.tenant_id, "facts": result.facts,
                        "findings": [{"index": i, **f} for i, f in enumerate(findings[:80])]}
        allowed = collect_ids(tool_results["findings"]) | collect_ids(result.facts)
        user = (
            "Tool results (the only facts you may use):\n```json\n" + json.dumps(tool_results, default=str)[:180_000]
            + "\n```\nReturn ONLY a JSON object: {\"summary\": str (1-3 sentences, plain language, cite record ids "
              "in brackets), \"order\": [finding indices, most important first], \"notes\": [{\"index\": int, "
              "\"note\": str, \"source_refs\": [record ids from that finding]}]}"
        )
        messages: list[dict] = [{"role": "user", "content": user}]
        total = {"tokens_in": 0, "tokens_out": 0, "usd": 0.0, "model": self.model}
        last_err = None
        for attempt in range(2):
            try:
                resp = self._call(self._system(agent.id), messages, settings.max_output_tokens)
                c = self.cost(resp.usage)
                for k in ("tokens_in", "tokens_out", "usd"):
                    total[k] += c[k]
                if resp.stop_reason == "refusal":
                    raise ValueError("model declined the request")
                text = self._text(resp)
                data = self._parse_json(text)
                self._validate(data, allowed, len(findings))
                return Narrative(summary=data["summary"], order=data.get("order"), notes=data.get("notes", []),
                                 cost=LLMCost(**total), mode="live")
            except Exception as exc:  # noqa: BLE001 - validation or API error, retry once then fall back
                last_err = str(exc)
                log.warning("live narrative failed for %s (attempt %d): %s", agent.id, attempt + 1, exc)
                if attempt == 0 and "text" in locals():
                    messages = messages + [{"role": "assistant", "content": text},
                                           {"role": "user", "content": f"Validation error: {exc}. Fix it and return only the JSON object."}]
        n = self.mock.narrate(agent, ctx, result, findings)
        n.summary += f" (Live narrative unavailable — fell back to deterministic summary: {last_err})"
        n.cost = LLMCost(**total)
        n.mode = "live-fallback"
        return n

    @staticmethod
    def _validate(data: dict, allowed: set[str], n: int) -> None:
        if not isinstance(data.get("summary"), str) or not data["summary"].strip():
            raise ValueError("summary missing")
        cited = set(re.findall(r"\b[A-Z]{2,5}-[A-Z0-9-]{2,12}\b", data["summary"]))
        unknown = {c for c in cited if c not in allowed and not c.startswith(("STD-", "POL-", "AIR-", "CTL-", "PAT-"))}
        if unknown:
            raise ValueError(f"summary cites ids not present in tool results: {sorted(unknown)[:5]}")
        for note in data.get("notes", []):
            if not note.get("source_refs"):
                raise ValueError("every note needs source_refs")
            bad = [r for r in note["source_refs"] if r not in allowed]
            if bad:
                raise ValueError(f"note cites unknown ids {bad[:5]}")
        for i in data.get("order") or []:
            if not isinstance(i, int) or not 0 <= i < max(n, 1):
                raise ValueError("order contains invalid index")

    def complete(self, prompt: str, schema: dict | None = None) -> dict:
        resp = self._call([{"type": "text", "text": (PROMPTS / "_common.md").read_text()}],
                          [{"role": "user", "content": prompt}], settings.max_output_tokens)
        return {"text": self._text(resp), "cost": self.cost(resp.usage), "mode": "live"}


_llm: Any = None


def get_llm():  # noqa: ANN201
    global _llm
    want = "live" if settings.llm_mode == "live" else "mock"
    if _llm is None or _llm.mode != want:
        _llm = AnthropicLLM() if want == "live" else MockLLM()
    return _llm


def set_mode(mode: str) -> None:
    settings.llm_mode = mode
    get_llm()
