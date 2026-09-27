"""TradingSignal-equivalent primary-sequence summary, pinned to the 2026-09-27 snapshot."""

from decimal import Decimal

import pytest
from regime_fixture import TIMEFRAMES, V2, load_fixture, replay_dataset
from test_sequential import BUY, dataset

from wheelhouse_service.indicators.demark import evaluate_demark
from wheelhouse_service.indicators.demark.summary import as_tradingsignal, summarize

STRUCTURAL = (
    "side", "regime", "phase", "step", "target", "setupStep", "countdownStep",
    "barsSinceQualified13", "lastSignal", "prev", "second", "rounds",
)
# 5m's previous SELL 13 sits 2-7 USDT from its thresholds; the feeds disagree there.
FEED_SENSITIVE = {"5m": {"prev", "barsSinceQualified13"}}
PRICES = ("riskLevel", "risk9", "setupClose", "close13", "tdst")


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "strong"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _replay(tf):
    data, as_of = replay_dataset(tf)
    summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], as_of)
    assert summary is not None
    return as_tradingsignal(summary)


@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_structure_matches_tradingsignal(tf):
    expected = load_fixture()["timeframes"][tf]
    across, risk = _replay(tf)
    for key in STRUCTURAL:
        if key in FEED_SENSITIVE.get(tf, set()):
            continue
        assert _strip(across.get(key)) == _strip(expected["across"].get(key)), key
    for key in ("provisional", "risk13Ts", "risk9Ts", "side", "setupRun"):
        assert risk[key] == expected["risk"][key], key
    assert risk["nextBarNeeds"]["direction"] == expected["risk"]["nextBarNeeds"]["direction"]


@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_prices_differ_only_by_feed(tf):
    expected = load_fixture()["timeframes"][tf]["risk"]
    _, risk = _replay(tf)
    for key in PRICES:
        assert (risk[key] is None) == (expected[key] is None), key
        if risk[key] is not None:
            # Binance vs TradingSignal's feed: largest observed gap is 64.54 (4h risk9).
            assert abs(Decimal(risk[key]) - Decimal(str(expected[key]))) <= 70, key


def test_15m_prices_are_exact_on_tradingsignal_candles():
    expected = load_fixture()["timeframes"]["15m"]["risk"]
    _, risk = _replay("15m")
    for key in ("risk9", "setupClose", "riskLevel", "tdst"):
        assert abs(Decimal(risk[key]) - Decimal(str(expected[key]))) < Decimal("1e-6"), key


def test_5m_previous_thirteen_is_the_locally_observed_one():
    across, _ = _replay("5m")
    assert across["prev"] == {"side": "SELL", "countdown": 13, "qualified": True, "barsAgo": 35}


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
