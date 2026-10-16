"""On-chain model cost lines and the URPD median cost."""

import re
from datetime import datetime
from typing import Literal

from ..market import Model
from .brk import Urpd

LineName = Literal["true_mean", "short_term", "average", "long_term", "median"]

# The four lines that come from day1 series; `median` comes from the URPD snapshot.
LINE_SERIES: dict[LineName, str] = {
    "true_mean": "true_market_mean",
    "short_term": "sth_realized_price",
    "average": "realized_price",
    "long_term": "lth_realized_price",
}

_LINEAR = re.compile(r"lin(\d+)")


class ModelLine(Model):
    name: LineName
    price: float


def last_complete(
    rows: dict[str, list[tuple[datetime, float | None]]],
) -> tuple[datetime, dict[str, float]] | None:
    """The latest time at which every line series has a value above 0, keyed by series name.

    A partial point, such as today's when one series has not been published yet, is skipped.
    """
    by_time: dict[datetime, dict[str, float]] = {}
    for name in LINE_SERIES.values():
        for time, value in rows.get(name, []):
            if value is not None and value > 0:
                by_time.setdefault(time, {})[name] = value
    complete = [time for time, values in by_time.items() if len(values) == len(LINE_SERIES)]
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


def model_lines(last: dict[str, float], urpd: Urpd | None) -> list[ModelLine]:
    """The four series lines, plus the URPD median when a snapshot with supply is given."""
    lines = [ModelLine(name=name, price=last[series]) for name, series in LINE_SERIES.items()]
    if urpd is not None:
        median = median_cost(urpd)
        if median is not None:
            lines.append(ModelLine(name="median", price=median))
    return lines
