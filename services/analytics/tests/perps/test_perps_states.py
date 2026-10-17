"""The original perp-squeeze page's v1 state rules, and O6's ranking against the past only,
checked on synthetic 10-minute grids."""

import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from wheelhouse_service.perps.states import (
    TABLE_STATES,
    Block,
    Grid,
    StatesResult,
    Table,
    Thresholds,
    compute_states,
    in_table_view,
    quantile,
    shares,
)
from wheelhouse_service.rules import Rules
from wheelhouse_service.stats import quantile_r7

STEP = 600
DAY = 86_400
H4 = 24  # buckets in a 4h block
H8 = 48  # buckets in an 8h block
# 2023-11-14 00:00 UTC: a day boundary, so both 4h and 8h blocks start here.
DAY0 = 19_675 * DAY
V1: Rules = frozenset()
O6: Rules = frozenset({"O6"})

Values = list[float | None]


@dataclass
class Part:
    """A run of buckets to concatenate into a grid."""

    price: Values
    oi: Values
    vd: Values
    long_liq: Values
    short_liq: Values
    liq_covered: list[bool]
    vd_covered: list[bool]


def block(
    *,
    dpx: float = 0.0,
    doi: float = 0.0,
    delta: float = 0.0,
    lliq: float = 0.0,
    sliq: float = 0.0,
    n: int = H4,
    p0: float = 100.0,
    liq: bool = True,
    vd: bool = True,
) -> Part:
    """`n` buckets whose block features come out as given: moves sit on the first/last bucket."""
    price: Values = [p0] * n
    price[-1] = p0 * (1 + dpx / 100)
    oi: Values = [1000.0] * n
    oi[-1] = 1000.0 + doi
    vds: Values = [0.0] * n
    vds[0] = delta
    longs: Values = [0.0] * n
    longs[0] = lliq
    shorts: Values = [0.0] * n
    shorts[0] = sliq
    if not liq:
        longs = [None] * n
        shorts = [None] * n
    if not vd:
        vds = [None] * n
    return Part(price, oi, vds, longs, shorts, [liq] * n, [vd] * n)


# At least 100 of these keep every threshold on them: T_sLiq = T_lLiq = 10, T_oi = 100, T_px = 1.
FILL = {"dpx": 1.0, "doi": 100.0, "lliq": 10.0, "sliq": 10.0}


def filler(n: int = H4, liq: bool = True) -> Part:
    """A chop block: every feature sits exactly on the threshold it makes, none crosses."""
    return block(n=n, liq=liq, **FILL)


def grid(
    *parts: Part,
    start: int = DAY0,
    rest: dict[str, Values] | None = None,
    quarantined: int = 0,
) -> Grid:
    def cat(name: str) -> list[float | None]:
        return [v for p in parts for v in getattr(p, name)]

    price = cat("price")
    return Grid(
        start=start,
        last=start + (len(price) - 1) * STEP,
        price=price,
        oi=cat("oi"),
        vd=cat("vd"),
        long_liq=cat("long_liq"),
        short_liq=cat("short_liq"),
        liq_covered=[c for p in parts for c in p.liq_covered],
        vd_covered=[c for p in parts for c in p.vd_covered],
        rest_series=rest if rest is not None else {"bybit:price": price},
        quarantined_days=quarantined,
    )


def at(t: int) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def table(result: StatesResult, show_days: int) -> Table:
    return next(t for t in result.tables if t.show_days == show_days)


def row_of(tbl: Table, state: str) -> tuple[int, int, float | None, int | None]:
    r = next(r for r in tbl.rows if r.state == state)
    return r.count, r.share, r.max_move, r.run_blocks


def test_blocks_align_to_epoch_drop_leading_partial_and_half_rule() -> None:
    # The grid starts 5 buckets before a 4h boundary: those 5 are a leading stub and are dropped.
    start = DAY0 + 4 * 3600 - 5 * STEP
    r = compute_states(grid(block(n=5), block(), block(), block(n=12), start=start), "4h", rules=V1)
    assert [b.t0 for b in r.blocks] == [at(DAY0 + 4 * 3600), at(DAY0 + 8 * 3600)]
    assert [b.t1 for b in r.blocks] == [at(DAY0 + 8 * 3600 - STEP), at(DAY0 + 12 * 3600 - STEP)]
    assert all(b.buckets == H4 and not b.forming for b in r.blocks)
    # 12 trailing buckets are under half a block plus one: a tail, drawn but not judged.
    assert r.tail is not None
    assert (r.tail.t0, r.tail.t1) == (at(DAY0 + 12 * 3600), r.last)
    assert r.tail.price_close == 100.0
    assert (r.thresholds.n_px, r.thresholds.n_oi) == (2, 2)

    r = compute_states(grid(block(n=5), block(), block(), block(n=13), start=start), "4h", rules=V1)
    assert r.tail is None
    assert len(r.blocks) == 3
    b = r.blocks[-1]
    assert (b.t0, b.t1, b.buckets, b.forming) == (at(DAY0 + 12 * 3600), r.last, 13, True)
    assert (r.thresholds.n_px, r.thresholds.n_oi) == (3, 3)


