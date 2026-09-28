"""TradingSignal-equivalent primary-sequence summary, pinned to captured snapshots."""

from decimal import Decimal

import pytest
from regime_fixture import (
    FIXTURE,
    FIXTURE_0350,
    FIXTURE_0400,
    FIXTURE_0407,
    FIXTURE_0416,
    FIXTURE_0431,
    FIXTURE_0915,
    TIMEFRAMES,
    V2,
    load_fixture,
    replay_dataset,
)
from test_sequential import BUY, dataset

from wheelhouse_service.indicators.demark import evaluate_demark
from wheelhouse_service.indicators.demark.summary import as_tradingsignal, summarize

STRUCTURAL = (
    "side", "regime", "phase", "step", "target", "setupStep", "countdownStep",
    "barsSinceQualified13", "lastSignal", "prev", "second", "rounds",
)
PRICES = ("riskLevel", "risk9", "setupClose", "close13", "tdst")
# TradingSignal computed this risk block one 5m bar after its across block (setup 4 vs 3).
RISK_ONE_BAR_LATER = {(FIXTURE_0915, "5m")}
FIXTURES = (
    FIXTURE, FIXTURE_0350, FIXTURE_0400, FIXTURE_0407, FIXTURE_0416, FIXTURE_0431, FIXTURE_0915
)
CASES = [(path, tf) for path in FIXTURES for tf in TIMEFRAMES]


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "strong"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _replay(tf, path=FIXTURE):
    data, as_of = replay_dataset(tf, path)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], as_of)
    assert summary is not None
    return as_tradingsignal(summary)


@pytest.mark.parametrize(("path", "tf"), CASES)
def test_structure_matches_tradingsignal(path, tf):
    expected = load_fixture(path)["timeframes"][tf]
    across, risk = _replay(tf, path)
    for key in STRUCTURAL:
        assert _strip(across.get(key)) == _strip(expected["across"].get(key)), key
    for key in ("provisional", "risk13Ts", "risk9Ts", "side"):
        assert risk[key] == expected["risk"][key], key
    assert risk["nextBarNeeds"]["direction"] == expected["risk"]["nextBarNeeds"]["direction"]
    if (path, tf) in RISK_ONE_BAR_LATER:
        return
    assert risk["setupRun"] == expected["risk"]["setupRun"]
    need = Decimal(str(expected["risk"]["nextBarNeeds"]["price"]))
    assert abs(Decimal(risk["nextBarNeeds"]["price"]) - need) < Decimal("1e-6")


@pytest.mark.parametrize(("path", "tf"), CASES)
def test_prices_match_tradingsignal(path, tf):
    expected = load_fixture(path)["timeframes"][tf]["risk"]
    _, risk = _replay(tf, path)
    for key in PRICES:
        assert (risk[key] is None) == (expected[key] is None), key
        if risk[key] is not None:
            # TradingSignal serialises floats (84632.79999999999); prices have one decimal.
            assert abs(Decimal(risk[key]) - Decimal(str(expected[key]))) < Decimal("1e-6"), key


def test_no_observed_sequence_returns_none():
    data = dataset([100, 101, 102])
    result = evaluate_demark(data, V2)
    assert summarize(result, [b.bar for b in data.bars], data.market_at) is None


def test_deferred_thirteen_reports_twelve_in_countdown():
    closes = BUY + [90, 89, 88, 87, 86, 85, 84, 94, 94, 93, 92, 91, 90, 89]
    data = dataset(closes)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], data.market_at)
    assert summary is not None
    assert summary.phase == "countdown"
    assert summary.step == 12
    assert summary.countdown_step == 12
