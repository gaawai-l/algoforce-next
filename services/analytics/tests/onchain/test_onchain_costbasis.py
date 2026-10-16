import json
import math
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path
from typing import Any, get_args

import pytest

from wheelhouse_service.onchain.brk import Urpd
from wheelhouse_service.onchain.costbasis import (
    BUCKETS,
    LINE_ORDER,
    Band,
    Bucket,
    BucketCostBasis,
    Candidate,
    CohortClusters,
    cost_basis,
    fit_gmm,
    select_components,
)
from wheelhouse_service.onchain.levels import LINE_SERIES, LineName, ModelLine, median_cost

GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-16T1829Z"
DAY = date(2026, 10, 16)
# How the original page names each model line.
LABELS: dict[LineName, str] = {
    "true_mean": "True mean",
    "short_term": "Short-term",
    "average": "Average",
    "median": "Median",
    "long_term": "Long-term",
}
EDGES = {"low": " −σ", "mid": "", "high": " +σ"}
# Far above every domain in these tests, so the line is dropped.
OFF = 1_000_000.0

# From expected-{bucket}.json (oracle_c7.py), which the test also compares in full.
DAY1_LAST = {
    "true_mean": 77481.81,
    "short_term": 74475.07,
    "average": 53845.04,
    "long_term": 49245.48,
}
DOMAIN = {200: (1000.0, 125800.0), 500: (1000.0, 126000.0), 1000: (1000.0, 126000.0)}
STH_K = {200: [63500, 82300], 500: [63750, 82250], 1000: [63500, 82500]}
LTH_K = {
    200: [6900, 39100, 67300, 84900, 108100],
    500: [6750, 38750, 67250, 84750, 108250],
    1000: [7500, 39500, 67500, 85500, 108500],
}
RESISTANCE = {
    200: [86000, 88000, 96000, 104000],
    500: [86000, 88000, 96000, 104000],
    1000: [86000, 90000, 96000, 104000],
}
SUPPORT = [76000, 74000, 70000, 64000]
STH_IN_PROFIT = {200: 0.6385303598567579, 500: 0.6227192201679547, 1000: 0.6227192222272292}
LTH_IN_PROFIT_1000 = 0.5854495647196322


def _json(name: str) -> Any:
    return json.loads((GOLDEN / name).read_text())


def golden_today(bucket: int) -> dict[str, Urpd]:
    return {
        cohort: Urpd.model_validate(_json(f"urpd_{cohort}_lin{bucket}.json"))
        for cohort in ("all", "sth", "lth")
    }


def golden_past(bucket: int) -> list[Urpd]:
    """The D-1, D-7, D-30 and D-90 snapshots of every cohort for one bucket width."""
    return [
        Urpd.model_validate(_json(path.name))
        for path in sorted(GOLDEN.glob(f"urpd_*_lin{bucket}_*.json"))
    ]


def golden_lines() -> list[ModelLine]:
    """The last day1 value of the four series lines, plus the P1 median of `all lin500`."""
    lines = [
        ModelLine(name=name, price=_json(f"day1_{series}.json")["data"][-1])
        for name, series in LINE_SERIES.items()
    ]
    median = median_cost(golden_today(500)["all"])
    assert median is not None
    return [*lines, ModelLine(name="median", price=median)]


@cache
def golden_result(bucket: Bucket) -> BucketCostBasis:
    result = cost_basis(golden_today(bucket), golden_past(bucket), bucket, golden_lines())
    assert result is not None
    return result


def label(candidate: Candidate) -> str:
    if candidate.kind == "line":
        assert candidate.line is not None
        return LABELS[candidate.line]
    assert candidate.cohort is not None and candidate.edge is not None
    return f"{candidate.cohort.upper()} M{candidate.index}{EDGES[candidate.edge]}"


def to_fixed(value: float, digits: int) -> str:
    """JavaScript `value.toFixed(digits)` for a positive value."""
    return str(Decimal(value).quantize(Decimal(1).scaleb(-digits), ROUND_HALF_UP))


