"""Synthetic data generator.

    python -m data_gen.generate --tenant northgrid --seed 42 --out data/northgrid.db
    python -m data_gen.generate --tenant meridian --seed 42 --out data/meridian.db
    python -m data_gen.generate --all

Deterministic: same seed + same DEMO_TODAY -> identical databases.
After writing the source tables it builds the knowledge graph and bootstraps the human-in-the-loop tables
(agent settings, baseline agent runs) unless --no-bootstrap is given.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_gen.generators import data_ai, engineering, inventory, strategy  # noqa: E402
from data_gen.generators.core import TENANT_CATALOG, GenContext, load_yaml  # noqa: E402


def build_rows(tenant_id: str, seed: int, today: date) -> GenContext:
    ctx = GenContext(
        tenant_id=tenant_id, seed=seed, today=today, catalog=load_yaml(TENANT_CATALOG[tenant_id]),
        common=load_yaml("common"), risk_rules=load_yaml("ai_risk_rules"),
    )
    inventory.gen_tenant_and_users(ctx)
    inventory.gen_capabilities(ctx)
    inventory.gen_applications(ctx)
    inventory.gen_contracts(ctx)
    inventory.gen_cloud(ctx)
    inventory.gen_invoices(ctx)
    inventory.gen_sso(ctx)
    inventory.gen_cmdb(ctx)
    inventory.finalize_costs(ctx)
    engineering.gen_standards_patterns(ctx)
    engineering.gen_apis(ctx)
    engineering.gen_integrations(ctx)
    engineering.gen_repos(ctx)
    engineering.gen_incidents(ctx)
    engineering.gen_adrs(ctx)
    engineering.gen_design_docs(ctx)
    engineering.gen_discussions(ctx)
    strategy.gen_strategy(ctx)
    strategy.gen_projects(ctx)
    data_ai.gen_datasets(ctx)
    data_ai.gen_pipelines(ctx)
    data_ai.gen_bi(ctx)
    data_ai.gen_policies(ctx)
    data_ai.gen_ai(ctx)
    # ground truth tables
    for s in ctx.catalog["shadow_it"]:
        for raw in s["vendor_raw"] + s.get("sso_raw", []):
            ctx.rows.setdefault("gt_shadow_it", []).append({
                "id": ctx.next_id("GTS", 4), "tenant_id": tenant_id, "source_system": "ground_truth",
                "created_at": today.isoformat(), "raw_name": raw, "canonical": s["name"], "truth": s.get("truth", "shadow"),
                "genai": bool(s.get("genai")), "source": "sso" if raw in s.get("sso_raw", []) else s["channel"],
            })
        ctx.plant("shadow_it_tool", s["name"], truth=s.get("truth", "shadow"), genai=bool(s.get("genai")),
                  channel=s["channel"], invoice_ids=s.get("_invoice_ids", [])[:3])
    for i, p in enumerate(ctx.planted):
        ctx.rows.setdefault("gt_planted", []).append({
            "id": f"GTP-{i + 1:04d}", "tenant_id": tenant_id, "source_system": "ground_truth",
            "created_at": today.isoformat(), "anomaly": p["anomaly"], "subject_id": p["subject_id"], "details": p["details"],
        })
    return ctx


def write_db(ctx: GenContext, out: Path) -> None:
    from app.db import models
    from app.db.session import create_schema, dispose_engine, get_engine
    from sqlalchemy import insert

    out.parent.mkdir(parents=True, exist_ok=True)
    dispose_engine(ctx.tenant_id)
    if out.exists():
        out.unlink()
    for suffix in ("-wal", "-shm"):
        Path(str(out) + suffix).unlink(missing_ok=True)
    engine = get_engine(ctx.tenant_id, path=str(out)) if out.resolve() != _default_path(ctx.tenant_id) else get_engine(ctx.tenant_id)
    create_schema(engine)
    with engine.begin() as conn:
        for table_name, rows in ctx.rows.items():
            if table_name not in models.metadata.tables:
                continue
            t = models.metadata.tables[table_name]
            clean = [{k: v for k, v in r.items() if not k.startswith("_") and k in t.c} for r in rows]
            if clean:
                conn.execute(insert(t), clean)


def _default_path(tenant_id: str) -> Path:
    from app.config import settings

    return settings.db_path(tenant_id).resolve()


def write_raw_exports(ctx: GenContext, raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)

    def to_csv(name: str, rows: list[dict], cols: list[str]) -> None:
        with open(raw_dir / name, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    def to_json(name: str, rows: list[dict]) -> None:
        with open(raw_dir / name, "w") as fh:
            json.dump([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows], fh, indent=1, default=str)

    to_csv("sso.csv", ctx.rows["sso_usage"], ["id", "app_name_raw", "month", "unique_users", "logins"])
    to_csv("invoices.csv", ctx.rows["invoice_lines"], ["id", "vendor", "amount_usd", "invoice_date", "cost_center", "description", "payment_channel"])
    to_json("cmdb.json", ctx.rows["cmdb_cis"])
    to_json("cloud.json", ctx.rows["cloud_resources"])
    to_json("repos.json", ctx.rows["repos"])
    to_json("catalog.json", ctx.rows["applications"])
    to_json("contracts.json", ctx.rows["contracts"])
    to_json("data_catalog.json", ctx.rows["datasets"])
    to_json("pipelines.json", ctx.rows["pipelines"])
    to_json("ai_assets.json", ctx.rows["ai_assets"])
    to_json("apis.json", ctx.rows["apis"])
    docs = raw_dir / "documents"
    docs.mkdir(exist_ok=True)
    for d in ctx.rows["strategy_docs"]:
        (docs / f"{d['id']}.md").write_text(d["body_md"])


def generate(tenant_id: str, seed: int, out: Path | None = None, bootstrap: bool = True, quiet: bool = False) -> GenContext:
    from app.config import demo_today, settings

    t0 = time.time()
    today = demo_today()
    ctx = build_rows(tenant_id, seed, today)
    out = out or settings.db_path(tenant_id)
    write_db(ctx, out)
    write_raw_exports(ctx, out.parent / tenant_id / "raw")
    if bootstrap and out.resolve() == _default_path(tenant_id):
        from app.services.bootstrap import bootstrap_tenant

        bootstrap_tenant(tenant_id)
    if not quiet:
        counts = {k: len(v) for k, v in sorted(ctx.rows.items()) if not k.startswith("gt_")}
        print(f"[{tenant_id}] generated in {time.time() - t0:.1f}s -> {out}")
        print("   " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return ctx


def main() -> None:
    from app.config import TENANTS, settings

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", choices=TENANTS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seed", type=int, default=settings.seed)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--no-bootstrap", action="store_true", help="skip KG build and baseline agent runs")
    ap.add_argument("--if-missing", action="store_true", help="only generate tenants whose DB file does not exist")
    args = ap.parse_args()
    tenants = TENANTS if args.all or not args.tenant else [args.tenant]
    for t in tenants:
        if args.if_missing and settings.db_path(t).exists():
            print(f"[{t}] exists, skipping")
            continue
        generate(t, args.seed, args.out if len(tenants) == 1 else None, bootstrap=not args.no_bootstrap)


if __name__ == "__main__":
    main()
