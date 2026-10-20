from datetime import datetime, timedelta

import pytest
from sizes_fixture import SE, golden_rows, page_pnl, page_size

from wheelhouse_service.onchain.brk import (
    MAX_SERIES_CHARS,
    SIZE_BANDS,
    SIZE_SERIES,
    SIZE_SUFFIXES,
)
from wheelhouse_service.onchain.sizes import SizeCohorts, size_cohorts

HOUR = timedelta(hours=1)
Rows = dict[str, list[tuple[datetime, float | None]]]
SUPPLY, PROFIT, LOSS, CAP = SIZE_SUFFIXES
# The band each of the null tests below hits: 1-10 BTC.
BAND_6 = SIZE_BANDS[6]


def flat_rows(value: float = 1.0) -> Rows:
    """Every size series at `value` in each hour from SE - 2160h through SE."""
    hours = [SE - HOUR * n for n in range(2160, -1, -1)]
    return {name: [(at, value) for at in hours] for name in SIZE_SERIES}


def with_value(rows: Rows, name: str, at: datetime, value: float | None) -> Rows:
    """`rows` with the value of `name` at `at` replaced."""
    rows[name] = [(hour, value if hour == at else old) for hour, old in rows[name]]
    return rows


def computed(rows: Rows) -> SizeCohorts:
    result = size_cohorts(rows)
    assert result is not None
    return result


def cells(result: SizeCohorts) -> dict[tuple[int, str], float | int | None]:
    """Every cell of `result`, by band place and field."""
    out: dict[tuple[int, str], float | int | None] = {}
    for place, band in enumerate(result.bands):
        out[(place, "supply")] = band.supply
        out[(place, "realized_cap")] = band.realized_cap
        for window in band.windows:
            out[(place, f"{window.window} supply_change")] = window.supply_change
            out[(place, f"{window.window} profit")] = window.profit
            out[(place, f"{window.window} loss")] = window.loss
    return out


def test_size_series_cover_twelve_bands_four_ways():
    assert len(SIZE_BANDS) == 12
    assert (SIZE_BANDS[0], SIZE_BANDS[-1]) == ("addrs_under_1k_sats", "addrs_over_100k_btc")
    assert len(SIZE_SERIES) == len(set(SIZE_SERIES)) == 48
    assert SIZE_SERIES[:4] == tuple(f"addrs_under_1k_sats{s}" for s in SIZE_SUFFIXES)
    # More than MAX_SERIES_CHARS: an incremental round needs two requests (Task 2).
    assert len(",".join(SIZE_SERIES)) == 2003
    assert len(",".join(SIZE_SERIES)) > MAX_SERIES_CHARS


def test_matches_the_page_supply_cell_by_cell():
    result = size_cohorts(golden_rows())
    assert result is not None and result.last_at == SE and result.rules == []
    assert result.no_block == []
    for page, band in zip(page_size(), result.bands, strict=True):
        assert band.supply == page["supply"]
        assert [w.window for w in band.windows] == ["1d", "7d", "30d", "90d"]
        assert [w.supply_change for w in band.windows] == [
            page["d"][k] for k in ("1d", "7d", "30d", "90d")
        ]
    assert [b.band for b in result.bands] == list(SIZE_BANDS)


def test_matches_the_page_pnl_cell_by_cell():
    result = size_cohorts(golden_rows())
    assert result is not None
    for page, band in zip(page_pnl(), result.bands, strict=True):
        assert band.realized_cap == page[0]
        assert [(w.profit, w.loss) for w in band.windows] == [
            (page[1], page[2]),
            (page[3], page[4]),
            (page[5], page[6]),
            (page[7], page[8]),
        ]
    # The two half-dollar cells: Math.round goes up where Python's round() would go to even.
    assert result.bands[0].windows[0].profit == 89
    assert result.bands[5].windows[3].profit == 2425253219


@pytest.mark.parametrize(
    ("raw", "dollars"), [(88.5, 89), (-88.5, -88), (2.5, 3), (-2.5, -2), (0.49, 0)]
)
def test_dollars_round_half_up_like_math_round(raw: float, dollars: int):
    band = SIZE_BANDS[0]
    rows = flat_rows()
    # The 7d profit and loss differ by `raw`; the realized cap is `raw` itself.
    with_value(rows, f"{band}{PROFIT}", SE - HOUR * 168, 1.0 - raw)
    with_value(rows, f"{band}{LOSS}", SE - HOUR * 168, 1.0 - raw)
    with_value(rows, f"{band}{CAP}", SE, raw)
    result = computed(rows).bands[0]
    assert (result.windows[1].profit, result.windows[1].loss) == (dollars, dollars)
    assert result.realized_cap == dollars