def cohorts(result: BucketCostBasis) -> dict[str, CohortClusters]:
    return {"sth": result.sth, "lth": result.lth}


def snapshot(
    cohort: str,
    supplies: dict[float, float],
    *,
    bucket: int = 500,
    close: float = 80_000.0,
    day: date = DAY,
) -> Urpd:
    return Urpd.model_validate(
        {
            "cohort": cohort,
            "date": day.isoformat(),
            "aggregation": f"lin{bucket}",
            "close": close,
            "total_supply": sum(supplies.values()),
            "buckets": [
                {"price_floor": floor, "supply": s, "realized_cap": 0.0, "unrealized_pnl": 0.0}
                for floor, s in supplies.items()
            ],
        }
    )


def market(
    supplies: dict[float, float],
    *,
    bucket: int = 500,
    close: float = 80_000.0,
    sth: dict[float, float] | None = None,
    lth: dict[float, float] | None = None,
) -> dict[str, Urpd]:
    """Today's three snapshots: `supplies` for all; STH and LTH are empty unless given."""
    return {
        "all": snapshot("all", supplies, bucket=bucket, close=close),
        "sth": snapshot("sth", sth or {}, bucket=bucket, close=close),
        "lth": snapshot("lth", lth or {}, bucket=bucket, close=close),
    }


def live(low: int, high: int, step: int = 500) -> dict[float, float]:
    """One live bucket (1 BTC) at every floor from `low` up to, not including, `high`."""
    return {float(floor): 1.0 for floor in range(low, high, step)}


def lines(prices: dict[LineName, float] | None = None) -> list[ModelLine]:
    """All five model lines; those not given sit at OFF."""
    given = prices or {}
    return [ModelLine(name=name, price=given.get(name, OFF)) for name in LABELS]


def spans(bands: list[Band]) -> list[tuple[float, float, list[str]]]:
    return [(band.low, band.high, [label(c) for c in band.candidates]) for band in bands]


@pytest.mark.parametrize("bucket", BUCKETS)
def test_golden_parity(bucket: Bucket) -> None:
    expected = _json(f"expected-{bucket}.json")
    assert {line.name: line.price for line in golden_lines()[:4]} == DAY1_LAST
    result = golden_result(bucket)

    assert (result.domain_low, result.domain_high) == DOMAIN[bucket]
    assert [result.domain_low, result.domain_high] == pytest.approx(expected["domain"], rel=1e-9)
    assert result.spot == pytest.approx(expected["spot"], rel=1e-9)
    assert [peak.price for peak in result.sth.peaks] == STH_K[bucket]
    assert [peak.price for peak in result.lth.peaks] == LTH_K[bucket]
    assert result.sth.in_profit == pytest.approx(STH_IN_PROFIT[bucket], rel=1e-9)
    if bucket == 1000:
        assert result.lth.in_profit == pytest.approx(LTH_IN_PROFIT_1000, rel=1e-9)

    for cohort, clusters in cohorts(result).items():
        want = expected["cohorts"][cohort]
        assert clusters.cohort == cohort
        assert clusters.total == pytest.approx(want["total"], rel=1e-9)
        assert clusters.in_profit == pytest.approx(want["in_profit"], rel=1e-9)
        assert len(clusters.peaks) == len(want["peaks"])
        for peak, peak_want in zip(clusters.peaks, want["peaks"], strict=True):
            # The oracle names the peak's price `at`.
            assert list(peak.model_dump().values()) == pytest.approx(
                [peak_want[key] for key in ("at", "width", "btc", "share", "strength")], rel=1e-9
            )
        assert len(clusters.components) == len(want["components"])
        for component, component_want in zip(clusters.components, want["components"], strict=True):
            assert list(component.model_dump().values()) == pytest.approx(
                [component_want[key] for key in ("mu", "sigma", "share", "btc")], rel=1e-9
            )

    assert result.resistance == RESISTANCE[bucket] == expected["resistance"]
    assert result.support == SUPPORT == expected["support"]
    for side, bands in (("above", result.above), ("below", result.below)):
        assert spans(bands) == [
            (want["low"], want["high"], want["labels"]) for want in expected[side]
        ]