def test_blocks_align_to_epoch_8h() -> None:
    # 04:00 is a 4h boundary but not an 8h one: the 24 buckets before 08:00 are a leading stub.
    start = DAY0 + 4 * 3600
    r = compute_states(grid(block(n=H4), block(n=H8), block(n=H8), start=start), "8h", rules=V1)
    assert [b.t0 for b in r.blocks] == [at(DAY0 + 8 * 3600), at(DAY0 + 16 * 3600)]
    assert all(b.buckets == H8 and not b.forming for b in r.blocks)
    assert r.tail is None
    assert (r.thresholds.n_px, r.thresholds.n_oi) == (2, 2)


def test_quantile_floor_rank() -> None:
    assert quantile([4.0, 1.0, 3.0, 2.0], 0.75) == 3.0  # sorted[floor(0.75 * 3)] = sorted[2]
    assert quantile([4.0, 1.0, 3.0, 2.0], 0.9) == 3.0  # floor(2.7) = 2, no interpolation
    assert quantile([5.0], 0.9) == 5.0
    assert quantile([], 0.9) == 0.0


CASCADE = [
    ("shortsq", {"dpx": 2.0, "sliq": 30.0, "lliq": 10.0}),  # sLiq is exactly 3x lLiq
    ("longsq", {"dpx": -2.0, "sliq": 10.0, "lliq": 30.0}),
    ("shortun", {"doi": -100.0, "delta": 5.0}),
    ("longun", {"doi": -100.0, "delta": -5.0}),
    ("longbd", {"doi": 100.0, "dpx": 0.5, "delta": 5.0}),
    ("shortbd", {"doi": 100.0, "dpx": -0.5, "delta": -5.0}),
    ("spot", {"dpx": 1.0, "doi": 50.0}),
    ("chop", {"dpx": 0.5}),
    ("shortun", {"doi": -100.0, "delta": 0.0}),  # no taker side: the original calls it short
    # A big OI drop that also meets the squeeze rule: squeeze comes first in the cascade.
    ("shortsq", {"dpx": 2.0, "sliq": 30.0, "lliq": 10.0, "doi": -200.0}),
    # sLiq and dPx exactly on T_sLiq and T_px: the rule uses >=.
    ("shortsq", {"dpx": 1.0, "sliq": 10.0}),
]


def test_cascade_each_branch() -> None:
    parts = [filler() for _ in range(100)] + [block(**kw) for _, kw in CASCADE]
    r = compute_states(grid(*parts), "4h", rules=V1)
    t = r.thresholds
    assert (t.s_liq, t.l_liq, t.oi) == (10.0, 10.0, 100.0)
    assert t.px == pytest.approx(1.0)
    assert (t.n_liq, t.n_px, t.n_oi) == (111, 111, 111)
    assert not r.collecting
    assert [b.state for b in r.blocks[-len(CASCADE) :]] == [s for s, _ in CASCADE]
    assert all(b.state == "chop" for b in r.blocks[: -len(CASCADE)])
    # v1 ranks every block against one set of thresholds: the blocks carry none of their own.
    assert all(b.thresholds is None for b in r.blocks)
    tbl = table(r, 30)
    assert [row.state for row in tbl.rows] == list(TABLE_STATES)
    assert (tbl.in_view, tbl.judged) == (111, 111)
    assert sum(row.share or 0 for row in tbl.rows) == 100


def test_both_liquidations_zero_degenerate_squeeze() -> None:
    # No liquidations at all: both P90s are 0, and 0 >= 3 * 0 passes, so any block whose price
    # moves by T_px either way is a squeeze. The original behaves the same way.
    moves = [1.0 if k % 2 else -1.0 for k in range(45)] + [2.0, -2.0]
    r = compute_states(grid(*[block(dpx=m) for m in moves]), "4h", rules=V1)
    assert (r.thresholds.s_liq, r.thresholds.l_liq) == (0.0, 0.0)
    assert r.thresholds.px == pytest.approx(1.0)
    assert [b.state for b in r.blocks] == ["shortsq" if m > 0 else "longsq" for m in moves]


