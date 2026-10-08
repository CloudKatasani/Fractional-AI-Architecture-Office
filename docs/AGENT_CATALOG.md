# Agent Catalog

Generated from `backend/app/agents/registry.py` (single source of truth). Regenerate with `make docs`.

## Enterprise Architecture

| id | Name | Inputs | Output | Actions | Approver | Default autonomy | Demo trigger |
|---|---|---|---|---|---|---|---|
| `ea.strategy_capability_mapper` | Strategy-to-Capability Mapper | strategy_docs, goals, capabilities | GoalCapabilityLink | link_goal_capability | principal_architect | L2 | Map strategy |
| `ea.capability_curator` | Capability Map Curator | capabilities, applications | CapabilityAssessment | update_capability_scores | principal_architect | L2 | Assess capabilities |
| `ea.investment_traceability` | Investment Traceability | projects, goals, capabilities | InvestmentAlignment | flag_orphan_project, propose_funding_review | cio | L2 | Trace investment |
| `ea.roadmap_drafter` | Roadmap Drafter | applications, integrations, goals, projects, capabilities | RoadmapScenario | adopt_roadmap_scenario | cio | L2 | Draft roadmaps |
| `ea.impact_analyst` | Impact Analyst | kg_nodes, kg_edges, applications | ImpactReport | — | — | L1 | Analyse impact |
| `ea.board_assistant` | Architecture Board Assistant | approvals, kg_edges, adrs, design_docs, standards | BoardPack | record_board_decision | principal_architect | L2 | Prepare board pack |

- **Strategy-to-Capability Mapper** — Extracts strategic goals from strategy documents and links each goal to the business capabilities it depends on; flags goals with no capability and high-importance / low-maturity capabilities.
- **Capability Map Curator** — Computes the capability heat map (importance x (5 - maturity)), counts realising applications and flags capabilities with no application or more than six.
- **Investment Traceability** — Traces every project to strategic goals and capabilities; sums budget per goal, lists orphan projects (no goal) and unfunded goals (no project), and computes the share of budget aligned to strategy.
- **Roadmap Drafter** — Sequences end-of-support remediation, portfolio consolidations, boundary-violation fixes and unfunded strategic capabilities into three 6-quarter scenarios with dependencies and trade-offs.
- **Impact Analyst** — Given a trigger (vendor exit, regulation, M&A, application retirement or any graph node) traverses the knowledge graph to depth 3 and lists affected capabilities, applications, datasets, AI and people.
- **Architecture Board Assistant** — Prepares the architecture board pack: pending approvals, open violations, new ADRs since the last board and each design submission checked against standards; records board decisions.

## Application Architecture

| id | Name | Inputs | Output | Actions | Approver | Default autonomy | Demo trigger |
|---|---|---|---|---|---|---|---|
| `app.design_review` | Design Review Agent | design_docs, standards, apis | DesignReview | publish_review, request_exception | tech_lead | L2 | Review design |
| `app.adr_writer` | ADR Writer | discussions, applications, adrs | ADRDraft | publish_adr | tech_lead | L3 | Draft ADRs |
| `app.pattern_advisor` | Pattern Advisor | patterns, standards, apis | PatternRecommendation | — | — | L1 | Recommend pattern |
| `app.drift_detector` | Drift Detector | repos, integrations, applications | DriftFinding | create_remediation_ticket, approve_exception | security_architect | L3 | Detect drift |
| `app.integration_api_architect` | Integration and API Architect | apis, applications, integrations | APIFinding | designate_canonical_api, deprecate_api | principal_architect | L2 | Review APIs |
| `app.tech_debt_radar` | Tech Debt Radar | repos, incidents, applications | DebtItem | add_to_debt_register | tech_lead | L2 | Scan debt |
| `app.threat_model_assistant` | Threat Model Assistant | design_docs, applications, standards | ThreatModel | publish_threat_model | security_architect | L2 | Model threats |

