"""Stored perp inputs folded into one exchange view's 10m grid (spec §3.1 and §3.2)."""

import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .rows import Exchange, Stream
from .states import DAY, REFERENCE_DAYS, STEP, Grid
from .store import PerpsStore, Venue

BAR = 300  # one 5m kline or OI period

# The REST series each view needs; the keys name them in QC and in `series_missing:<key>`.
REQUIRED: dict[Exchange, tuple[str, ...]] = {
    "binance": ("bybit:price", "binance:oi", "binance:kline"),
    "bybit": ("bybit:price", "bybit:oi"),
    "all": ("bybit:price", "binance:oi", "binance:kline", "bybit:oi"),
}
# How far past a bucket's start the last row it reads is stamped: price reads the bar opening at
# t+5m, delta the bars opening at t and t+5m, OI the row at t+10m.
LAG = {"bybit:price": BAR, "binance:kline": BAR, "binance:oi": STEP, "bybit:oi": STEP}
# Whether the raw side field means longs were liquidated (spec §3.1).
LONGS: dict[Venue, dict[str, bool]] = {
    "binance": {"SELL": True, "BUY": False},
    "bybit": {"Buy": True, "Sell": False},
}
LIQ_STREAM: dict[Venue, Stream] = {"binance": "binance_liq", "bybit": "bybit_liq"}

Values = list[float | None]


@dataclass(frozen=True)
class _Part:
    """One venue's columns on the grid."""

    oi: Values
    vd: Values
    vd_covered: list[bool]
    long_liq: Values
    short_liq: Values
    liq_covered: list[bool]


def build_grid(store: PerpsStore, exchange: Exchange, start: int) -> Grid | list[str]:
    """The view's grid from bucket `start` to its data edge, or the required series that reach no
    bucket from `start` on.

    The edge `last` is the earliest of the required series' last buckets: for each series, the
    last bucket its last stored row (NULL or not) can fill. Collected streams only set coverage.
    """
    venues: tuple[Venue, ...] = (exchange,) if exchange != "all" else ("binance", "bybit")
    spot = store.klines("bybit", start)
    perp = store.klines("binance", start) if "binance" in venues else {}
    oi_rows = {venue: store.oi(venue, start) for venue in venues}
    stored: dict[str, Mapping[int, object]] = {
        "bybit:price": spot,
        "binance:kline": perp,
        "binance:oi": oi_rows.get("binance", {}),
        "bybit:oi": oi_rows.get("bybit", {}),
    }
    edges = {key: _edge(stored[key], LAG[key]) for key in REQUIRED[exchange]}
    missing = [key for key, edge in edges.items() if edge is None or edge < start]
    if missing:
        return missing
    last = min(edge for edge in edges.values() if edge is not None)
    buckets = range(start, last + STEP, STEP)

    price = [spot[t + BAR][0] if t + BAR in spot else None for t in buckets]
    series: dict[str, Values] = {"bybit:price": price}
    parts: dict[Venue, _Part] = {}
    for venue in venues:
        oi = [oi_rows[venue].get(t + STEP, (None, ""))[0] for t in buckets]
        series[f"{venue}:oi"] = oi
        if venue == "binance":
            vd = [_kline_delta(perp, t) for t in buckets]
            series["binance:kline"] = vd
            vd_covered = [True] * len(buckets)
        else:
            vd_covered = _covered(store, "bybit_trades", start, len(buckets))
            trades = store.trades("bybit", start)
            vd = [
                (_net(trades[t]) if t in trades else 0.0) if covered else None
                for t, covered in zip(buckets, vd_covered, strict=True)
            ]
        liq_covered = _covered(store, LIQ_STREAM[venue], start, len(buckets))
        longs, shorts = _liquidations(store, venue, start, liq_covered)
        parts[venue] = _Part(oi, vd, vd_covered, longs, shorts, liq_covered)

    view = parts[exchange] if exchange != "all" else _sum(parts["binance"], parts["bybit"])
    return Grid(
        start=start,
        last=last,
        price=price,
        oi=view.oi,
        vd=view.vd,
        long_liq=view.long_liq,
        short_liq=view.short_liq,
        liq_covered=view.liq_covered,
        vd_covered=view.vd_covered,
        rest_series={key: series[key] for key in REQUIRED[exchange]},
        quarantined_days=_quarantined_days(oi_rows.get("binance", {}), start, last),
    )


