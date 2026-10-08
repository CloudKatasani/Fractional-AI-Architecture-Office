# Implementation decisions

Decisions taken while building the prototype (spec §0.6 and §16). Most recent last.

## Open decisions from §16

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | uv vs pip; Alembic vs create_all | `pip install -r requirements.txt` (uses `uv pip` when uv is installed); SQLAlchemy Core `metadata.create_all` on every generation | Simplest; data is always regenerated from the seed, so migrations add nothing. |
| 2 | Store Mermaid or render on request | Render on request from the knowledge graph (`kg/export.py`); diagrams produced by agents (drift, reference architecture, lineage) are stored in the run's `artifacts` | Always reflects the current graph; runs stay reproducible. |
| 3 | Discovery threshold / alias catalog | rapidfuzz `token_sort_ratio` threshold **85** plus: exact normalised match, vendor match (incl. abbreviated vendor names like "Helix Con"), product hints from invoice descriptions, and *distinctive acronyms* (an upper-case token such as `MDM`, `OMS`, `GIS` that occurs in exactly one application name). No hand-maintained alias list is needed. | Ground-truth recall is **99.6% (NorthGrid) / 99.8% (Meridian)** — tested (`test_discovery_recall_on_ground_truth`, ≥ 90% required). |
| 4 | TIME thresholds | Business fit ≥ 3.0 and technical health ≥ 3.0 → Invest; high fit/low health → Migrate; low fit/high health → Tolerate; low/low → Eliminate (`settings.time_fit_threshold`, `time_health_threshold`). Fit = 1 + 4 × (0.3·importance + 0.4·usage + 0.1·owner confirmed + 0.2·criticality); health = 5 − debt − EOS − incident penalties. | Formula weights were tuned (not the thresholds) until all four quadrants are populated for both tenants (~65–70% Invest). |
| 5 | Risk rule table location | `data_gen/catalogs/ai_risk_rules.yaml`, shared by both tenants, with tenant-specific regulation names (`tenant_regulations`). | As recommended. |

## Other decisions

- **Repository layout**: the spec's `arch-office/` tree lives at the repository root (no extra nesting).
- **Python version**: developed and tested on Python 3.13; code targets 3.12+ (no 3.13-only features).
- **One SQLite file per tenant** (`data/{tenant}.db`) holds source tables, ground truth, knowledge graph, runs, approvals and audit.
  SQLAlchemy Core (not ORM) with JSON columns for list fields; rows are plain dicts.
- **The `applications` table is the client's existing (partial) inventory** (EA repository + CMDB merge, 180/240 rows). Shadow IT
  exists only in invoices, expense reports and SSO logs; Discovery proposes it as *candidate* application nodes (`CAND-…`)
  which become approved `Application` nodes when an owner confirms them. Two candidates per tenant are actually retired tools so
  the owner has something to reject.
- **CMDB coverage**: spec says both "~12% of apps not in CMDB" and "CMDB CIs 60–70% of apps". We kept the 12% rule (88% of apps have a
  CI, plus 6 duplicates and 3–4 retired CIs ≈ 5%).
- **Volumes slightly outside ranges**: Meridian has 165 contracts (spec 120–160) because the 240-app estate has more vendor apps;
  Meridian PII share is ~53% of datasets (spec "~30%") because telecom subscriber/CDR data is PII-heavy — curated layers are
  de-identified to keep it from being higher. Tests use the bounds actually asserted in `test_planted_anomalies.py`.
- **AI use cases**: 19 (NorthGrid) / 25 (Meridian) = the catalogue lists from §5.2 plus one prohibited use case each.
- **Demo numbers**: §11 quotes illustrative counts ("22 shadow IT candidates", "11 AI assets, 5 unregistered", "9 CMDB duplicates").
  The generated data reproduces 22 shadow IT candidates and 3 expense-paid GenAI tools exactly; other counts differ (e.g. 21 AI
  assets, 6 duplicates + 3 stale CIs). `docs/DEMO_SCRIPT.md` is **generated** from the data by `make docs` so it always matches the UI.
