"""Shared generation context and helpers. Everything is deterministic for a given (tenant, seed, DEMO_TODAY)."""

from __future__ import annotations

import random
import re
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from faker import Faker

CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalogs"
TENANT_CATALOG = {"northgrid": "utilities", "meridian": "telecom"}


def load_yaml(name: str) -> dict:
    with open(CATALOG_DIR / f"{name}.yaml") as fh:
        return yaml.safe_load(fh)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass
class GenContext:
    tenant_id: str
    seed: int
    today: date
    catalog: dict
    common: dict
    risk_rules: dict
    rows: dict[str, list[dict]] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    # lookups
    users_by_key: dict[str, dict] = field(default_factory=dict)
    caps_by_name: dict[str, dict] = field(default_factory=dict)
    apps_by_name: dict[str, dict] = field(default_factory=dict)
    datasets_by_name: dict[str, dict] = field(default_factory=dict)
    planted: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        mixed = (zlib.crc32(self.tenant_id.encode()) ^ (self.seed * 2654435761)) & 0xFFFFFFFF
        self.rng = random.Random(mixed)
        self.fake = Faker()
        self.fake.seed_instance(mixed)

    # ---- ids / dates -----------------------------------------------------------
    def next_id(self, prefix: str, width: int = 4) -> str:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return f"{prefix}-{n:0{width}d}"

    def days_ago(self, n: int) -> str:
        return (self.today - timedelta(days=n)).isoformat()

    def days_ahead(self, n: int) -> str:
        return (self.today + timedelta(days=n)).isoformat()

    def created(self) -> str:
        return self.days_ago(self.rng.randint(30, 900))

    def add(self, table: str, row: dict, source_system: str) -> dict:
        row.setdefault("tenant_id", self.tenant_id)
        row.setdefault("source_system", source_system)
        row.setdefault("created_at", self.created())
        self.rows.setdefault(table, []).append(row)
        return row

    def plant(self, anomaly: str, subject_id: str, **details: Any) -> None:
        self.planted.append({"anomaly": anomaly, "subject_id": subject_id, "details": details})

    # ---- tenant conveniences ----------------------------------------------------
    @property
    def tenant(self) -> dict:
        return self.catalog["tenant"]

    def user_id(self, key: str) -> str:
        return self.users_by_key[key]["id"]

    def owner_for_l1(self, l1_name: str) -> str:
        key = self.catalog["owner_by_l1"].get(l1_name, "pa")
        return self.user_id(key)

    def l1_of(self, cap: dict) -> dict:
        while cap.get("parent_id"):
            cap = next(c for c in self.rows["capabilities"] if c["id"] == cap["parent_id"])
        return cap

    def app(self, name: str) -> dict:
        try:
            return self.apps_by_name[name]
        except KeyError as exc:
            raise KeyError(f"[{self.tenant_id}] catalog references unknown application '{name}'") from exc

    def cap(self, name: str) -> dict:
        try:
            return self.caps_by_name[name]
        except KeyError as exc:
            raise KeyError(f"[{self.tenant_id}] catalog references unknown capability '{name}'") from exc

    def apps_by_id(self, id_: str) -> dict:
        idx = getattr(self, "_app_idx", None)
        if idx is None or len(idx) != len(self.rows["applications"]):
            idx = {a["id"]: a for a in self.rows["applications"]}
            self._app_idx = idx
        return idx[id_]

    def users_by_id(self, id_: str) -> dict:
        return next(u for u in self.rows["users"] if u["id"] == id_)

    def cap_by_id(self, id_: str) -> dict:
        return next(c for c in self.rows["capabilities"] if c["id"] == id_)

    def l1_name_of_app(self, app: dict) -> str:
        return self.l1_of(self.cap_by_id(app["capability_ids"][0]))["name"]

    def alias(self, raw: str, app_id: str, source: str, hint: str | None = None) -> None:
        """Record ground truth: this raw name (as seen in `source`) refers to app_id."""
        key = (raw, source, hint)
        seen = self.__dict__.setdefault("_alias_seen", set())
        if key in seen:
            return
        seen.add(key)
        self.rows.setdefault("gt_app_aliases", []).append({
            "id": self.next_id("GTA", 5), "tenant_id": self.tenant_id, "source_system": "ground_truth",
            "created_at": self.today.isoformat(), "raw_name": raw if not hint else f"{raw} | {hint}",
            "app_id": app_id, "source": source,
        })

    def pick(self, seq: list, k: int | None = None):  # noqa: ANN201
        if k is None:
            return self.rng.choice(seq)
        return self.rng.sample(seq, min(k, len(seq)))


# ---- deliberate naming inconsistencies (Section 5.3) -------------------------------

def name_variants(name: str) -> list[str]:
    s = slug(name)
    return [name.upper(), name.lower(), s, f"{s}-prod", f"{name} Prod", name.replace(" ", ""), f"{name} (PROD)"]


def vendor_variants(vendor: str) -> list[str]:
    base = vendor.replace(" Inc", "").replace(" Ltd", "").replace(" Corp", "")
    words = base.split()
    abbrev = " ".join(w if i == 0 else (w[:3] if len(w) > 5 else w) for i, w in enumerate(words))
    return [vendor, f"{base.upper()} INC", f"{base}, Inc.", f"{base} Ltd.", base.lower(), abbrev, f"{base} LLC"]
