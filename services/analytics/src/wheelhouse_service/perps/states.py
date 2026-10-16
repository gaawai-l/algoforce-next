"""Perp states on a filled 10-minute grid, following the original perp-squeeze page's v1 rules."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model

STEP = 600  # seconds per grid bucket
DAY = 86_400
# Thresholds rank the blocks from the 90 UTC days before last's date, plus that date.
REFERENCE_DAYS = 90
SHOW_DAYS = (7, 30)
# Fewer covered blocks than this many days' worth in the reference: collecting, nothing judged.
COLLECTING_DAYS = 7
# QC: the longest run of null buckets a series may have, in seconds.
MAX_GAP = 1800

Window = Literal["4h", "8h"]
WINDOW_BUCKETS: dict[Window, int] = {"4h": 24, "8h": 48}
BLOCKS_PER_DAY: dict[Window, int] = {"4h": 6, "8h": 3}

State = Literal["shortsq", "longsq", "shortun", "longun", "longbd", "shortbd", "spot", "chop"]
# Table 1's rows in the original's order; ties in the largest-remainder rounding follow it too.
TABLE_STATES: tuple[State, ...] = (
    "shortsq",
    "longsq",
    "shortun",
    "longun",
    "longbd",
    "shortbd",
    "spot",
    "chop",
)


@dataclass(frozen=True)
class Grid:
    """One exchange view on the 10m grid: one entry per bucket from `start` to `last`.

    Collected inputs are 0.0 in covered buckets without events and None where uncovered; REST
    inputs are None where missing.
    """

    start: int  # the first bucket, a multiple of STEP
    last: int  # the last closed bucket, a multiple of STEP
    price: list[float | None]
    oi: list[float | None]
    vd: list[float | None]
    long_liq: list[float | None]
    short_liq: list[float | None]
    liq_covered: list[bool]
    vd_covered: list[bool]  # all True for a view that does not need Bybit's collected delta
    # Every REST series the view needs, e.g. `bybit:price`, `binance:oi`, for QC.
    rest_series: dict[str, list[float | None]]
    quarantined_days: int

    def __post_init__(self) -> None:
        if self.start % STEP or self.last % STEP:
            raise ValueError(f"grid start and last must be multiples of {STEP}")
        if self.last < self.start:
            raise ValueError("grid ends before it starts")
        n = (self.last - self.start) // STEP + 1
        columns: list[tuple[str, Sequence[object]]] = [
            ("price", self.price),
            ("oi", self.oi),
            ("vd", self.vd),
            ("long_liq", self.long_liq),
            ("short_liq", self.short_liq),
            ("liq_covered", self.liq_covered),
            ("vd_covered", self.vd_covered),
        ]
        columns += self.rest_series.items()
        for name, values in columns:
            if len(values) != n:
                raise ValueError(f"grid {name} has {len(values)} buckets, expected {n}")


class Imputed(Model):
    """Which features the original's rules set to 0 for missing inputs."""

    dpx: bool
    doi: bool
    sums: bool


class Block(Model):
    t0: AwareDatetime
    t1: AwareDatetime  # the start of the block's last bucket
    buckets: int
    forming: bool
    liq_covered: bool
    delta_covered: bool
    covered: bool
    dpx: float
    doi: float
    delta: float
    lliq: float
    sliq: float
    imputed: Imputed
    state: State | None
    # Drawn values: the last non-null price and OI; sums of the non-null buckets, null if none.
    price_close: float | None
    oi_close: float | None
    delta_sum: float | None
    lliq_sum: float | None
    sliq_sum: float | None


class Tail(Model):
    """The trailing buckets short of a block: drawn, never judged."""

    t0: AwareDatetime
    t1: AwareDatetime
    price_close: float | None
    oi_close: float | None
    delta_sum: float | None
    lliq_sum: float | None
    sliq_sum: float | None


class Thresholds(Model):
    s_liq: float
    l_liq: float
    oi: float
    px: float
    n_liq: int  # reference blocks with liquidations covered: the sample of s_liq and l_liq
    n_all: int  # all reference blocks: the sample of oi and px


class TableRow(Model):
    state: State
    count: int
    share: int | None  # percent, by largest remainder; None for every row when nothing is judged
    max_move: float | None  # percent, sign kept
    run_blocks: int | None


class Table(Model):
    show_days: int
    view_from: AwareDatetime
    judged: int
    in_view: int
    rows: list[TableRow]
    latest: State | None
    latest_uncovered: bool


class StatesResult(Model):
    window: Window
    last: AwareDatetime
    thresholds: Thresholds
    blocks: list[Block]  # only the blocks that overlap the 30-day view
    tail: Tail | None
    tables: list[Table]
    covered_days: float
    collecting: bool
    qc: list[str]
    series_missing: list[str]


