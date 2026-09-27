"""Replay inputs for the 2026-09-27T16:28:32Z AlphaBTC / TradingSignal snapshot."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from wheelhouse_service.indicators.demark import DemarkConfig
from wheelhouse_service.market import DURATIONS, Bar, Dataset, StoredBar, Stream

FIXTURE = Path(__file__).parent / "fixtures" / "alphabtc-td9-2026-09-27T162832Z.json"
TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
V2 = DemarkConfig(
    ruleset_version="wheelhouse-sequential-2",
    same_side_policy="retain_active",
    perfection_policy="strict_at_nine",
)


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def replay_dataset(tf: str) -> tuple[Dataset, datetime]:
    """All 500 bars as closed input, matching how TradingSignal counted its forming bar."""
    entry = load_fixture()["timeframes"][tf]
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
