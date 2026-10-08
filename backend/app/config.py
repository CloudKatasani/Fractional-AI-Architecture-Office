"""Runtime configuration, read from environment (and an optional .env file at the repo root)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

TENANTS = ["northgrid", "meridian"]
TENANT_CATALOG = {"northgrid": "utilities", "meridian": "telecom"}


@dataclass
class Settings:
    llm_mode: str = field(default_factory=lambda: os.environ.get("LLM_MODE", "mock").lower() or "mock")
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "") or "claude-sonnet-4-5")
    seed: int = field(default_factory=lambda: int(os.environ.get("SEED", "42") or 42))
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / (os.environ.get("DATA_DIR", "data") or "data"))
    max_output_tokens: int = 2000
    # TIME classifier thresholds (Section 16.4)
    time_fit_threshold: float = 3.0
    time_health_threshold: float = 3.0
    # Discovery fuzzy-match threshold (Section 16.3)
    discovery_threshold: int = 85

    @property
    def demo_today(self) -> date:
        raw = os.environ.get("DEMO_TODAY", "").strip()
        return date.fromisoformat(raw) if raw else date.today()

    def db_path(self, tenant_id: str) -> Path:
        return self.data_dir / f"{tenant_id}.db"


settings = Settings()


def demo_today() -> date:
    return settings.demo_today
