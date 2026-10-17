"""On-chain model cost lines and the URPD median cost."""

import re
from datetime import date, datetime
from typing import Literal

from ..market import Model
from ..rules import Rules
from .brk import Urpd

LineName = Literal["true_mean", "short_term", "average", "long_term", "median", "one_day_to_week"]

# The four lines that come from day1 series; `median` comes from the URPD snapshot.
LINE_SERIES: dict[LineName, str] = {
    "true_mean": "true_market_mean",
    "short_term": "sth_realized_price",
    "average": "realized_price",
    "long_term": "lth_realized_price",
}
# O5 adds the cost of the coins last moved 1 day to 1 week ago, the cycle's W, as a fifth series.
O5_LINE_SERIES: dict[LineName, str] = {
    **LINE_SERIES,
    "one_day_to_week": "utxos_1d_to_1w_old_realized_price",
}


def line_series(rules: Rules) -> dict[LineName, str]:
    """The lines that come from day1 series under `rules`, with their series names."""
    return O5_LINE_SERIES if "O5" in rules else LINE_SERIES


_LINEAR = re.compile(r"lin(\d+)")


class ModelLine(Model):
    name: LineName
    price: float


def last_complete(
    rows: dict[str, list[tuple[datetime, float | None]]],
    *,
    rules: Rules,
    through: date | None,
) -> tuple[datetime, dict[str, float]] | None:
    """The latest time at which every line series has a value above 0, keyed by series name.

    A partial point, such as today's when one series has not been published yet, is skipped.
    O1: so is every point dated after `through`, so the lines are of a closed day. O5: the 1d–1w
    series is one of the line series.
    """
    limit = through if "O1" in rules else None
    series = line_series(rules)
    by_time: dict[datetime, dict[str, float]] = {}
    for name in series.values():
        for time, value in rows.get(name, []):
            if limit is not None and time.date() > limit:
                continue
            if value is not None and value > 0:
                by_time.setdefault(time, {})[name] = value
    complete = [time for time, values in by_time.items() if len(values) == len(series)]
    if not complete:
        return None
    latest = max(complete)
    return latest, by_time[latest]


def median_cost(urpd: Urpd) -> float | None:
    """The price at which half of the supply is held below, interpolated inside its bucket."""
    match = _LINEAR.fullmatch(urpd.aggregation)
    if match is None:
        raise ValueError(f"unsupported URPD aggregation: {urpd.aggregation}")
    width = float(match.group(1))
    total = sum(bucket.supply for bucket in urpd.buckets)
    if total <= 0:
        return None
    half = total / 2
    below = 0.0
    for bucket in sorted(urpd.buckets, key=lambda bucket: bucket.price_floor):
        if below + bucket.supply >= half:
            return bucket.price_floor + width * (half - below) / bucket.supply
        below += bucket.supply
    # Unreachable: the cumulative supply reaches `total`, which is at least `half`.
    raise AssertionError("median bucket not found")


def model_lines(last: dict[str, float], urpd: Urpd | None, *, rules: Rules) -> list[ModelLine]:
    """The four series lines, plus the URPD median when a snapshot with supply is given.

    O5 adds the 1d–1w line last, from `last` like the four.
    """
    lines = [ModelLine(name=name, price=last[series]) for name, series in LINE_SERIES.items()]
    if urpd is not None:
        median = median_cost(urpd)
        if median is not None:
            lines.append(ModelLine(name="median", price=median))
    if "O5" in rules:
        name: LineName = "one_day_to_week"
        lines.append(ModelLine(name=name, price=last[O5_LINE_SERIES[name]]))
    return lines
