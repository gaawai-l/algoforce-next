"""Stored perp inputs folded into one exchange view's 10m grid (spec §3.1 and §3.2): the REST
series bucket by bucket, Coinalyze's series window by window (proposal §3.1, §3.3–§3.6)."""

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from .coinalyze import KIND_VENUES, STEPS
from .rows import CzKind, CzPoint, CzVenue, Exchange
from .states import DAY, REFERENCE_DAYS, STEP, Grid
from .store import PerpsStore, Venue

BAR = 300  # one 5m kline or OI period, and one Coinalyze 5min interval
H4 = STEPS["4hour"]  # one Coinalyze 4hour window: 14_400 seconds, 24 buckets
WINDOW = H4 // STEP

# The REST series each view needs; the keys name them in QC and in `series_missing:<key>`.
# Hyperliquid's view sets its liquidations by All's OI, so it needs both venues' OI too.
REQUIRED: dict[Exchange, tuple[str, ...]] = {
    "binance": ("bybit:price", "binance:oi", "binance:kline"),
    "bybit": ("bybit:price", "bybit:oi"),
    "all": ("bybit:price", "binance:oi", "binance:kline", "bybit:oi"),
    "hyperliquid": ("bybit:price", "binance:oi", "bybit:oi"),
}
# How far past a bucket's start the last row it reads is stamped: price reads the bar opening at
# t+5m, delta the bars opening at t and t+5m, OI the row at t+10m.
LAG = {"bybit:price": BAR, "binance:kline": BAR, "binance:oi": STEP, "bybit:oi": STEP}
# The venues whose columns each view reads: All venues sums the first three.
VIEW_VENUES: dict[Exchange, tuple[CzVenue, ...]] = {
    "all": ("binance", "bybit", "okx"),
    "binance": ("binance",),
    "bybit": ("bybit",),
    "hyperliquid": ("binance", "bybit", "okx", "hyperliquid"),
}
REST_VENUES: tuple[Venue, ...] = ("binance", "bybit")

Values = list[float | None]
Rows = Mapping[int, CzPoint]


class Placed(NamedTuple):
    """One venue's Coinalyze column on the grid buckets start..last."""

    values: Values  # liq: (longs, shorts) in two Placed; delta; or OI
    covered: list[bool]  # all True for OI, whose gaps are None values
    whole: list[bool]  # the bucket closes a window placed whole from 4hour (OI: or opens it)


def cz_liquidations(rows4: Rows, rows5: Rows, start: int, last: int) -> tuple[Placed, Placed]:
    """Longs and shorts liquidated per bucket, placed window by window from `start`, a multiple
    of H4, to `last` (proposal §3.3, §3.4):

    - a filled window next to another filled one (`rows4` reaches back to `start - H4`):
      Coinalyze's own gap, uncovered throughout;
    - a window closed by `last` with a 4hour row: the row's value in its last bucket, 0.0 in the
      others, all covered;
    - any other: each bucket the sum of its two 5min intervals, uncovered without both.
    """
    sums, whole = _sums(rows4, rows5, start, last, outage=True)
    covered = [s is not None for s in sums]
    return (
        Placed([None if s is None else s[0] for s in sums], covered, whole),
        Placed([None if s is None else s[1] for s in sums], covered, whole),
    )


def cz_delta(rows4: Rows, rows5: Rows, start: int, last: int) -> Placed:
    """2·taker buy − volume per bucket, placed as the liquidations are, without the gap rule."""
    sums, whole = _sums(rows4, rows5, start, last, outage=False)
    return Placed(
        [None if s is None else 2 * s[1] - s[0] for s in sums], [s is not None for s in sums], whole
    )


