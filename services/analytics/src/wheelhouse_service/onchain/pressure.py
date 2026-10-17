"""Seller pressure from the hourly BRK series, following the rules of the original page (v1).

O3 keeps the rows that v1 drops: an hour without a block carries the hour before over, and a value a
series gap leaves unknown is null instead of costing its row. O1 leaves the row still forming out of
the thresholds and the current reading. O2 gives every hour its own thresholds from the hours before
it, a level against them and, back from the current reading, a run.
"""

import math
from bisect import bisect_left, insort
from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Literal, NamedTuple

from pydantic import AwareDatetime, Field

from ..market import Model
from ..rules import Rule, Rules
from ..stats import quantile_r7
from .brk import HOUR1_SERIES

# Only the most recent hours count, whatever else the store holds: see `lookback`.
V1_LOOKBACK = 2600
# The most points of each series the seller pressure view sends: the widest span on offer, that
# many hours when none is missing. Under O2 each of them needs a window before it.
SHOWN_HOURS = 2160
# v1's levels look at the clock hours up to and including the last row of each chart; O1 ends that
# window at closed_at, and O2 gives each hour h its own, [h - 720h, h).
WINDOW = timedelta(hours=720)
HOUR = timedelta(hours=1)
# Under O2 an hour with fewer values than this in the window before it has no thresholds.
MIN_SAMPLES = 168
# Realized flows are rounded to whole units of this many dollars.
QUANTUM = 100
# The widest step between kept rows that passes QC: an hour without a block drops two rows.
MAX_STEP = timedelta(hours=3)
# Under O3 no row is dropped, so any step over an hour is a missing hour.
O3_MAX_STEP = HOUR

PRICE = "price_close"
STH_PROFIT = "sth_realized_profit_cumulative"
STH_LOSS = "sth_realized_loss_cumulative"
LTH_PROFIT = "lth_realized_profit_cumulative"
LTH_LOSS = "lth_realized_loss_cumulative"
YOUNG_PROFIT = "utxos_under_1h_old_realized_profit_cumulative"
YOUNG_LOSS = "utxos_under_1h_old_realized_loss_cumulative"
STH_IN_LOSS = "sth_supply_in_loss"
STH_IN_PROFIT = "sth_supply_in_profit"
YOUNG_IN_LOSS = "utxos_under_1h_old_supply_in_loss"
YOUNG_IN_PROFIT = "utxos_under_1h_old_supply_in_profit"

Series = dict[datetime, float | None]
# The original page's self-checks that concern seller pressure, in its order.
QcCode = Literal["hour_gap", "intraday_legs", "sth_supply"]
# O2: a value at or over its P95 is extreme, at or over its P75 a warning.
Level = Literal["extreme", "warning", "none"]


class PressureLevels(Model):
    """P95 and P75 of one chart over the last 720 clock hours, and how many values they use.

    Under O2 they are the start hour's: the 720 hours before it, the hour itself left out.
    """

    p95: float | None
    p75: float | None
    n: int


class PressureLossPoint(Model):
    at: AwareDatetime
    # Null only under O3, where a series gap leaves the leg unknown.
    lth: float | None
    sth: float | None
    # O3 only. `no_block`: the hour had no block, so its flows are 0 and its levels carried over.
    # `gap`: a series the value needs is null. Both default to False, so stored payloads still load.
    no_block: bool = False
    gap: bool = False
    # O2 only, else null; the defaults keep stored payloads readable. The thresholds come from the
    # 720 hours before this one. The level is null when they or the value are, and under O1 while
    # the hour is still forming.
    p95: float | None = None
    p75: float | None = None
    level: Level | None = None


class PressurePoint(Model):
    at: AwareDatetime
    # Null only under O3: a series gap, a share or supply whose denominator is not positive, or an
    # hour without a block on chart 2.
    value: float | None
    no_block: bool = False
    gap: bool = False
    # As on PressureLossPoint; always null on the price.
    p95: float | None = None
    p75: float | None = None
    level: Level | None = None