def quantile(values: Sequence[float], q: float) -> float:
    """The original's percentile: the value at floor(q * (n - 1)) once sorted; 0 when empty."""
    if not values:
        return 0.0
    return sorted(values)[math.floor(q * (len(values) - 1))]


def shares(counts: Sequence[int]) -> list[int] | None:
    """Whole percents of `counts` (in TABLE_STATES order) adding up to 100, by largest remainder.

    None when nothing is counted: there is no share to give, and 0% would read as a real value.
    """
    n = sum(counts)
    if n == 0:
        return None
    raw = [100 * c / n for c in counts]
    whole = [math.floor(v) for v in raw]
    rems = [v - f for v, f in zip(raw, whole, strict=True)]
    left = 100 - sum(whole)
    # sorted() is stable, so equal remainders keep TABLE_STATES order, as the original's sort.
    for k in sorted(range(len(counts)), key=lambda k: -rems[k]):
        if left > 0 and rems[k] > 0:
            whole[k] += 1
            left -= 1
    return whole


def in_table_view(t0: int, t1: int, frm: int, last: int) -> bool:
    """Table 1's rule: the block's midpoint t0 + (t1 + 10m - t0) / 2 lies in [frm, last + 10m]."""
    twice_mid = t0 + t1 + STEP
    return 2 * frm <= twice_mid <= 2 * (last + STEP)


def _at(t: int) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def _sum0(values: Sequence[float | None]) -> float:
    """Nulls as 0, added in order like the original's loop."""
    total = 0.0
    for v in values:
        total += v or 0.0
    return total


