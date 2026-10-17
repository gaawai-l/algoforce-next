import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from onchain_fixture import load_series

from wheelhouse_service.onchain.brk import EPOCH, HOUR1_SERIES
from wheelhouse_service.onchain.pressure import (
    LOOKBACK,
    WINDOW,
    Pressure,
    PressureLossPoint,
    quantile_r7,
    seller_pressure,
)
from wheelhouse_service.rules import Rules

HOUR = timedelta(hours=1)
V1: Rules = frozenset()
O3: Rules = frozenset({"O3"})
Rows = dict[str, list[tuple[datetime, float | None]]]
Columns = dict[str, list[float | None]]

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

# What each cumulative series adds per hour. In $100 units the legs are LP 20, LL 10, SPx1 40 and
# SLx1 25 (STH minus the under-1h residual), so a plain hour is worth (10 + 25) * 100 = 3500 on
# chart 1 and 25 / 95 on chart 2.
STEPS: dict[str, float] = {
    STH_PROFIT: 5_000.0,
    STH_LOSS: 3_000.0,
    LTH_PROFIT: 2_000.0,
    LTH_LOSS: 1_000.0,
    YOUNG_PROFIT: 1_000.0,
    YOUNG_LOSS: 500.0,
}
# Supply after taking out the under-1h coins: loss 50, profit 30, so a plain hour is 50 / 80.
SUPPLY: dict[str, float] = {
    STH_IN_LOSS: 60.0,
    STH_IN_PROFIT: 40.0,
    YOUNG_IN_LOSS: 10.0,
    YOUNG_IN_PROFIT: 10.0,
}
BASE = datetime(2026, 1, 1, tzinfo=UTC)
PLAIN_LOSS = 3_500.0
PLAIN_SHARE = 25 / 95
PLAIN_SUPPLY = 50 / 80


def columns(count: int, increments: dict[str, Callable[[int], float]] | None = None) -> Columns:
    """`count` hourly values per series: the cumulative ones grow, the rest stay constant."""
    custom = increments or {}
    out: Columns = {PRICE: [100_000.0 + h for h in range(count)]}
    for name, step in STEPS.items():
        grow = custom.get(name, lambda _h, step=step: step)
        total = 0.0
        values: list[float | None] = []
        for h in range(count):
            total += grow(h)
            values.append(total)
        out[name] = values
    for name, level in SUPPLY.items():
        out[name] = [level] * count
    return out


def rows_of(cols: Columns, start: datetime = BASE) -> Rows:
    return {name: [(start + HOUR * h, v) for h, v in enumerate(vs)] for name, vs in cols.items()}


def no_block(cols: Columns, hour: int) -> None:
    """BRK publishes the timestamp of an hour without a block but nothing else."""
    for values in cols.values():
        values[hour] = None


def hold(cols: Columns, name: str, hour: int) -> None:
    """Make cumulative series `name` add nothing in `hour`; every other hour keeps its step."""
    cols[name] = [
        None if v is None else v - STEPS[name] if h >= hour else v for h, v in enumerate(cols[name])
    ]


def at(hour: int) -> datetime:
    return BASE + HOUR * hour


def computed(cols: Columns, rules: Rules = V1) -> Pressure:
    result = seller_pressure(rows_of(cols), rules=rules)
    assert result is not None
    return result


def no_block_hour(cols: Columns, hour: int) -> None:
    """An hour without a block as BRK has it: nothing realized, then every value null."""
    for name in STEPS:
        hold(cols, name, hour)
    no_block(cols, hour)


def flagged(result: Pressure) -> list[tuple[str, datetime]]:
    """The points marked as without a block or behind a gap, as (chart, time)."""
    charts = {
        "loss": result.loss,
        "share": result.share,
        "supply": result.supply,
        "price": result.price,
    }
    return [
        (name, point.at)
        for name, points in charts.items()
        for point in points
        if point.no_block or point.gap
    ]


