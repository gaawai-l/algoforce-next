"""Response contracts of the read-only perps API, and the freshness rule behind them (spec §3.7,
§4)."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model
from .rows import Exchange, Stream
from .states import STEP, Block, Table, Tail, Thresholds, Window
from .sync import Directions, Verdict

DataState = Literal["fresh", "delayed", "stale", "unavailable"]

# Judged from the end of the last closed bucket, `last + 10m`.
FRESH_WITHIN = timedelta(minutes=30)
DELAYED_WITHIN = timedelta(hours=2)


def freshness(last: datetime | None, now: datetime) -> DataState:
    """How fresh a view whose last closed bucket starts at `last` is at `now`."""
    if last is None:
        return "unavailable"
    age = now - (last + timedelta(seconds=STEP))
    if age <= FRESH_WITHIN:
        return "fresh"
    return "delayed" if age <= DELAYED_WITHIN else "stale"


class CollectorStatus(Model):
    """One collected stream, from its stored coverage (P4-R10), and what its collectors in this
    process have run into."""

    stream: Stream
    live: bool  # a connection's last proof of life is at most 60 s old
    last_proof: AwareDatetime | None  # the latest stored coverage end of either connection
    down_since: AwareDatetime | None  # last_proof while not live; null while live or never run
    covered_days: float  # days covered in the last 90, both connections' union
    since: AwareDatetime | None  # the start of the earliest stored coverage
    # By code, both connections summed, since this process started them: every connection end
    # (rotated, stopped, or a failure such as stalled) and every problem counted (coverage_split,
    # bad_frame, ...). Empty while the collectors do not run in this process.
    problems: dict[str, int]


class PerpStatesView(Model):
    """One exchange view and window. While unavailable, everything from `last` on is null or
    empty and `reasons` say why."""

    exchange: Exchange
    window: Window
    data_state: DataState
    reasons: list[str]
    computed_at: AwareDatetime | None
    last: AwareDatetime | None
    thresholds: Thresholds | None
    blocks: list[Block]
    tail: Tail | None
    tables: list[Table]
    covered_days: float | None
    collecting: bool | None
    qc: list[str]
    series_missing: list[str]
    # Only the streams this view reads: liquidations, and Bybit's trades for its delta.
    collectors: list[CollectorStatus]


class HostStatus(Model):
    host: str
    last_success: AwareDatetime | None
    error: str | None  # the code of the last failure, until the host succeeds again
    backoff_until: AwareDatetime | None  # null once the deadline has passed


class PerpsStatus(Model):
    last_run_at: AwareDatetime | None
    last_error: str | None  # "sync_failed" when the last round failed unexpectedly
    hosts: list[HostStatus]
    collectors: list[CollectorStatus]
    # Both venues' liquidation sides: ok when both are, inverted when either is, else pending.
    direction: Verdict
    # Each venue's check and Bybit's size units; null before the first round.
    direction_check: Directions | None
