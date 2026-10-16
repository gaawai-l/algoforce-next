"""TradingSignal-equivalent primary-sequence summary, pinned to captured snapshots."""

from decimal import Decimal

import pytest
from regime_fixture import (
    FIXTURE,
    FIXTURE_0400,
    FIXTURE_0416,
    FIXTURE_0928,
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
# Fields where Binance and TradingSignal's feed put a bar on different candles.
FEED_SENSITIVE = {
    # 5m's previous SELL 13 sits 2-7 USDT from its thresholds.
    FIXTURE: {"5m": {"prev", "barsSinceQualified13"}},
    # 15m's SELL 13 lands one bar later on Binance, as in the golden sample.
    FIXTURE_0928: {"15m": {"prev", "barsSinceQualified13"}},
    FIXTURE_0400: {"15m": {"prev", "barsSinceQualified13"}},
    FIXTURE_0416: {"15m": {"prev", "barsSinceQualified13"}},
}
# 5m's last SELL 13 is the golden sample's one, 28 bars apart between the feeds.
RISK_FEED_SENSITIVE = {FIXTURE_0416: {"5m": {"risk13Ts"}}}
PRICE_FEED_SENSITIVE = {
    # The countdown's lowest true lows differ by 3.8 USDT, so the feeds pick different
    # extreme bars (Binance's carries a 170 USDT wick).
    FIXTURE_0928: {"5m": {"riskLevel"}},
    FIXTURE_0416: {"5m": {"riskLevel"}},
}
PRICES = ("riskLevel", "risk9", "setupClose", "close13", "tdst")
FIXTURES = (FIXTURE, FIXTURE_0928, FIXTURE_0400, FIXTURE_0416)
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
        if key in FEED_SENSITIVE[path].get(tf, set()):
            continue
        assert _strip(across.get(key)) == _strip(expected["across"].get(key)), key
    for key in ("provisional", "risk13Ts", "risk9Ts", "side", "setupRun"):
        if key in RISK_FEED_SENSITIVE.get(path, {}).get(tf, set()):
            continue
        assert risk[key] == expected["risk"][key], key
    assert risk["nextBarNeeds"]["direction"] == expected["risk"]["nextBarNeeds"]["direction"]


@pytest.mark.parametrize(("path", "tf"), CASES)
def test_prices_differ_only_by_feed(path, tf):
    expected = load_fixture(path)["timeframes"][tf]["risk"]
    _, risk = _replay(tf, path)
    for key in PRICES:
        assert (risk[key] is None) == (expected[key] is None), key
        if risk[key] is not None and key not in PRICE_FEED_SENSITIVE.get(path, {}).get(tf, ()):
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