def fixture_rows(last: datetime) -> Rows:
    """Every captured hour1 row up to and including `last`."""
    rows: Rows = {}
    for name in HOUR1_SERIES:
        series = load_series(name, "hour1")
        stamped = [(EPOCH + HOUR * (series.start + k), v) for k, v in enumerate(series.data)]
        rows[name] = [(time, v) for time, v in stamped if time <= last]
    return rows


def test_parity_with_original_page_at_0800():
    result = seller_pressure(fixture_rows(datetime(2026, 10, 16, 8, tzinfo=UTC)), rules=V1)
    assert result is not None
    assert result.last_at == datetime(2026, 10, 16, 8, tzinfo=UTC)
    assert result.kept == 2576
    assert result.loss[-1].at == result.last_at
    assert result.loss[-1].lth == pytest.approx(1983300.0, rel=1e-12)
    assert result.loss[-1].sth == pytest.approx(8540500.0, rel=1e-12)
    assert result.loss_levels.n == 716
    assert result.loss_levels.p95 == pytest.approx(41345525.0, rel=1e-12)
    assert result.loss_levels.p75 == pytest.approx(10050150.0, rel=1e-12)
    assert result.share[-1].at == result.last_at
    assert result.share[-1].value == pytest.approx(0.41893330324776934, rel=1e-12)
    assert result.share_levels.n == 716
    assert result.share_levels.p95 == pytest.approx(0.5611976039771673, rel=1e-12)
    assert result.share_levels.p75 == pytest.approx(0.22150410301296825, rel=1e-12)
    assert result.supply[-1].at == result.last_at
    assert result.supply[-1].value == pytest.approx(0.2957342245796155, rel=1e-12)
    assert result.supply_levels.n == 716
    assert result.supply_levels.p95 == pytest.approx(0.38687086545521404, rel=1e-12)
    assert result.supply_levels.p75 == pytest.approx(0.26151208272764137, rel=1e-12)
    # One price per kept row, and the 11 hours without a block cost 22 rows (xgap is 0 here: the
    # under-1h series have nulls at the same hours).
    assert len(result.price) == result.kept
    assert result.xgap == 0
    # v1 marks no point: those marks are O3's.
    assert not any(flagged(result))


def test_qc_passes_on_the_parity_input():
    result = seller_pressure(fixture_rows(datetime(2026, 10, 16, 8, tzinfo=UTC)), rules=V1)
    assert result is not None
    assert result.qc == []


def test_lookback_ignores_rows_beyond_2600():
    full = fixture_rows(datetime(2026, 10, 16, 9, tzinfo=UTC))
    assert all(len(points) == LOOKBACK for points in full.values())
    baseline = seller_pressure(full, rules=V1)
    assert baseline is not None
    first = full[PRICE][0][0]
    # 500 older hours whose cumulative values would turn the oldest kept row into a huge loss if the
    # window reached back to them, and whose supply and price would add rows and shift the levels.
    older = {
        name: [(first - HOUR * k, 1.0 if name != PRICE else 5.0) for k in range(500, 0, -1)]
        for name in HOUR1_SERIES
    }
    extended = {name: older[name] + full[name] for name in HOUR1_SERIES}
    assert seller_pressure(extended, rules=V1) == baseline


def test_no_block_hour_drops_itself_and_next():
    cols = columns(800)
    no_block(cols, 700)
    result = computed(cols)
    dropped = {at(700), at(701)}
    assert dropped.isdisjoint({p.at for p in result.loss})
    assert dropped.isdisjoint({p.at for p in result.price})
    assert {at(699), at(702)} <= {p.at for p in result.loss}
    # Hours 1..799 are candidates (hour 0 only serves as the previous row).
    assert result.kept == 799 - 2
    assert result.xgap == 0
    assert result.last_at == at(799)


def test_levels_window_is_clock_hours_not_rows():
    cols = columns(800)
    no_block(cols, 700)
    result = computed(cols)
    # The last 720 clock hours hold two dropped rows; the window does not reach back for more.
    assert result.loss_levels.n == 718
    assert result.share_levels.n == 718
    assert result.supply_levels.n == 718