@pytest.mark.parametrize("bucket", BUCKETS)
def test_matches_page_readings(bucket: Bucket) -> None:
    page = _json("page.json")[str(bucket)]
    result = golden_result(bucket)

    def k(value: float) -> str:
        return f"${to_fixed(value / 1000, 1)}k"

    assert page["tbl2"][1:] == [
        "Resistance " + " ".join(k(v) for v in result.resistance),
        "Support " + " ".join(k(v) for v in result.support),
    ]

    def row(side: str, band: Band) -> list[str]:
        return [
            side,
            f"${band.low:,.0f} – ${band.high:,.0f}",
            str(len(band.candidates)),
            ", ".join(label(c) for c in band.candidates),
        ]

    near = [
        *(row("above", band) for band in reversed(result.above)),
        ["spot", f"${result.spot:,.0f}", "", ""],
        *(row("below", band) for band in result.below),
    ]
    assert [reading[:4] for reading in page["near"]] == near

    def subtitle(clusters: CohortClusters) -> str:
        assert clusters.total >= 1e6 and clusters.in_profit is not None
        return (
            f"{to_fixed(clusters.total / 1e6, 2)}M BTC total"
            f" · {to_fixed(clusters.in_profit * 100, 0)}% in profit"
        )

    assert page["subs"] == [subtitle(result.sth), subtitle(result.lth)]
    assert page["labs"] == [
        f"{letter}{i}"
        for clusters in (result.sth, result.lth)
        for letter, count in (("K", len(clusters.peaks)), ("M", len(clusters.components)))
        for i in range(1, count + 1)
    ]
    assert [peak["at"] for peak in page["peaks"]] == pytest.approx(
        [peak.price for peak in [*result.sth.peaks, *result.lth.peaks]], abs=1e-6
    )
    assert [dot["lane"] for dot in page["dots"]] == ["sth"] * len(result.sth.components) + [
        "lth"
    ] * len(result.lth.components)
    assert [dot["mu"] for dot in page["dots"]] == pytest.approx(
        [c.mu for c in [*result.sth.components, *result.lth.components]], abs=0.01
    )


def test_trim_keeps_two_padding_rows() -> None:
    # Prices under $1,000 go first, even when live. Of the rest, 0.5 BTC is not live, so the live
    # run is floors 3000-4000 and two rows either side of it stay.
    supplies = {
        0.0: 9.0,
        500.0: 9.0,
        1000.0: 0.5,
        1500.0: 0.5,
        2000.0: 0.5,
        2500.0: 0.3,
        3000.0: 1.0,
        3500.0: 2.0,
        4000.0: 1.0,
        4500.0: 0.0,
        5000.0: 0.0,
        5500.0: 0.0,
    }
    result = cost_basis(market(supplies), [], 500, lines())
    assert result is not None
    assert (result.domain_low, result.domain_high) == (2000.0, 5500.0)


def test_trim_without_live_rows_keeps_last_three() -> None:
    supplies = {float(floor): 0.5 for floor in range(1000, 5500, 500)}
    result = cost_basis(market(supplies), [], 500, lines())
    assert result is not None
    assert (result.domain_low, result.domain_high) == (4000.0, 5500.0)


def test_spot_on_slice_boundary() -> None:
    result = cost_basis(
        market(live(70_000, 90_000), close=80_000.0),
        [],
        500,
        lines({"short_term": 79_000.0, "true_mean": 80_500.0, "average": 82_500.0}),
    )
    assert result is not None
    # Spot's own band is [80000, 82000), so True mean at 80500 is in neither list.
    assert spans(result.above) == [(82_000.0, 84_000.0, ["Average"])]
    assert spans(result.below) == [(78_000.0, 80_000.0, ["Short-term"])]
    assert result.resistance == [84_000.0]
    assert result.support == [78_000.0]


