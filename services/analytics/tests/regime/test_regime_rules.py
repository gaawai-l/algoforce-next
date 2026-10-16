"""AlphaBTC v2.95.0 regime rules (research/alphabtc-regime-cycle-source-2026-09-28.md §2)."""

import pytest
from regime_fixture import V2, replay_dataset

from wheelhouse_service.indicators.demark import evaluate_demark
from wheelhouse_service.indicators.demark.summary import summarize
from wheelhouse_service.indicators.regime.alphabtc import (
    TimeframeState,
    adjust,
    derive_state,
    new_trend,
    regime_of,
    signals,
)


def _summary(tf):
    data, as_of = replay_dataset(tf)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], as_of)
    assert summary is not None
    return summary


# Expected values were read from the AlphaBTC page for the same TD data.
@pytest.mark.parametrize(
    ("tf", "s9", "s13", "carry13", "countdown"),
    [
        ("5m", "down", False, False, 3),
        ("15m", "up", True, True, 13),
        ("1h", "down", True, True, 13),
        ("4h", "up", False, False, 8),
        ("1d", "up", False, False, 9),
    ],
)
def test_state_matches_alphabtc(tf, s9, s13, carry13, countdown):
    state = derive_state(_summary(tf))
    assert (state.s9, state.s13, state.carry13, state.countdown) == (s9, s13, carry13, countdown)


def test_anchor_regimes_match_alphabtc():
    assert regime_of(derive_state(_summary("1h")), "fresh") == "pump"
    assert regime_of(derive_state(_summary("4h")), "fresh") == "decay"


def _state(s9, s13):
    return TimeframeState(
        s9=s9, s13=s13, carry13=False, countdown=13 if s13 else 0,
        setup9_at=None, qualified13_at=None, setup9_seconds_ago=None,
        qualified13_seconds_ago=None, beyond_risk9=None,
    )


@pytest.mark.parametrize(
    ("s9", "s13", "expected"),
    [("up", False, "decay"), ("up", True, "rev"), ("down", False, "rev"),
     ("down", True, "pump"), ("none", False, "none")],
)
def test_regime_table(s9, s13, expected):
    assert regime_of(_state(s9, s13), "fresh") == expected


@pytest.mark.parametrize("status", ["stale", "unavailable"])
def test_regime_is_unavailable_without_usable_anchor_data(status):
    assert regime_of(_state("down", True), status) == "unavailable"
    assert regime_of(None, "fresh") == "unavailable"


@pytest.mark.parametrize("status", ["fresh", "delayed", "simulated"])
def test_regime_uses_fresh_delayed_or_simulated_anchor(status):
    assert regime_of(_state("down", True), status) == "pump"


@pytest.mark.parametrize(
    ("level", "side", "regime", "expected"),
    [(2, "buy", "pump", 3), (2, "sell", "pump", 1), (3, "buy", "rev", 2),
     (3, "sell", "rev", 4), (2, "buy", "decay", 2), (5, "buy", "pump", 5),
     (1, "sell", "pump", 1), (3, "sell", "unavailable", 3), (3, "buy", "none", 3)],
)
def test_adjust_clamps_and_follows_regime(level, side, regime, expected):
    assert adjust(level, side, regime) == expected


# Confidence words shown on AlphaBTC (board "日内网格", intraday regime = pump):
# 5m BUY1 中等(3); 15m SELL1 弱(1), SELL2 中等偏弱(2); 1h BUY1 中等(3), BUY2 中等偏强(4);
# 4h SELL1 弱(1); 1d SELL1 弱(1).
@pytest.mark.parametrize(
    ("tf", "expected"),
    [
        ("5m", [("buy", True, 3), ("buy", False, None)]),
        ("15m", [("sell", True, 1), ("sell", True, 2)]),
        ("1h", [("buy", True, 3), ("buy", True, 4)]),
        ("4h", [("sell", True, 1), ("sell", False, None)]),
        ("1d", [("sell", True, 1), ("sell", False, None)]),
    ],
)
def test_intraday_levels_match_alphabtc_page(tf, expected):
    summary = _summary(tf)
    got = signals(derive_state(summary), summary, "pump", "decay")
    assert [(s.side, s.active, s.intraday_level) for s in got] == expected


def test_signal_prices_come_from_setup_and_thirteen_closes():
    summary = _summary("1h")
    one, two = signals(derive_state(summary), summary, "pump", "decay")
    assert one.price == summary.risk.setup_close
    assert two.price == summary.risk.close13
    assert (one.base_level, two.base_level) == (2, 3)
    assert (one.swing_level, two.swing_level) == (2, 3)


# 4h: the snapshot's second SELL setup completed 9 at 12:00; 5m: second SELL setup at 6.
def test_new_trend_follows_second_setup_during_countdown():
    trend = new_trend(_summary("4h"))
    assert (trend.present, trend.trend, trend.step, trend.confirmed) == (True, "up", 9, True)
    assert trend.seconds == 14400
    idle = new_trend(_summary("5m"))
    assert (idle.present, idle.trend, idle.step) == (True, "up", 6)
    assert idle.seconds == 1500


def test_deferred_thirteen_is_not_a_reversal():
    from test_sequential import BUY, dataset

    closes = BUY + [90, 89, 88, 87, 86, 85, 84, 94, 94, 93, 92, 91, 90, 89]
    data = dataset(closes)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], data.market_at)
    state = derive_state(summary)
    assert (state.s9, state.s13, state.countdown) == ("down", False, 12)
    assert regime_of(state, "simulated") == "rev"


# Times equal the snapshot's establishedTs / exhaustedTs / lastSignal / risk9Ts fields.
@pytest.mark.parametrize(
    ("tf", "setup9_at", "ago9", "qualified13_at", "ago13"),
    [
        ("5m", "2026-09-27T14:55:00+00:00", 5400, None, None),
        ("15m", "2026-09-26T13:45:00+00:00", 95400, "2026-09-27T01:45:00+00:00", 52200),
        ("1h", "2026-09-23T14:00:00+00:00", 352800, "2026-09-25T21:00:00+00:00", 154800),
        ("4h", "2026-09-22T00:00:00+00:00", 489600, None, None),
        ("1d", "2026-08-25T00:00:00+00:00", 2851200, None, None),
    ],
)
def test_signal_times_match_snapshot(tf, setup9_at, ago9, qualified13_at, ago13):
    state = derive_state(_summary(tf))
    assert state.setup9_at is not None and state.setup9_at.isoformat() == setup9_at
    assert state.setup9_seconds_ago == ago9
    got13 = state.qualified13_at.isoformat() if state.qualified13_at else None
    assert (got13, state.qualified13_seconds_ago) == (qualified13_at, ago13)


def test_beyond_risk9_compares_in_the_primary_direction():
    # Controller ruling: 15m carries the SELL 13 (s9 up) but risk9 belongs to the BUY
    # primary, so "beyond" means close below risk9 (AlphaBTC's carried direction would say True).
    fifteen = derive_state(_summary("15m"))
    assert (fifteen.s9, fifteen.beyond_risk9) == ("up", False)
    four = _summary("4h")  # uptrend primary, risk9 about 85,954
    assert derive_state(four).beyond_risk9 is False
    assert derive_state(four.model_copy(update={"close": "90000"})).beyond_risk9 is True
    one = _summary("1h")  # downtrend primary, risk9 about 81,788
    assert derive_state(one.model_copy(update={"close": "80000"})).beyond_risk9 is True