def test_levels_window_excludes_the_hour_720_back():
    # LTH loss grows by 100 * h in hour h, so chart 1 is (h + 25) * 100 and strictly increasing.
    cols = columns(800, {LTH_LOSS: lambda h: 100.0 * h})
    result = computed(cols)
    # t > t_last - 720h: hours 80..799. Hour 79 is exactly 720 hours back and is out.
    assert result.loss_levels.n == 720
    p95 = (80 + 719 * 0.95 + 25) * 100
    p75 = (80 + 719 * 0.75 + 25) * 100
    assert result.loss_levels.p95 == pytest.approx(p95, rel=1e-12)
    assert result.loss_levels.p75 == pytest.approx(p75, rel=1e-12)


def test_under_1h_null_keeps_rows_and_counts_xgap_twice():
    cols = columns(10)
    cols[YOUNG_LOSS][5] = None
    result = computed(cols)
    assert result.kept == 9
    assert result.xgap == 2
    by_time = {p.at: p for p in result.loss}
    # Nothing is taken out where the under-1h value is unknown: STH loss is 3000, not 2500.
    assert by_time[at(5)].sth == 3_000.0
    assert by_time[at(6)].sth == 3_000.0
    assert by_time[at(4)].sth == 2_500.0
    assert by_time[at(7)].sth == 2_500.0
    # The profit leg is not taken out either: SPx1 is 50 here, not 40.
    shares = {p.at: p.value for p in result.share}
    assert shares[at(5)] == pytest.approx(30 / (20 + 10 + 50 + 30), rel=1e-12)
    assert shares[at(4)] == pytest.approx(PLAIN_SHARE, rel=1e-12)


def test_under_1h_profit_null_also_skips_the_loss_exclusion():
    cols = columns(10)
    cols[YOUNG_PROFIT][5] = None
    result = computed(cols)
    assert result.xgap == 2
    assert {p.at: p.sth for p in result.loss}[at(5)] == 3_000.0


@pytest.mark.parametrize(
    ("delta", "expected"),
    [(150.0, 200.0), (149.99, 100.0), (50.0, 100.0), (49.99, 0.0), (0.0, 0.0)],
)
def test_rounding_is_half_up_in_hundreds(delta: float, expected: float):
    cols = columns(2)
    cols[LTH_LOSS] = [1_000.0, 1_000.0 + delta]
    result = computed(cols)
    assert result.loss[-1].lth == expected


def test_negative_leg_is_clamped_to_zero():
    cols = columns(2)
    cols[LTH_LOSS] = [1_000.0, 400.0]
    assert computed(cols).loss[-1].lth == 0.0


def test_young_residual_is_subtracted_before_rounding():
    # Raw STH 149 less raw under-1h 50 is 99, which rounds to 1 unit; rounding each first gives
    # 1 - 1 = 0.
    cols = columns(2)
    cols[STH_LOSS] = [0.0, 149.0]
    cols[YOUNG_LOSS] = [0.0, 50.0]
    assert computed(cols).loss[-1].sth == 100.0


def test_young_residual_larger_than_sth_is_clamped_to_zero():
    cols = columns(2)
    cols[STH_LOSS] = [0.0, 1_000.0]
    cols[YOUNG_LOSS] = [0.0, 5_000.0]
    assert computed(cols).loss[-1].sth == 0.0