class Pressure(Model):
    last_at: AwareDatetime
    loss: list[PressureLossPoint]
    share: list[PressurePoint]
    supply: list[PressurePoint]
    price: list[PressurePoint]
    loss_levels: PressureLevels
    share_levels: PressureLevels
    supply_levels: PressureLevels
    kept: int
    xgap: int
    # The two fields below have defaults so that payloads stored before them stay readable until
    # the next derivation. `qc` lists the checks that failed; empty when all pass.
    qc: list[QcCode] = Field(default_factory=list)
    # The newest hour with a price, kept or not: BRK is current even when that hour was dropped.
    # Never older than `last_at`, whose price O3 can leave null.
    latest_at: AwareDatetime | None = None
    # The rules it was derived under; payloads stored before rules existed read as none.
    rules: list[Rule] = []
    # O1 only: the newest row that had closed when this was computed, the current reading. Null
    # when none had, and without O1, where the current reading is the last row.
    closed_at: AwareDatetime | None = None
    # O2 only: the clock hours in a row at warning or above, back from the current reading. Null
    # when the current reading has no level, which is not 0.
    loss_run: int | None = None
    share_run: int | None = None
    supply_run: int | None = None


class _Row(NamedTuple):
    """One kept hour. The flows are whole units of QUANTUM dollars; None only under O3."""

    at: datetime
    price: float | None
    lth_profit: int | None
    lth_loss: int | None
    sth_profit: int | None  # without the coins held under 1h
    sth_loss: int | None  # without the coins held under 1h
    no_block: bool = False


class _Thresholds(NamedTuple):
    p95: float | None
    p75: float | None
    n: int


def lookback(rules: Rules) -> int:
    """How many of the most recent hours count, whatever else the store holds.

    Under O2 the oldest hour on show needs a full window of kept rows before it, and one hour more:
    the oldest hour read only serves as the previous row. That holds when no hour is missing; when
    some are, the oldest points on show reach further back, and a window that would start before
    the first kept row has no thresholds rather than fewer values.
    """
    return SHOWN_HOURS + WINDOW // HOUR + 1 if "O2" in rules else V1_LOOKBACK


def _units(dollars: float) -> int:
    """Whole units of QUANTUM dollars, halves rounded up like JavaScript's Math.round."""
    return math.floor(dollars / QUANTUM + 0.5)


def _units_of(dollars: float | None) -> int | None:
    return None if dollars is None else _units(dollars)


def _dollars(units: int | None) -> float | None:
    return None if units is None else float(units * QUANTUM)


def _leg(cumulative: Series, at: datetime) -> float | None:
    """What a cumulative series added in the hour ending at `at`, never below 0."""
    now, before = cumulative.get(at), cumulative.get(at - HOUR)
    if now is None or before is None:
        return None
    return max(0.0, now - before)


def _last(points: Sequence[tuple[datetime, float | None]]) -> datetime | None:
    return points[-1][0] if points else None


def _levels(
    points: Sequence[tuple[datetime, float | None]], end: datetime | None
) -> PressureLevels:
    """The window is the 720 clock hours up to and including `end`; a null value is not in it.

    v1 ends it at the chart's last point, O1 at the current reading. None means no window at all.
    """
    if end is None:
        return PressureLevels(p95=None, p75=None, n=0)
    oldest = end - WINDOW
    values = sorted(value for at, value in points if oldest < at <= end and value is not None)
    return PressureLevels(
        p95=quantile_r7(values, 0.95), p75=quantile_r7(values, 0.75), n=len(values)
    )