def test_liq_thresholds_use_liq_covered_blocks_only() -> None:
    base = [block(sliq=float(k)) for k in range(42)]
    # Liquidations covered, Bybit delta not: ranked for T_sLiq, but never judged.
    x = block(sliq=1000.0, vd=False)
    # One bucket without liquidation coverage: the whole block stays out of the liquidation sample.
    y = block(sliq=2000.0)
    y.long_liq[5] = y.short_liq[5] = None
    y.liq_covered[5] = False
    r = compute_states(grid(*base, x, y), "4h", rules=V1)
    assert (r.thresholds.n_liq, r.thresholds.n_px, r.thresholds.n_oi) == (43, 44, 44)
    # Over 0..41 and 1000: sorted[floor(0.9 * 42)] = 37. With y it would be 38, without x 36.
    assert r.thresholds.s_liq == 37.0
    bx, by = r.blocks[-2:]
    assert (bx.liq_covered, bx.delta_covered, bx.covered, bx.state) == (True, False, False, None)
    assert (by.liq_covered, by.delta_covered, by.covered, by.state) == (False, True, False, None)
    assert not r.collecting
    assert all(b.state is not None for b in r.blocks[:-2])


def test_oi_px_thresholds_use_all_blocks() -> None:
    base = [block(doi=float(k + 1), dpx=0.1 * (k + 1)) for k in range(42)]
    uncovered = [block(doi=1000.0, dpx=5.0, liq=False) for _ in range(2)]
    r = compute_states(grid(*base, *uncovered), "4h", rules=V1)
    assert (r.thresholds.n_liq, r.thresholds.n_px, r.thresholds.n_oi) == (42, 44, 44)
    # sorted[floor(0.75 * 43)] = sorted[32]: 33 and 3.3. Covered blocks alone would give 31 and 3.1.
    assert r.thresholds.oi == 33.0
    assert r.thresholds.px == pytest.approx(3.3)


def test_collecting_gate() -> None:
    def run(covered: int) -> StatesResult:
        parts = [filler() for _ in range(covered)] + [filler(liq=False) for _ in range(5)]
        return compute_states(grid(*parts), "4h", rules=V1)

    r = run(41)
    assert r.collecting
    assert r.covered_days == 41 / 6
    assert all(b.state is None for b in r.blocks)
    assert all(t.judged == 0 and all(row.share is None for row in t.rows) for t in r.tables)
    # Thresholds are still ranked while collecting; uncovered blocks do not count for the gate.
    assert (r.thresholds.n_px, r.thresholds.n_oi) == (46, 46)

    r = run(42)
    assert not r.collecting
    assert r.covered_days == 7.0
    assert [b.state is not None for b in r.blocks] == [True] * 42 + [False] * 5


def test_collecting_gate_8h() -> None:
    def run(covered: int) -> StatesResult:
        return compute_states(grid(*[filler(n=H8) for _ in range(covered)]), "8h", rules=V1)

    r = run(20)
    assert r.collecting and all(b.state is None for b in r.blocks)
    assert r.covered_days == 20 / 3
    r = run(21)
    assert not r.collecting and all(b.state == "chop" for b in r.blocks)
    assert r.covered_days == 7.0


def test_imputed_flags() -> None:
    no_open = block(dpx=1.0)
    no_open.price[0] = None
    zero_close = block(dpx=1.0)
    zero_close.price[-1] = 0.0
    no_oi = block(doi=50.0)
    no_oi.oi[-1] = None
    vd_hole = block(delta=5.0)
    vd_hole.vd[3] = None  # a missing Binance kline: covered, but null
    clean = block(dpx=1.0, doi=50.0, delta=5.0)
    no_liq = block(liq=False)
    parts = [filler() for _ in range(42)] + [no_open, zero_close, no_oi, vd_hole, clean, no_liq]
    blocks = compute_states(grid(*parts), "4h", rules=V1).blocks[-6:]

    a, b, c, d, e, f = blocks
    assert (a.dpx, a.imputed.dpx, a.imputed.doi, a.imputed.sums) == (0.0, True, False, False)
    assert a.price_close == 101.0
    assert (b.dpx, b.imputed.dpx) == (0.0, True)
    assert b.price_close == 0.0
    assert (c.doi, c.imputed.doi, c.imputed.dpx) == (0.0, True, False)
    assert c.oi_close == 1000.0  # the last non-null OI
    assert (d.delta, d.delta_sum, d.imputed.sums, d.delta_covered) == (5.0, 5.0, True, True)
    assert (e.imputed.dpx, e.imputed.doi, e.imputed.sums) == (False, False, False)
    assert e.dpx == pytest.approx(1.0)
    assert (e.doi, e.delta, e.price_close, e.oi_close) == (50.0, 5.0, 101.0, 1050.0)
    assert (e.lliq_sum, e.sliq_sum) == (0.0, 0.0)
    assert (f.lliq, f.sliq, f.imputed.sums) == (0.0, 0.0, True)
    assert (f.lliq_sum, f.sliq_sum, f.delta_sum) == (None, None, 0.0)


