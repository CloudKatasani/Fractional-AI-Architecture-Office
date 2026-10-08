"""Database schema (SQLAlchemy Core). One SQLite file per tenant.

Every synthetic-source table carries id, tenant_id, source_system, created_at (Section 5.1).
List/dict fields are stored as JSON columns.
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, Float, Integer, MetaData, String, Table, Text

metadata = MetaData()


def _entity(name: str, *cols: Column) -> Table:
    return Table(
        name,
        metadata,
        Column("id", String, primary_key=True),
        Column("tenant_id", String, nullable=False, index=True),
        Column("source_system", String),
        Column("created_at", String),
        *cols,
    )


S, I, F, B, J, T = String, Integer, Float, Boolean, JSON, Text  # noqa: E741


def c(name: str, typ, **kw) -> Column:  # noqa: ANN001
    return Column(name, typ, **kw)


tenants = Table(
    "tenants",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String),
    Column("industry", String),
    Column("employees", Integer),
    Column("it_spend_usd", Integer),
    Column("notes", Text),
    Column("boundary_label", String),
    Column("home_region", String),
)

users = _entity("users", c("name", S), c("role", S), c("email", S), c("title", S))

capabilities = _entity(
    "capabilities", c("name", S), c("level", I), c("parent_id", S), c("strategic_importance", I),
    c("maturity", I), c("owner_user_id", S), c("keywords", J), c("description", T),
)
strategy_docs = _entity("strategy_docs", c("title", S), c("type", S), c("body_md", T), c("year", I))
goals = _entity(
    "goals", c("statement", S), c("source_doc_id", S), c("horizon_year", I), c("kpi", S), c("keywords", J),
)
applications = _entity(
    "applications", c("name", S), c("vendor", S), c("category", S), c("hosting", S), c("criticality", I),
    c("owner_user_id", S), c("capability_ids", J), c("lifecycle_status", S), c("in_cmdb", B),
    c("discovered_via", J), c("tech_stack", J), c("annual_cost_usd", F), c("user_count_90d", I),
    c("last_login_days", I), c("version", S), c("vendor_eos_date", S), c("contract_renewal_date", S),
    c("data_classification", S), c("ot_system", B), c("regulatory_scope", J), c("features", J),
    c("zone", S), c("cluster", S), c("description", T),
)
contracts = _entity(
    "contracts", c("vendor", S), c("app_ids", J), c("annual_value_usd", F), c("licensed_seats", I),
    c("renewal_date", S), c("auto_renew", B), c("term_months", I), c("market_benchmark_usd", F),
)
invoice_lines = _entity(
    "invoice_lines", c("vendor", S), c("amount_usd", F), c("invoice_date", S), c("cost_center", S),
    c("matched_app_id", S), c("description", S), c("payment_channel", S),
)
sso_usage = _entity(
    "sso_usage", c("app_name_raw", S), c("month", S), c("unique_users", I), c("logins", I),
)
cloud_resources = _entity(
    "cloud_resources", c("provider", S), c("account", S), c("resource_type", S), c("tags", J),
    c("monthly_cost_usd", F), c("utilization_pct", F), c("untagged", B), c("region", S),
)
cmdb_cis = _entity(
    "cmdb_cis", c("ci_name", S), c("ci_type", S), c("app_id", S), c("last_updated", S), c("ci_status", S),
)
apis = _entity(
    "apis", c("name", S), c("owner_app_id", S), c("style", S), c("consumers", J), c("spec_url", S),
    c("duplicate_group", S), c("auth", S), c("data_classification", S), c("via_gateway", B), c("resource", S),
)
integrations = _entity(
    "integrations", c("from_app_id", S), c("to_app_id", S), c("pattern", S), c("frequency", S),
    c("approved", B), c("data_classification", S), c("description", S), c("crosses_boundary", B),
)
repos = _entity(
    "repos", c("name", S), c("app_id", S), c("language", S), c("framework", S), c("framework_version", S),
    c("eol", B), c("last_commit_days", I), c("open_critical_vulns", I), c("has_iac", B),
    c("declared_dependencies", J), c("actual_dependencies", J), c("loc_k", I), c("framework_release_year", I),
)
incidents = _entity(
    "incidents", c("app_id", S), c("severity", I), c("date", S), c("root_cause_category", S),
    c("minutes_to_resolve", I), c("title", S),
)
projects = _entity(
    "projects", c("name", S), c("budget_usd", F), c("status", S), c("capability_ids", J), c("goal_ids", J),
    c("app_ids", J), c("start", S), c("end", S), c("sponsor_user_id", S),
)
design_docs = _entity(
    "design_docs", c("title", S), c("team", S), c("body_md", T), c("submitted_at", S), c("status", S),
    c("reviewed_at", S), c("app_ids", J), c("components", J),
)
standards = _entity(
    "standards", c("title", S), c("rule_text", T), c("domain", S), c("severity", S), c("checks", J),
)
patterns = _entity(
    "patterns", c("name", S), c("when_to_use", T), c("components", J), c("diagram_mermaid", T),
    c("standard_ids", J), c("keywords", J), c("nfrs", J),
)
adrs = _entity(
    "adrs", c("title", S), c("status", S), c("context", T), c("decision", T), c("consequences", T),
    c("app_ids", J), c("date", S), c("options", J), c("source_discussion_id", S),
)
datasets = _entity(
    "datasets", c("name", S), c("domain", S), c("owner_user_id", S), c("classification", S),
    c("system_app_id", S), c("pii", B), c("retention_days", I), c("quality_score", F), c("has_contract", B),
    c("environment", S), c("region", S), c("zone", S), c("layer", S), c("tags", J), c("base_name", S),
)
pipelines = _entity(
    "pipelines", c("name", S), c("tool", S), c("inputs", J), c("outputs", J), c("owner", S), c("schedule", S),
    c("target_env", S), c("approved_cross_zone", B),
)
bi_assets = _entity(
    "bi_assets", c("name", S), c("tool", S), c("dataset_ids", J), c("consumers", S), c("last_viewed_days", I),
)
data_policies = _entity(
    "data_policies", c("rule", T), c("regulation", S), c("severity", S), c("check", J), c("title", S),
)
ai_usecases = _entity(
    "ai_usecases", c("title", S), c("sponsor_dept", S), c("description", T), c("status", S), c("dataset_ids", J),
    c("value_estimate_usd", F), c("feasibility_notes", T), c("uses_personal_data", B),
    c("affects_individuals", B), c("safety_relevant", B), c("automated_decision", B), c("pattern", S),
    c("tags", J), c("sponsor_priority", I), c("owner_user_id", S),
)
ai_assets = _entity(
    "ai_assets", c("name", S), c("type", S), c("owner", S), c("vendor", S), c("data_used", J),
    c("eval_status", S), c("monthly_cost_usd", F), c("registered", B), c("usecase_id", S), c("department", S),
    c("paid_via", S), c("lifecycle", S),
)
discussions = _entity(
    "discussions", c("channel", S), c("participants", J), c("body_md", T), c("extracted", J), c("title", S),
    c("date", S),
)
tickets = _entity(
    "tickets", c("key", S), c("title", S), c("description", T), c("status", S), c("assignee", S),
    c("approval_id", S), c("target_id", S),
)

# Hidden ground truth (tests and "show what we planted" only)
gt_app_aliases = _entity("gt_app_aliases", c("raw_name", S), c("app_id", S), c("source", S))
gt_shadow_it = _entity("gt_shadow_it", c("raw_name", S), c("canonical", S), c("truth", S), c("genai", B), c("source", S))
gt_planted = _entity("gt_planted", c("anomaly", S), c("subject_id", S), c("details", J))

# Knowledge graph
kg_nodes = Table(
    "kg_nodes", metadata,
    Column("id", String, primary_key=True), Column("tenant_id", String, index=True), Column("type", String, index=True),
    Column("name", String), Column("props_json", JSON), Column("confidence", Float), Column("source_refs_json", JSON),
    Column("created_by", String), Column("status", String), Column("updated_at", String),
)
kg_edges = Table(
    "kg_edges", metadata,
    Column("id", String, primary_key=True), Column("tenant_id", String, index=True), Column("type", String, index=True),
    Column("from_id", String, index=True), Column("to_id", String, index=True), Column("props_json", JSON),
    Column("confidence", Float), Column("source_refs_json", JSON), Column("created_by", String),
    Column("status", String), Column("updated_at", String),
)

# Human-in-the-loop (Section 8.1)
agent_runs = Table(
    "agent_runs", metadata,
    Column("id", String, primary_key=True), Column("tenant_id", String, index=True), Column("agent_id", String, index=True),
    Column("trigger", String), Column("input_json", JSON), Column("output_json", JSON), Column("status", String),
    Column("started_at", String), Column("finished_at", String), Column("cost_json", JSON),
    Column("autonomy_level", Integer), Column("user_id", String),
)
approvals = Table(
    "approvals", metadata,
    Column("id", String, primary_key=True), Column("tenant_id", String, index=True), Column("run_id", String),
    Column("agent_id", String), Column("action_type", String), Column("target_id", String), Column("target_type", String),
    Column("payload_json", JSON), Column("rationale", Text), Column("source_refs_json", JSON),
    Column("approver_role", String, index=True), Column("status", String, index=True), Column("decided_by_user_id", String),
    Column("decided_at", String), Column("decision_note", Text), Column("edited_payload_json", JSON),
    Column("created_at", String), Column("applied", Boolean), Column("side_effects_json", JSON),
    Column("priority", Integer),
)
audit_events = Table(
    "audit_events", metadata,
    Column("id", String, primary_key=True), Column("tenant_id", String, index=True), Column("ts", String, index=True),
    Column("actor_type", String), Column("actor_id", String), Column("event_type", String), Column("subject_type", String),
    Column("subject_id", String), Column("details_json", JSON), Column("run_id", String), Column("approval_id", String),
)
agent_settings = Table(
    "agent_settings", metadata,
    Column("tenant_id", String, primary_key=True), Column("agent_id", String, primary_key=True),
    Column("autonomy_level", Integer), Column("enabled", Boolean), Column("acceptance_rate_30d", Float),
    Column("last_run_at", String), Column("seed_accepted", Integer), Column("seed_decided", Integer),
)
meta_kv = Table("meta_kv", metadata, Column("key", String, primary_key=True), Column("value", JSON))

ENTITY_TABLES = [
    "users", "capabilities", "strategy_docs", "goals", "applications", "contracts", "invoice_lines", "sso_usage",
    "cloud_resources", "cmdb_cis", "apis", "integrations", "repos", "incidents", "projects", "design_docs",
    "standards", "patterns", "adrs", "datasets", "pipelines", "bi_assets", "data_policies", "ai_usecases",
    "ai_assets", "discussions",
]