def test_supply_rounds_like_to_fixed_2():
    supply = f"{SIZE_BANDS[0]}{SUPPLY}"
    # 1.125 - 1.0 is exactly 0.125: toFixed(2) gives 0.13, Python's round(0.125, 2) 0.12.
    up = computed(with_value(flat_rows(), supply, SE, 1.125)).bands[0]
    assert up.windows[1].supply_change == 0.13
    down = computed(with_value(flat_rows(), supply, SE - HOUR * 168, 1.125)).bands[0]
    assert down.windows[1].supply_change == -0.13
    # The float nearest 2.675 is just below it, and toFixed(2) rounds that exact value: "2.67".
    below = computed(with_value(flat_rows(), supply, SE, 2.675)).bands[0]
    assert below.supply == 2.67


def test_a_no_block_anchor_leaves_that_window_missing():
    flat = computed(flat_rows())
    assert flat.no_block == []
    assert all(
        value == (1 if field in ("supply", "realized_cap") else 0)
        for (_, field), value in cells(flat).items()
    )
    rows = flat_rows()
    for name in SIZE_SERIES:
        with_value(rows, name, SE - HOUR * 168, None)
    result = computed(rows)
    assert result.no_block == ["7d"]
    missing = {
        (place, f"7d {field}"): None
        for place in range(len(SIZE_BANDS))
        for field in ("supply_change", "profit", "loss")
    }
    assert cells(result) == cells(flat) | missing
    # Listed in window order.
    for name in SIZE_SERIES:
        with_value(rows, name, SE - HOUR * 720, None)
    assert computed(rows).no_block == ["7d", "30d"]


def test_a_partly_null_anchor_is_not_a_no_block_hour():
    flat = computed(flat_rows())
    result = computed(with_value(flat_rows(), f"{BAND_6}{SUPPLY}", SE - HOUR * 168, None))
    assert result.bands[6].windows[1].supply_change is None
    assert cells(result) == cells(flat) | {(6, "7d supply_change"): None}
    # A gap in one series, not an hour without a block.
    assert result.no_block == []


def test_a_null_last_value_leaves_only_that_series_missing():
    flat = computed(flat_rows())
    result = computed(with_value(flat_rows(), f"{BAND_6}{SUPPLY}", SE, None))
    band = result.bands[6]
    assert band.supply is None
    assert [w.supply_change for w in band.windows] == [None] * 4
    assert band.realized_cap is not None
    assert all(w.profit is not None and w.loss is not None for w in band.windows)
    missing = {(6, "supply"): None} | {
        (6, f"{window} supply_change"): None for window in ("1d", "7d", "30d", "90d")
    }
    assert cells(result) == cells(flat) | missing
    assert result.no_block == []


def test_a_short_history_leaves_the_long_window_missing():
    flat = computed(flat_rows())
    rows = {name: values[-1000:] for name, values in flat_rows().items()}
    result = computed(rows)
    assert result.last_at == SE
    for band in result.bands:
        assert all(
            w.supply_change is not None and w.profit is not None and w.loss is not None
            for w in band.windows[:3]
        )
        assert (band.windows[3].supply_change, band.windows[3].profit, band.windows[3].loss) == (
            None,
            None,
            None,
        )
    missing = {
        (place, f"90d {field}"): None
        for place in range(len(SIZE_BANDS))
        for field in ("supply_change", "profit", "loss")
    }
    assert cells(result) == cells(flat) | missing
    # The anchor hour has no row at all, which is not an hour without a block.
    assert result.no_block == []


def test_last_at_is_the_newest_hour_every_series_has():
    rows = flat_rows()
    supply = f"{SIZE_BANDS[0]}{SUPPLY}"
    rows[supply] = [*rows[supply], (SE + HOUR, 5.0)]
    result = computed(rows)
    assert result.last_at == SE
    assert cells(result) == cells(computed(flat_rows()))


def test_nothing_to_read_is_none():
    assert size_cohorts({name: [] for name in SIZE_SERIES}) is None
    rows = flat_rows()
    rows[f"{BAND_6}{CAP}"] = []
    assert size_cohorts(rows) is None
