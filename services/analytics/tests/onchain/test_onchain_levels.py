from datetime import UTC, datetime, timedelta

import pytest
from onchain_fixture import load_series, load_urpd

from wheelhouse_service.onchain.brk import Urpd
from wheelhouse_service.onchain.levels import (
    LINE_SERIES,
    ModelLine,
    last_complete,
    median_cost,
    model_lines,
)

NOON = datetime(2026, 10, 16, 12, tzinfo=UTC)
YESTERDAY = NOON - timedelta(days=1)
Rows = dict[str, list[tuple[datetime, float | None]]]


def urpd(supplies: list[float], aggregation: str = "lin500") -> Urpd:
    """A snapshot whose buckets start at 0 and are 500 wide, holding `supplies` in order."""
    return Urpd.model_validate(
        {
            "cohort": "all",
            "date": "2026-10-16",
            "aggregation": aggregation,
            "close": 1_000.0,
            "total_supply": sum(supplies),
            "buckets": [
                {"price_floor": 500.0 * i, "supply": s, "realized_cap": 0.0, "unrealized_pnl": 0.0}
                for i, s in enumerate(supplies)
            ],
        }
    )


def rows(today: dict[str, float | None]) -> Rows:
    """Yesterday has all four series; today has `today`."""
    return {
        name: [(YESTERDAY, 10.0 + i), (NOON, today[name])]
        for i, name in enumerate(LINE_SERIES.values())
    }


def test_median_interpolates_inside_bucket():
    # Half of the supply (2 of 4) is reached halfway through the 500..1000 bucket.
    assert median_cost(urpd([1.0, 2.0, 1.0])) == 750.0


def test_median_includes_buckets_below_1000():
    # Three of the five units sit in the 0..500 bucket, so the median is below 1000.
    assert median_cost(urpd([3.0, 1.0, 1.0])) == pytest.approx(500.0 * 2.5 / 3.0)


def test_median_is_none_without_supply():
    assert median_cost(urpd([0.0, 0.0])) is None


def test_median_rejects_unsupported_aggregation():
    with pytest.raises(ValueError, match="log500"):
        median_cost(urpd([1.0], aggregation="log500"))


def test_last_complete_skips_partial_today():
    today: dict[str, float | None] = {name: 20.0 for name in LINE_SERIES.values()}
    today["realized_price"] = None
    assert last_complete(rows(today)) == (
        YESTERDAY,
        {
            "true_market_mean": 10.0,
            "sth_realized_price": 11.0,
            "realized_price": 12.0,
            "lth_realized_price": 13.0,
        },
    )


def test_last_complete_requires_every_series_positive():
    today: dict[str, float | None] = {name: 20.0 for name in LINE_SERIES.values()}
    today["lth_realized_price"] = 0.0
    found = last_complete(rows(today))
    assert found is not None
    assert found[0] == YESTERDAY
    assert last_complete({name: [(NOON, None)] for name in LINE_SERIES.values()}) is None
    assert last_complete({}) is None


def test_model_lines_without_urpd_has_four_lines():
    last = {
        "true_market_mean": 4.0,
        "sth_realized_price": 3.0,
        "realized_price": 2.0,
        "lth_realized_price": 1.0,
    }
    assert model_lines(last, None) == [
        ModelLine(name="true_mean", price=4.0),
        ModelLine(name="short_term", price=3.0),
        ModelLine(name="average", price=2.0),
        ModelLine(name="long_term", price=1.0),
    ]


def test_model_lines_appends_median():
    last = {
        "true_market_mean": 4.0,
        "sth_realized_price": 3.0,
        "realized_price": 2.0,
        "lth_realized_price": 1.0,
    }
    lines = model_lines(last, urpd([1.0, 2.0, 1.0]))
    assert lines[-1] == ModelLine(name="median", price=750.0)
    assert [line.name for line in lines[:-1]] == ["true_mean", "short_term", "average", "long_term"]


def test_fixture_median_is_near_page_value():
    # The page showed $63,721 at 08:20 UTC; the fixture snapshot was fetched later, so it can drift.
    median = median_cost(load_urpd("all"))
    assert median is not None
    assert abs(median - 63_721) <= 1_000


def test_fixture_series_have_a_complete_last_point():
    found = last_complete({name: _rows(name) for name in LINE_SERIES.values()})
    assert found is not None
    assert all(price > 0 for price in found[1].values())


def _rows(name: str) -> list[tuple[datetime, float | None]]:
    series = load_series(name, "day1")
    epoch = datetime(2009, 1, 1, tzinfo=UTC)
    return [(epoch + timedelta(days=series.start + i), v) for i, v in enumerate(series.data)]
