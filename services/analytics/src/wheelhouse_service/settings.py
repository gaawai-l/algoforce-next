"""Explicit local-development settings; no credentials are needed."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    port: int = 8787
    log_level: str = "info"
    data_dir: Path = Path(__file__).resolve().parents[4] / ".local" / "analytics"

    @classmethod
    def from_env(cls) -> "Settings":
        port = int(os.environ.get("WHEELHOUSE_PORT", "8787"))
        if not 1024 <= port <= 65535:
            raise ValueError("WHEELHOUSE_PORT must be between 1024 and 65535")
        level = os.environ.get("WHEELHOUSE_LOG_LEVEL", "info").lower()
        if level not in {"debug", "info", "warning", "error"}:
            raise ValueError("Unsupported WHEELHOUSE_LOG_LEVEL")
        return cls(
            port=port,
            log_level=level,
            data_dir=Path(os.environ.get("WHEELHOUSE_DATA_DIR", str(cls.data_dir))),
        )