- **Baseline runs**: `make data` runs every runnable agent once (trigger `scheduled`) and records ~10 historical decisions
  ("last month's cycle", low-stakes items only) so the dashboard, audit trail and acceptance rates are populated on first load.
  Re-running an agent updates its pending approvals instead of duplicating them; decided items are not re-proposed unless the
  proposal changed.
- **Autonomy semantics**: L1 = findings only (observations can be promoted to approvals by a human, e.g. *Send to owners for
  confirmation*); L2 = approvals created, the graph is updated on approval; L3 = additionally executes side effects on approval
  (simulated Jira tickets, ADR published to the ADR repository); L4 is rejected by the API and shown as display-only.
  Default autonomy: Discovery, Lineage, Pattern Advisor, Impact Analyst, Copilot, Evidence and Briefing L1; ADR Writer, Drift
  Detector L3; everything else L2.
- **Role rules**: the principal architect may decide everything except CIO (budget) and risk-officer (AI risk) items.
  App owners see owner items for their own applications and unowned shadow-IT candidates.
- **Acceptance rate**: (seeded accepted + approved) / (seeded decided + decided) per agent; seeds give realistic promotion guidance.
- **Savings metrics**: *identified* = sum of `est_savings_usd` in the latest Cost & License Optimizer and Overlap Finder runs;
  *approved* = approved savings-bearing approvals, de-duplicated per cluster (a business case and a consolidation of the same
  cluster count once); *realized* = approved renegotiations / cancellations older than 30 days (the notice period has passed).
- **Tech-debt trend**: only the current point is computed; the five earlier monthly points are synthetic (labelled as such), per §10.2.
- **Live mode**: the LLM never computes findings. It receives the deterministic tool results and returns `{summary, order, notes}`;
  every cited id must exist in the tool results, otherwise the response is rejected and retried once with the validation error, then
  the deterministic narrative is used (marked `live-fallback`). The static system prompt is sent with `cache_control` (prompt caching).
  The live Copilot is a tool-use loop over `kg_search`, `kg_neighbors`, `kg_lineage`, `kg_impact`, `search_standards`, `search_patterns`.
  Default model is taken from `ANTHROPIC_MODEL` (spec default `claude-sonnet-4-5`; any current Claude model id works).
- **Mock narratives**: Jinja templates in `backend/app/llm/templates/`; optional hand-written overrides in
  `backend/app/llm/mock_responses/{agent_id}/{tenant}_{key}.json` (one example for the demo design review).
- **Impact analysis**: integration edges are followed one hop only (they are "terminal"), and capabilities do not fan out to every
  other application that realises them — otherwise depth-3 traversal touches most of the estate. Estimated cost = replacement/change
  cost of the triggering applications × a factor per trigger type + $40k rework per dependent application (synthetic).
- **Copilot (mock)**: 24 regex handlers over the graph cover the 12 suggested questions per tenant and common variants (owner of X,
  apps for capability Y, what depends on Z, lineage, costs, renewals, boundary crossings, duplicates, residency, risk, strategy gaps,
  explain a node). Follow-ups use the conversation history the UI sends with each question: pronouns (“those”, “them”, “it”)
  resolve to the records cited in the previous answer, set questions filter that set (high risk, owners, cost, contracts, PII,
  end of support), and “what about X?” re-asks the previous question with X as the subject. There is no static Q→A list: answers are computed from the graph, so they stay true after approvals change it.
- **Frontend types**: `src/api/schema.d.ts` is generated from the running API's OpenAPI document (`npm run gen:api`); a small
  hand-written subset of shared shapes lives in `src/api/client.ts`.
- **docker-compose**: not provided (optional in the spec); `make setup && make demo` is the supported path.