def _edge(rows: Mapping[int, object], lag: int) -> int | None:
    """The last bucket the last stored row can fill, the row being stamped `lag` past its start."""
    return (max(rows) - lag) // STEP * STEP if rows else None


def _kline_delta(
    perp: Mapping[int, tuple[float, float | None, float | None]], t: int
) -> float | None:
    """2·takerBuy − volume over the bars opening at t and t+5m; None unless both are complete."""
    total = 0.0
    for bar in (perp.get(t), perp.get(t + BAR)):
        if bar is None or bar[1] is None or bar[2] is None:
            return None
        total += 2 * bar[2] - bar[1]
    return total


def _net(buy_sell: tuple[float, float]) -> float:
    return buy_sell[0] - buy_sell[1]


def _covered(store: PerpsStore, stream: Stream, start: int, n: int) -> list[bool]:
    """Whether each bucket [t, t+10m) lies wholly inside the union of the stream's connections."""
    covered = [False] * n
    for lo, hi in store.coverage(stream, start):
        first = max(0, math.ceil((lo - start) / STEP))
        stop = min(n, math.floor((hi - start) / STEP))
        for i in range(first, stop):
            covered[i] = True
    return covered


def _event(venue: Venue, raw: Mapping[str, Any]) -> tuple[bool, float] | None:
    """(longs liquidated, quantity in BTC); None for a Binance event that is not FILLED."""
    if venue == "binance":
        if raw["X"] != "FILLED":
            return None
        return LONGS[venue][raw["S"]], float(raw["z"])
    return LONGS[venue][raw["S"]], float(raw["v"])


def _liquidations(
    store: PerpsStore, venue: Venue, start: int, covered: Sequence[bool]
) -> tuple[Values, Values]:
    """Long and short liquidations per bucket: 0.0 where covered without events, None where not.

    An event key seen on both connections counts as often as the connection that saw it most.
    """
    counts: dict[str, Counter[int]] = defaultdict(Counter)
    events: dict[str, tuple[float, bool, float]] = {}
    for conn, ts, raw_json, key in store.liquidations(venue, start):
        event = _event(venue, json.loads(raw_json))
        if event is not None:
            counts[key][conn] += 1
            events[key] = (ts, *event)
    sums: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])  # bucket: [longs, shorts]
    for key, per_conn in counts.items():
        ts, longs, qty = events[key]
        i = int((ts - start) // STEP)
        if 0 <= i < len(covered) and covered[i]:
            sums[i][0 if longs else 1] += max(per_conn.values()) * qty
    zero = [0.0, 0.0]
    long_liq: Values = [sums.get(i, zero)[0] if c else None for i, c in enumerate(covered)]
    short_liq: Values = [sums.get(i, zero)[1] if c else None for i, c in enumerate(covered)]
    return long_liq, short_liq


def _add(a: Values, b: Values) -> Values:
    return [x + y if x is not None and y is not None else None for x, y in zip(a, b, strict=True)]


def _both(a: list[bool], b: list[bool]) -> list[bool]:
    return [x and y for x, y in zip(a, b, strict=True)]


def _sum(a: _Part, b: _Part) -> _Part:
    """All venues: sums, None or uncovered wherever either venue is."""
    return _Part(
        oi=_add(a.oi, b.oi),
        vd=_add(a.vd, b.vd),
        vd_covered=_both(a.vd_covered, b.vd_covered),
        long_liq=_add(a.long_liq, b.long_liq),
        short_liq=_add(a.short_liq, b.short_liq),
        liq_covered=_both(a.liq_covered, b.liq_covered),
    )


def _quarantined_days(oi: Mapping[int, tuple[float | None, str]], start: int, last: int) -> int:
    """Archive days with a quarantined (NULL) row read by the reference window's buckets.

    Archive rows are stamped create_time + 5m, so the file's day is that of `t - 5m`.
    """
    first = max(start, last // DAY * DAY - REFERENCE_DAYS * DAY) + STEP
    return len(
        {
            (t - BAR) // DAY
            for t, (value, source) in oi.items()
            if source == "archive" and value is None and first <= t <= last + STEP
        }
    )
