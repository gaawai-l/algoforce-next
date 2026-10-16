"""The original perp-squeeze page's v1 state rules, checked on synthetic 10-minute grids."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from wheelhouse_service.perps.states import (
    TABLE_STATES,
    Grid,
    StatesResult,
    Table,
    compute_states,
    in_table_view,
    quantile,
    shares,
)

STEP = 600
DAY = 86_400
H4 = 24  # buckets in a 4h block
H8 = 48  # buckets in an 8h block
# 2023-11-14 00:00 UTC: a day boundary, so both 4h and 8h blocks start here.
DAY0 = 19_675 * DAY

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
    r = compute_states(grid(block(n=5), block(), block(), block(n=12), start=start), "4h")
    assert [b.t0 for b in r.blocks] == [at(DAY0 + 4 * 3600), at(DAY0 + 8 * 3600)]
    assert [b.t1 for b in r.blocks] == [at(DAY0 + 8 * 3600 - STEP), at(DAY0 + 12 * 3600 - STEP)]
    assert all(b.buckets == H4 and not b.forming for b in r.blocks)
    # 12 trailing buckets are under half a block plus one: a tail, drawn but not judged.
    assert r.tail is not None
    assert (r.tail.t0, r.tail.t1) == (at(DAY0 + 12 * 3600), r.last)
    assert r.tail.price_close == 100.0
    assert r.thresholds.n_all == 2

    r = compute_states(grid(block(n=5), block(), block(), block(n=13), start=start), "4h")
    assert r.tail is None
    assert len(r.blocks) == 3
    b = r.blocks[-1]
    assert (b.t0, b.t1, b.buckets, b.forming) == (at(DAY0 + 12 * 3600), r.last, 13, True)
    assert r.thresholds.n_all == 3


def test_blocks_align_to_epoch_8h() -> None:
    # 04:00 is a 4h boundary but not an 8h one: the 24 buckets before 08:00 are a leading stub.
    start = DAY0 + 4 * 3600
    r = compute_states(grid(block(n=H4), block(n=H8), block(n=H8), start=start), "8h")
    assert [b.t0 for b in r.blocks] == [at(DAY0 + 8 * 3600), at(DAY0 + 16 * 3600)]
    assert all(b.buckets == H8 and not b.forming for b in r.blocks)
    assert r.tail is None
    assert r.thresholds.n_all == 2


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
    r = compute_states(grid(*parts), "4h")
    t = r.thresholds
    assert (t.s_liq, t.l_liq, t.oi) == (10.0, 10.0, 100.0)
    assert t.px == pytest.approx(1.0)
    assert (t.n_liq, t.n_all) == (111, 111)
    assert not r.collecting
    assert [b.state for b in r.blocks[-len(CASCADE) :]] == [s for s, _ in CASCADE]
    assert all(b.state == "chop" for b in r.blocks[: -len(CASCADE)])
    tbl = table(r, 30)
    assert [row.state for row in tbl.rows] == list(TABLE_STATES)
    assert (tbl.in_view, tbl.judged) == (111, 111)
    assert sum(row.share or 0 for row in tbl.rows) == 100


def test_both_liquidations_zero_degenerate_squeeze() -> None:
    # No liquidations at all: both P90s are 0, and 0 >= 3 * 0 passes, so any block whose price
    # moves by T_px either way is a squeeze. The original behaves the same way.
    moves = [1.0 if k % 2 else -1.0 for k in range(45)] + [2.0, -2.0]
    r = compute_states(grid(*[block(dpx=m) for m in moves]), "4h")
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
    r = compute_states(grid(*base, x, y), "4h")
    assert (r.thresholds.n_liq, r.thresholds.n_all) == (43, 44)
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
    r = compute_states(grid(*base, *uncovered), "4h")
    assert (r.thresholds.n_liq, r.thresholds.n_all) == (42, 44)
    # sorted[floor(0.75 * 43)] = sorted[32]: 33 and 3.3. Covered blocks alone would give 31 and 3.1.
    assert r.thresholds.oi == 33.0
    assert r.thresholds.px == pytest.approx(3.3)


def test_collecting_gate() -> None:
    def run(covered: int) -> StatesResult:
        parts = [filler() for _ in range(covered)] + [filler(liq=False) for _ in range(5)]
        return compute_states(grid(*parts), "4h")

    r = run(41)
    assert r.collecting
    assert r.covered_days == 41 / 6
    assert all(b.state is None for b in r.blocks)
    assert all(t.judged == 0 and all(row.share is None for row in t.rows) for t in r.tables)
    # Thresholds are still ranked while collecting; uncovered blocks do not count for the gate.
    assert r.thresholds.n_all == 46

    r = run(42)
    assert not r.collecting
    assert r.covered_days == 7.0
    assert [b.state is not None for b in r.blocks] == [True] * 42 + [False] * 5


def test_collecting_gate_8h() -> None:
    def run(covered: int) -> StatesResult:
        return compute_states(grid(*[filler(n=H8) for _ in range(covered)]), "8h")

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
    blocks = compute_states(grid(*parts), "4h").blocks[-6:]

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
    r = compute_states(grid(*parts), "4h")
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
    r = compute_states(grid(*parts), "4h")
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
    r = compute_states(grid(*[filler() for _ in range(42)], filler(n=13)), "4h")
    week = table(r, 7)
    assert week.view_from == at(DAY0 + 2 * 3600)
    assert r.last == at(DAY0 + 7 * DAY + 2 * 3600)
    assert week.in_view == 43  # block 0 counts
    # One bucket later, `from` moves 600 s past block 0's midpoint.
    r = compute_states(grid(*[filler() for _ in range(42)], filler(n=14)), "4h")
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
    r = compute_states(grid(*[filler() for _ in range(42)], block(**build)), "4h")
    assert r.blocks[-1].forming
    assert [(t.latest, t.latest_uncovered) for t in r.tables] == [("longbd", False)] * 2

    r = compute_states(
        grid(*[filler() for _ in range(42)], block(**build, liq=False)),
        "4h",
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
    r = compute_states(g, "4h")
    assert r.last == at(start + 95 * DAY + 12 * STEP)
    assert r.thresholds.n_all == 90 * 6 + 1
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
    r = compute_states(grid(*parts, rest={"bybit:price": edge}), "4h")
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
    r = compute_states(grid(*parts, rest=rest, quarantined=2), "4h")
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
    r = compute_states(grid(*[filler() for _ in range(240)], filler(n=15)), "4h")
    frm = DAY0 + (240 * H4 + 14) * STEP - 30 * DAY
    assert table(r, 30).view_from == at(frm)
    assert [t.show_days for t in r.tables] == [7, 30]
    assert r.blocks[0].t0 == at(DAY0 + 60 * 4 * 3600)  # straddles `from`, so it is kept
    assert len(r.blocks) == 240 - 60 + 1
    assert r.thresholds.n_all == 241


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
    r = compute_states(grid(*[filler() for _ in range(42)], block(doi=100.0, n=15)), "4h")
    b = r.blocks[-1]
    assert (b.forming, b.buckets, b.t1) == (True, 15, r.last)
    assert (b.doi, b.imputed.doi, b.oi_close) == (100.0, False, 1100.0)
