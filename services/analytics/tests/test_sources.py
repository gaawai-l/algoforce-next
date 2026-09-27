from datetime import timedelta

import httpx
import pytest
from test_data import START

from wheelhouse_service.market import Stream
from wheelhouse_service.sources import BinanceSource, FetchError, FixtureSource


def test_official_candle_boundary_and_decimal_precision_are_normalized():
    stream = Stream(source="binance", symbol="BTCUSDT", timeframe="1h")
    start = int(START.timestamp() * 1000)
    rows = [[start, "100.12345678", "101.5", "99.1", "100.3", None, start + 3600000 - 1]]
    during = BinanceSource.normalize(
        stream, rows, START + timedelta(minutes=30), closed_before=START + timedelta(minutes=30)
    )
    closed = BinanceSource.normalize(
        stream, rows, START + timedelta(hours=1), closed_before=START + timedelta(hours=1)
    )
    assert during.bars[0].is_closed is False
    assert closed.bars[0].is_closed is True
    assert closed.bars[0].close_time == START + timedelta(hours=1)
    assert closed.bars[0].open == "100.12345678"
    assert closed.bars[0].volume is None
    assert closed.raw_payload["rows"] == rows


def test_provider_outage_has_no_synthetic_fallback():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        with pytest.raises(FetchError, match="provider_unavailable"):
            BinanceSource(client).fetch(
                Stream(source="binance", symbol="BTCUSDT", timeframe="1h"), START
            )


def test_fixture_is_deterministic_and_uses_the_same_batch_contract():
    stream = Stream(source="fixture", symbol="BTCUSDT", timeframe="5m")
    first = FixtureSource().fetch(stream, START)
    assert first == FixtureSource().fetch(stream, START)
    assert first.stream.source == "fixture"
    assert len(first.bars) == 320
    assert all(bar.close_time <= first.fetched_at for bar in first.bars)


def test_request_crossing_close_boundary_does_not_finalize_a_forming_sample():
    stream = Stream(source="binance", symbol="BTCUSDT", timeframe="1h")
    start = int(START.timestamp() * 1000)
    rows = [[start, "100", "101", "99", "100", "12", start + 3600000 - 1]]
    received = START + timedelta(hours=1, seconds=1)
    sampled = START + timedelta(minutes=59, seconds=59)
    result = BinanceSource.normalize(stream, rows, received, closed_before=sampled)
    assert result.bars[0].is_closed is False
    assert result.fetched_at == received