- **Design Review Agent** — Checks design submissions against architecture standards (integration, data classification, approved GenAI platforms, NFRs, boundary rules); every concern maps to a standard id; suggests APIs to reuse.
- **ADR Writer** — Extracts context, options, decision and consequences from design discussions and drafts Architecture Decision Records linked to the applications mentioned.
- **Pattern Advisor** — Matches a short feature description to reference patterns by keywords and NFRs; returns the top two with starter diagram, applicable standards and existing APIs to reuse.
- **Drift Detector** — Compares declared vs runtime dependencies from repositories, finds unapproved integrations and direct DB links across restricted boundaries (IT/OT, BSS/OSS); renders intended vs actual diagrams.
- **Integration and API Architect** — Finds duplicate APIs, APIs with weak authentication on confidential data and confidential APIs bypassing the gateway; proposes a canonical API and the consumers to migrate; drafts OpenAPI stubs.
- **Tech Debt Radar** — Scores each application on EOL framework (30), framework age (0-20), critical vulnerabilities (0-25) and severity-weighted incidents in 90 days (0-25); ranks and estimates fix effort (S/M/L).
- **Threat Model Assistant** — Builds a STRIDE table over a design's components and data flows, pulls data classification and maps mitigations to standards.

## Portfolio Architecture

| id | Name | Inputs | Output | Actions | Approver | Default autonomy | Demo trigger |
|---|---|---|---|---|---|---|---|
| `pf.app_discovery` | Application Discovery | sso_usage, invoice_lines, cloud_resources, cmdb_cis, applications | DiscoveryFinding | confirm_app, merge_cmdb_ci, retire_cmdb_ci, assign_owner | app_owner | L1 | Run discovery |
| `pf.cost_license_optimizer` | Cost and License Optimizer | applications, contracts, cloud_resources, invoice_lines, sso_usage | CostFinding | renegotiate_contract, cancel_renewal, tag_resources | cio | L2 | Find savings |
| `pf.overlap_finder` | Overlap Finder | applications, capabilities, repos, incidents | OverlapCluster | propose_consolidation | principal_architect | L2 | Find overlaps |
| `pf.time_classifier` | TIME Classifier | applications, capabilities, repos, incidents | TimeDisposition | set_disposition | app_owner | L2 | Classify portfolio |
| `pf.lifecycle_watcher` | Lifecycle Watcher | applications, contracts, repos | LifecycleAlert | create_renewal_task, plan_upgrade | principal_architect | L2 | Check lifecycle |
| `pf.business_case_builder` | Rationalization Business Case Builder | applications, contracts, integrations, repos | BusinessCase | approve_business_case | cio | L2 | Build business case |

- **Application Discovery** — Reconciles SSO logs, invoices, expense reports, cloud tags and CMDB records into one application inventory; surfaces shadow IT, CMDB duplicates and stale CIs with confidence per match.
- **Cost and License Optimizer** — Computes TCO per application (contract share + tagged cloud + 15% overhead) and flags low seat utilisation, auto-renewals within 90 days, untagged cloud spend, unused apps and above-market pricing.
- **Overlap Finder** — Groups applications realising the same L2 capability (or category) with overlapping feature tags and recommends a survivor by usage, cost, technical debt and strategic fit.
- **TIME Classifier** — Scores business fit (capability importance, usage, owner confirmation) and technical health (debt score, vendor end of support, incidents) and places each app in a TIME quadrant.
- **Lifecycle Watcher** — Watches vendor end-of-support dates (12 months), contract renewals (180 days) and end-of-life frameworks; severity by days remaining and business criticality.
- **Rationalization Business Case Builder** — Builds a one-page business case for an overlap cluster or disposition set: 3-year savings, one-time migration cost, payback, simple NPV, risks and a timeline.

## Data & AI Architecture

| id | Name | Inputs | Output | Actions | Approver | Default autonomy | Demo trigger |
|---|---|---|---|---|---|---|---|
| `dai.lineage_mapper` | Lineage Mapper | datasets, pipelines, bi_assets, ai_assets | LineageReport | — | — | L1 | Trace lineage |
| `dai.data_product_designer` | Data Product Designer | datasets, pipelines, bi_assets, ai_assets | DataProductProposal | approve_data_contract | data_governance_lead | L2 | Propose data products |
| `dai.governance_policy_checker` | Governance Policy Checker | datasets, pipelines, bi_assets, data_policies, ai_assets, ai_usecases | PolicyFinding | apply_masking, set_retention, assign_owner, block_pipeline | data_governance_lead | L2 | Check policies |
| `dai.ai_usecase_intake` | AI Use-Case Intake | ai_usecases, datasets | UseCaseScore | prioritize_usecase | principal_architect | L2 | Rank backlog |
| `dai.ai_risk_classifier` | AI Risk Classifier | ai_usecases, datasets | RiskClassification | set_risk_tier | risk_officer | L2 | Classify risk |
| `dai.ai_ref_arch_generator` | AI Reference Architecture Generator | ai_usecases, patterns, standards, datasets | ReferenceArchitecture | approve_reference_design | principal_architect | L2 | Generate reference design |
| `dai.model_agent_registry_steward` | Model and Agent Registry Steward | ai_assets, ai_usecases, invoice_lines | RegistryFinding | register_asset, require_eval, suspend_asset | risk_officer | L2 | Audit AI registry |