def _sum_present(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return _sum0(present) if present else None


def _last_present(values: Sequence[float | None]) -> float | None:
    return next((v for v in reversed(values) if v is not None), None)


def _move(open_: float | None, close: float | None) -> float | None:
    """Percent change from `open_` to `close`; None unless both are positive."""
    if open_ is None or close is None or open_ <= 0 or close <= 0:
        return None
    return (close / open_ - 1) * 100


def _spans(grid: Grid, w: int) -> tuple[list[tuple[int, int]], tuple[int, int] | None]:
    """Blocks as (first, last) bucket indexes from the first epoch-aligned bucket, and the tail.

    A leading partial block is dropped. A trailing one is a block (forming) when it has at least
    w/2 + 1 buckets, else the tail.
    """
    n = len(grid.price)
    i = (-grid.start) % (w * STEP) // STEP
    spans: list[tuple[int, int]] = []
    while i < n:
        j = min(n - 1, i + w - 1)
        if j - i < w // 2:
            return spans, (i, j)
        spans.append((i, j))
        i += w
    return spans, None


def _block(grid: Grid, i0: int, i1: int, w: int) -> Block:
    price, oi = grid.price[i0 : i1 + 1], grid.oi[i0 : i1 + 1]
    vd = grid.vd[i0 : i1 + 1]
    longs, shorts = grid.long_liq[i0 : i1 + 1], grid.short_liq[i0 : i1 + 1]
    dpx, o0, o1 = _move(price[0], price[-1]), oi[0], oi[-1]
    liq_covered = all(grid.liq_covered[i0 : i1 + 1])
    delta_covered = all(grid.vd_covered[i0 : i1 + 1])
    return Block(
        t0=_at(grid.start + i0 * STEP),
        t1=_at(grid.start + i1 * STEP),
        buckets=i1 - i0 + 1,
        forming=i1 - i0 + 1 < w,
        liq_covered=liq_covered,
        delta_covered=delta_covered,
        covered=liq_covered and delta_covered,
        dpx=0.0 if dpx is None else dpx,
        doi=o1 - o0 if o0 is not None and o1 is not None else 0.0,
        delta=_sum0(vd),
        lliq=_sum0(longs),
        sliq=_sum0(shorts),
        imputed=Imputed(
            dpx=dpx is None,
            doi=o0 is None or o1 is None,
            sums=None in vd or None in longs or None in shorts,
        ),
        state=None,
        price_close=_last_present(price),
        oi_close=_last_present(oi),
        delta_sum=_sum_present(vd),
        lliq_sum=_sum_present(longs),
        sliq_sum=_sum_present(shorts),
    )


def _classify(b: Block, t: Thresholds) -> State:
    """The first state whose rule holds, in the original's order."""
    if b.sliq >= t.s_liq and b.dpx >= t.px and b.sliq >= 3 * b.lliq:
        return "shortsq"
    if b.lliq >= t.l_liq and b.dpx <= -t.px and b.lliq >= 3 * b.sliq:
        return "longsq"
    if b.doi <= -t.oi:
        return "longun" if b.delta < 0 else "shortun"
    if b.doi >= t.oi and b.dpx > 0 and b.delta > 0:
        return "longbd"
    if b.doi >= t.oi and b.dpx < 0 and b.delta < 0:
        return "shortbd"
    if abs(b.dpx) >= t.px and abs(b.doi) < t.oi:
        return "spot"
    return "chop"


def _table(grid: Grid, blocks: list[Block], spans: list[tuple[int, int]], show_days: int) -> Table:
    frm = max(grid.start, grid.last - show_days * DAY)
    view = [
        k
        for k, (i0, i1) in enumerate(spans)
        if in_table_view(grid.start + i0 * STEP, grid.start + i1 * STEP, frm, grid.last)
    ]
    judged = [(k, s) for k in view if (s := blocks[k].state) is not None]
    counts = {s: sum(1 for _, js in judged if js == s) for s in TABLE_STATES}
    # Runs: judged blocks of one state with consecutive indexes; an unjudged block ends a run.
    # Each state keeps its largest move by size, the first one on ties.
    best: dict[State, tuple[float, int]] = {}
    a = 0
    while a < len(judged):
        first, state = judged[a]
        b = a
        while b + 1 < len(judged) and judged[b + 1] == (judged[b][0] + 1, state):
            b += 1
        move = _move(grid.price[spans[first][0]], grid.price[spans[judged[b][0]][1]])
        if move is not None and (state not in best or abs(move) > abs(best[state][0])):
            best[state] = (move, b - a + 1)
        a = b + 1
    pct = shares([counts[s] for s in TABLE_STATES])
    last = blocks[-1] if blocks else None
    return Table(
        show_days=show_days,
        view_from=_at(frm),
        judged=len(judged),
        in_view=len(view),
        rows=[
            TableRow(
                state=s,
                count=counts[s],
                share=None if pct is None else pct[k],
                max_move=best[s][0] if s in best else None,
                run_blocks=best[s][1] if s in best else None,
            )
            for k, s in enumerate(TABLE_STATES)
        ],
        latest=last.state if last else None,
        latest_uncovered=last is not None and not last.covered,
    )


def _qc(grid: Grid, ref_start: int) -> tuple[list[str], list[str]]:
    """QC codes over the reference window's buckets, and the REST series with no value there."""
    first = max(0, (ref_start - grid.start) // STEP)
    codes: list[str] = []
    missing: list[str] = []
    for key, series in grid.rest_series.items():
        values = series[first:]
        nulls = run = longest = 0
        for v in values:
            if v is None:
                nulls += 1
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        if nulls * 100 > len(values):
            codes.append(f"missing:{key}")
        if longest * STEP > MAX_GAP:
            codes.append(f"gap:{key}:{longest * STEP}")
        if nulls == len(values):
            missing.append(key)
    if grid.quarantined_days:
        codes.append(f"archive_quarantined:{grid.quarantined_days}")
    return codes, missing


def compute_states(grid: Grid, window: Window) -> StatesResult:
    w = WINDOW_BUCKETS[window]
    ref_start = grid.last // DAY * DAY - REFERENCE_DAYS * DAY
    all_spans, tail_span = _spans(grid, w)
    # Only reference blocks are ranked, judged and shown: the views lie inside the reference.
    spans = [(i0, i1) for i0, i1 in all_spans if grid.start + i0 * STEP >= ref_start]
    blocks = [_block(grid, i0, i1, w) for i0, i1 in spans]

    liq_sample = [b for b in blocks if b.liq_covered]
    thresholds = Thresholds(
        s_liq=quantile([b.sliq for b in liq_sample], 0.90),
        l_liq=quantile([b.lliq for b in liq_sample], 0.90),
        oi=quantile([abs(b.doi) for b in blocks], 0.75),
        px=quantile([abs(b.dpx) for b in blocks], 0.75),
        n_liq=len(liq_sample),
        n_all=len(blocks),
    )
    covered = sum(b.covered for b in blocks)
    collecting = covered < COLLECTING_DAYS * BLOCKS_PER_DAY[window]
    if not collecting:
        blocks = [
            b.model_copy(update={"state": _classify(b, thresholds)}) if b.covered else b
            for b in blocks
        ]

    tables = [_table(grid, blocks, spans, days) for days in SHOW_DAYS]
    frm = max(grid.start, grid.last - max(SHOW_DAYS) * DAY)
    shown = [
        b for (i0, _), b in zip(spans, blocks, strict=True) if grid.start + (i0 + w) * STEP > frm
    ]

    tail = None
    if tail_span is not None:
        t0, t1 = tail_span
        part = _block(grid, t0, t1, w)
        tail = Tail(
            t0=part.t0,
            t1=part.t1,
            price_close=part.price_close,
            oi_close=part.oi_close,
            delta_sum=part.delta_sum,
            lliq_sum=part.lliq_sum,
            sliq_sum=part.sliq_sum,
        )
    qc, series_missing = _qc(grid, ref_start)
    return StatesResult(
        window=window,
        last=_at(grid.last),
        thresholds=thresholds,
        blocks=shown,
        tail=tail,
        tables=tables,
        covered_days=covered / BLOCKS_PER_DAY[window],
        collecting=collecting,
        qc=qc,
        series_missing=series_missing,
    )
