"""Replay inputs for AlphaBTC / TradingSignal snapshots (golden: 2026-09-27T16:28:32Z)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wheelhouse_service.indicators.demark import DemarkConfig
from wheelhouse_service.market import DURATIONS, Bar, Dataset, StoredBar, Stream

FIXTURE = Path(__file__).parent / "fixtures" / "alphabtc-td9-2026-09-27T162832Z.json"
# Same-side 9 suppressed while a countdown runs: unperfected on 5m, perfected on 4h.
FIXTURE_0928 = Path(__file__).parent / "fixtures" / "alphabtc-td9-2026-09-28T034955Z.json"
# 5m BUY 13 qualifying on the forming bar.
FIXTURE_0400 = Path(__file__).parent / "fixtures" / "alphabtc-td9-2026-09-28T040023Z.json"
# 5m flips to SELL 3 bars after a BUY 13 whose risk level holds; its SELL S9's
# countdown reached 12 before an opposite Setup cancelled it.
FIXTURE_0416 = Path(__file__).parent / "fixtures" / "alphabtc-td9-2026-09-28T041636Z.json"
TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
V2 = DemarkConfig(
    ruleset_version="wheelhouse-sequential-2",
    same_side_policy="retain_active",
    perfection_policy="strict_at_nine",
)


def load_fixture(path: Path = FIXTURE) -> dict[str, Any]:
    return json.loads(path.read_text())


def replay_dataset(tf: str, path: Path = FIXTURE) -> tuple[Dataset, datetime]:
    """All 500 bars as closed input, matching how TradingSignal counted its forming bar."""
    entry = load_fixture(path)["timeframes"][tf]
    step = timedelta(seconds=DURATIONS[tf])
    bars = []
    for t, o, h, low, c in entry["bars"]:
        opened = datetime.fromtimestamp(t, UTC)
        bars.append(
            StoredBar(
                revision_id=f"fx:{tf}:{t}",
                revision=1,
                fetched_at=opened + step,
                bar=Bar(
                    open_time=opened,
                    close_time=opened + step,
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    is_closed=True,
                ),
            )
        )
    end = bars[-1].bar.close_time
    stream = Stream(source="binance", symbol="BTCUSDT", timeframe=tf)  # type: ignore[arg-type]
    dataset = Dataset(
        stream=stream, market_at=end, knowledge_at=end, fetched_at=end, bars=bars, forming=[]
    )
    return dataset, datetime.fromtimestamp(entry["as_of"], UTC)
