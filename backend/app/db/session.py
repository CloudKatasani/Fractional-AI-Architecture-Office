"""Engine per tenant and a small typed-ish repository over SQLAlchemy Core tables.

All reads are filtered by tenant_id (P5). Rows are returned as plain dicts.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Engine, create_engine, delete, event, insert, select, update

from app.config import TENANTS, settings
from app.db import models

_engines: dict[str, Engine] = {}
_lock = threading.Lock()
# Bumped whenever a tenant DB is written; used to invalidate in-memory caches (graph, table cache).
_versions: dict[str, int] = {}


def get_engine(tenant_id: str, path: str | None = None) -> Engine:
    if tenant_id not in TENANTS and path is None:
        raise ValueError(f"Unknown tenant {tenant_id}")
    key = path or tenant_id
    with _lock:
        if key not in _engines:
            db_path = path or str(settings.db_path(tenant_id))
            eng = create_engine(f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False})

            @event.listens_for(eng, "connect")
            def _pragma(dbapi_conn, _rec):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()

            _engines[key] = eng
        return _engines[key]


def dispose_engine(tenant_id: str) -> None:
    with _lock:
        eng = _engines.pop(tenant_id, None)
    if eng is not None:
        eng.dispose()
    bump_version(tenant_id)


def bump_version(tenant_id: str) -> int:
    _versions[tenant_id] = _versions.get(tenant_id, 0) + 1
    return _versions[tenant_id]


def version(tenant_id: str) -> int:
    return _versions.get(tenant_id, 0)


def table(name: str):  # noqa: ANN201
    return models.metadata.tables[name]


class Repo:
    """Tenant-scoped data access. Cheap to construct; caches table reads until the tenant version changes."""

    def __init__(self, tenant_id: str, engine: Engine | None = None):
        self.tenant_id = tenant_id
        self.engine = engine or get_engine(tenant_id)
        self._cache: dict[str, tuple[int, list[dict]]] = {}

    # ---- reads -----------------------------------------------------------------
    def all(self, name: str, **filters: Any) -> list[dict]:
        rows = self._all_cached(name)
        if not filters:
            return list(rows)
        return [r for r in rows if all(r.get(k) == v for k, v in filters.items())]

    def _all_cached(self, name: str) -> list[dict]:
        v = version(self.tenant_id)
        hit = self._cache.get(name)
        if hit and hit[0] == v:
            return hit[1]
        t = table(name)
        stmt = select(t)
        if "tenant_id" in t.c:
            stmt = stmt.where(t.c.tenant_id == self.tenant_id)
        with self.engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(stmt)]
        self._cache[name] = (v, rows)
        return rows

    def get(self, name: str, id_: str) -> dict | None:
        for r in self._all_cached(name):
            if r.get("id") == id_:
                return r
        return None

    def by_id(self, name: str) -> dict[str, dict]:
        return {r["id"]: r for r in self._all_cached(name)}

    def count(self, name: str) -> int:
        return len(self._all_cached(name))

    # ---- writes ----------------------------------------------------------------
    def insert(self, name: str, rows: dict | Iterable[dict]) -> None:
        rows = [rows] if isinstance(rows, dict) else list(rows)
        if not rows:
            return
        t = table(name)
        for r in rows:
            if "tenant_id" in t.c:
                r.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as conn:
            conn.execute(insert(t), rows)
        bump_version(self.tenant_id)

    def update(self, name: str, id_: str, values: dict, key: str = "id") -> None:
        t = table(name)
        stmt = update(t).where(t.c[key] == id_)
        if "tenant_id" in t.c:
            stmt = stmt.where(t.c.tenant_id == self.tenant_id)
        with self.engine.begin() as conn:
            conn.execute(stmt.values(**values))
        bump_version(self.tenant_id)

    def update_where(self, name: str, where: dict, values: dict) -> None:
        t = table(name)
        stmt = update(t)
        for k, v in where.items():
            stmt = stmt.where(t.c[k] == v)
        with self.engine.begin() as conn:
            conn.execute(stmt.values(**values))
        bump_version(self.tenant_id)

    def delete_all(self, name: str) -> None:
        t = table(name)
        with self.engine.begin() as conn:
            conn.execute(delete(t))
        bump_version(self.tenant_id)

    def get_meta(self, key: str, default: Any = None) -> Any:
        t = models.meta_kv
        with self.engine.connect() as conn:
            row = conn.execute(select(t).where(t.c.key == key)).first()
        return row._mapping["value"] if row else default

    def set_meta(self, key: str, value: Any) -> None:
        t = models.meta_kv
        with self.engine.begin() as conn:
            conn.execute(delete(t).where(t.c.key == key))
            conn.execute(insert(t), [{"key": key, "value": value}])
        bump_version(self.tenant_id)


def create_schema(engine: Engine) -> None:
    models.metadata.drop_all(engine)
    models.metadata.create_all(engine)