def cz_oi(rows4: Rows, rows5: Rows, start: int, last: int) -> Placed:
    """Open interest per bucket: a window closed by `last` with a 4hour row has its open in its
    first bucket and its close in its last, None between; elsewhere a bucket holds the close of
    its second 5min interval, the OI at t+10m, or None."""
    values: Values = [None] * _count(start, last)
    whole = [False] * len(values)
    for w in range(start, last + 1, H4):
        first, end, row = (w - start) // STEP, w + H4 - STEP, rows4.get(w)
        if row is not None and end <= last:
            values[first], values[first + WINDOW - 1] = row.a, row.b
            whole[first] = whole[first + WINDOW - 1] = True
            continue
        for t in range(w, min(end, last) + 1, STEP):
            q = rows5.get(t + BAR)
            if q is not None:
                values[(t - start) // STEP] = q.b
    return Placed(values, [True] * len(values), whole)


def estimate_liquidations(
    longs: Values,
    shorts: Values,
    covered: Sequence[bool],
    all_oi: Values,
    venue_oi: Values,
) -> tuple[Values, Values, list[bool]]:
    """A venue's liquidations estimated from All's, bucket by bucket, as the original does
    (proposal §3.5): uncovered where All's are; 0.0 where All's are 0.0 on both sides; else both
    sides times venue_oi / all_oi, uncovered where either OI is missing or not positive."""
    est_longs: Values = []
    est_shorts: Values = []
    est_covered: list[bool] = []
    for lliq, sliq, c, total, own in zip(longs, shorts, covered, all_oi, venue_oi, strict=True):
        if not c or lliq is None or sliq is None:
            est_longs.append(None)
            est_shorts.append(None)
            est_covered.append(False)
        elif lliq == 0 and sliq == 0:
            est_longs.append(0.0)
            est_shorts.append(0.0)
            est_covered.append(True)
        elif total is None or own is None or total <= 0 or own <= 0:
            est_longs.append(None)
            est_shorts.append(None)
            est_covered.append(False)
        else:
            share = own / total
            est_longs.append(lliq * share)
            est_shorts.append(sliq * share)
            est_covered.append(True)
    return est_longs, est_shorts, est_covered


def build_grid(
    store: PerpsStore,
    exchange: Exchange,
    start: int,
    excluded: frozenset[CzVenue] = frozenset(),
) -> Grid | list[str]:
    """The view's grid from bucket `start`, a UTC midnight, to its data edge, or the required
    REST series that reach no bucket from `start` on.

    The edge `last` is the earliest of the required series' last buckets: for each series, the
    last bucket its last stored row (NULL or not) can fill. Each venue's columns come from its
    REST series or from Coinalyze (proposal §3.1); the Coinalyze columns of a venue in
    `excluded` are missing throughout.
    """
    required = REQUIRED[exchange]
    spot = store.klines("bybit", start)
    perp = store.klines("binance", start) if "binance:kline" in required else {}
    rest_oi = {venue: store.oi(venue, start) for venue in REST_VENUES if f"{venue}:oi" in required}
    stored: dict[str, Mapping[int, object]] = {
        "bybit:price": spot,
        "binance:kline": perp,
        "binance:oi": rest_oi.get("binance", {}),
        "bybit:oi": rest_oi.get("bybit", {}),
    }
    edges = {key: _edge(stored[key], LAG[key]) for key in required}
    missing = [key for key, edge in edges.items() if edge is None or edge < start]
    if missing:
        return missing
    last = min(edge for edge in edges.values() if edge is not None)
    buckets = range(start, last + STEP, STEP)

    price = [spot[t + BAR][0] if t + BAR in spot else None for t in buckets]
    series: dict[str, Values] = {"bybit:price": price}
    for venue, rows in rest_oi.items():
        series[f"{venue}:oi"] = [rows.get(t + STEP, (None, ""))[0] for t in buckets]
    if "binance:kline" in required:
        series["binance:kline"] = [_kline_delta(perp, t) for t in buckets]

    def cz_rows(kind: CzKind, venue: CzVenue) -> tuple[Rows, Rows]:
        if venue in excluded:
            return {}, {}
        # 4hour from the window before the start: the start's own window checks it for a gap.
        four = store.cz_series(kind, H4, venue, start - H4)
        return four, store.cz_series(kind, BAR, venue, start)

    def rest(key: str) -> Placed:
        return Placed(series[key], [True] * len(buckets), [False] * len(buckets))

    def liquidations(venue: CzVenue) -> tuple[Placed, Placed]:
        return cz_liquidations(*cz_rows("liq", venue), start, last)

    def delta(venue: CzVenue) -> Placed:
        if venue == "binance":
            return rest("binance:kline")
        return cz_delta(*cz_rows("ohlcv", venue), start, last)

    def oi(venue: CzVenue) -> Placed:
        if venue == "binance" or venue == "bybit":
            return rest(f"{venue}:oi")
        return cz_oi(*cz_rows("oi", venue), start, last)

    venues = VIEW_VENUES[exchange]
    ois = {venue: oi(venue) for venue in venues}
    if exchange == "hyperliquid":
        # All's liquidations times Hyperliquid's OI over All's; All's whole windows stay marked.
        pairs = [liquidations(venue) for venue in VIEW_VENUES["all"]]
        all_longs = _combine([pair[0] for pair in pairs], start, last)
        all_shorts = _combine([pair[1] for pair in pairs], start, last)
        all_oi = _combine([ois[venue] for venue in VIEW_VENUES["all"]], start, last, oi=True)
        own = ois["hyperliquid"]
        est_longs, est_shorts, est_covered = estimate_liquidations(
            all_longs.values, all_shorts.values, all_longs.covered, all_oi.values, own.values
        )
        pairs = [
            (
                Placed(est_longs, est_covered, all_longs.whole),
                Placed(est_shorts, est_covered, all_shorts.whole),
            )
        ]
        oi_columns, delta_columns = [own], [delta("hyperliquid")]
    else:
        pairs = [liquidations(venue) for venue in venues]
        oi_columns, delta_columns = list(ois.values()), [delta(venue) for venue in venues]
    view_oi = _combine(oi_columns, start, last, oi=True)
    vd = _combine(delta_columns, start, last)
    long_liq = _combine([pair[0] for pair in pairs], start, last)
    short_liq = _combine([pair[1] for pair in pairs], start, last)
    window_qc, window_missing = _window_qc(
        {f"{v}:oi": ois[v].values for v in venues if v in KIND_VENUES["oi"]}, start, last
    )
    return Grid(
        start=start,
        last=last,
        price=price,
        oi=view_oi.values,
        vd=vd.values,
        long_liq=long_liq.values,
        short_liq=short_liq.values,
        liq_covered=long_liq.covered,
        vd_covered=vd.covered,
        rest_series={key: series[key] for key in required},
        quarantined_days=_quarantined_days(rest_oi.get("binance", {}), start, last),
        window_qc=window_qc,
        window_missing=window_missing,
    )


def _count(start: int, last: int) -> int:
    return (last - start) // STEP + 1


def _sums(
    rows4: Rows, rows5: Rows, start: int, last: int, *, outage: bool
) -> tuple[list[tuple[float, float] | None], list[bool]]:
    """Per bucket the (a, b) of a summed kind, placed window by window as `cz_liquidations`
    describes (the gap rule only with `outage`), None where uncovered; and the buckets that
    close a window placed whole."""
    sums: list[tuple[float, float] | None] = [None] * _count(start, last)
    whole = [False] * len(sums)
    for w in range(start, last + 1, H4):
        first, end, row = (w - start) // STEP, w + H4 - STEP, rows4.get(w)
        if outage and _outage(rows4, w):
            continue
        if row is not None and end <= last:
            sums[first : first + WINDOW] = [(0.0, 0.0)] * (WINDOW - 1) + [(row.a, row.b)]
            whole[first + WINDOW - 1] = True
            continue
        for t in range(w, min(end, last) + 1, STEP):
            p, q = rows5.get(t), rows5.get(t + BAR)
            if p is not None and q is not None:
                sums[(t - start) // STEP] = (p.a + q.a, p.b + q.b)
    return sums, whole


def _outage(rows4: Rows, w: int) -> bool:
    """Coinalyze's own gap (proposal §3.4): window `w` is filled, and so is one next to it."""
    row = rows4.get(w)
    if row is None or not row.filled:
        return False
    return any((other := rows4.get(w + side)) is not None and other.filled for side in (-H4, H4))


def _total(parts: Sequence[float | None]) -> float | None:
    """The venues' sum, added in order; None if any is."""
    total = 0.0
    for part in parts:
        if part is None:
            return None
        total += part
    return total


def _combine(columns: Sequence[Placed], start: int, last: int, *, oi: bool = False) -> Placed:
    """The venues' columns of one input summed (proposal §3.3, review C2): bucket by bucket, None
    or uncovered wherever one venue is; then, in a window some venue placed whole, the whole
    window is None, and uncovered unless it is OI, when the sum is None at its last bucket. A
    single venue's column goes through the same."""
    values = [_total(parts) for parts in zip(*(c.values for c in columns), strict=True)]
    covered = [all(parts) for parts in zip(*(c.covered for c in columns), strict=True)]
    whole = [any(parts) for parts in zip(*(c.whole for c in columns), strict=True)]
    for w in range(start, last - H4 + STEP + 1, H4):
        first = (w - start) // STEP
        end = first + WINDOW - 1
        if whole[end] and values[end] is None:
            values[first : end + 1] = [None] * WINDOW
            if not oi:
                covered[first : end + 1] = [False] * WINDOW
    return Placed(values, covered, whole)


def _window_qc(
    series: Mapping[str, Values], start: int, last: int
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Coinalyze's OI checked window by window (proposal §3.6): over the reference's windows
    closed by `last`, a window is missing where the series is None at its first or last bucket.
    `missing:<key>` when over 1% are, and the key among the missing series when all are."""
    first = max(start, last // DAY * DAY - REFERENCE_DAYS * DAY)
    windows = range(first, last - H4 + STEP + 1, H4)
    codes: list[str] = []
    missing: list[str] = []
    for key, values in series.items():
        gone = sum(
            values[(w - start) // STEP] is None or values[(w - start) // STEP + WINDOW - 1] is None
            for w in windows
        )
        if gone * 100 > len(windows):
            codes.append(f"missing:{key}")
        if windows and gone == len(windows):
            missing.append(key)
    return tuple(codes), tuple(missing)


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
