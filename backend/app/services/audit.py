"""Audit trail (P3). The Audit screen reads only from audit_events."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db.session import Repo


def log(tenant_id: str, actor_type: str, actor_id: str, event_type: str, subject_type: str, subject_id: str,
        details: dict | None = None, run_id: str | None = None, approval_id: str | None = None, ts: str | None = None) -> str:
    eid = "AUD-" + uuid.uuid4().hex[:12].upper()
    Repo(tenant_id).insert("audit_events", {
        "id": eid, "tenant_id": tenant_id, "ts": ts or datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "actor_type": actor_type, "actor_id": actor_id, "event_type": event_type, "subject_type": subject_type,
        "subject_id": subject_id, "details_json": details or {}, "run_id": run_id, "approval_id": approval_id,
    })
    return eid
