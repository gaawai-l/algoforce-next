"""The size-cohort changes of Charts 5 and 6, following the original state-report loader (v1).

For each of the twelve wallet-size bands the loader (`raw/script_3_app.js` lines 323-339) reads the
supply and the realized cap at the newest hour, and for each window the change of the supply and
of the realized profit and loss cumulatives since the hour `hours` before it. Supplies are kept to
0.01 BTC as `+x.toFixed(2)` keeps them, dollars whole as `Math.round` rounds them.

One deliberate departure: where either end of a difference is null or has no row, the original
subtracts null as 0 and shows the whole cumulative as the change. Here that cell is None. An anchor
hour without a block, null in every series, is also listed in `no_block`, so the page can say why.
"""

import math
from datetime import datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model
from ..rules import Rule
from .brk import SIZE_BANDS, SIZE_SERIES, SIZE_SUFFIXES
from .costbasis import _cents

WindowKey = Literal["1d", "7d", "30d", "90d"]
WINDOWS: tuple[tuple[WindowKey, int], ...] = (
    ("1d", 24),
    ("7d", 168),
    ("30d", 720),
    ("90d", 2160),
)
# Rows read per series: the original's start=-2250 (`raw/script_3_app.js` lines 125-131).
DEPTH = 2250
HOUR = timedelta(hours=1)
SUPPLY, PROFIT, LOSS, CAP = SIZE_SUFFIXES

Series = dict[datetime, float | None]


class SizeWindow(Model):
    window: WindowKey
    # BTC, to 0.01 like toFixed(2).
    supply_change: float | None
    # Whole dollars like Math.round.
    profit: int | None
    loss: int | None


class SizeBand(Model):
    # A SIZE_BANDS prefix.
    band: str
    # BTC at last_at, to 0.01.
    supply: float | None
    # USD at last_at, whole dollars.
    realized_cap: int | None
    # In WINDOWS order.
    windows: list[SizeWindow]


class SizeCohorts(Model):
    last_at: AwareDatetime
    # In SIZE_BANDS order.
    bands: list[SizeBand]
    # Windows whose anchor hour (last_at - hours) had no block: every one of the 48 series has a
    # row there and all of them are null. Their cells are None; the page says why.
    no_block: list[WindowKey]
    rules: list[Rule] = []


def _dollars(value: float) -> int:
    """JavaScript `Math.round`: a half goes up, toward +infinity, never to even."""
    return math.floor(value + 0.5)


def _difference(values: Series, start: datetime, end: datetime) -> float | None:
    """`values[end] - values[start]`, or None when either is null or has no row: never null as 0."""
    first, last = values.get(start), values.get(end)
    if first is None or last is None:
        return None
    return last - first


def size_cohorts(rows: dict[str, list[tuple[datetime, float | None]]]) -> SizeCohorts | None:
    """Each band's supply, realized cap and window changes at the newest hour, or None.

    `rows` holds every SIZE_SERIES series in time order. The newest hour is the latest one that
    every series has a row for; with a series that has no rows at all there is nothing to read.
    """
    if any(not rows[name] for name in SIZE_SERIES):
        return None
    last_at = min(rows[name][-1][0] for name in SIZE_SERIES)
    series: dict[str, Series] = {name: dict(rows[name]) for name in SIZE_SERIES}

    bands: list[SizeBand] = []
    for band in SIZE_BANDS:
        supply = series[f"{band}{SUPPLY}"].get(last_at)
        cap = series[f"{band}{CAP}"].get(last_at)
        windows: list[SizeWindow] = []
        for window, hours in WINDOWS:
            start = last_at - HOUR * hours
            change = _difference(series[f"{band}{SUPPLY}"], start, last_at)
            profit = _difference(series[f"{band}{PROFIT}"], start, last_at)
            loss = _difference(series[f"{band}{LOSS}"], start, last_at)
            windows.append(
                SizeWindow(
                    window=window,
                    supply_change=None if change is None else _cents(change),
                    profit=None if profit is None else _dollars(profit),
                    loss=None if loss is None else _dollars(loss),
                )
            )
        bands.append(
            SizeBand(
                band=band,
                supply=None if supply is None else _cents(supply),
                realized_cap=None if cap is None else _dollars(cap),
                windows=windows,
            )
        )

    def blockless(at: datetime) -> bool:
        return all(at in values and values[at] is None for values in series.values())

    return SizeCohorts(
        last_at=last_at,
        bands=bands,
        no_block=[window for window, hours in WINDOWS if blockless(last_at - HOUR * hours)],
    )