def test_prob_largest_remainder() -> None:
    # The page's all/4h/30d counts: SS 8, LS 14, SU 8, LU 3, NL 5, NS 6, spot 21, chop 115.
    assert shares([8, 14, 8, 3, 5, 6, 21, 115]) == [4, 8, 4, 2, 3, 3, 12, 64]
    # Equal remainders: the spare point goes by TABLE_STATES order, not by position of the count.
    assert shares([0, 0, 0, 0, 0, 0, 1, 1]) == [0, 0, 0, 0, 0, 0, 50, 50]
    assert shares([0, 0, 0, 0, 0, 1, 1, 1]) == [0, 0, 0, 0, 0, 34, 33, 33]
    assert shares([0, 1, 0, 0, 0, 0, 1, 1]) == [0, 34, 0, 0, 0, 0, 33, 33]
    # Nothing judged: there are no shares to give, rather than 0% for every state.
    assert shares([0, 0, 0, 0, 0, 0, 0, 0]) is None


def test_prob_empty_when_every_block_in_view_is_uncovered() -> None:
    # 50 covered blocks pass the gate; the last 43 (over 7 days) are uncovered.
    parts = [filler() for _ in range(50)] + [filler(liq=False) for _ in range(43)]
    r = compute_states(grid(*parts), "4h", rules=V1)
    assert not r.collecting
    week = table(r, 7)
    assert (week.in_view, week.judged) == (42, 0)
    assert all((row.count, row.share, row.max_move) == (0, None, None) for row in week.rows)
    assert (week.latest, week.latest_uncovered) == (None, True)
    month = table(r, 30)
    assert (month.in_view, month.judged) == (93, 50)
    assert row_of(month, "chop") == (50, 100, pytest.approx(1.0), 50)  # one run of 50


def test_max_move_runs() -> None:
    chop_a = [filler() for _ in range(50)]  # one run, 100 -> 101: +1%
    gap = [filler(liq=False)]  # uncovered: ends the run
    chop_b = [filler() for _ in range(51)]  # also +1%: a tie, so the first run stays
    spot_1 = block(dpx=1.5, doi=50.0)  # 100 -> 101.5
    spot_2 = block(dpx=1.5, doi=50.0, p0=101.5)  # -> 103.0225: one run with spot_1, +3.0225%
    spot_down = block(dpx=-2.0, doi=50.0)  # -2%: smaller than the run, by size
    long_null = block(doi=-100.0, delta=-5.0)
    long_null.price[0] = None  # a run whose open is null is skipped
    long_ok = block(doi=-100.0, delta=-5.0, dpx=-0.5)
    short_zero = block(doi=-100.0, delta=5.0)
    short_zero.price[-1] = 0.0  # a run whose close is not positive is skipped
    tail = [spot_1, spot_2, filler(), spot_down, filler(), long_null, filler(), long_ok, filler()]
    parts = chop_a + gap + chop_b + tail + [short_zero, filler()]
    r = compute_states(grid(*parts), "4h", rules=V1)
    assert [b.state for b in r.blocks[-11:]] == [
        "spot",
        "spot",
        "chop",
        "spot",
        "chop",
        "longun",
        "chop",
        "longun",
        "chop",
        "shortun",
        "chop",
    ]
    tbl = table(r, 30)
    assert (tbl.in_view, tbl.judged) == (113, 112)

    count, _, move, run = row_of(tbl, "chop")
    assert (count, move, run) == (106, pytest.approx(1.0), 50)
    count, _, move, run = row_of(tbl, "spot")
    assert (count, move, run) == (3, pytest.approx(3.0225), 2)
    count, _, move, run = row_of(tbl, "longun")
    assert (count, move, run) == (2, pytest.approx(-0.5), 1)
    assert row_of(tbl, "shortun") == (1, 1, None, None)
    assert row_of(tbl, "shortsq") == (0, 0, None, None)


