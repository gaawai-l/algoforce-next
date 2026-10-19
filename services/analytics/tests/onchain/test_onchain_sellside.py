import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from onchain_fixture import load_series

from wheelhouse_service.onchain.brk import EPOCH, HOUR1_SERIES, SELL_SIDE_SERIES, SeriesData
from wheelhouse_service.onchain.pressure import V1_LOOKBACK
from wheelhouse_service.onchain.sellside import INPUTS, SellSide, SellSideLegs, sell_side

HOUR = timedelta(hours=1)
BASE = datetime(2026, 1, 1, tzinfo=UTC)
GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-19T0530Z"
Rows = dict[str, list[tuple[datetime, float | None]]]
Columns = dict[str, list[float | None]]

PRICE = "price_close"
YOUNG = "utxos_under_1h_old"
DAY = "utxos_1h_to_1d_old"
PNL = ("_realized_profit_cumulative", "_realized_loss_cumulative")
VOLB = ("_transfer_volume_in_profit_cumulative", "_transfer_volume_in_loss_cumulative")
VOLU = tuple(f"{suffix}_usd" for suffix in VOLB)
# What each cumulative series adds per hour. Under 1h and 1h-1d take out of the STH legs:
# pnl profit 5000 - 1000 = 4000 under x1 and 4000 - 400 = 3600 under x24.
STEPS: dict[str, float] = {
    **{f"lth{PNL[0]}": 2_000.0, f"lth{PNL[1]}": 1_000.0},
    **{f"sth{PNL[0]}": 5_000.0, f"sth{PNL[1]}": 3_000.0},
    **{f"lth{VOLB[0]}": 20.0, f"lth{VOLB[1]}": 10.0},
    **{f"sth{VOLB[0]}": 50.0, f"sth{VOLB[1]}": 30.0},
    **{f"lth{VOLU[0]}": 2e6, f"lth{VOLU[1]}": 1e6},
    **{f"sth{VOLU[0]}": 5e6, f"sth{VOLU[1]}": 3e6},
    **{f"{YOUNG}{PNL[0]}": 1_000.0, f"{YOUNG}{PNL[1]}": 500.0},
    **{f"{YOUNG}{VOLB[0]}": 10.0, f"{YOUNG}{VOLB[1]}": 5.0},
    **{f"{YOUNG}{VOLU[0]}": 1e6, f"{YOUNG}{VOLU[1]}": 5e5},
    **{f"{DAY}{PNL[0]}": 400.0, f"{DAY}{PNL[1]}": 200.0},
    **{f"{DAY}{VOLB[0]}": 4.0, f"{DAY}{VOLB[1]}": 2.0},
    **{f"{DAY}{VOLU[0]}": 4e5, f"{DAY}{VOLU[1]}": 2e5},
}
PLAIN = {
    "pnl": SellSideLegs(
        lth_profit=[2_000.0],
        lth_loss=[1_000.0],
        sth_profit=[5_000.0],
        sth_loss=[3_000.0],
        sth_profit_x1=[4_000.0],
        sth_loss_x1=[2_500.0],
        sth_profit_x24=[3_600.0],
        sth_loss_x24=[2_300.0],
    ),
    "volb": SellSideLegs(
        lth_profit=[20.0],
        lth_loss=[10.0],
        sth_profit=[50.0],
        sth_loss=[30.0],
        sth_profit_x1=[40.0],
        sth_loss_x1=[25.0],
        sth_profit_x24=[36.0],
        sth_loss_x24=[23.0],
    ),
    "volu": SellSideLegs(
        lth_profit=[2e6],
        lth_loss=[1e6],
        sth_profit=[5e6],
        sth_loss=[3e6],
        sth_profit_x1=[4e6],
        sth_loss_x1=[2.5e6],
        sth_profit_x24=[3.6e6],
        sth_loss_x24=[2.3e6],
    ),
}


def columns(count: int) -> Columns:
    """`count` hourly values per series: every cumulative grows by its step, the price by 1."""
    out: Columns = {PRICE: [100_000.0 + h for h in range(count)]}
    for name, step in STEPS.items():
        out[name] = [step * (h + 1) for h in range(count)]
    return out


def rows_of(cols: Columns, start: datetime = BASE) -> Rows:
    return {name: [(start + HOUR * h, v) for h, v in enumerate(vs)] for name, vs in cols.items()}


def at(hour: int) -> datetime:
    return BASE + HOUR * hour


def computed(cols: Columns) -> SellSide:
    result = sell_side(rows_of(cols))
    assert result is not None
    return result