def test_share_skips_zero_denominator():
    cols = columns(10)
    # Hour 5 adds nothing to the four realized cumulatives, so the denominator is 0.
    for name in (STH_PROFIT, STH_LOSS, LTH_PROFIT, LTH_LOSS):
        hold(cols, name, 5)
    # Hour 7 adds nothing to STH loss only, so its share is 0 and still counts.
    hold(cols, STH_LOSS, 7)
    result = computed(cols)
    shares = {p.at: p.value for p in result.share}
    assert at(5) not in shares
    assert shares[at(7)] == 0.0
    assert shares[at(6)] == pytest.approx(PLAIN_SHARE, rel=1e-12)
    # The row itself is kept: chart 1 shows 0 there, and chart 3 still reads it.
    assert {p.at: (p.lth, p.sth) for p in result.loss}[at(5)] == (0.0, 0.0)
    assert at(5) in {p.at for p in result.supply}
    assert result.kept == 9
    assert result.share_levels.n == 8


def test_supply_only_on_kept_rows():
    cols = columns(12)
    no_block(cols, 4)
    # One supply series is null in hour 8: the row stays on chart 1 and is skipped on chart 3.
    cols[YOUNG_IN_LOSS][8] = None
    # Once the under-1h coins are taken out nothing is left in hour 9, so there is no share.
    cols[STH_IN_LOSS][9] = 10.0
    cols[STH_IN_PROFIT][9] = 10.0
    result = computed(cols)
    supply = {p.at: p.value for p in result.supply}
    # Hour 5 follows the hour without a block; its supply is complete but its row is dropped.
    assert at(4) not in supply
    assert at(5) not in supply
    assert {p.at for p in result.loss} >= {at(8), at(9)}
    assert at(8) not in supply
    assert at(9) not in supply
    assert supply[at(10)] == pytest.approx(PLAIN_SUPPLY, rel=1e-12)
    assert set(supply) == {at(h) for h in (1, 2, 3, 6, 7, 10, 11)}
    assert result.supply_levels.n == 7


def test_supply_excludes_the_under_1h_coins_and_reads_the_same_row():
    cols = columns(3)
    cols[STH_IN_LOSS][2] = 90.0
    cols[YOUNG_IN_LOSS][2] = 30.0
    cols[STH_IN_PROFIT][2] = 50.0
    cols[YOUNG_IN_PROFIT][2] = 10.0
    # loss 60, profit 40, read at the row itself (not the previous one).
    assert computed(cols).supply[-1].value == pytest.approx(0.6, rel=1e-12)


def test_price_is_the_close_of_each_kept_row():
    cols = columns(6)
    result = computed(cols)
    assert [(p.at, p.value) for p in result.price] == [(at(h), 100_000.0 + h) for h in range(1, 6)]


def test_row_with_a_null_price_is_dropped():
    cols = columns(8)
    cols[PRICE][4] = None
    result = computed(cols)
    assert at(4) not in {p.at for p in result.price}
    # Only the price is missing there, so the cumulatives still give hour 5 a previous row.
    assert at(5) in {p.at for p in result.price}
    assert result.kept == 6


def test_series_are_aligned_by_time_not_by_position():
    cols = columns(10)
    short = rows_of(cols)
    # The price series is three rows shorter at the start, so every index is off by three.
    short[PRICE] = short[PRICE][3:]
    nulled = columns(10)
    nulled[PRICE][:3] = [None] * 3
    assert seller_pressure(short, rules=V1) == computed(nulled)


def test_row_missing_from_one_series_counts_as_null():
    cols = columns(10)
    gapped = rows_of(cols)
    gapped[STH_LOSS] = [point for point in gapped[STH_LOSS] if point[0] != at(4)]
    nulled = columns(10)
    nulled[STH_LOSS][4] = None
    assert seller_pressure(gapped, rules=V1) == computed(nulled)
    assert computed(nulled).kept == 9 - 2


def test_empty_when_nothing_can_be_kept():
    assert seller_pressure({name: [] for name in HOUR1_SERIES}, rules=V1) is None
    cols = columns(5)
    for hour in range(5):
        cols[PRICE][hour] = None
    assert seller_pressure(rows_of(cols), rules=V1) is None
    assert seller_pressure(rows_of(columns(1)), rules=V1) is None