def test_table_in_view_closed_at_from() -> None:
    # Block 0's midpoint is DAY0 + 2h. With 1021 buckets, last - 7d is exactly that midpoint.
    r = compute_states(grid(*[filler() for _ in range(42)], filler(n=13)), "4h", rules=V1)
    week = table(r, 7)
    assert week.view_from == at(DAY0 + 2 * 3600)
    assert r.last == at(DAY0 + 7 * DAY + 2 * 3600)
    assert week.in_view == 43  # block 0 counts
    # One bucket later, `from` moves 600 s past block 0's midpoint.
    r = compute_states(grid(*[filler() for _ in range(42)], filler(n=14)), "4h", rules=V1)
    week = table(r, 7)
    assert week.view_from == at(DAY0 + 2 * 3600 + STEP)
    assert week.in_view == 42
    # The predicate itself: midpoint = t0 + (t1 + 10m - t0) / 2, closed at both ends.
    t0, t1 = DAY0, DAY0 + 23 * STEP
    mid = DAY0 + 2 * 3600
    assert in_table_view(t0, t1, mid, mid + DAY)
    assert not in_table_view(t0, t1, mid + 300, mid + DAY)  # midpoint at from - 300
    assert in_table_view(t0, t1, mid - DAY, mid - STEP)  # midpoint at last + 10m
    assert not in_table_view(t0, t1, mid - DAY, mid - STEP - 300)


def test_latest_marker() -> None:
    build = {"doi": 100.0, "dpx": 0.5, "delta": 5.0, "n": 13}
    r = compute_states(grid(*[filler() for _ in range(42)], block(**build)), "4h", rules=V1)
    assert r.blocks[-1].forming
    assert [(t.latest, t.latest_uncovered) for t in r.tables] == [("longbd", False)] * 2

    r = compute_states(
        grid(*[filler() for _ in range(42)], block(**build, liq=False)),
        "4h",
        rules=V1,
    )
    assert [(t.latest, t.latest_uncovered) for t in r.tables] == [(None, True)] * 2


def test_reference_window_uses_last_not_clock() -> None:
    # Data from 2020: the reference is the 90 UTC days before last's date, plus that date.
    start = 18_262 * DAY  # 2020-01-01
    parts = [filler() for _ in range(95 * 6)] + [filler(n=13)]
    g = grid(*parts, start=start)
    # Nulls before the reference window do not count for QC.
    price = list(g.price)
    price[: 5 * 144] = [None] * (5 * 144)
    g = grid(*parts, start=start, rest={"bybit:price": price})
    r = compute_states(g, "4h", rules=V1)
    assert r.last == at(start + 95 * DAY + 12 * STEP)
    assert (r.thresholds.n_px, r.thresholds.n_oi) == (90 * 6 + 1, 90 * 6 + 1)
    assert r.covered_days == (90 * 6 + 1) / 6
    assert (r.qc, r.series_missing) == ([], [])


def test_qc_codes() -> None:
    parts = [filler() for _ in range(50)]
    n = 50 * H4
    # Exactly 1% missing, with a 3-bucket (1800 s) hole: both limits pass.
    edge: Values = [1.0] * n
    edge[100:103] = [None] * 3
    for k in range(9):
        edge[200 + 100 * k] = None
    r = compute_states(grid(*parts, rest={"bybit:price": edge}), "4h", rules=V1)
    assert (r.qc, r.series_missing) == ([], [])

    tail_hole: Values = [1.0] * (n - 4) + [None] * 4  # 2400 s at the end of the grid
    sparse: Values = [1.0] * n
    for k in range(13):  # 13 of 1200: over 1%, but no hole over one bucket
        sparse[50 + 90 * k] = None
    rest: dict[str, Values] = {
        "bybit:price": [1.0] * n,
        "binance:oi": tail_hole,
        "binance:kline": sparse,
        "bybit:oi": [None] * n,
    }
    r = compute_states(grid(*parts, rest=rest, quarantined=2), "4h", rules=V1)
    assert r.qc == [
        "gap:binance:oi:2400",
        "missing:binance:kline",
        "missing:bybit:oi",
        f"gap:bybit:oi:{n * STEP}",
        "archive_quarantined:2",
    ]
    assert r.series_missing == ["bybit:oi"]


def test_blocks_limited_to_30d_view() -> None:
    # 40 days of blocks and a 15-bucket forming block: last - 30d falls inside block 60.
    r = compute_states(grid(*[filler() for _ in range(240)], filler(n=15)), "4h", rules=V1)
    frm = DAY0 + (240 * H4 + 14) * STEP - 30 * DAY
    assert table(r, 30).view_from == at(frm)
    assert [t.show_days for t in r.tables] == [7, 30]
    assert r.blocks[0].t0 == at(DAY0 + 60 * 4 * 3600)  # straddles `from`, so it is kept
    assert len(r.blocks) == 240 - 60 + 1
    assert (r.thresholds.n_px, r.thresholds.n_oi) == (241, 241)