def test_slices_clip_to_domain() -> None:
    result = cost_basis(
        market(live(1000, 126_000), close=60_000.0),
        [],
        500,
        lines({"short_term": 1500.0, "long_term": 125_000.0}),
    )
    assert result is not None
    assert (result.domain_low, result.domain_high) == (1000.0, 126_000.0)
    assert spans(result.below) == [(1000.0, 2000.0, ["Short-term"])]
    assert spans(result.above) == [(124_000.0, 126_000.0, ["Long-term"])]


def test_line_outside_domain_not_counted() -> None:
    # Domain [3000, 9000]: unclipped, the end slices would be [2000, 4000) and [8000, 10000).
    result = cost_basis(
        market(live(3000, 9000), close=7000.0),
        [],
        500,
        lines({"short_term": 2500.0, "true_mean": 9500.0, "average": 5000.0}),
    )
    assert result is not None
    assert (result.domain_low, result.domain_high) == (3000.0, 9000.0)
    assert spans(result.above) == []
    assert spans(result.below) == [(4000.0, 6000.0, ["Average"])]


def test_line_rounding_half_up() -> None:
    result = cost_basis(
        market(live(1000, 80_000), close=40_000.0),
        [],
        500,
        lines({"short_term": 74_998.5, "true_mean": 999.5}),
    )
    assert result is not None
    # Half up: 74998.5 -> 74999, where round-half-even would give 74998.
    [above] = result.above
    assert [c.price for c in above.candidates] == [74_999.0]
    # The line is rounded before the domain check: 999.5 -> 1000 is inside [1000, 80000].
    [below] = result.below
    assert (below.low, below.high) == (1000.0, 2000.0)
    assert [(c.line, c.price) for c in below.candidates] == [("true_mean", 1000.0)]


def test_supply_rounding_matches_tofixed() -> None:
    # toFixed(2) rounds the exact binary value half up: 0.125 -> 0.13 (Python's round gives
    # 0.12), and 1.005, stored as 1.00499..., -> 1.00.
    result = cost_basis(
        market(live(1000, 3500), sth={2000.0: 0.125}, lth={2000.0: 1.005}),
        [],
        500,
        lines(),
    )
    assert result is not None
    assert result.sth.total == 0.13
    assert result.lth.total == 1.0


def test_in_profit_counts_row_at_spot() -> None:
    # Spot sits exactly on the 2250 row, which counts as in profit; the row priced 250 is
    # below $1,000 and left out of the total.
    result = cost_basis(
        market(live(1000, 3500), close=2250.0, sth={0.0: 10.0, 1000.0: 1.0, 2000.0: 3.0}),
        [],
        500,
        lines(),
    )
    assert result is not None
    assert result.sth.total == 4.0
    assert result.sth.in_profit == 1.0
    assert result.lth.total == 0.0
    assert result.lth.in_profit is None


def test_past_floor_extends_grid() -> None:
    today = market(live(1000, 5500), sth={2000.0: 1.0})
    plain = cost_basis(today, [], 500, lines())
    # A past snapshot adds its floors to the grid, never its supply.
    past = [
        snapshot("all", {5500.0: 3.0}, day=DAY - timedelta(days=1)),
        snapshot("sth", {2000.0: 50.0}, day=DAY - timedelta(days=1)),
    ]
    extended = cost_basis(today, past, 500, lines())
    assert plain is not None and extended is not None
    assert (plain.domain_low, plain.domain_high) == (1000.0, 5500.0)
    assert (extended.domain_low, extended.domain_high) == (1000.0, 6000.0)
    assert plain.sth.total == extended.sth.total == 1.0


