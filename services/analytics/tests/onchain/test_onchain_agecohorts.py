import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wheelhouse_service.onchain.agecohorts import BANDS, INPUTS, AgeCohorts, age_cohorts
from wheelhouse_service.onchain.brk import (
    AGE_COHORTS,
    AGE_ONLY_SERIES,
    AGE_SERIES,
    AGE_SUFFIXES,
    EPOCH,
    HOUR1_SERIES,
    SELL_SIDE_SERIES,
    SeriesData,
)
from wheelhouse_service.onchain.pressure import V1_LOOKBACK

HOUR = timedelta(hours=1)
BASE = datetime(2026, 1, 1, tzinfo=UTC)
GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-19T1453Z"
Rows = dict[str, list[tuple[datetime, float | None]]]
Columns = dict[str, list[float | None]]

PRICE = "price_close"
PNL, PNL_LOSS, VOLB, VOLB_LOSS, VOLU, VOLU_LOSS = AGE_SUFFIXES
# What a cumulative of each suffix adds per hour, times the cohort's place in AGE_COHORTS plus one.
UNIT = {PNL: 1_000.0, PNL_LOSS: 500.0, VOLB: 1.0, VOLB_LOSS: 0.5, VOLU: 1e5, VOLU_LOSS: 5e4}
MEASURE_OF = {
    PNL: ("pnl", "profit"),
    PNL_LOSS: ("pnl", "loss"),
    VOLB: ("volb", "profit"),
    VOLB_LOSS: ("volb", "loss"),
    VOLU: ("volu", "profit"),
    VOLU_LOSS: ("volu", "loss"),
}


def columns(count: int) -> Columns:
    """`count` hourly values per series: every cumulative grows by its step, the price by 1."""
    out: Columns = {PRICE: [100_000.0 + h for h in range(count)]}
    for place, cohort in enumerate(AGE_COHORTS):
        for suffix, unit in UNIT.items():
            out[f"{cohort}{suffix}"] = [unit * (place + 1) * (h + 1) for h in range(count)]
    return out


def rows_of(cols: Columns, start: datetime = BASE) -> Rows:
    return {name: [(start + HOUR * h, v) for h, v in enumerate(vs)] for name, vs in cols.items()}


def at(hour: int) -> datetime:
    return BASE + HOUR * hour


def computed(cols: Columns) -> AgeCohorts:
    result = age_cohorts(rows_of(cols))
    assert result is not None
    return result


def band(result: AgeCohorts, hour: int, suffix: str, index: int) -> float:
    """One band's value of the kept row at `hour`."""
    measure, side = MEASURE_OF[suffix]
    values: list[list[float]] = getattr(getattr(result, measure), side)
    return values[index][result.at.index(at(hour))]


def golden_rows() -> Rows:
    rows: Rows = {}
    for name in INPUTS:
        series = SeriesData.model_validate_json((GOLDEN / f"hour1_{name}.json").read_text())
        rows[name] = [(EPOCH + HOUR * (series.start + k), v) for k, v in enumerate(series.data)]
    return rows


def test_inputs_are_the_price_and_six_cumulatives_of_every_age_cohort():
    assert len(AGE_COHORTS) == 23
    assert len(AGE_SERIES) == len(set(AGE_SERIES)) == 138
    assert INPUTS == (PRICE, *AGE_SERIES)
    # The two youngest cohorts are fetched already for the sell side; the rest are the age stage's.
    shared = set(AGE_SERIES) & {*HOUR1_SERIES, *SELL_SIDE_SERIES}
    assert {name.split("_old_")[0] for name in shared} == {"utxos_under_1h", "utxos_1h_to_1d"}
    assert len(shared) == 12
    assert set(AGE_ONLY_SERIES) == set(AGE_SERIES) - shared


def test_the_twelve_bands_take_every_cohort_once_in_age_order():
    assert [name for name, _ in BANDS] == [
        "<1d",
        "1d–1w",
        "1w–1m",
        "1m–3m",
        "3m–6m",
        "6m–1y",
        "1y–2y",
        "2y–3y",
        "3y–5y",
        "5y–7y",
        "7y–10y",
        "10y+",
    ]
    assert [cohort for _, cohorts in BANDS for cohort in cohorts] == list(AGE_COHORTS)


def test_matches_the_original_page_loader_row_for_row():
    """The page's AGEPL, from its own loader code run on the same fetch."""
    expected = json.loads((GOLDEN / "expected_age_cohorts.json").read_text())
    result = age_cohorts(golden_rows())
    assert result is not None
    t0 = datetime.fromtimestamp(expected["t0"], UTC)
    assert result.at == [t0 + HOUR * h for h in expected["H"]]
    assert len(result.at) == 395
    assert result.price == expected["PX"]
    assert expected["groups"] == [name for name, _ in BANDS]
    # The page stores whole $100 and $1000 and multiplies them back when it draws.
    for measure, (profit, loss, mult) in {
        "pnl": ("P", "L", 100),
        "volb": ("bP", "bL", 1),
        "volu": ("uP", "uL", 1000),
    }.items():
        bands = getattr(result, measure)
        assert bands.profit == [[v * mult for v in values] for values in expected[profit]]
        assert bands.loss == [[v * mult for v in values] for values in expected[loss]]
    assert result.last_at == result.latest_at == datetime(2026, 10, 19, 14, tzinfo=UTC)
    assert result.rules == []