def test_grid_rejects_misaligned_or_ragged_input() -> None:
    good = grid(filler(), filler())
    with pytest.raises(ValueError, match="multiples of 600"):
        replace(good, start=good.start + 300, last=good.last + 300)
    with pytest.raises(ValueError, match="multiples of 600"):
        replace(good, last=good.last + 300)
    with pytest.raises(ValueError, match="ends before it starts"):
        replace(good, start=good.last + STEP)
    with pytest.raises(ValueError, match="oi has 47 buckets, expected 48"):
        replace(good, oi=good.oi[:-1])
    with pytest.raises(ValueError, match="liq_covered has 49 buckets, expected 48"):
        replace(good, liq_covered=[*good.liq_covered, True])
    with pytest.raises(ValueError, match="bybit:oi has 47 buckets, expected 48"):
        replace(good, rest_series={"bybit:price": good.price, "bybit:oi": good.oi[:-1]})


def test_forming_block_doi_nonzero_when_oi_present() -> None:
    r = compute_states(grid(*[filler() for _ in range(42)], block(doi=100.0, n=15)), "4h", rules=V1)
    b = r.blocks[-1]
    assert (b.forming, b.buckets, b.t1) == (True, 15, r.last)
    assert (b.doi, b.imputed.doi, b.oi_close) == (100.0, False, 1100.0)


def run(*specs: dict[str, Any]) -> list[Part]:
    """Blocks built from `specs`, each opening at the close before it: O6's dPx, from the bucket
    before the block, then equals v1's, from its own first bucket."""
    parts: list[Part] = []
    p0 = 100.0
    for spec in specs:
        part = block(p0=p0, **spec)
        parts.append(part)
        close = part.price[-1]
        assert close is not None
        p0 = close
    return parts


def features(rng: random.Random) -> dict[str, Any]:
    """A block with random features: mostly small, some large, so that most states occur."""
    big = 4.0 if rng.random() < 0.15 else 1.0
    return {
        "dpx": rng.uniform(-1.5, 1.5) * big,
        "doi": rng.uniform(-150.0, 150.0) * big,
        "delta": rng.uniform(-5.0, 5.0),
        "lliq": rng.uniform(0.0, 20.0) * (10.0 if rng.random() < 0.1 else 1.0),
        "sliq": rng.uniform(0.0, 20.0) * (10.0 if rng.random() < 0.1 else 1.0),
    }


def since(g: Grid, start: int) -> Grid:
    """The grid from bucket `start` on."""
    k = (start - g.start) // STEP
    return Grid(
        start=start,
        last=g.last,
        price=g.price[k:],
        oi=g.oi[k:],
        vd=g.vd[k:],
        long_liq=g.long_liq[k:],
        short_liq=g.short_liq[k:],
        liq_covered=g.liq_covered[k:],
        vd_covered=g.vd_covered[k:],
        rest_series={key: values[k:] for key, values in g.rest_series.items()},
        quarantined_days=g.quarantined_days,
    )


def own(b: Block) -> Thresholds:
    assert b.thresholds is not None
    return b.thresholds


def test_o6_later_blocks_change_no_earlier_state_or_threshold():
    rng = random.Random(6)
    past = [features(rng) for _ in range(100)]
    calm = [features(rng) for _ in range(30)]
    wild = [
        {
            **f,
            "dpx": 5 * f["dpx"],
            "doi": 5 * f["doi"],
            "lliq": 20 * f["lliq"],
            "sliq": 20 * f["sliq"],
        }
        for f in calm
    ]
    grids = [grid(*run(*past, *later)) for later in (calm, wild)]

    a, b = (compute_states(g, "4h", rules=O6) for g in grids)
    assert [(x.state, x.thresholds) for x in a.blocks[:100]] == [
        (x.state, x.thresholds) for x in b.blocks[:100]
    ]
    assert sum(x.state is not None for x in a.blocks[:100]) > 50
    # v1 ranks every block against the whole window, later blocks included: the same past reads
    # differently once the later blocks change.
    a, b = (compute_states(g, "4h", rules=V1) for g in grids)
    assert a.thresholds != b.thresholds
    assert [x.state for x in a.blocks[:100]] != [x.state for x in b.blocks[:100]]


def test_o6_ranks_by_r7_over_the_blocks_before():
    # 43 blocks before the probe: sLiq 0..42, dOI 1..43, dPx 0.1..4.3 %. The first one has no
    # bucket before it, so its dPx is imputed and left out of the px sample.
    specs = [{"sliq": float(k), "doi": float(k + 1), "dpx": 0.1 * (k + 1)} for k in range(43)]
    r = compute_states(grid(*run(*specs, {})), "4h", rules=O6)

    t = own(r.blocks[-1])
    assert (t.n_liq, t.n_px, t.n_oi) == (43, 42, 43)
    # R-7, between the neighbours at (n - 1) * q. The floor rank of v1 would give 37, 32 and 3.2.
    assert t.s_liq == pytest.approx(37.8)
    assert t.l_liq == 0.0
    assert t.oi == pytest.approx(32.5)
    assert t.px == pytest.approx(3.275)
    assert t.px == quantile_r7(sorted(abs(b.dpx) for b in r.blocks[1:43]), 0.75)
    assert r.blocks[-1].state == "chop"


