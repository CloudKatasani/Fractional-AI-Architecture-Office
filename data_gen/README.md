# Synthetic data generator

```
python -m data_gen.generate --tenant northgrid --seed 42 --out data/northgrid.db
python -m data_gen.generate --tenant meridian --seed 42 --out data/meridian.db
python -m data_gen.generate --all
```

Deterministic: same seed + same `DEMO_TODAY` → identical data. All dates are relative to `DEMO_TODAY` (default today).
Industry content is hand-authored in `catalogs/utilities.yaml`, `catalogs/telecom.yaml`, `catalogs/common.yaml` and
`catalogs/ai_risk_rules.yaml`; generators in `generators/` add the long tail and the planted anomalies.
Raw per-source exports (`sso.csv`, `invoices.csv`, `cmdb.json`, `cloud.json`, `repos.json`, `catalog.json`, …) are written
to `data/{tenant}/raw/`. After writing the tables the generator builds the knowledge graph and runs every agent once
(baseline, trigger `scheduled`) plus a small set of historical decisions (`backend/app/services/bootstrap.py`).

## Tables and volumes

| Table | NorthGrid | Meridian | Notes |
|---|---|---|---|
| `users` | 11 | 12 |  |
| `capabilities` | 71 | 69 |  |
| `strategy_docs` | 7 | 7 |  |
| `goals` | 12 | 13 |  |
| `applications` | 180 | 240 |  |
| `contracts` | 132 | 165 |  |
| `invoice_lines` | 2235 | 2298 |  |
| `sso_usage` | 3241 | 4118 |  |
| `cloud_resources` | 400 | 520 |  |
| `cmdb_cis` | 167 | 221 |  |
| `apis` | 110 | 114 |  |
| `integrations` | 272 | 358 |  |
| `repos` | 79 | 114 |  |
| `incidents` | 410 | 389 |  |
| `projects` | 42 | 43 |  |
| `design_docs` | 16 | 16 |  |
| `standards` | 26 | 26 |  |
| `patterns` | 12 | 12 |  |
| `adrs` | 18 | 20 |  |
| `datasets` | 145 | 124 |  |
| `pipelines` | 173 | 194 |  |
| `bi_assets` | 65 | 65 |  |
| `data_policies` | 11 | 12 |  |
| `ai_usecases` | 19 | 25 |  |
| `ai_assets` | 21 | 24 |  |
| `discussions` | 22 | 22 |  |
| `tickets` | 0 | 0 | simulated Jira |
| `gt_app_aliases` | 1094 | 1301 | hidden ground truth: raw name → application |
| `gt_shadow_it` | 50 | 40 | hidden ground truth: shadow IT |
| `gt_planted` | 228 | 268 | hidden ground truth: every planted anomaly |
| `kg_nodes` | 2098 | 2499 | knowledge graph |
| `kg_edges` | 3424 | 4042 | knowledge graph |
| `agent_runs` | 26 | 26 | baseline runs |
| `approvals` | 257 | 317 | baseline proposals + history |
| `audit_events` | 332 | 392 |  |

## Planted anomalies (counts)

| Anomaly | NorthGrid | Meridian |
|---|---|---|
| app not in cmdb | 22 | 29 |
| bcsi cross zone unapproved | 4 | 0 |
| bi reads pii directly | 2 | 2 |
| cmdb duplicate | 6 | 6 |
| cmdb stale retired app | 3 | 4 |
| contract trap | 2 | 3 |
| cpni to marketing without consent | 0 | 2 |
| dataset without owner | 5 | 5 |
| dependency drift | 22 | 24 |
| design violates standards | 7 | 7 |
| direct db link | 8 | 8 |
| duplicate api | 6 | 6 |
| insecure api | 3 | 3 |
| low seat utilization | 6 | 6 |
| orphan project | 12 | 16 |
| pii retention over policy | 4 | 6 |
| pii without retention | 4 | 6 |
| production model without eval | 1 | 1 |
| residency violation | 0 | 3 |
| restricted data to nonprod | 4 | 4 |
| shadow it tool | 22 | 19 |
| unapproved integration | 14 | 22 |
| unfunded goal | 2 | 2 |
| unregistered ai asset | 8 | 10 |
| untagged cloud resource | 52 | 68 |
| vendor eos within 9 months | 4 | 1 |
| zombie app no users | 5 | 5 |

Every planted anomaly is listed with its subject record in table `gt_planted` and shown in the UI under
**Ingested Sources → show what we planted**. Tests in `backend/tests/test_planted_anomalies.py` assert the ranges.