def _rolling(
    samples: Sequence[tuple[datetime, float]],
    hours: Sequence[datetime],
    earliest: datetime | None,
) -> list[_Thresholds]:
    """O2: the thresholds of each of the ascending `hours`, from the samples in [h - 720h, h).

    The samples are in time order. A sorted window slides along them, so each hour only adds the
    samples it gains and removes those it loses. Both are null with fewer than MIN_SAMPLES, and
    when the window starts before `earliest`: older rows were left out, so it would be cut short.
    """
    window: list[float] = []
    added = removed = 0
    out: list[_Thresholds] = []
    for hour in hours:
        while added < len(samples) and samples[added][0] < hour:
            insort(window, samples[added][1])
            added += 1
        while removed < added and samples[removed][0] < hour - WINDOW:
            del window[bisect_left(window, samples[removed][1])]
            removed += 1
        if len(window) < MIN_SAMPLES or (earliest is not None and hour - WINDOW < earliest):
            out.append(_Thresholds(None, None, len(window)))
        else:
            p95, p75 = quantile_r7(window, 0.95), quantile_r7(window, 0.75)
            out.append(_Thresholds(p95, p75, len(window)))
    return out


def _level(value: float | None, thresholds: _Thresholds) -> Level | None:
    if value is None or thresholds.p95 is None or thresholds.p75 is None:
        return None
    if value >= thresholds.p95:
        return "extreme"
    return "warning" if value >= thresholds.p75 else "none"


def _run(levels: dict[datetime, Level | None], start: datetime) -> int | None:
    """The clock hours in a row at warning or above, back from `start`; null when it has no level.

    A missing row or a null value has no level, so either ends the run.
    """
    if levels.get(start) is None:
        return None
    run, at = 0, start
    while levels.get(at) in ("warning", "extreme"):
        run += 1
        at -= HOUR
    return run


def _roll[P: (PressureLossPoint, PressurePoint)](
    points: list[P],
    values: Sequence[float | None],
    start: datetime | None,
    earliest: datetime | None,
) -> tuple[list[P], PressureLevels, int | None]:
    """O2: the points with their thresholds and levels, the start hour's thresholds and the run.

    `values` are those of `points`. Only the points up to `start`, the current reading, are
    samples and have a level: under O1 those after it are still forming, and with `start` None no
    row has closed. A window starting before `earliest` has no thresholds: see `_rolling`.
    """

    def counted(at: datetime) -> bool:
        return start is not None and at <= start

    samples = [
        (point.at, value)
        for point, value in zip(points, values, strict=True)
        if value is not None and counted(point.at)
    ]
    hours = sorted({point.at for point in points} | ({start} if start is not None else set()))
    thresholds = dict(zip(hours, _rolling(samples, hours, earliest), strict=True))
    levels: dict[datetime, Level | None] = {}
    rolled: list[P] = []
    for point, value in zip(points, values, strict=True):
        own = thresholds[point.at]
        level = _level(value, own) if counted(point.at) else None
        levels[point.at] = level
        rolled.append(point.model_copy(update={"p95": own.p95, "p75": own.p75, "level": level}))
    if start is None:
        return rolled, PressureLevels(p95=None, p75=None, n=0), None
    current = thresholds[start]
    return (
        rolled,
        PressureLevels(p95=current.p95, p75=current.p75, n=current.n),
        _run(levels, start),
    )


def _carry_over_no_block(
    series: dict[str, Series], hours: list[datetime]
) -> tuple[list[datetime], set[datetime]]:
    """O3: an hour without a block, every series null there, takes every value of the hour before.

    `series` is filled in place, so the flows of such an hour are 0 and the next hour's differences
    read as usual. Hours without a block at the start of the window have nothing to carry over and
    are dropped: the window starts at the first hour with a block, which only serves as the previous
    row. Returns the hours left and those without a block.
    """

    def empty(at: datetime) -> bool:
        return all(series[name].get(at) is None for name in HOUR1_SERIES)

    start = next((i for i, at in enumerate(hours) if not empty(at)), len(hours))
    hours = hours[start:]
    no_block: set[datetime] = set()
    for at in hours[1:]:
        if empty(at):
            no_block.add(at)
            for name in HOUR1_SERIES:
                series[name][at] = series[name].get(at - HOUR)
    return hours, no_block