def test_o6_dpx_runs_from_the_bucket_before_the_block():
    base = run(*[FILL] * 50)
    close = base[-1].price[-1]
    assert close is not None
    # The price jumps 5% between the blocks, then rises 1% more inside the block.
    jump = block(p0=close * 1.05, dpx=(1.06 / 1.05 - 1) * 100, doi=50.0)
    g = grid(*base, jump, filler())

    v1 = compute_states(g, "4h", rules=V1).blocks[-2]
    o6 = compute_states(g, "4h", rules=O6)
    assert (v1.dpx, v1.state) == (pytest.approx(100 / 105), "chop")
    assert (o6.blocks[-2].dpx, o6.blocks[-2].imputed.dpx) == (pytest.approx(6.0), False)
    assert o6.blocks[-2].state == "spot"
    # The grid's first block has no bucket before it.
    assert (o6.blocks[0].dpx, o6.blocks[0].imputed.dpx) == (0.0, True)

    # Without the close before it the move is unknown: imputed and not judged, while v1 judges
    # it from its own first bucket. The blocks after it leave it out of their px sample.
    parts = run(*[FILL] * 50, FILL, {})
    parts[49].price[-1] = None
    v1, o6 = (compute_states(grid(*parts), "4h", rules=rules) for rules in (V1, O6))
    assert (v1.blocks[50].imputed.dpx, v1.blocks[50].state) == (False, "chop")
    x = o6.blocks[50]
    assert (x.covered, x.dpx, x.imputed.dpx, x.state) == (True, 0.0, True, None)
    # Blocks 0 (no bucket before it), 49 (no close) and 50 (no base) are out of the px sample.
    t = own(o6.blocks[51])
    assert (t.n_liq, t.n_px, t.n_oi) == (51, 48, 51)
    assert o6.blocks[51].state is not None


def test_o6_squeeze_needs_liquidations_on_its_side():
    # No liquidations at all: both P90s are 0, so v1 calls any large move a squeeze.
    moves = [{"dpx": 1.0 if k % 2 else -1.0, "doi": 100.0} for k in range(50)]
    probes = [
        {"dpx": 2.0, "doi": 50.0},
        {"dpx": -2.0, "doi": 50.0},
        {"dpx": 2.0, "doi": 50.0, "sliq": 1.0},
        {"dpx": -2.0, "doi": 50.0, "lliq": 1.0},
    ]
    g = grid(*run(*moves, *probes))

    v1, o6 = (compute_states(g, "4h", rules=rules) for rules in (V1, O6))
    assert [b.state for b in v1.blocks[-4:]] == ["shortsq", "longsq", "shortsq", "longsq"]
    assert [b.state for b in o6.blocks[-4:]] == ["spot", "spot", "shortsq", "longsq"]
    assert (own(o6.blocks[-4]).s_liq, own(o6.blocks[-4]).l_liq) == (0.0, 0.0)


def test_o6_leaves_imputed_blocks_unjudged_and_out_of_their_own_samples():
    parts = run(*[FILL] * 50, {"doi": 50.0}, {"delta": 5.0}, {})
    parts[50].oi[-1] = None  # no OI close: dOI imputed
    parts[51].vd[3] = None  # a missing Binance kline: covered, but a sum is imputed

    v1, o6 = (compute_states(grid(*parts), "4h", rules=rules) for rules in (V1, O6))
    assert [b.state is not None for b in v1.blocks[50:]] == [True, True, True]
    assert [(b.covered, b.state) for b in o6.blocks[50:52]] == [(True, None), (True, None)]
    assert (o6.blocks[50].imputed.doi, o6.blocks[51].imputed.sums) == (True, True)
    # Only the OI sample loses block 50; block 51 stays in every sample. Block 0 has no dPx.
    t = own(o6.blocks[52])
    assert (t.n_liq, t.n_px, t.n_oi) == (52, 51, 51)
    assert o6.blocks[52].state is not None


def test_o6_checks_each_thresholds_sample_on_its_own():
    # The first 10 blocks have no liquidation coverage.
    parts = run(*[{**FILL, "liq": False}] * 10, *[FILL] * 45)
    r = compute_states(grid(*parts), "4h", rules=O6)

    t = own(r.blocks[50])
    assert (t.n_liq, t.n_px, t.n_oi) == (40, 49, 50)
    assert (t.s_liq, t.l_liq, t.oi, t.px) == (None, None, 100.0, pytest.approx(1.0))
    assert (r.blocks[50].covered, r.blocks[50].state) == (True, None)
    t = own(r.blocks[52])
    assert (t.n_liq, t.s_liq, t.l_liq) == (42, 10.0, 10.0)
    assert r.blocks[52].state is not None

    # Blocks 1-5 have no OI close: the OI sample alone falls short.
    parts = run(*[FILL] * 45, {})
    for k in range(1, 6):
        parts[k].oi[-1] = None
    r = compute_states(grid(*parts), "4h", rules=O6)
    t = own(r.blocks[45])
    assert (t.n_liq, t.n_px, t.n_oi) == (45, 44, 40)
    assert t.oi is None
    assert None not in (t.s_liq, t.l_liq, t.px)
    assert r.blocks[45].state is None


