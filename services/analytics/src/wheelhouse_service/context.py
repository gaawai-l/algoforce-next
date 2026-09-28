"""Cross-timeframe DeMark context: TradingSignal-equivalent summaries plus AlphaBTC regime.

Read-only and computed on demand from stored closed bars; nothing is persisted.
"""

from datetime import datetime
from typing import Literal

from .calculation import data_state
from .indicators.demark import evaluate_demark
from .indicators.demark.models import DemarkConfig
from .indicators.demark.summary import DemarkSummary, summarize
from .indicators.regime.alphabtc import (
    USABLE_STATUS,
    NewTrend,
    RegimeValue,
    Signal,
    TimeframeState,
    derive_state,
    new_trend,
    regime_of,
    signals,
)
from .market import DURATIONS, Dataset, Model, Source, Stream, Timeframe
from .repository import Repository

# TradingSignal evaluates 500 bars including one forming bar; 499 closed bars keep the same start.
WINDOW = 499
TIMEFRAMES: tuple[Timeframe, ...] = ("5m", "15m", "1h", "4h", "1d")
CONFIG = DemarkConfig(
    ruleset_version="wheelhouse-sequential-2",
    same_side_policy="retain_active",
    perfection_policy="strict_at_nine",
)
DataStatus = Literal["fresh", "delayed", "stale", "unavailable", "simulated"]
Symbol = Literal["BTCUSDT", "ETHUSDT", "MUUSDT"]


class WindowResult(Model):
    status: DataStatus
    bars_used: int
    gapped: bool
    last_closed_at: datetime | None
    summary: DemarkSummary | None


class TimeframeContext(Model):
    timeframe: Timeframe
    status: DataStatus
    bars_used: int
    history_complete: bool
    history_gapped: bool
    last_closed_at: datetime | None
    summary: DemarkSummary | None
    state: TimeframeState | None
    signals: list[Signal]
    new_trend: NewTrend | None


class RegimeState(Model):
    anchor: Timeframe
    value: RegimeValue


class MarketContext(Model):
    source: Source
    symbol: Symbol
    checked_at: datetime
    market_at: datetime
    knowledge_at: datetime
    mode: Literal["as_known", "retrospective"]
    config: DemarkConfig
    window: int
    timeframes: list[TimeframeContext]
    intraday: RegimeState
    swing: RegimeState


def load_window(
    repository: Repository, stream: Stream, *, market_at: datetime, knowledge_at: datetime
) -> tuple[DataStatus, Dataset]:
    # A small margin covers forming rows that the SQL limit counts before closed filtering.
    dataset = repository.read(
        stream, market_at=market_at, knowledge_at=knowledge_at, limit=WINDOW + 20
    )
    window = dataset.model_copy(update={"bars": dataset.bars[-WINDOW:], "forming": []})
    last = window.bars[-1].bar.close_time if window.bars else None
    status = data_state(stream.source, last, market_at, DURATIONS[stream.timeframe])
    return status, window


def _window(
    repository: Repository, stream: Stream, *, market_at: datetime, knowledge_at: datetime
) -> WindowResult:
    status, window = load_window(
        repository, stream, market_at=market_at, knowledge_at=knowledge_at
    )
    if not window.bars:
        return WindowResult(
            status=status, bars_used=0, gapped=False, last_closed_at=None, summary=None
        )
    end = window.bars[-1].bar.close_time
    bars = [b.bar for b in window.bars]
    result = evaluate_demark(window, CONFIG)
    return WindowResult(
        status=status,
        bars_used=len(bars),
        gapped=result.history_status == "gapped",
        last_closed_at=end,
        summary=summarize(result, bars, end),
    )


def compose(
    source: Source,
    symbol: Symbol,
    windows: dict[Timeframe, WindowResult],
    *,
    checked_at: datetime,
    market_at: datetime,
    knowledge_at: datetime,
) -> MarketContext:
    states = {
        tf: derive_state(w.summary) if w.summary is not None else None for tf, w in windows.items()
    }
    intraday = regime_of(states["1h"], windows["1h"].status)
    swing = regime_of(states["4h"], windows["4h"].status)
    timeframes = []
    for tf in TIMEFRAMES:
        w = windows[tf]
        # Stale or missing data shows no values at all (spec §1.4), not yesterday's reading.
        usable = w.status in USABLE_STATUS
        summary = w.summary if usable else None
        state = states[tf] if usable else None
        timeframes.append(
            TimeframeContext(
                timeframe=tf,
                status=w.status,
                bars_used=w.bars_used,
                history_complete=w.bars_used >= WINDOW,
                history_gapped=w.gapped,
                last_closed_at=w.last_closed_at,
                summary=summary,
                state=state,
                signals=(
                    signals(state, summary, intraday, swing)
                    if state is not None and summary is not None
                    else []
                ),
                new_trend=new_trend(summary) if summary is not None else None,
            )
        )
    return MarketContext(
        source=source,
        symbol=symbol,
        checked_at=checked_at,
        market_at=market_at,
        knowledge_at=knowledge_at,
        mode="retrospective" if knowledge_at > market_at else "as_known",
        config=CONFIG,
        window=WINDOW,
        timeframes=timeframes,
        intraday=RegimeState(anchor="1h", value=intraday),
        swing=RegimeState(anchor="4h", value=swing),
    )


def build_context(
    repository: Repository,
    source: Source,
    symbol: Symbol,
    *,
    market_at: datetime,
    knowledge_at: datetime,
    checked_at: datetime,
) -> MarketContext:
    windows = {
        tf: _window(
            repository,
            Stream(source=source, symbol=symbol, timeframe=tf),
            market_at=market_at,
            knowledge_at=knowledge_at,
        )
        for tf in TIMEFRAMES
    }
    return compose(
        source,
        symbol,
        windows,
        checked_at=checked_at,
        market_at=market_at,
        knowledge_at=knowledge_at,
    )
