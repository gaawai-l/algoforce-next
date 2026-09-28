"""BTC on-chain market cycle as AlphaBTC shows it: six states, 0-100 index, grind-down monitor.

Computed on demand from bitview daily series through the last complete UTC day.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from .indicators.cycle.alphabtc import (
    INDEX_SERIES,
    PRESSURE_SERIES,
    START,
    STATE_SERIES,
    CycleIndex,
    CycleStates,
    ShortTermPressure,
    cycle_index,
    short_term_pressure,
    states,
)
from .indicators.demark.models import Model
from .onchain import Daily, OnchainError, fetch_daily, last_day

SERIES = (*STATE_SERIES, *INDEX_SERIES, *PRESSURE_SERIES)
Fetch = Callable[..., Daily]


class MarketCycle(Model):
    source: Literal["bitview"]
    status: Literal["fresh", "stale", "unavailable"]
    checked_at: datetime
    as_of: date | None
    states: CycleStates | None
    index: CycleIndex | None
    pressure: ShortTermPressure | None
    error: str | None


def compose_cycle(series: Daily, *, since: date, checked_at: datetime) -> MarketCycle:
    as_of = last_day(since, series)
    # bitview publishes a day once it ends; anything older than yesterday is behind.
    fresh = as_of >= checked_at.astimezone(UTC).date() - timedelta(days=1)
    return MarketCycle(
        source="bitview",
        status="fresh" if fresh else "stale",
        checked_at=checked_at,
        as_of=as_of,
        states=states(since, series),
        index=cycle_index(series),
        pressure=short_term_pressure(since, series),
        error=None,
    )


def build_cycle(checked_at: datetime, fetch: Fetch = fetch_daily) -> MarketCycle:
    try:
        series = fetch(SERIES, since=START, now=checked_at)
        return compose_cycle(series, since=START, checked_at=checked_at)
    except (OnchainError, ValueError) as exc:
        return MarketCycle(
            source="bitview",
            status="unavailable",
            checked_at=checked_at,
            as_of=None,
            states=None,
            index=None,
            pressure=None,
            error=str(exc),
        )
