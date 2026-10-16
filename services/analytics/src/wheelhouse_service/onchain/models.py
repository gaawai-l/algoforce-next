"""Response contracts of the read-only on-chain API, and the freshness rule behind them."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model
from .cycle import Component, CycleState, Episode
from .levels import ModelLine

DataState = Literal["fresh", "stale", "unavailable"]

# BRK publishes the new day's row some time after UTC midnight; until then yesterday's is current.
GRACE_END = time(2, 0)


def day1_state(last: date | None, now: datetime) -> DataState:
    """Freshness of daily data whose latest row is dated `last`, judged at `now`."""
    if last is None:
        return "unavailable"
    at = now.astimezone(UTC)
    if last == at.date():
        return "fresh"
    if last == at.date() - timedelta(days=1) and at.time() < GRACE_END:
        return "fresh"
    return "stale"


class DatasetStatus(Model):
    name: Literal["day1", "urpd"]
    data_state: DataState
    last_at: AwareDatetime | None
    reasons: list[str]


class OnchainStatus(Model):
    brk_version: str | None
    refreshing: bool
    last_success_at: AwareDatetime | None
    last_error: str | None
    datasets: list[DatasetStatus]


class CycleView(Model):
    data_state: DataState
    reasons: list[str]
    refreshing: bool
    # The time of the in-progress row, when `as_of` is today; otherwise null.
    forming_at: AwareDatetime | None
    as_of: date | None
    state: CycleState | None
    since: date | None
    day: int | None
    components: list[Component]
    episodes: list[Episode]
    changes: int
    brk_version: str | None


class LevelsView(Model):
    data_state: DataState
    reasons: list[str]
    refreshing: bool
    forming_at: AwareDatetime | None
    as_of: AwareDatetime | None
    urpd_date: date | None
    onchain_close: float | None
    lines: list[ModelLine]
    brk_version: str | None