- **Lineage Mapper** — Builds lineage from pipelines, BI assets and AI assets; answers upstream/downstream questions and flags datasets feeding AI with a quality score below 0.6.
- **Data Product Designer** — Groups datasets by domain and proposes data products (owner, schema summary, SLAs, quality rules) for domains with 3+ datasets and 2+ consuming teams, with a draft data contract.
- **Governance Policy Checker** — Evaluates data policy predicates: PII without retention, retention over/under policy, restricted data in non-production, BI reading PII directly, datasets without owner, residency, PCI scope, CPNI use.
- **AI Use-Case Intake** — Scores AI use cases on value (estimate, sponsor priority) and feasibility (data exists, quality, ownership, pattern maturity), checks data readiness and ranks the backlog.
- **AI Risk Classifier** — Tiers AI use cases (unacceptable / high / limited / minimal) with EU AI Act-style rules; lists the triggering rule ids, required controls and documentation. Unacceptable use cases are blocked.
- **AI Reference Architecture Generator** — Emits a reference design for a use case's pattern (RAG, agent with tools, fine-tune, classic ML, vision): components on approved platforms, data-flow diagram, security controls, eval plan, cost band.
- **Model and Agent Registry Steward** — Inventories AI assets; flags unregistered (shadow) AI, missing evaluation, unknown training data, unapproved vendors and expense-paid tools; computes AI spend by department.

## Shared

| id | Name | Inputs | Output | Actions | Approver | Default autonomy | Demo trigger |
|---|---|---|---|---|---|---|---|
| `shared.orchestrator` | Orchestrator | agent registry | Combined AgentOutputs | — | — | L2 | Ask the office |
| `shared.graph_curator` | Knowledge Graph Curator | approvals, kg_nodes, kg_edges | graph updates | — | — | L3 | Runs after every decision |
| `shared.copilot` | Architecture Copilot | kg_nodes, kg_edges, standards, patterns | Answer with citations | — | — | L1 | Ask a question |
| `shared.diagram_generator` | Diagram Generator | kg_nodes, kg_edges | Mermaid text | — | — | L1 | Render diagram |
| `shared.evidence_audit` | Evidence and Audit Agent | data_policies, agent_runs, approvals, audit_events, ai_usecases, applications | EvidenceItem | — | — | L1 | Generate evidence pack |
| `shared.exec_briefing` | Executive Briefing Agent | metrics, approvals, agent_runs | BriefingPoint | — | — | L1 | Generate briefing |

- **Orchestrator** — Routes a natural-language request or UI trigger to one or more agents, merges their outputs, creates approvals and enforces autonomy gating.
- **Knowledge Graph Curator** — Applies approved actions to the knowledge graph, resolves conflicts by confidence, recomputes derived properties and (at autonomy L3) executes simulated side effects such as tickets and ADR publication.
- **Architecture Copilot** — Answers questions over the knowledge graph (owners, dependencies, costs, lineage, policies, patterns) with cited record ids and optional diagrams.
- **Diagram Generator** — Produces Mermaid diagrams from the knowledge graph: capability map, C4-style context for an application, data flow for a dataset, integration map for a capability.
- **Evidence and Audit Agent** — Assembles an evidence pack for a regulation or policy: applicable controls, current findings, approvals with timestamps and approvers; exports markdown and JSON.
- **Executive Briefing Agent** — Writes the monthly executive summary: inventory accuracy, savings identified / approved / realised, AI use cases by tier, design review SLA, debt trend, upcoming renewals and the top decisions needed.