def test_o6_judges_later_blocks_once_their_past_is_long_enough():
    parts = run(*[FILL] * 80)
    r = compute_states(grid(*parts), "4h", rules=O6)

    # Block k ranks blocks 0..k-1, and its px sample lacks block 0: 42 of them from block 43 on.
    assert [b.state is not None for b in r.blocks] == [False] * 43 + [True] * 37
    assert [own(b).px is None for b in r.blocks] == [True] * 43 + [False] * 37
    assert [own(b).n_px for b in r.blocks[:3]] == [0, 0, 1]
    # Table 1 counts what was judged in each view, and nothing is collecting.
    assert [(t.show_days, t.in_view, t.judged) for t in r.tables] == [(7, 42, 37), (30, 80, 37)]
    assert sum(row.count for row in table(r, 30).rows) == 37
    assert not r.collecting
    # v1 judges all 80 blocks against one set of thresholds.
    assert table(compute_states(grid(*parts), "4h", rules=V1), 30).judged == 80

    # 8h blocks need 21 in each sample.
    r = compute_states(grid(*run(*[{**FILL, "n": H8}] * 30)), "8h", rules=O6)
    assert [b.state is not None for b in r.blocks] == [False] * 22 + [True] * 8


def test_o6_heads_the_view_with_the_reference_blocks_thresholds():
    # R, the last block, is not covered and so not judged: its thresholds still head the view.
    r = compute_states(grid(*run(*[FILL] * 60, {**FILL, "liq": False})), "4h", rules=O6)
    assert (r.blocks[-1].covered, r.blocks[-1].state) == (False, None)
    assert r.thresholds == own(r.blocks[-1])
    assert (r.thresholds.n_liq, r.thresholds.n_px, r.thresholds.n_oi) == (60, 59, 60)
    assert not r.collecting

    # Collecting while R's liquidation sample is short.
    r = compute_states(grid(*run(*[FILL] * 42)), "4h", rules=O6)
    assert (r.thresholds.n_liq, r.thresholds.s_liq, r.collecting) == (41, None, True)
    r = compute_states(grid(*run(*[FILL] * 43)), "4h", rules=O6)
    assert (r.thresholds.n_liq, r.collecting) == (42, False)

    # No block at all: no R, so nothing is ranked.
    r = compute_states(grid(block(n=5)), "4h", rules=O6)
    assert (r.blocks, r.tail is not None) == ([], True)
    assert r.thresholds == Thresholds(
        s_liq=None, l_liq=None, oi=None, px=None, n_liq=0, n_px=0, n_oi=0
    )
    assert r.collecting


def test_backfill_of_121_days_keeps_v1_and_gives_o6_its_full_past():
    rng = random.Random(121)
    # 121 whole days of 4h blocks and a forming one: `last` falls on day 121, 02:00.
    long = grid(*run(*[features(rng) for _ in range(121 * 6)], {"n": 13}))
    day = long.last // DAY * DAY
    assert long.start == day - 121 * DAY
    short = since(long, day - 91 * DAY)  # what a 90-day backfill held

    for window, per_day in (("4h", 6), ("8h", 3)):
        v1 = compute_states(long, window, rules=V1)
        # v1's states, thresholds and Table 1 read the 90-day reference only.
        assert v1 == compute_states(short, window, rules=V1)
        assert sum(b.state is not None for b in v1.blocks) > 0
        o6 = compute_states(long, window, rules=O6)
        assert (o6.covered_days, o6.qc, o6.series_missing) == (
            v1.covered_days,
            v1.qc,
            v1.series_missing,
        )
        assert [b.t0 for b in o6.blocks] == [b.t0 for b in v1.blocks]
        # Every block in view, the earliest included, ranks a full 90 days before it ...
        full = 90 * per_day
        assert {(own(b).n_liq, own(b).n_px, own(b).n_oi) for b in o6.blocks} == {(full,) * 3}
        # ... which 91 days of grid would cut short for the earliest ones.
        cut = compute_states(short, window, rules=O6)
        assert own(cut.blocks[0]).n_oi == 61 * per_day  # [day - 91, day - 30)