def hour_of(result: SellSide, hour: int) -> dict[str, SellSideLegs]:
    """Each measure's legs of the kept row at `hour`, as one-value legs."""
    index = result.at.index(at(hour))
    return {
        measure: SellSideLegs.model_validate(
            {leg: [values[index]] for leg, values in getattr(result, measure)}
        )
        for measure in ("pnl", "volb", "volu")
    }


def fixture_rows(directory: Path | None, last: datetime | None = None) -> Rows:
    rows: Rows = {}
    for name in INPUTS:
        if directory is None:
            series = load_series(name, "hour1")
        else:
            payload = json.loads((directory / f"hour1_{name}.json").read_text())
            series = SeriesData.model_validate(payload)
        stamped = [(EPOCH + HOUR * (series.start + k), v) for k, v in enumerate(series.data)]
        rows[name] = [(time, v) for time, v in stamped if last is None or time <= last]
    return rows


def test_inputs_are_the_pressure_series_it_needs_and_the_sell_side_series():
    assert len(INPUTS) == 25
    assert set(INPUTS) - set(HOUR1_SERIES) == set(SELL_SIDE_SERIES)
    assert len(SELL_SIDE_SERIES) == 18
    assert not set(SELL_SIDE_SERIES) & set(HOUR1_SERIES)


def test_matches_the_original_page_data_row_for_row():
    """The page's DATA, re-computed from the same fetch by a port that matched it cell for cell."""
    expected = json.loads((GOLDEN / "expected_sell_side.json").read_text())
    result = sell_side(fixture_rows(GOLDEN))
    assert result is not None
    assert [a.isoformat().replace("+00:00", "Z") for a in result.at] == expected["at"]
    assert result.xgap == expected["xgap"] == 0
    assert result.qc == []
    assert result.last_at == datetime(2026, 10, 19, 5, tzinfo=UTC)
    # The page stores $100 and $1000 units and BTC to 0.1; the payload holds the same values.
    units = {"pnl": ("", 100), "volb": ("b", 1), "volu": ("u", 1000)}
    keys = {
        "lth_profit": "LP",
        "lth_loss": "LL",
        "sth_profit": "SP",
        "sth_loss": "SL",
        "sth_profit_x1": "SPx1",
        "sth_loss_x1": "SLx1",
        "sth_profit_x24": "SPx24",
        "sth_loss_x24": "SLx24",
    }
    for measure, (prefix, unit) in units.items():
        legs = getattr(result, measure)
        for leg, key in keys.items():
            got = [value / unit for value in getattr(legs, leg)]
            assert got == expected[prefix + key], (measure, leg)
    assert result.price == expected["PX"]


def test_pnl_means_match_the_original_page_at_0800_on_10_16():
    """NOTES' 10-16 08:00 reading: 24-hour means of the legs, from the 10-16 capture."""
    result = sell_side(fixture_rows(None, datetime(2026, 10, 16, 8, tzinfo=UTC)))
    assert result is not None
    assert result.last_at == datetime(2026, 10, 16, 8, tzinfo=UTC)

    def mean(leg: str) -> float:
        return sum(getattr(result.pnl, leg)[-24:]) / 24

    assert mean("lth_profit") == pytest.approx(8_587_654.1666666, rel=1e-12)
    assert mean("lth_loss") == pytest.approx(7_196_520.8333333, rel=1e-12)
    assert mean("sth_profit_x24") == pytest.approx(6_865_541.6666666, rel=1e-12)
    assert mean("sth_loss_x24") == pytest.approx(7_778_608.3333333, rel=1e-12)
    assert mean("sth_profit_x1") == pytest.approx(10_696_808.333333, rel=1e-12)
    assert mean("sth_loss_x1") == pytest.approx(9_058_400.0, rel=1e-12)
    assert mean("sth_profit") == pytest.approx(11_211_950.0, rel=1e-12)
    assert mean("sth_loss") == pytest.approx(9_433_170.8333333, rel=1e-12)


def test_a_plain_hour_takes_the_young_cohorts_out_of_the_sth_legs():
    result = computed(columns(4))
    assert result.at == [at(1), at(2), at(3)]
    assert hour_of(result, 2) == PLAIN
    assert result.price == [100_001.0, 100_002.0, 100_003.0]
    assert result.xgap == 0


def test_a_negative_step_is_clamped_to_zero():
    cols = columns(4)
    cols[f"lth{PNL[0]}"][2] = 0.0
    result = computed(cols)
    assert hour_of(result, 2)["pnl"].lth_profit == [0.0]