def test_qc_hour_gap_fails_only_on_a_step_over_three_hours():
    # One hour without a block drops two rows: kept rows three hours apart, which passes.
    one = columns(12)
    no_block(one, 5)
    assert computed(one).qc == []
    # Two in a row leave a 4-hour hole between the kept rows at hours 4 and 8.
    two = columns(12)
    no_block(two, 5)
    no_block(two, 6)
    result = computed(two)
    kept = [p.at for p in result.price]
    assert kept[kept.index(at(4)) + 1] == at(8)
    assert result.qc == ["hour_gap"]


def test_qc_intraday_legs_fails_when_an_under_1h_cumulative_is_null():
    cols = columns(10)
    cols[YOUNG_LOSS][5] = None
    result = computed(cols)
    assert result.xgap == 2
    assert result.qc == ["intraday_legs"]


def test_qc_sth_supply_fails_on_a_null_on_a_kept_row():
    cols = columns(10)
    cols[STH_IN_PROFIT][5] = None
    assert computed(cols).qc == ["sth_supply"]
    # A null on a row that is not kept does not count, and the under-1h supply is not checked.
    dropped = columns(10)
    dropped[PRICE][5] = None
    dropped[STH_IN_LOSS][5] = None
    dropped[YOUNG_IN_LOSS][7] = None
    assert computed(dropped).qc == []


def test_qc_lists_failures_in_check_order():
    cols = columns(12)
    cols[STH_IN_LOSS][10] = None
    cols[YOUNG_PROFIT][2] = None
    no_block(cols, 5)
    no_block(cols, 6)
    assert computed(cols).qc == ["hour_gap", "intraday_legs", "sth_supply"]


def test_latest_at_is_the_newest_priced_row_before_the_row_gate():
    # The hour without a block drops itself and the next one, the newest hour BRK has.
    cols = columns(10)
    no_block(cols, 8)
    result = computed(cols)
    assert result.last_at == at(7)
    assert result.latest_at == at(9)
    assert result.latest_at - result.last_at == 2 * HOUR
    # A trailing hour without a price is not newer data.
    unpriced = columns(10)
    unpriced[PRICE][9] = None
    assert computed(unpriced).latest_at == at(8)


def test_payload_stored_before_qc_still_loads():
    stored = computed(columns(5)).model_dump(mode="json")
    del stored["qc"], stored["latest_at"]
    old = Pressure.model_validate(stored)
    assert old.qc == []
    assert old.latest_at is None


def test_quantile_r7():
    assert quantile_r7([1.0, 2.0, 3.0, 4.0], 0.75) == 3.25
    assert quantile_r7([], 0.75) is None


