"""The hourly bands of the age-cohort chart, following the original state-report loader (v1).

Each hour splits what was realized, or spent, across twelve bands of coin age, in profit and at a
loss, for the sell-side chart's three measures. Smoothing, the fold into six bands, the span and
the shares depend on the reader's choices, so they are left to the page.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import AwareDatetime

from ..market import Model
from ..rules import Rule
from .brk import AGE_SERIES
from .pressure import V1_LOOKBACK
from .sellside import HOUR, MEASURES, PRICE, SUFFIXES, Measure, Series, _round, _step

# The original's twelve bands, youngest first, and the BRK cohorts each one adds up.
BANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("<1d", ("utxos_under_1h_old", "utxos_1h_to_1d_old")),
    ("1d–1w", ("utxos_1d_to_1w_old",)),
    ("1w–1m", ("utxos_1w_to_1m_old",)),
    ("1m–3m", ("utxos_1m_to_2m_old", "utxos_2m_to_3m_old")),
    ("3m–6m", ("utxos_3m_to_4m_old", "utxos_4m_to_5m_old", "utxos_5m_to_6m_old")),
    ("6m–1y", ("utxos_6m_to_9m_old", "utxos_9m_to_1y_old")),
    ("1y–2y", ("utxos_1y_to_18m_old", "utxos_18m_to_2y_old")),
    ("2y–3y", ("utxos_2y_to_3y_old",)),
    ("3y–5y", ("utxos_3y_to_4y_old", "utxos_4y_to_5y_old")),
    ("5y–7y", ("utxos_5y_to_6y_old", "utxos_6y_to_7y_old")),
    ("7y–10y", ("utxos_7y_to_8y_old", "utxos_8y_to_10y_old")),
    ("10y+", ("utxos_10y_to_12y_old", "utxos_12y_to_15y_old", "utxos_over_15y_old")),
)
INPUTS = (PRICE, *AGE_SERIES)
SIDES = ("profit", "loss")


class AgeBands(Model):
    """One measure's twelve bands, youngest first, each one value per kept hour."""

    profit: list[list[float]]
    loss: list[list[float]]


class AgeCohorts(Model):
    last_at: AwareDatetime
    # The newest hour with a price, kept or not: BRK is current even when that hour was dropped.
    latest_at: AwareDatetime
    at: list[AwareDatetime]
    price: list[float]
    pnl: AgeBands
    volb: AgeBands
    volu: AgeBands
    rules: list[Rule] = []


def age_cohorts(rows: dict[str, list[tuple[datetime, float | None]]]) -> AgeCohorts | None:
    """The bands of every hour the original page keeps, or None when it keeps none.

    `rows` holds every INPUTS series in time order, lined up by timestamp; an hour a series does
    not have counts as a null there. An hour is kept when it has a price and every one of the 138
    cumulatives is known for it and for the hour before, whichever measure is read.
    """
    # The window ends at the newest hour with a price row, as the page's does: an hour the age
    # cohorts' own stage fetched beyond it could not be kept anyway.
    stamps = [at for at, _ in rows[PRICE]]
    if not stamps:
        return None
    first = max(stamps) - HOUR * (V1_LOOKBACK - 1)
    series: dict[str, Series] = {
        name: {at: value for at, value in rows[name] if at >= first} for name in INPUTS
    }
    hours = sorted({at for values in series.values() for at in values})

    kept: list[datetime] = []
    prices: list[float] = []
    bands: dict[Measure, dict[str, list[list[float]]]] = {
        measure: {side: [[] for _ in BANDS] for side in SIDES} for measure in MEASURES
    }
    # The oldest hour has no hour before it, so it only serves as one.
    for at in hours[1:]:
        price = series[PRICE].get(at)
        if price is None:
            continue
        steps = {name: _step(series[name], at) for name in AGE_SERIES}
        known = {name: step for name, step in steps.items() if step is not None}
        if len(known) < len(steps):
            continue
        kept.append(at)
        # The page keeps the price to 0.1 (toFixed), as it does for the sell-side chart.
        prices.append(float(Decimal(price).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)))
        for measure, suffixes in SUFFIXES.items():
            for side, suffix in zip(SIDES, suffixes, strict=True):
                for column, (_, cohorts) in zip(bands[measure][side], BANDS, strict=True):
                    # Each cohort is clamped on its own before the band adds them up, in order.
                    total = 0.0
                    for cohort in cohorts:
                        total += known[f"{cohort}{suffix}"]
                    column.append(_round(measure, total))
    if not kept:
        return None

    priced = [at for at, value in series[PRICE].items() if value is not None]
    return AgeCohorts(
        last_at=kept[-1],
        latest_at=max([*priced, kept[-1]]),
        at=kept,
        price=prices,
        pnl=AgeBands.model_validate(bands["pnl"]),
        volb=AgeBands.model_validate(bands["volb"]),
        volu=AgeBands.model_validate(bands["volu"]),
    )