def test_select_components_uses_bic_without_peaks() -> None:
    # Two tight bumps far apart: 20 positive rows (cap 4) in a 25-row domain.
    bump = [1.0, 2.0, 4.0, 7.0, 9.0, 9.0, 7.0, 4.0, 2.0, 1.0]
    xs = [10_000.0 + 10 * i for i in range(10)] + [50_000.0 + 10 * i for i in range(10)]
    ws = bump + bump
    rows = 25

    def bic(k: int) -> float:
        fit = fit_gmm(xs, ws, k)
        assert fit is not None
        return -2 * fit[1] + (3 * k - 1) * math.log(max(rows, 2))

    scores = [bic(k) for k in range(1, 5)]
    best = scores.index(min(scores)) + 1
    assert best == 2
    assert scores.count(min(scores)) == 1
    best_fit = fit_gmm(xs, ws, best)
    assert best_fit is not None
    assert select_components(xs, ws, peaks=0, rows=rows) == best_fit[0]
    assert len(select_components(xs, ws, peaks=3, rows=rows)) == min(4, 3)
    # The penalty uses the domain rows, not the positive ones: over 1000 rows it picks k = 1.
    one = fit_gmm(xs, ws, 1)
    assert one is not None
    assert one[0] != best_fit[0]
    assert select_components(xs, ws, peaks=0, rows=1000) == one[0]
    # Fewer than 2 rows count as 2, so the penalty never takes log 0.
    assert select_components(xs, ws, peaks=0, rows=0) == best_fit[0]


def test_line_order_lists_every_line_once() -> None:
    assert set(LINE_ORDER) == set(get_args(LineName)) and len(LINE_ORDER) == 5


def test_gmm_zero_density_falls_back() -> None:
    # The last row is so far from every component that its density underflows to 0; it takes
    # equal responsibilities and adds log 1 = 0 rather than failing on log 0.
    xs = [0.0, 1.0, 2.0, 1e6]
    ws = [1e6, 1e6, 1e6, 1e-3]
    fit = fit_gmm(xs, ws, 2)
    assert fit is not None
    components, log_l = fit
    assert math.isfinite(log_l)
    for component in components:
        assert (xs[-1] - component.mu) / component.sigma > 40
        assert all(math.isfinite(v) for v in component.model_dump().values())


def test_four_lines_raise() -> None:
    today = market(live(1000, 5000))
    with pytest.raises(ValueError):
        cost_basis(today, [], 500, lines()[:4])
    with pytest.raises(ValueError):
        cost_basis(today, [], 500, [*lines()[:4], lines()[0]])


def test_gmm_needs_three_positive_rows() -> None:
    xs = [1000.0, 2000.0, 3000.0, 4000.0]
    assert select_components(xs, [1.0, 1.0, 0.0, 0.0], peaks=1, rows=4) == []
    assert len(select_components(xs, [1.0, 1.0, 1.0, 0.0], peaks=1, rows=4)) == 1


def test_component_k_capped_by_rows() -> None:
    xs = [1000.0 * i for i in range(1, 12)]
    nine = [1.0] * 9 + [0.0, 0.0]
    ten = [1.0] * 10 + [0.0]
    assert len(select_components(xs, nine, peaks=4, rows=11)) == 1
    assert len(select_components(xs, ten, peaks=4, rows=11)) == 2


def test_mismatched_dates_raise() -> None:
    today = market(live(1000, 5000))
    today["sth"] = snapshot("sth", {}, day=DAY - timedelta(days=1))
    with pytest.raises(ValueError):
        cost_basis(today, [], 500, lines())


def test_wrong_aggregation_raises() -> None:
    with pytest.raises(ValueError):
        cost_basis(market(live(1000, 5000)), [], 200, lines())
    past = [snapshot("all", {1000.0: 1.0}, bucket=200, day=DAY - timedelta(days=1))]
    with pytest.raises(ValueError):
        cost_basis(market(live(1000, 5000)), past, 500, lines())


def test_missing_cohort_raises() -> None:
    today = market(live(1000, 5000))
    del today["lth"]
    with pytest.raises(ValueError):
        cost_basis(today, [], 500, lines())


def test_no_rows_from_min_price_returns_none() -> None:
    assert cost_basis(market({0.0: 5.0, 500.0: 5.0}), [], 500, lines()) is None
