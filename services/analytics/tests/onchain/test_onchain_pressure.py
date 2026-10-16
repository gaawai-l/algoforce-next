from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from onchain_fixture import load_series

from wheelhouse_service.onchain.brk import EPOCH, HOUR1_SERIES
from wheelhouse_service.onchain.pressure import (
    LOOKBACK,
    WINDOW,
    Pressure,
    quantile_r7,
    seller_pressure,
)

HOUR = timedelta(hours=1)
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


def computed(cols: Columns) -> Pressure:
    result = seller_pressure(rows_of(cols))
    assert result is not None
    return result


def fixture_rows(last: datetime) -> Rows:
    """Every captured hour1 row up to and including `last`."""
    rows: Rows = {}
    for name in HOUR1_SERIES:
        series = load_series(name, "hour1")
        stamped = [(EPOCH + HOUR * (series.start + k), v) for k, v in enumerate(series.data)]
        rows[name] = [(time, v) for time, v in stamped if time <= last]
    return rows


def test_parity_with_original_page_at_0800():
    result = seller_pressure(fixture_rows(datetime(2026, 10, 16, 8, tzinfo=UTC)))
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


def test_lookback_ignores_rows_beyond_2600():
    full = fixture_rows(datetime(2026, 10, 16, 9, tzinfo=UTC))
    assert all(len(points) == LOOKBACK for points in full.values())
    baseline = seller_pressure(full)
    assert baseline is not None
    first = full[PRICE][0][0]
    # 500 older hours whose cumulative values would turn the oldest kept row into a huge loss if the
    # window reached back to them, and whose supply and price would add rows and shift the levels.
    older = {
        name: [(first - HOUR * k, 1.0 if name != PRICE else 5.0) for k in range(500, 0, -1)]
        for name in HOUR1_SERIES
    }
    extended = {name: older[name] + full[name] for name in HOUR1_SERIES}
    assert seller_pressure(extended) == baseline


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
    assert seller_pressure(short) == computed(nulled)


def test_row_missing_from_one_series_counts_as_null():
    cols = columns(10)
    gapped = rows_of(cols)
    gapped[STH_LOSS] = [point for point in gapped[STH_LOSS] if point[0] != at(4)]
    nulled = columns(10)
    nulled[STH_LOSS][4] = None
    assert seller_pressure(gapped) == computed(nulled)
    assert computed(nulled).kept == 9 - 2


def test_empty_when_nothing_can_be_kept():
    assert seller_pressure({name: [] for name in HOUR1_SERIES}) is None
    cols = columns(5)
    for hour in range(5):
        cols[PRICE][hour] = None
    assert seller_pressure(rows_of(cols)) is None
    assert seller_pressure(rows_of(columns(1))) is None


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