def _less(leg: float | None, young: float) -> float | None:
    """A short-term holders' leg without the coins held under 1h, never below 0."""
    return None if leg is None else max(0.0, leg - young)


def seller_pressure(
    rows: dict[str, list[tuple[datetime, float | None]]], *, rules: Rules, computed_at: datetime
) -> Pressure | None:
    """The three seller pressure charts, or None when no row can be kept.

    `rows` holds every HOUR1_SERIES series in time order. Series are lined up by timestamp, and an
    hour a series does not have counts as a null there. Under v1 nothing is filled in: a row is
    kept only when the price and the four realized cumulatives are known for it and for the hour
    before. Under O3 every hour after the first is kept: an hour without a block carries the hour
    before over, and what a null leaves unknown is null and marked as a gap.

    `computed_at` is when the rows were read: under O1 a row has closed once its hour is over by
    then. v1 does not use it.
    """
    o1, o2, o3 = "O1" in rules, "O2" in rules, "O3" in rules
    stamps = [at for name in HOUR1_SERIES for at, _ in rows[name]]
    if not stamps:
        return None
    first = max(stamps) - HOUR * (lookback(rules) - 1)
    series: dict[str, Series] = {
        name: {at: value for at, value in rows[name] if at >= first} for name in HOUR1_SERIES
    }
    hours = sorted({at for values in series.values() for at in values})
    no_block: set[datetime] = set()
    if o3:
        hours, no_block = _carry_over_no_block(series, hours)

    kept: list[_Row] = []
    xgap = 0
    # The oldest hour has no previous row, so it only serves as one.
    for at in hours[1:]:
        price = series[PRICE].get(at)
        if at in no_block:
            # Nothing happened on chain that hour: its flows are 0, not unknown.
            kept.append(_Row(at, price, 0, 0, 0, 0, no_block=True))
            continue
        sth_profit = _leg(series[STH_PROFIT], at)
        sth_loss = _leg(series[STH_LOSS], at)
        lth_profit = _leg(series[LTH_PROFIT], at)
        lth_loss = _leg(series[LTH_LOSS], at)
        if not o3 and (
            price is None
            or sth_profit is None
            or sth_loss is None
            or lth_profit is None
            or lth_loss is None
        ):
            continue
        young_profit = _leg(series[YOUNG_PROFIT], at)
        young_loss = _leg(series[YOUNG_LOSS], at)
        if young_profit is None or young_loss is None:
            # Keep the hour but take nothing out of the short-term holders.
            xgap += 1
            young_profit = young_loss = 0.0
        # The coins held under 1h come out of the raw difference, which is rounded only once.
        kept.append(
            _Row(
                at,
                price,
                _units_of(lth_profit),
                _units_of(lth_loss),
                _units_of(_less(sth_profit, young_profit)),
                _units_of(_less(sth_loss, young_loss)),
            )
        )
    if not kept:
        return None

    loss = [
        PressureLossPoint(
            at=r.at,
            lth=_dollars(r.lth_loss),
            sth=_dollars(r.sth_loss),
            no_block=r.no_block,
            gap=r.lth_loss is None or r.sth_loss is None,
        )
        for r in kept
    ]
    # One unknown leg leaves the total unknown.
    loss_totals = [
        (
            r.at,
            None
            if r.lth_loss is None or r.sth_loss is None
            else float((r.lth_loss + r.sth_loss) * QUANTUM),
        )
        for r in kept
    ]

    share: list[PressurePoint] = []
    for r in kept:
        if r.lth_profit is None or r.lth_loss is None or r.sth_profit is None or r.sth_loss is None:
            share.append(PressurePoint(at=r.at, value=None, gap=True))
            continue
        total = r.lth_profit + r.lth_loss + r.sth_profit + r.sth_loss
        if total > 0:
            share.append(PressurePoint(at=r.at, value=r.sth_loss / total))
        elif o3:
            # Without a block, or with nothing realized, there is no share; it is not 0.
            share.append(PressurePoint(at=r.at, value=None, no_block=r.no_block))

    supply: list[PressurePoint] = []
    for r in kept:
        in_loss, in_profit = series[STH_IN_LOSS].get(r.at), series[STH_IN_PROFIT].get(r.at)
        young_in_loss, young_in_profit = (
            series[YOUNG_IN_LOSS].get(r.at),
            series[YOUNG_IN_PROFIT].get(r.at),
        )
        if in_loss is None or in_profit is None or young_in_loss is None or young_in_profit is None:
            if o3:
                supply.append(PressurePoint(at=r.at, value=None, no_block=r.no_block, gap=True))
            continue
        old_loss, old_profit = in_loss - young_in_loss, in_profit - young_in_profit
        if old_loss + old_profit > 0:
            supply.append(
                PressurePoint(
                    at=r.at, value=old_loss / (old_loss + old_profit), no_block=r.no_block
                )
            )
        elif o3:
            supply.append(PressurePoint(at=r.at, value=None, no_block=r.no_block))

    # The current reading: under O1 the newest closed row, which may be none; else the last row.
    closed_at = (
        next((r.at for r in reversed(kept) if computed_at >= r.at + HOUR), None) if o1 else None
    )
    start = closed_at if o1 else kept[-1].at
    # With rows older than the lookback left out, no sample can come from before the first kept
    # row, so a window reaching back past it is cut short. Without them, the rows are all the
    # history there is, and its start only has fewer values.
    earliest = kept[0].at if min(stamps) < first else None
    loss_run = share_run = supply_run = None
    if o2:
        loss_values = [value for _, value in loss_totals]
        loss, loss_levels, loss_run = _roll(loss, loss_values, start, earliest)
        share, share_levels, share_run = _roll(share, [p.value for p in share], start, earliest)
        supply, supply_levels, supply_run = _roll(
            supply, [p.value for p in supply], start, earliest
        )
    else:
        share_values = [(p.at, p.value) for p in share]
        supply_values = [(p.at, p.value) for p in supply]
        # v1's window ends at each chart's last point, O1's at the current reading.
        loss_levels = _levels(loss_totals, start if o1 else _last(loss_totals))
        share_levels = _levels(share_values, start if o1 else _last(share_values))
        supply_levels = _levels(supply_values, start if o1 else _last(supply_values))

    qc: list[QcCode] = []
    max_step = O3_MAX_STEP if o3 else MAX_STEP
    if any(b.at - a.at > max_step for a, b in pairwise(kept)):
        qc.append("hour_gap")
    if xgap:
        qc.append("intraday_legs")
    if any(
        series[STH_IN_LOSS].get(r.at) is None or series[STH_IN_PROFIT].get(r.at) is None
        for r in kept
    ):
        qc.append("sth_supply")

    # Under v1 the last row has a price, so it is never newer than the newest priced hour. Under O3
    # it may lack only its price and still be the newest hour BRK has.
    priced = [at for at, value in series[PRICE].items() if value is not None]
    return Pressure(
        last_at=kept[-1].at,
        loss=loss,
        share=share,
        supply=supply,
        price=[
            PressurePoint(at=r.at, value=r.price, no_block=r.no_block, gap=r.price is None)
            for r in kept
        ],
        loss_levels=loss_levels,
        share_levels=share_levels,
        supply_levels=supply_levels,
        kept=len(kept),
        xgap=xgap,
        qc=qc,
        latest_at=max([*priced, kept[-1].at]),
        closed_at=closed_at,
        loss_run=loss_run,
        share_run=share_run,
        supply_run=supply_run,
    )