def test_each_band_adds_up_its_cohorts():
    result = computed(columns(4))
    # 3m-6m is cohorts 6, 7 and 8, the 7th to 9th: (7 + 8 + 9) x the unit.
    assert band(result, 2, PNL, 4) == 24_000.0
    assert band(result, 2, PNL_LOSS, 4) == 12_000.0
    assert band(result, 2, VOLB, 4) == 24.0
    assert band(result, 2, VOLU_LOSS, 4) == 1.2e6
    # 10y+ is the last three cohorts: 21 + 22 + 23.
    assert band(result, 2, PNL, 11) == 66_000.0
    assert band(result, 2, VOLB_LOSS, 0) == 1.5


def test_each_cohort_is_clamped_before_its_band_adds_them_up():
    cols = columns(4)
    young = f"utxos_under_1h_old{PNL}"
    # The under-1h cumulative falls by 5,000 in hour 2; 1h-1d still adds 2,000.
    cols[young] = [1_000.0, 2_000.0, -3_000.0, -2_000.0]
    result = computed(cols)
    assert band(result, 2, PNL, 0) == 2_000.0
    assert band(result, 3, PNL, 0) == 3_000.0


@pytest.mark.parametrize(
    "name",
    [
        f"utxos_under_1h_old{PNL}",
        f"utxos_2y_to_3y_old{VOLB_LOSS}",
        f"utxos_over_15y_old{VOLU}",
    ],
)
def test_any_unknown_cumulative_drops_the_hour_and_the_next(name: str):
    cols = columns(6)
    cols[name][2] = None
    assert computed(cols).at == [at(1), at(4), at(5)]


def test_an_unknown_price_drops_only_its_hour():
    cols = columns(5)
    cols[PRICE][2] = None
    assert computed(cols).at == [at(1), at(3), at(4)]


@pytest.mark.parametrize(
    ("suffix", "step", "expected"),
    [
        # Two cohorts of 40 each would round to nothing apiece; the band rounds their sum.
        (PNL, 40.0, 100.0),
        (VOLU, 400.0, 1_000.0),
        (VOLB, 0.04, 0.1),
    ],
)
def test_a_band_is_rounded_once_after_its_cohorts_are_added(
    suffix: str, step: float, expected: float
):
    cols = columns(4)
    # 1m-3m is the band of 1m-2m and 2m-3m.
    for cohort in ("utxos_1m_to_2m_old", "utxos_2m_to_3m_old"):
        cols[f"{cohort}{suffix}"] = [step * h for h in range(4)]
    assert band(computed(cols), 2, suffix, 3) == expected


@pytest.mark.parametrize(
    ("suffix", "step", "expected"),
    [
        (PNL, 150.0, 200.0),
        (PNL, 149.0, 100.0),
        (VOLU, 1_500.0, 2_000.0),
        (VOLB, 0.25, 0.3),
        # 0.15 is a little under 0.15 in binary, so toFixed(1) gives 0.1.
        (VOLB, 0.15, 0.1),
    ],
)
def test_bands_are_rounded_half_up_to_their_quantum(suffix: str, step: float, expected: float):
    cols = columns(4)
    cols[f"utxos_2y_to_3y_old{suffix}"] = [step * h for h in range(4)]
    assert band(computed(cols), 2, suffix, 7) == expected


def test_the_price_is_kept_to_a_tenth_half_up():
    cols = columns(4)
    cols[PRICE] = [100_000.25, 100_000.25, 100_000.25, 100_000.75]
    assert computed(cols).price == [100_000.3, 100_000.3, 100_000.8]


def test_only_the_last_2600_hours_count():
    result = computed(columns(V1_LOOKBACK + 10))
    # The oldest hour of the lookback only serves as the previous one.
    assert result.at[0] == at(10 + 1)
    assert result.at[-1] == at(V1_LOOKBACK + 9)
    assert len(result.at) == V1_LOOKBACK - 1


def test_the_window_ends_at_the_newest_price_hour():
    rows = rows_of(columns(V1_LOOKBACK + 10))
    # The age stage fetched one hour more than the first stage, price included, had.
    rows[PRICE] = rows[PRICE][:-1]
    result = age_cohorts(rows)
    assert result is not None
    assert result.at[0] == at(10)
    assert result.at[-1] == at(V1_LOOKBACK + 8)


def test_series_are_aligned_by_time_not_by_position():
    cols = columns(5)
    rows = rows_of(cols)
    # One series starts an hour late: its hour 1 has no hour before it, so hour 1 is dropped.
    late = f"utxos_5y_to_6y_old{VOLU_LOSS}"
    rows[late] = rows[late][1:]
    result = age_cohorts(rows)
    assert result is not None
    assert result.at == [at(2), at(3), at(4)]
    # 5y-7y is cohorts 17 and 18: (17 + 18) x 50,000.
    assert band(result, 3, VOLU_LOSS, 9) == 1.75e6


def test_none_when_no_hour_can_be_kept():
    cols = columns(3)
    cols[PRICE] = [None, None, None]
    assert age_cohorts(rows_of(cols)) is None


def test_latest_at_is_the_newest_priced_hour_even_when_dropped():
    cols = columns(5)
    cols[f"utxos_6m_to_9m_old{PNL_LOSS}"][4] = None
    result = computed(cols)
    assert result.last_at == at(3)
    assert result.latest_at == at(4)
