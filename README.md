# Fractional AI Architecture Office — prototype

A runnable, demo-grade prototype that shows how AI agents plus a human decision gate deliver **Enterprise, Application,
Portfolio and Data & AI Architecture as a service**, on two synthetic clients: **NorthGrid Energy** (electric & gas utility)
and **Meridian Telecom** (mobile + fixed broadband).

*Agents propose, humans decide.* Every fact an agent shows cites a source record; nothing becomes official without a human
approval recorded in the audit log.

```bash
make setup     # Python deps (pip/uv) + npm install
make demo      # generates data if missing, starts API :8000 and UI :5173
```

Open http://localhost:5173 and follow [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) (15 minutes). The demo runs fully offline in
**mock mode** (default, deterministic, no API key). For **live mode** set `LLM_MODE=live` and `ANTHROPIC_API_KEY` in `.env`
(or click the *Mock LLM* badge once the key is set).

| Command | What it does |
|---|---|
| `make setup` | install Python requirements and frontend packages, create `.env` from `.env.example` |
| `make data` | generate both tenants if their DB is missing (`python -m data_gen.generate --all`) |
| `make reset` | regenerate both tenants from the seed and regenerate the docs |
| `make api` / `make ui` | run the FastAPI backend (http://localhost:8000/docs) / the Vite dev server |
| `make demo` | `data` + API in the background + UI in the foreground; `make stop` stops the API |
| `make build` | build the static UI into `frontend/dist` (then served by the API at http://localhost:8000) |
| `make test` | pytest with coverage (agents, kg, data_gen) |
| `make docs` | regenerate `docs/AGENT_CATALOG.md`, `docs/DEMO_SCRIPT.md`, `data_gen/README.md` |
| `make lint` | ruff + TypeScript + eslint |

Requirements: Python 3.12+, Node 18+. Configuration (`.env`): `LLM_MODE`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `SEED`,
`DEMO_TODAY` (all synthetic dates are relative to it), `DATA_DIR`.

## Architecture

```
 data_gen/ (catalogs YAML + seeded generators) ──► data/{tenant}.db  (SQLite, one per tenant)
                                                    │  source tables · gt_* ground truth
                                                    │  kg_nodes / kg_edges  (knowledge graph)
                                                    │  agent_runs · approvals · audit_events · agent_settings · tickets
 backend/app/
   kg/          build.py (deterministic graph build) · queries.py (NetworkX: neighbors, lineage, impact, path,
                orphans, violations) · export.py (Mermaid: capability map, C4 context, data flow, integration map, drift)
   agents/      base.py (Agent, AgentOutput, Evidence, validation, persistence)  registry.py (single source of truth)
                enterprise/ application/ portfolio/ data_ai/ shared/   — 32 agents, 26 directly runnable
   llm/         client.py (MockLLM | AnthropicLLM) · prompts/{agent_id}.md · templates/{agent_id}.jinja · mock_responses/
   orchestrator/approval_gate.py (draft-first gate, roles, dedupe)   agents/shared/graph_curator.py (applies decisions)
   routers/     /api/v1 … tenants, users, metrics, kg, portfolio, ai, app, ea, data, agents, runs, approvals, audit,
                copilot, evidence, briefing, raw, admin
 frontend/      React 18 + Vite + TS + Tailwind + Recharts + react-force-graph-2d + Mermaid
```

**Agent contract.** `Agent.run(ctx)` → `mock_run` computes typed findings deterministically from the data (this is also the
tool layer in live mode) → every finding is validated against the agent's Pydantic `Finding` schema with non-empty
`source_refs` (retry once, then flag) → the LLM (mock template or Claude) writes the summary and ranks findings using only the
tool results → `agent_runs` + `audit_events` are written → at autonomy ≥ L2 each `ProposedAction` becomes a pending row in
`approvals`. A human decision (`POST /approvals/{id}/decide`) is the only way anything becomes approved; the graph curator then
applies it to the knowledge graph and, at L3, executes simulated side effects (Jira tickets, ADR publication).

**Autonomy levels** (per agent, per tenant, Agents page): L1 observe · L2 propose · L3 act with approval · L4 display only.

See [`docs/AGENT_CATALOG.md`](docs/AGENT_CATALOG.md) for all agents, [`data_gen/README.md`](data_gen/README.md) for the data
model and planted anomalies, and [`docs/DECISIONS.md`](docs/DECISIONS.md) for implementation decisions.

## How to add an agent

1. Create `backend/app/agents/<domain>/<name>.py` with a `Finding` subclass (typed fields; `source_refs` is inherited and
   mandatory) and an `Agent` subclass setting `id`, `name`, `domain`, `description`, `inputs`, `outputs`, `finding_model`,
   `approver_role`, `default_autonomy`, `demo_trigger`, `action_types` (and `params_spec` if it takes parameters).
2. Implement `mock_run(ctx) -> AnalysisResult(findings, actions, facts)` using `ctx.repo` (tenant-scoped tables) and `ctx.kg`
   (knowledge graph). Cite records with `ev(record_id, table, excerpt)`. Write only *draft* graph state.
3. Add a narrative template `backend/app/llm/templates/<agent_id>.jinja` (variables: `f` = facts, `findings`).
4. Register the class in `backend/app/agents/registry.py` (and optionally seed acceptance in `SEED_ACCEPTANCE`).
5. If its actions need special handling on approval, add a branch in `agents/shared/graph_curator.py` (every approval
   already produces a `Decision` node; L3 ticket side effects are configured in `TICKET_ACTIONS`).
6. `make docs` regenerates the catalog and creates the live-mode prompt `llm/prompts/<agent_id>.md` if it does not exist. Add tests in `backend/tests/test_agents.py` — the parametrised grounding test covers it automatically.

## How to add a tenant / industry catalog

1. Write `data_gen/catalogs/<industry>.yaml` following `utilities.yaml` (tenant block, users, capabilities, named applications,
   filler nouns, shadow IT, aliases, APIs, DB links, data domains, AI use cases / assets, strategy docs, goals, projects, design
   docs, decisions, ADR titles, impact triggers, copilot questions, evidence regulations).
2. Add the tenant id to `TENANTS` / `TENANT_CATALOG` in `backend/app/config.py` and `data_gen/generators/core.py`, and to
   `TENANTS` in `frontend/src/state/AppState.tsx`.
3. `make reset`, then `make test` — the planted-anomaly tests tell you which volumes or traps are missing.

## Tests

`make test` runs 80 tests: data volumes and planted anomalies, determinism, graph queries, discovery recall on ground truth
(≥ 90%), TIME quadrants, risk-tier distribution and rule citations, design-review standard ids for every planted design,
drift boundary violations, grounding of every agent's output, the approval flow (roles, L1 promotion, L3 tickets, edit & approve,
bulk rules), tenant isolation, copilot citations, audit export, and the live-mode narrative path (validation, one retry, fallback) with a fake Anthropic client. Coverage on `agents/`, `kg/`, `data_gen/` is ~92%.

## Out of scope

Authentication/SSO, multi-tenant hosting, real connectors (Jira, ServiceNow, clouds, LeanIX/Ardoq), L4 autonomy execution,
mobile layout, billing, i18n, production hardening.
