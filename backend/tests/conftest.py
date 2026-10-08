"""Test fixtures: generate both tenants once per session into an isolated data directory."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="arch_office_test_"))
os.environ["DATA_DIR"] = str(_TMP)
os.environ["DEMO_TODAY"] = "2026-10-07"
os.environ["LLM_MODE"] = "mock"
os.environ["SEED"] = "42"

import pytest  # noqa: E402
from app.config import settings  # noqa: E402

settings.data_dir = _TMP
settings.llm_mode = "mock"


@pytest.fixture(scope="session")
def generated() -> dict:
    from data_gen.generate import generate

    ctxs = {}
    for t in ("northgrid", "meridian"):
        ctxs[t] = generate(t, 42, quiet=True)
    return ctxs


@pytest.fixture(scope="session")
def client(generated):  # noqa: ANN001, ANN201
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def run_agent(tenant: str, agent_id: str, **params):  # noqa: ANN201
    from app.agents.base import AgentContext
    from app.agents.registry import get_agent

    return get_agent(agent_id).run(AgentContext(tenant_id=tenant, params=params, trigger="ui"))


def analyze(tenant: str, agent_id: str, **params):  # noqa: ANN201
    from app.agents.base import AgentContext
    from app.agents.registry import get_agent

    return get_agent(agent_id).mock_run(AgentContext(tenant_id=tenant, params=params))
