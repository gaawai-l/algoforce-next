"""The hourly legs of the sell-side chart, following the original state-report loader (v1).

Each hour splits what was realized, or spent, into long- and short-term holders in profit and at a
loss, for three measures: realized P&L in USD and spent volume in BTC and in USD. The short-term
legs also come without the coins held under 1h and under 24h. Smoothing, the span and the shares
depend on the reader's choices, so they are left to the page.
"""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model
from ..rules import Rule
from .pressure import V1_LOOKBACK

HOUR = timedelta(hours=1)
PRICE = "price_close"
Measure = Literal["pnl", "volb", "volu"]
MEASURES: tuple[Measure, ...] = ("pnl", "volb", "volu")
# The suffix of each measure's (profit, loss) cumulatives.
SUFFIXES: dict[Measure, tuple[str, str]] = {
    "pnl": ("_realized_profit_cumulative", "_realized_loss_cumulative"),
    "volb": ("_transfer_volume_in_profit_cumulative", "_transfer_volume_in_loss_cumulative"),
    "volu": (
        "_transfer_volume_in_profit_cumulative_usd",
        "_transfer_volume_in_loss_cumulative_usd",
    ),
}
# The cohorts taken out of the STH legs: under 1h for x1, both for x24.
YOUNG = ("utxos_under_1h_old", "utxos_1h_to_1d_old")
INPUTS = (
    PRICE,
    *(
        f"{holder}{suffix}"
        for suffixes in SUFFIXES.values()
        for holder in ("sth", "lth")
        for suffix in suffixes
    ),
    *(
        f"{cohort}{suffix}"
        for suffixes in SUFFIXES.values()
        for cohort in YOUNG
        for suffix in suffixes
    ),
)

Series = dict[datetime, float | None]


class SellSideLegs(Model):
    """One measure's legs, one value per kept hour, lined up with `SellSide.at`."""

    lth_profit: list[float]
    lth_loss: list[float]
    sth_profit: list[float]
    sth_loss: list[float]
    # Without the coins held under 1h, and under 24h.
    sth_profit_x1: list[float]
    sth_loss_x1: list[float]
    sth_profit_x24: list[float]
    sth_loss_x24: list[float]


class SellSide(Model):
    last_at: AwareDatetime
    # The newest hour with a price, kept or not: BRK is current even when that hour was dropped.
    latest_at: AwareDatetime
    at: list[AwareDatetime]
    price: list[float]
    pnl: SellSideLegs
    volb: SellSideLegs
    volu: SellSideLegs
    # Hours whose excluded cohorts had a gap: nothing was taken out of their STH legs.
    xgap: int
    qc: list[Literal["intraday_legs"]]
    rules: list[Rule] = []


def _round(measure: Measure, value: float) -> float:
    """The page's storage quantum: $100 and $1000 half up like Math.round, BTC like toFixed(1)."""
    if measure == "volb":
        return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    quantum = 100 if measure == "pnl" else 1000
    units = Decimal(value / quantum).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return float(units * quantum)


def _step(cumulative: Series, at: datetime) -> float | None:
    """What a cumulative series added in the hour ending at `at`, never below 0."""
    now, before = cumulative.get(at), cumulative.get(at - HOUR)
    if now is None or before is None:
        return None
    return max(0.0, now - before)


def sell_side(rows: dict[str, list[tuple[datetime, float | None]]]) -> SellSide | None:
    """The legs of every hour the original page keeps, or None when it keeps none.

    `rows` holds every INPUTS series in time order, lined up by timestamp; an hour a series does
    not have counts as a null there. An hour is kept when it has a price and all twelve main
    cumulatives are known for it and for the hour before. The excluded cohorts have a gate of their
    own: when any of their values is unknown, nothing is taken out that hour.
    """
    stamps = [at for name in INPUTS for at, _ in rows[name]]
    if not stamps:
        return None
    first = max(stamps) - HOUR * (V1_LOOKBACK - 1)
    series: dict[str, Series] = {
        name: {at: value for at, value in rows[name] if at >= first} for name in INPUTS
    }
    hours = sorted({at for values in series.values() for at in values})

    kept: list[datetime] = []
    prices: list[float] = []
    legs: dict[Measure, dict[str, list[float]]] = {
        measure: {leg: [] for leg in SellSideLegs.model_fields} for measure in MEASURES
    }
    xgap = 0
    # The oldest hour has no hour before it, so it only serves as one.
    for at in hours[1:]:
        price = series[PRICE].get(at)
        if price is None:
            continue
        steps = {
            (measure, holder, side): _step(series[f"{holder}{suffix}"], at)
            for measure, suffixes in SUFFIXES.items()
            for holder in ("sth", "lth")
            for side, suffix in zip(("profit", "loss"), suffixes, strict=True)
        }
        known = {key: value for key, value in steps.items() if value is not None}
        if len(known) < len(steps):
            continue
        young = {
            (measure, cohort, side): _step(series[f"{cohort}{suffix}"], at)
            for measure, suffixes in SUFFIXES.items()
            for cohort in YOUNG
            for side, suffix in zip(("profit", "loss"), suffixes, strict=True)
        }
        gap = any(value is None for value in young.values())
        if gap:
            xgap += 1
        kept.append(at)
        # The page keeps the price to 0.1 (toFixed), and its legend rounds that.
        prices.append(float(Decimal(price).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)))
        for measure in MEASURES:
            out = legs[measure]
            for side in ("profit", "loss"):
                lth, sth = known[(measure, "lth", side)], known[(measure, "sth", side)]
                under_1h = 0.0 if gap else young[(measure, YOUNG[0], side)] or 0.0
                under_1d = under_1h + (0.0 if gap else young[(measure, YOUNG[1], side)] or 0.0)
                out[f"lth_{side}"].append(_round(measure, lth))
                out[f"sth_{side}"].append(_round(measure, sth))
                # The cohorts come out of the raw difference, which is rounded only once.
                out[f"sth_{side}_x1"].append(_round(measure, max(0.0, sth - under_1h)))
                out[f"sth_{side}_x24"].append(_round(measure, max(0.0, sth - under_1d)))
    if not kept:
        return None

    priced = [at for at, value in series[PRICE].items() if value is not None]
    return SellSide(
        last_at=kept[-1],
        latest_at=max([*priced, kept[-1]]),
        at=kept,
        price=prices,
        pnl=SellSideLegs.model_validate(legs["pnl"]),
        volb=SellSideLegs.model_validate(legs["volb"]),
        volu=SellSideLegs.model_validate(legs["volu"]),
        xgap=xgap,
        qc=["intraday_legs"] if xgap else [],
    )
