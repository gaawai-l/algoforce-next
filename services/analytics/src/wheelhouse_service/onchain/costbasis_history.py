"""The cost-basis history of Chart 8 (Cost Basis Distribution, All Coins), following the original
state-report loader (v1).

The original (`raw/script_3_app.js` lines 379-402) reads one all-coins lin500 URPD snapshot per day
for the last 1,461 days and maps each onto the grid of the newest: the $500 buckets from $1,000 up,
a bucket an older snapshot lacks being 0. Here each day is stored as that row (`history_row`), the
supply of each bucket to 0.01 BTC, and `cost_basis_history` lays the rows out on the newest grid.

One deliberate departure: the original keeps only the days it fetched, so a failed fetch drops a
column. Here every calendar day of the window has a column; a day without a row is `pending`, one
BRK had no snapshot for is `absent`, and both have no close and no supply, never 0. A row fetched
before its day ended is marked `forming`.
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from ..market import Model
from ..rules import Rule
from .brk import Urpd

# The original's `dates.slice(-1461)`: four years of days, the newest included.
HISTORY_DAYS = 1461
# The backfill of missing days: requests per sync round, the pause between two requests, and the
# longest a round may take.
HISTORY_BUDGET = 120
HISTORY_PAUSE_SECONDS = 0.5
HISTORY_DEADLINE_SECONDS = 300
# A day BRK had no snapshot for is asked for again once this long has passed.
ABSENT_RETRY = timedelta(days=1)
# The grid: $500 buckets from $1,000 up. Cost basis under $1,000 is left out, as on Chart 7.
FLOOR_MIN = 1000
FLOOR_STEP = 500

DayStatus = Literal["closed", "forming", "pending", "absent"]


class HistoryDay(Model):
    day: date
    # Both None when BRK had no snapshot of the day when asked at fetched_at.
    close: float | None
    # BTC to 0.01 per bucket of the grid from FLOOR_MIN, up to the snapshot's highest bucket.
    supply: list[float] | None
    fetched_at: AwareDatetime

    @model_validator(mode="after")
    def close_with_supply(self) -> Self:
        if (self.close is None) != (self.supply is None):
            raise ValueError("Close and supply must both be present or both be missing")
        return self


class CostBasisHistory(Model):
    latest_day: date
    # The price floor of each row of the grid, in USD.
    floors: list[int]
    # HISTORY_DAYS calendar days, the oldest first and latest_day last.
    days: list[date]
    # One entry per day; None for a pending or absent day.
    close: list[float | None]
    supply: list[list[float] | None]
    status: list[DayStatus]
    rules: list[Rule] = []
    backfill_error: str | None = None


def history_row(urpd: Urpd) -> list[float]:
    """The supply of each grid bucket up to the snapshot's highest, 0 for one it lacks, to 0.01
    BTC: the original's `c8row`. Empty when no bucket is on the grid, a bad snapshot."""
    cells: dict[int, float] = {}
    for bucket in urpd.buckets:
        floor = round(bucket.price_floor)
        if floor >= FLOOR_MIN and (floor - FLOOR_MIN) % FLOOR_STEP == 0:
            cells[(floor - FLOOR_MIN) // FLOOR_STEP] = round(bucket.supply, 2)
    if not cells:
        return []
    return [cells.get(index, 0.0) for index in range(max(cells) + 1)]


def cost_basis_history(rows: Mapping[date, HistoryDay], latest: date) -> CostBasisHistory | None:
    """The HISTORY_DAYS days up to `latest` on the grid of its row, or None without that row."""
    newest = rows.get(latest)
    if newest is None or not newest.supply:
        return None
    width = len(newest.supply)
    days = [latest - timedelta(days=n) for n in range(HISTORY_DAYS - 1, -1, -1)]
    close: list[float | None] = []
    supply: list[list[float] | None] = []
    status: list[DayStatus] = []
    for day in days:
        row = rows.get(day)
        # An empty supply is no data, as for an absent day: never a column of zeros.
        if row is None or not row.supply:
            close.append(None)
            supply.append(None)
            status.append("pending" if row is None else "absent")
            continue
        close.append(row.close)
        supply.append(row.supply[:width] + [0.0] * (width - len(row.supply)))
        # Not models.day_start: models imports DayStatus from here.
        end = datetime.combine(day + timedelta(days=1), time(), tzinfo=UTC)
        status.append("forming" if row.fetched_at < end else "closed")
    return CostBasisHistory(
        latest_day=latest,
        floors=[FLOOR_MIN + FLOOR_STEP * index for index in range(width)],
        days=days,
        close=close,
        supply=supply,
        status=status,
    )
