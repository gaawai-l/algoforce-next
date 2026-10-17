"""Response contracts of the read-only on-chain API, and the freshness rule behind them."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model
from ..rules import Rule
from .costbasis import BucketCostBasis
from .cycle import Component, CycleState, Episode
from .levels import ModelLine
from .pressure import PressureLevels, PressureLossPoint, PressurePoint, QcCode

DataState = Literal["fresh", "stale", "unavailable"]
# Hourly data adds `delayed`: late, but not yet old enough to call stale.
HourState = Literal["fresh", "delayed", "stale", "unavailable"]

# BRK publishes the new day's row some time after UTC midnight; until then yesterday's is current.
GRACE_END = time(2, 0)
# Hourly rows older than this are delayed, and older than the second one are stale.
HOUR1_FRESH = timedelta(hours=2)
HOUR1_DELAYED = timedelta(hours=6)


def closed_day(at: datetime) -> date:
    """The latest closed day at `at`, for day1 rows and URPD snapshots alike.

    BRK may still revise a day's values until GRACE_END on the next day, so yesterday only counts
    as closed from then on.
    """
    grace = timedelta(hours=GRACE_END.hour, minutes=GRACE_END.minute)
    return (at.astimezone(UTC) - grace).date() - timedelta(days=1)


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


def hour1_state(last: datetime | None, now: datetime) -> HourState:
    """Freshness of hourly data whose latest row starts at `last`, judged at `now`."""
    if last is None:
        return "unavailable"
    age = now - last
    if age <= HOUR1_FRESH:
        return "fresh"
    return "delayed" if age <= HOUR1_DELAYED else "stale"


class DatasetStatus(Model):
    name: Literal["day1", "urpd", "hour1"]
    # A superset of the daily states: only hourly data is ever delayed.
    data_state: HourState
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
    # Null when there is no cycle: an absent count is not zero.
    changes: int | None
    brk_version: str | None
    # The rules the payload was derived under, and whether they differ from the configured ones
    # until it is derived again. Empty and false when there is no payload; likewise below.
    rules: list[Rule]
    rules_pending: bool


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
    rules: list[Rule]
    rules_pending: bool


class CostBasisView(Model):
    # Follows the older of the snapshot's day and the lines' day.
    data_state: DataState
    reasons: list[str]
    refreshing: bool
    # The start of the latest day that was still open when its data was fetched; otherwise null.
    forming_at: AwareDatetime | None
    urpd_date: date | None
    lines_as_of: date | None
    snapshot_at: AwareDatetime | None
    computed_at: AwareDatetime | None
    # Only the bucket widths whose snapshots are all stored; the reasons name the rest.
    buckets: list[BucketCostBasis]
    brk_version: str | None
    rules: list[Rule]
    rules_pending: bool


class SellerPressureView(Model):
    data_state: HourState
    reasons: list[str]
    refreshing: bool
    # The time of the in-progress row, when the last row was still open when it was computed.
    forming_at: AwareDatetime | None
    last_at: AwareDatetime | None
    # Only the most recent points; the levels below always come from the whole computation.
    loss: list[PressureLossPoint]
    share: list[PressurePoint]
    supply: list[PressurePoint]
    price: list[PressurePoint]
    # Null when there is no data: an absent threshold is not zero.
    loss_levels: PressureLevels | None
    share_levels: PressureLevels | None
    supply_levels: PressureLevels | None
    xgap: int | None
    # The QC checks that failed; empty when they all pass or there is no data.
    qc: list[QcCode]
    brk_version: str | None
    rules: list[Rule]
    rules_pending: bool
