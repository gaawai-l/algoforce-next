"""Unit tests verifying QFI Labs MCP parity across cycle, seller, volatility and perps."""

from datetime import UTC, date, datetime, timedelta

import pytest

from wheelhouse_service.onchain.brk import HOUR1_SERIES
from wheelhouse_service.onchain.cycle import (
    classify,
    classify_horizon,
    regime_reading,
)
from wheelhouse_service.onchain.pressure import (
    seller_category,
    seller_horizons,
)
from wheelhouse_service.onchain.volatility import (
    VOLATILITY_SERIES,
    YOUNG_2M_BANDS,
    compute_volatility_horizon,
    volatility_category,
)
from wheelhouse_service.perps.states import Grid, block_tests, compute_intraweek, compute_states


def test_regime_reading_matches_qfi_reference_values() -> None:
    # 2026-11-10 reference from QFI MCP: depth=-1.085888, pvs=1.195481, spread=-2.281370 -> Repair
    r_1110 = regime_reading(-1.0858883546175022, 1.19548141103179, -2.281369765649292)
    assert r_1110.state == "repair"
    assert r_1110.weakest == "depth"
    assert r_1110.neighbour == "breakout"
    assert r_1110.raw == pytest.approx(0.1551269, rel=1e-5)
    assert r_1110.strength == pytest.approx(0.1551269, rel=1e-5)

    # 2026-11-18 reference from QFI MCP: depth=-13.948005, pvs=-10.035429, spread=-3.912576
    r_1118 = regime_reading(-13.948005, -10.035429, -3.912576)
    assert r_1118.state == "capitulation"
    assert r_1118.weakest == "pvs"
    assert r_1118.neighbour == "repair"
    assert r_1118.raw == pytest.approx(1.475798, rel=1e-5)
    assert r_1118.strength == 1.0


def test_classify_and_classify_horizon() -> None:
    d0 = date(2026, 11, 9)
    d1 = date(2026, 11, 10)
    rows = [
        (d0, 108.0, 97.0, 100.0, 105.0),  # depth > 7, pvs > 6.8, spread < -1.25 -> breakout
        (d1, 98.92, 97.74, 100.0, 99.0),  # raw repair, gated breakout
    ]
    cycle = classify(rows, rules=frozenset({"O1", "O4"}), closed_day=d1)
    assert cycle is not None
    assert cycle.state == "breakout"

    t0 = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
    hz = classify_horizon("intramonth", [(t0, 98.92, 97.74, 100.0)])
    assert hz is not None
    assert hz.horizon == "intramonth"
    assert hz.state == "repair"
    assert hz.neighbour == "breakout"
    assert hz.supported is False


def test_seller_horizons_and_noise_filter() -> None:
    assert seller_category(0.95) == "extreme"
    assert seller_category(0.80) == "warning"
    assert seller_category(0.50) == "normal"
    assert seller_category(0.20) == "quiet"

    # Build 800 hours of synthetic cumulative data with one huge noise spike at hour 750
    t0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    n = 800
    rows: dict[str, list[tuple[datetime, float | None]]] = {k: [] for k in HOUR1_SERIES}
    c_ll = c_lp = c_sl = c_sp = c_yl = c_yp = 0.0
    for i in range(n):
        at = t0 + timedelta(hours=i)
        # Normal hourly flow ~ 1000 each; at i == 750 inject a 1,000,000 spike with flat price
        step_ll = 1_000_000.0 if i == 750 else 1000.0 + (i % 50) * 10.0
        step_lp = 1000.0 + (i % 30) * 5.0
        step_sl = 800.0 + (i % 40) * 20.0
        step_sp = 900.0 + (i % 25) * 10.0
        c_ll += step_ll
        c_lp += step_lp
        c_sl += step_sl
        c_sp += step_sp
        rows["price_close"].append((at, 70000.0))
        rows["lth_realized_loss_cumulative"].append((at, c_ll))
        rows["lth_realized_profit_cumulative"].append((at, c_lp))
        rows["sth_realized_loss_cumulative"].append((at, c_sl))
        rows["sth_realized_profit_cumulative"].append((at, c_sp))
        rows["utxos_under_1h_old_realized_loss_cumulative"].append((at, c_yl))
        rows["utxos_under_1h_old_realized_profit_cumulative"].append((at, c_yp))
        rows["sth_supply_in_loss"].append((at, 1_000_000.0 + (i % 60) * 1000.0))
        rows["sth_supply_in_profit"].append((at, 2_000_000.0))
        rows["utxos_under_1h_old_supply_in_loss"].append((at, 10_000.0))
        rows["utxos_under_1h_old_supply_in_profit"].append((at, 10_000.0))

    answers, flagged = seller_horizons(rows, noise_filter=True)
    assert flagged == [t0 + timedelta(hours=750)]
    horizons = {a.horizon: a for a in answers}
    assert "intraday" in horizons
    assert 0.0 <= horizons["intraday"].strength <= 1.0


def test_volatility_spike_watch_horizon() -> None:
    assert volatility_category(0.96) == "extreme"
    assert volatility_category(0.75) == "warning"
    assert volatility_category(0.25) == "normal"
    assert volatility_category(0.10) == "quiet"

    t0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    n = 400  # > 2 * 168h for 7d intraday window
    rows: dict[str, list[tuple[datetime, float | None]]] = {k: [] for k in VOLATILITY_SERIES}
    for i in range(n):
        at = t0 + timedelta(hours=i)
        px = 70000.0 + (i % 24) * 50.0
        rows["price_close"].append((at, px))
        rows["supply_density"].append((at, 10.0 + (i % 50) * 0.2))
        for b in YOUNG_2M_BANDS:
            rows[f"{b}_supply"].append((at, 100_000.0))
            rows[f"{b}_realized_cap"].append((at, 100_000.0 * (70000.0 + (i % 12) * 30.0)))

    ans = compute_volatility_horizon("intraday", rows)
    assert ans is not None
    assert ans.horizon == "intraday"
    assert ans.as_of == t0 + timedelta(hours=n - 1)
    assert 0.0 <= ans.strength <= 1.0
    assert 0.0 <= ans.components.density <= 1.0
    assert 0.0 <= ans.components.narrowness <= 1.0


def test_perps_states_includes_block_tests_and_intraweek() -> None:
    start = 1_760_000_000 - (1_760_000_000 % (4 * 3600))
    n = 24 * 6 * 35  # 35 days of 10m buckets
    last = start + (n - 1) * 600
    grid = Grid(
        start=start,
        last=last,
        price=[70000.0 + (i % 100) * 10.0 for i in range(n)],
        oi=[150000.0 + (i % 50) * 20.0 for i in range(n)],
        vd=[10.0 if i % 2 == 0 else -5.0 for i in range(n)],
        long_liq=[1.0 for _ in range(n)],
        short_liq=[2.0 for _ in range(n)],
        liq_covered=[True for _ in range(n)],
        vd_covered=[True for _ in range(n)],
        rest_series={},
        quarantined_days=0,
    )
    res = compute_states(grid, "4h", rules=frozenset({"O1"}))
    closed_blocks = [b for b in res.blocks if not b.forming]
    assert closed_blocks
    tests = block_tests(closed_blocks[-1], res.thresholds)
    assert tests is not None
    iw = compute_intraweek(grid, rules=frozenset({"O1"}))
    assert iw.state is not None
    assert iw.tests is not None
