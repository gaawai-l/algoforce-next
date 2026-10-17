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
from wheelhouse_service.rules import Rules

NOON = datetime(2026, 10, 16, 12, tzinfo=UTC)
YESTERDAY = NOON - timedelta(days=1)
Rows = dict[str, list[tuple[datetime, float | None]]]
V1: Rules = frozenset()
O1: Rules = frozenset({"O1"})
O5: Rules = frozenset({"O5"})
# The cycle's W, which O5 also draws as the 1d–1w cost line.
W = "utxos_1d_to_1w_old_realized_price"


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


def test_median_does_not_depend_on_bucket_order():
    # Sorted, half of the supply (4 of 8) is reached in the 1500 bucket; walked in the order given
    # below it would be reached in that first bucket instead, at 1900.
    ordered = urpd([1.0, 1.0, 1.0, 5.0])
    first, second, third, fourth = ordered.buckets
    shuffled = ordered.model_copy(update={"buckets": [fourth, first, third, second]})
    assert median_cost(ordered) == pytest.approx(1600.0)
    assert median_cost(shuffled) == pytest.approx(1600.0)


def test_median_is_none_without_supply():
    assert median_cost(urpd([0.0, 0.0])) is None


def test_median_rejects_unsupported_aggregation():
    with pytest.raises(ValueError, match="log500"):
        median_cost(urpd([1.0], aggregation="log500"))


def test_last_complete_skips_partial_today():
    today: dict[str, float | None] = {name: 20.0 for name in LINE_SERIES.values()}
    today["realized_price"] = None
    assert last_complete(rows(today), rules=V1, through=None) == (
        YESTERDAY,
        {
            "true_market_mean": 10.0,
            "sth_realized_price": 11.0,
            "realized_price": 12.0,
            "lth_realized_price": 13.0,
        },
    )


def test_last_complete_picks_the_latest_of_several_complete_points():
    older, middle, newest = NOON - timedelta(days=2), NOON - timedelta(days=1), NOON
    # The points are deliberately out of chronological order within each series.
    complete: Rows = {
        name: [(middle, 2.0 + i), (newest, 3.0 + i), (older, 1.0 + i)]
        for i, name in enumerate(LINE_SERIES.values())
    }
    assert last_complete(complete, rules=V1, through=None) == (
        newest,
        {
            "true_market_mean": 3.0,
            "sth_realized_price": 4.0,
            "realized_price": 5.0,
            "lth_realized_price": 6.0,
        },
    )


@pytest.mark.parametrize("bad", [0.0, -1.0, None])
def test_last_complete_requires_every_series_positive(bad: float | None):
    today: dict[str, float | None] = {name: 20.0 for name in LINE_SERIES.values()}
    today["lth_realized_price"] = bad
    found = last_complete(rows(today), rules=V1, through=None)
    assert found is not None
    assert found[0] == YESTERDAY


def test_last_complete_is_none_without_a_complete_point():
    empty: Rows = {name: [(NOON, None)] for name in LINE_SERIES.values()}
    assert last_complete(empty, rules=V1, through=None) is None
    assert last_complete({}, rules=V1, through=None) is None
    # One series missing from `rows` entirely.
    today: dict[str, float | None] = {name: 20.0 for name in LINE_SERIES.values()}
    partial = {k: v for k, v in rows(today).items() if k != "realized_price"}
    assert last_complete(partial, rules=V1, through=None) is None


def test_last_complete_under_o1_reads_up_to_the_closed_day():
    today: dict[str, float | None] = {name: 20.0 for name in LINE_SERIES.values()}
    yesterday = {
        "true_market_mean": 10.0,
        "sth_realized_price": 11.0,
        "realized_price": 12.0,
        "lth_realized_price": 13.0,
    }
    closed = YESTERDAY.date()

    # Today is complete, but only yesterday is closed.
    assert last_complete(rows(today), rules=O1, through=closed) == (YESTERDAY, yesterday)
    # Without O1 the closed day is not a limit, and without a limit O1 reads the latest point.
    assert last_complete(rows(today), rules=V1, through=closed) == (NOON, {**today})
    assert last_complete(rows(today), rules=O1, through=None) == (NOON, {**today})
    # No complete point up to the closed day.
    assert last_complete(rows(today), rules=O1, through=closed - timedelta(days=1)) is None


def test_last_complete_under_o5_needs_the_1d_1w_series_too():
    today: dict[str, float | None] = {name: 20.0 for name in LINE_SERIES.values()}
    series = {**rows(today), W: [(YESTERDAY, 30.0), (NOON, None)]}

    # v1 does not read W, so today is complete.
    assert last_complete(series, rules=V1, through=None) == (NOON, {**today})
    # O5 does: today has no W yet, so the lines are yesterday's, W among them.
    assert last_complete(series, rules=O5, through=None) == (
        YESTERDAY,
        {
            "true_market_mean": 10.0,
            "sth_realized_price": 11.0,
            "realized_price": 12.0,
            "lth_realized_price": 13.0,
            W: 30.0,
        },
    )
    # Without W at all there are no lines under O5.
    assert last_complete(rows(today), rules=O5, through=None) is None


def test_model_lines_under_o5_add_the_1d_1w_line_last():
    last = {
        "true_market_mean": 4.0,
        "sth_realized_price": 3.0,
        "realized_price": 2.0,
        "lth_realized_price": 1.0,
        W: 5.0,
    }
    assert model_lines(last, urpd([1.0, 2.0, 1.0]), rules=O5) == [
        ModelLine(name="true_mean", price=4.0),
        ModelLine(name="short_term", price=3.0),
        ModelLine(name="average", price=2.0),
        ModelLine(name="long_term", price=1.0),
        ModelLine(name="median", price=750.0),
        ModelLine(name="one_day_to_week", price=5.0),
    ]
    # Without a snapshot it is still last; v1 leaves it out even when W is there.
    four = ["true_mean", "short_term", "average", "long_term"]
    assert [line.name for line in model_lines(last, None, rules=O5)] == [*four, "one_day_to_week"]
    assert [line.name for line in model_lines(last, None, rules=V1)] == four


def test_model_lines_without_urpd_has_four_lines():
    last = {
        "true_market_mean": 4.0,
        "sth_realized_price": 3.0,
        "realized_price": 2.0,
        "lth_realized_price": 1.0,
    }
    assert model_lines(last, None, rules=V1) == [
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
    lines = model_lines(last, urpd([1.0, 2.0, 1.0]), rules=V1)
    assert lines[-1] == ModelLine(name="median", price=750.0)
    assert [line.name for line in lines[:-1]] == ["true_mean", "short_term", "average", "long_term"]


def test_fixture_median_is_near_page_value():
    # The page showed $63,721 at 08:20 UTC; the fixture snapshot was fetched later, so it can drift.
    median = median_cost(load_urpd("all"))
    assert median is not None
    assert abs(median - 63_721) <= 1_000


def test_fixture_series_last_complete_point_is_the_last_day():
    fixture = {name: _rows(name) for name in LINE_SERIES.values()}
    found = last_complete(fixture, rules=V1, through=None)
    assert found is not None
    time, values = found
    assert time == datetime(2026, 10, 16, tzinfo=UTC)
    assert values == {name: fixture[name][-1][1] for name in LINE_SERIES.values()}


def _rows(name: str) -> list[tuple[datetime, float | None]]:
    series = load_series(name, "day1")
    epoch = datetime(2009, 1, 1, tzinfo=UTC)
    return [(epoch + timedelta(days=series.start + i), v) for i, v in enumerate(series.data)]