def test_quantile_r7_edges():
    assert quantile_r7([5.0], 0.95) == 5.0
    assert quantile_r7([1.0, 2.0, 3.0], 0.0) == 1.0
    assert quantile_r7([1.0, 2.0, 3.0], 1.0) == 3.0
    assert quantile_r7([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0
    assert quantile_r7([10.0, 20.0], 0.95) == pytest.approx(19.5, rel=1e-12)


def test_plain_hour_values():
    result = computed(columns(30))
    last = result.loss[-1]
    assert (last.lth, last.sth) == (1_000.0, 2_500.0)
    assert last.lth + last.sth == PLAIN_LOSS
    assert result.share[-1].value == pytest.approx(PLAIN_SHARE, rel=1e-12)
    assert result.supply[-1].value == pytest.approx(PLAIN_SUPPLY, rel=1e-12)
    for levels in (result.loss_levels, result.share_levels, result.supply_levels):
        assert levels.n == 29


def test_constants_match_the_original_page():
    assert LOOKBACK == 2600
    assert WINDOW == timedelta(hours=720)


def test_payload_stored_before_o3_marks_still_loads():
    stored = computed(columns(5)).model_dump(mode="json")
    for name in ("loss", "share", "supply", "price"):
        for point in stored[name]:
            del point["no_block"], point["gap"]
    old = Pressure.model_validate(stored)
    assert old == computed(columns(5))
    assert not any(flagged(old))


def test_o3_keeps_every_row_of_the_parity_input():
    rows = fixture_rows(datetime(2026, 10, 16, 8, tzinfo=UTC))
    v1 = seller_pressure(rows, rules=V1)
    result = seller_pressure(rows, rules=O3)
    assert v1 is not None and result is not None
    # The 11 hours without a block and the 11 after them are kept: every hour but the first.
    assert result.kept == 2598
    assert (result.loss_levels.n, result.share_levels.n, result.supply_levels.n) == (720, 718, 720)
    assert (result.last_at, result.latest_at, result.xgap, result.qc) == (
        v1.last_at,
        v1.latest_at,
        0,
        [],
    )
    no_block = [p.at for p in result.loss if p.no_block]
    assert len(no_block) == 11
    # None of them opens the window, and two fall in the 720 hours of the levels.
    assert result.loss[0].at < no_block[0]
    window = [at for at in no_block if at > result.last_at - WINDOW]
    assert window == [
        datetime(2026, 10, 3, 14, tzinfo=UTC),
        datetime(2026, 10, 3, 18, tzinfo=UTC),
    ]

    raw = {name: dict(points) for name, points in rows.items()}
    loss = {p.at: p for p in result.loss}
    share = {p.at: p for p in result.share}
    supply = {p.at: p for p in result.supply}
    price = {p.at: p for p in result.price}
    supply_of = {p.at: p.value for p in v1.supply}
    for at_ in no_block:
        before = at_ - HOUR
        assert all(raw[name][at_] is None for name in HOUR1_SERIES)
        # Flows are 0; the share has no denominator; supply and price carry the hour before over.
        assert (loss[at_].lth, loss[at_].sth, loss[at_].gap) == (0.0, 0.0, False)
        assert (share[at_].value, share[at_].no_block) == (None, True)
        assert (supply[at_].value, supply[at_].no_block) == (supply_of[before], True)
        assert (price[at_].value, price[at_].no_block) == (raw[PRICE][before], True)
        # The next hour differs from the carried values, so it holds only its own flows.
        after = loss[at_ + HOUR]
        lth_loss = raw[LTH_LOSS][at_ + HOUR] - raw[LTH_LOSS][before]  # type: ignore[operator]
        assert after.lth == math.floor(max(0.0, lth_loss) / 100 + 0.5) * 100
        assert not after.no_block and not after.gap
    # What v1 kept reads the same, and the only marks are the hours without a block.
    for name in ("loss", "share", "supply", "price"):
        by_time = {p.at: p for p in getattr(result, name)}
        assert all(by_time[p.at] == p for p in getattr(v1, name))
    assert {at_ for _, at_ in flagged(result)} == set(no_block)


def test_o3_hour_without_a_block_keeps_its_row_and_the_next():
    cols = columns(12)
    # Hour 4 has its own supply and price, which hour 5 carries over.
    cols[STH_IN_LOSS][4] = 90.0
    no_block_hour(cols, 5)
    v1, result = computed(cols), computed(cols, O3)
    assert (v1.kept, result.kept) == (11 - 2, 11)
    loss = {p.at: p for p in result.loss}
    assert loss[at(5)] == PressureLossPoint(at=at(5), lth=0.0, sth=0.0, no_block=True)
    # The next hour reads its differences as usual: a plain hour.
    assert (loss[at(6)].lth, loss[at(6)].sth, loss[at(6)].no_block) == (1_000.0, 2_500.0, False)
    assert {p.at: p.value for p in result.supply}[at(5)] == pytest.approx(80 / 110, rel=1e-12)
    assert {p.at: p.value for p in result.price}[at(5)] == 100_004.0
    assert [p.value for p in result.share if p.at == at(5)] == [None]
    assert flagged(result) == [(name, at(5)) for name in ("loss", "share", "supply", "price")]
    # Chart 1 counts the 0; chart 2 has no denominator there.
    assert (result.loss_levels.n, result.share_levels.n, result.supply_levels.n) == (11, 10, 11)
    assert result.xgap == 0
    assert result.qc == []


def test_o3_carries_over_hours_without_a_block_in_a_row():
    cols = columns(12)
    no_block_hour(cols, 5)
    no_block_hour(cols, 6)
    result = computed(cols, O3)
    assert result.kept == 11
    assert [p.at for p in result.loss if p.no_block] == [at(5), at(6)]
    assert {p.at: (p.lth, p.sth) for p in result.loss}[at(7)] == (1_000.0, 2_500.0)
    assert {p.at: p.value for p in result.price}[at(6)] == 100_004.0
    # v1 drops three rows here, which leaves a step of four hours.
    assert computed(cols).qc == ["hour_gap"]
    assert result.qc == []


def test_o3_partial_gap_nulls_the_legs_that_need_the_series():
    cols = columns(12)
    # STH loss is null in hour 5, so hours 5 and 6 cannot have an STH loss leg.
    cols[STH_LOSS][5] = None
    # LTH profit is null in hour 8: chart 1 does not need it, chart 2 does.
    cols[LTH_PROFIT][8] = None
    v1, result = computed(cols), computed(cols, O3)
    assert (v1.kept, result.kept) == (11 - 4, 11)
    loss = {p.at: p for p in result.loss}
    share = {p.at: p for p in result.share}
    for hour in (5, 6):
        assert (loss[at(hour)].lth, loss[at(hour)].sth, loss[at(hour)].gap) == (1_000.0, None, True)
        assert (share[at(hour)].value, share[at(hour)].gap) == (None, True)
    for hour in (8, 9):
        point = loss[at(hour)]
        assert (point.lth, point.sth, point.gap) == (1_000.0, 2_500.0, False)
        assert (share[at(hour)].value, share[at(hour)].gap) == (None, True)
    assert sorted(flagged(result)) == sorted(
        [("loss", at(5)), ("loss", at(6))] + [("share", at(h)) for h in (5, 6, 8, 9)]
    )
    # Chart 1's total is null where one leg is, and null values stay out of the levels.
    assert result.loss_levels.n == 11 - 2
    assert result.share_levels.n == 11 - 4
    assert result.supply_levels.n == 11
    assert result.loss_levels.p95 == PLAIN_LOSS
    assert result.xgap == 0
    assert result.qc == []


def test_o3_supply_gap_nulls_only_that_supply_point():
    cols = columns(12)
    cols[STH_IN_LOSS][5] = None
    cols[YOUNG_IN_PROFIT][8] = None
    result = computed(cols, O3)
    supply = {p.at: p for p in result.supply}
    assert (supply[at(5)].value, supply[at(5)].gap) == (None, True)
    assert (supply[at(8)].value, supply[at(8)].gap) == (None, True)
    # Supply is read at its own row, so the next hour is whole.
    assert supply[at(6)].value == pytest.approx(PLAIN_SUPPLY, rel=1e-12)
    assert sorted(flagged(result)) == [("supply", at(5)), ("supply", at(8))]
    assert result.supply_levels.n == 11 - 2
    assert result.qc == ["sth_supply"]


def test_o3_keeps_the_v1_handling_of_an_under_1h_null():
    cols = columns(10)
    cols[YOUNG_LOSS][5] = None
    v1, result = computed(cols), computed(cols, O3)
    # The row is kept, xgap counts it and the hour after, and nothing is taken out: as in v1.
    assert (result.kept, result.xgap, result.qc) == (9, 2, ["intraday_legs"])
    assert {p.at: p.sth for p in result.loss}[at(5)] == 3_000.0
    assert (result.loss, result.share, result.supply, result.price) == (
        v1.loss,
        v1.share,
        v1.supply,
        v1.price,
    )


@pytest.mark.parametrize("hours", [1, 2])
def test_o3_drops_hours_without_a_block_that_open_the_window(hours: int):
    # The window holds the last LOOKBACK hours, so with 5 more it opens at hour 5.
    cols = columns(LOOKBACK + 5)
    for hour in range(5, 5 + hours):
        no_block_hour(cols, hour)
    result = computed(cols, O3)
    # Nothing can be carried over into the window: the first hour with a block opens it and only
    # serves as the previous row.
    assert result.loss[0].at == at(5 + hours + 1)
    assert result.kept == LOOKBACK - hours - 1
    assert flagged(result) == []
    assert result.loss[0] == PressureLossPoint(at=at(5 + hours + 1), lth=1_000.0, sth=2_500.0)


def test_o3_keeps_a_row_whose_only_gap_is_the_price():
    cols = columns(8)
    cols[PRICE][4] = None
    v1, result = computed(cols), computed(cols, O3)
    assert (v1.kept, result.kept) == (6, 7)
    assert flagged(result) == [("price", at(4))]
    price = {p.at: p for p in result.price}
    assert (price[at(4)].value, price[at(4)].gap) == (None, True)
    # The rest of the row reads as usual.
    loss = {p.at: p for p in result.loss}
    assert (loss[at(4)].lth, loss[at(4)].sth) == (1_000.0, 2_500.0)
    assert {p.at: p.value for p in result.share}[at(4)] == pytest.approx(PLAIN_SHARE, rel=1e-12)
    assert {p.at: p.value for p in result.supply}[at(4)] == pytest.approx(PLAIN_SUPPLY, rel=1e-12)


def test_o3_keeps_the_newest_row_without_a_price_as_the_newest_hour():
    cols = columns(10)
    cols[PRICE][9] = None
    result = computed(cols, O3)
    assert result.last_at == result.latest_at == at(9)
    # No price at all still keeps the rows.
    unpriced = columns(10)
    unpriced[PRICE] = [None] * 10
    bare = computed(unpriced, O3)
    assert (bare.kept, bare.latest_at) == (9, at(9))
    assert all(p.value is None and p.gap for p in bare.price)


def test_o3_qc_hour_gap_fails_on_any_missing_hour():
    # With no row dropped, an hour without a block leaves every step at one hour.
    blocks = columns(12)
    no_block_hour(blocks, 5)
    assert computed(blocks, O3).qc == []
    # An hour BRK does not have at all leaves a two-hour step, which v1's three hours let pass.
    rows = rows_of(columns(12))
    rows = {name: [point for point in points if point[0] != at(5)] for name, points in rows.items()}
    v1 = seller_pressure(rows, rules=V1)
    result = seller_pressure(rows, rules=O3)
    assert v1 is not None and result is not None
    assert v1.qc == []
    # The hour after has nothing to difference against, so its flows are a gap; its under-1h legs
    # are unknown too, which xgap counts as on any kept row.
    assert result.qc == ["hour_gap", "intraday_legs"]
    assert result.xgap == 1
    loss = {p.at: p for p in result.loss}
    assert (loss[at(6)].lth, loss[at(6)].sth, loss[at(6)].gap) == (None, None, True)
    assert {p.at: p.value for p in result.price}[at(6)] == 100_006.0


def test_o3_hour_without_a_block_after_a_missing_hour_carries_nothing():
    rows = rows_of(columns(12))
    rows = {name: [point for point in points if point[0] != at(4)] for name, points in rows.items()}
    for name in HOUR1_SERIES:
        rows[name] = [(time, None if time == at(5) else value) for time, value in rows[name]]
    result = seller_pressure(rows, rules=O3)
    assert result is not None
    loss = {p.at: p for p in result.loss}
    # Still no block, so no flows; but its levels and the next hour's flows are unknown.
    assert loss[at(5)] == PressureLossPoint(at=at(5), lth=0.0, sth=0.0, no_block=True)
    assert {p.at: (p.value, p.gap) for p in result.price}[at(5)] == (None, True)
    assert (loss[at(6)].lth, loss[at(6)].sth, loss[at(6)].gap) == (None, None, True)
