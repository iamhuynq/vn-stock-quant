"""Environment-driven settings. Nothing here is hard-coded per machine."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

API_BASE_URL = "https://api.fireant.vn"


@dataclass(frozen=True)
class Settings:
    token: str | None
    data_dir: Path
    rate_limit_rps: float
    max_retries: int
    timeout_seconds: float


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    token = env.get("FIREANT_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[len("bearer ") :].strip()
    return Settings(
        token=token or None,
        data_dir=Path(env.get("DATA_DIR", "data")),
        rate_limit_rps=float(env.get("RATE_LIMIT_RPS", "2.5")),
        max_retries=int(env.get("MAX_RETRIES", "5")),
        timeout_seconds=float(env.get("REQUEST_TIMEOUT_SECONDS", "30")),
    )