def test_each_cohort_step_is_clamped_before_the_two_are_summed():
    cols = columns(4)
    # Under 1h falls by 600 in hour 2: alone it would add 400 to the STH profit leg.
    cols[f"{YOUNG}{PNL[0]}"][2] = cols[f"{YOUNG}{PNL[0]}"][1] - 600.0
    legs = hour_of(computed(cols), 2)["pnl"]
    assert legs.sth_profit_x1 == [5_000.0]
    assert legs.sth_profit_x24 == [4_600.0]


def test_one_unknown_cohort_value_takes_nothing_out_that_hour_and_the_next():
    cols = columns(5)
    cols[f"{DAY}{VOLU[1]}"][2] = None
    result = computed(cols)
    # Every measure keeps its whole STH legs in the two hours that read the null.
    for hour in (2, 3):
        for measure, legs in hour_of(result, hour).items():
            assert legs.sth_profit_x1 == legs.sth_profit_x24 == legs.sth_profit, measure
            assert legs.sth_loss_x1 == legs.sth_loss_x24 == legs.sth_loss, measure
    assert hour_of(result, 4) == PLAIN
    assert result.xgap == 2
    assert result.qc == ["intraday_legs"]


@pytest.mark.parametrize(
    "name", [f"lth{VOLU[1]}", f"sth{VOLB[0]}", f"lth{PNL[0]}"], ids=["volu", "volb", "pnl"]
)
def test_any_unknown_main_leg_drops_the_hour_and_the_next(name: str):
    cols = columns(6)
    cols[name][2] = None
    assert computed(cols).at == [at(1), at(4), at(5)]


def test_an_unknown_price_drops_only_its_hour():
    cols = columns(5)
    cols[PRICE][2] = None
    assert computed(cols).at == [at(1), at(3), at(4)]


def test_the_residual_is_rounded_once():
    cols = columns(4)
    # $1060 less $40 is $1020, $1000 once rounded; rounding each first would give $1100 - $0.
    cols[f"sth{PNL[0]}"] = [1_060.0 * (h + 1) for h in range(4)]
    cols[f"{YOUNG}{PNL[0]}"] = [40.0 * (h + 1) for h in range(4)]
    assert hour_of(computed(cols), 2)["pnl"].sth_profit_x1 == [1_000.0]


@pytest.mark.parametrize(
    ("measure", "name", "step", "expected"),
    [
        ("pnl", f"lth{PNL[0]}", 150.0, 200.0),
        ("pnl", f"lth{PNL[0]}", 149.0, 100.0),
        ("volu", f"lth{VOLU[0]}", 1_500.0, 2_000.0),
        ("volu", f"lth{VOLU[0]}", 1_499.0, 1_000.0),
        ("volb", f"lth{VOLB[0]}", 0.25, 0.3),
        ("volb", f"lth{VOLB[0]}", 0.125, 0.1),
        # Below the tie in binary, so down, as toFixed(1) does; a decimal reading would go up.
        ("volb", f"lth{VOLB[0]}", 0.15, 0.1),
        ("volb", f"lth{VOLB[0]}", 1.45, 1.4),
        ("volb", f"lth{VOLB[0]}", 0.75, 0.8),
    ],
)
def test_legs_are_rounded_half_up_to_their_quantum(
    measure: str, name: str, step: float, expected: float
):
    cols = columns(4)
    cols[name] = [step * h for h in range(4)]
    assert hour_of(computed(cols), 2)[measure].lth_profit == [expected]


def test_only_the_last_2600_hours_count():
    cols = columns(V1_LOOKBACK + 10)
    result = computed(cols)
    # The oldest hour of the lookback only serves as the previous one.
    assert result.at[0] == at(10 + 1)
    assert result.at[-1] == at(V1_LOOKBACK + 9)
    assert len(result.at) == V1_LOOKBACK - 1


def test_series_are_aligned_by_time_not_by_position():
    cols = columns(5)
    rows = rows_of(cols)
    # One series starts an hour late: its hour 1 has no hour before it, so hour 1 is dropped.
    rows[f"sth{VOLB[1]}"] = rows[f"sth{VOLB[1]}"][1:]
    result = sell_side(rows)
    assert result is not None
    assert result.at == [at(2), at(3), at(4)]
    assert hour_of(result, 3) == PLAIN


def test_none_when_no_hour_can_be_kept():
    cols = columns(3)
    cols[PRICE] = [None, None, None]
    assert sell_side(rows_of(cols)) is None


def test_latest_at_is_the_newest_priced_hour_even_when_dropped():
    cols = columns(5)
    cols[f"lth{VOLU[0]}"][4] = None
    result = computed(cols)
    assert result.last_at == at(3)
    assert result.latest_at == at(4)
