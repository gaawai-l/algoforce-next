"""Seller pressure from the hourly BRK series, following the rules of the original page (v1)."""

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import NamedTuple

from pydantic import AwareDatetime

from ..market import Model
from .brk import HOUR1_SERIES

# Only the most recent hours count, whatever else the store holds.
LOOKBACK = 2600
# Levels look at the clock hours up to and including the last row of each chart.
WINDOW = timedelta(hours=720)
HOUR = timedelta(hours=1)
# Realized flows are rounded to whole units of this many dollars.
QUANTUM = 100

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


class Levels(Model):
    """P95 and P75 of one chart over the last 720 clock hours, and how many values they use."""

    p95: float | None
    p75: float | None
    n: int


class LossPoint(Model):
    at: AwareDatetime
    lth: float
    sth: float


class Point(Model):
    at: AwareDatetime
    value: float


class Pressure(Model):
    last_at: AwareDatetime
    loss: list[LossPoint]
    share: list[Point]
    supply: list[Point]
    price: list[Point]
    loss_levels: Levels
    share_levels: Levels
    supply_levels: Levels
    kept: int
    xgap: int


class _Row(NamedTuple):
    """One kept hour. The flows are whole units of QUANTUM dollars."""

    at: datetime
    price: float
    lth_profit: int
    lth_loss: int
    sth_profit: int  # without the coins held under 1h
    sth_loss: int  # without the coins held under 1h


def quantile_r7(sorted_values: Sequence[float], q: float) -> float | None:
    """The R-7 quantile of ascending values: linear between the neighbours at (n - 1) * q."""
    n = len(sorted_values)
    if n == 0:
        return None
    if q <= 0 or n < 2:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    position = (n - 1) * q
    below = math.floor(position)
    return sorted_values[below] + (sorted_values[below + 1] - sorted_values[below]) * (
        position - below
    )


def _units(dollars: float) -> int:
    """Whole units of QUANTUM dollars, halves rounded up like JavaScript's Math.round."""
    return math.floor(dollars / QUANTUM + 0.5)


def _leg(cumulative: Series, at: datetime) -> float | None:
    """What a cumulative series added in the hour ending at `at`, never below 0."""
    now, before = cumulative.get(at), cumulative.get(at - HOUR)
    if now is None or before is None:
        return None
    return max(0.0, now - before)


def _levels(points: Sequence[tuple[datetime, float]]) -> Levels:
    if not points:
        return Levels(p95=None, p75=None, n=0)
    oldest = points[-1][0] - WINDOW
    values = sorted(value for at, value in points if at > oldest)
    return Levels(p95=quantile_r7(values, 0.95), p75=quantile_r7(values, 0.75), n=len(values))


def seller_pressure(rows: dict[str, list[tuple[datetime, float | None]]]) -> Pressure | None:
    """The three seller pressure charts, or None when no row can be kept.

    `rows` holds every HOUR1_SERIES series in time order. Series are lined up by timestamp, and an
    hour a series does not have counts as a null there. Nothing is filled in: a row is kept only
    when the price and the four realized cumulatives are known for it and for the hour before.
    """
    stamps = [at for name in HOUR1_SERIES for at, _ in rows[name]]
    if not stamps:
        return None
    first = max(stamps) - HOUR * (LOOKBACK - 1)
    series: dict[str, Series] = {
        name: {at: value for at, value in rows[name] if at >= first} for name in HOUR1_SERIES
    }

    kept: list[_Row] = []
    xgap = 0
    # The oldest hour has no previous row, so it only serves as one.
    for at in sorted({at for values in series.values() for at in values}):
        price = series[PRICE].get(at)
        sth_profit = _leg(series[STH_PROFIT], at)
        sth_loss = _leg(series[STH_LOSS], at)
        lth_profit = _leg(series[LTH_PROFIT], at)
        lth_loss = _leg(series[LTH_LOSS], at)
        if (
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
                _units(lth_profit),
                _units(lth_loss),
                _units(max(0.0, sth_profit - young_profit)),
                _units(max(0.0, sth_loss - young_loss)),
            )
        )
    if not kept:
        return None

    loss = [
        LossPoint(at=r.at, lth=float(r.lth_loss * QUANTUM), sth=float(r.sth_loss * QUANTUM))
        for r in kept
    ]
    loss_totals = [(r.at, float((r.lth_loss + r.sth_loss) * QUANTUM)) for r in kept]

    share: list[tuple[datetime, float]] = []
    for r in kept:
        total = r.lth_profit + r.lth_loss + r.sth_profit + r.sth_loss
        if total > 0:
            share.append((r.at, r.sth_loss / total))

    supply: list[tuple[datetime, float]] = []
    for r in kept:
        in_loss, in_profit = series[STH_IN_LOSS].get(r.at), series[STH_IN_PROFIT].get(r.at)
        young_in_loss, young_in_profit = (
            series[YOUNG_IN_LOSS].get(r.at),
            series[YOUNG_IN_PROFIT].get(r.at),
        )
        if in_loss is None or in_profit is None or young_in_loss is None or young_in_profit is None:
            continue
        old_loss, old_profit = in_loss - young_in_loss, in_profit - young_in_profit
        if old_loss + old_profit > 0:
            supply.append((r.at, old_loss / (old_loss + old_profit)))

    return Pressure(
        last_at=kept[-1].at,
        loss=loss,
        share=[Point(at=at, value=value) for at, value in share],
        supply=[Point(at=at, value=value) for at, value in supply],
        price=[Point(at=r.at, value=r.price) for r in kept],
        loss_levels=_levels(loss_totals),
        share_levels=_levels(share),
        supply_levels=_levels(supply),
        kept=len(kept),
        xgap=xgap,
    )
