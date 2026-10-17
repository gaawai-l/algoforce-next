"""Explicit local-development settings; no credentials are needed."""

import os
from dataclasses import dataclass
from pathlib import Path

from .rules import ALL_RULES, Rules, parse_rules


@dataclass(frozen=True)
class Settings:
    port: int = 8787
    log_level: str = "info"
    data_dir: Path = Path(__file__).resolve().parents[4] / ".local" / "analytics"
    # The perps REST worker and WebSocket collectors; on unless WHEELHOUSE_PERPS turns them off.
    perps_enabled: bool = True
    # The opt-in rule switches; all on unless WHEELHOUSE_RULES says otherwise.
    rules: Rules = ALL_RULES

    @classmethod
    def from_env(cls) -> "Settings":
        port = int(os.environ.get("WHEELHOUSE_PORT", "8787"))
        if not 1024 <= port <= 65535:
            raise ValueError("WHEELHOUSE_PORT must be between 1024 and 65535")
        level = os.environ.get("WHEELHOUSE_LOG_LEVEL", "info").lower()
        if level not in {"debug", "info", "warning", "error"}:
            raise ValueError("Unsupported WHEELHOUSE_LOG_LEVEL")
        perps = os.environ.get("WHEELHOUSE_PERPS", "on").lower()
        if perps not in {"1", "0", "true", "false", "on", "off"}:
            raise ValueError("WHEELHOUSE_PERPS must be 1/0, true/false or on/off")
        try:
            rules = parse_rules(os.environ.get("WHEELHOUSE_RULES"))
        except ValueError as exc:
            raise ValueError(f"WHEELHOUSE_RULES: {exc}") from exc
        return cls(
            port=port,
            log_level=level,
            data_dir=Path(os.environ.get("WHEELHOUSE_DATA_DIR", str(cls.data_dir))),
            perps_enabled=perps in {"1", "true", "on"},
            rules=rules,
        )
