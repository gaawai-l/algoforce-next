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


def test_usdt_perpetual_identity_and_mu_base_are_distinct_from_legacy_spot():
    for symbol in ("BTCUSDT", "ETHUSDT", "MUUSDT"):
        stream = Stream(source="binance", symbol=symbol, timeframe="1h")
        assert stream.venue == "binance-usdm-perpetual"
        assert stream.base_currency == symbol.removesuffix("USDT")
        legacy = Stream(source="binance", symbol=symbol, timeframe="1h", venue="binance-spot")
        assert legacy.key != stream.key
        assert Stream.model_validate_json(legacy.model_dump_json()).venue == "binance-spot"


def test_mu_fetch_uses_usdm_trade_klines_and_rejects_legacy_spot_jobs():
    seen = []
    start = int(START.timestamp() * 1000)

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200, json=[[start, "120", "122", "119", "121", "23", start + 3600000 - 1]]
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        stream = Stream(source="binance", symbol="MUUSDT", timeframe="1h")
        batch = BinanceSource(client).fetch(stream, START)
        assert str(seen[0].url).startswith("https://fapi.binance.com/fapi/v1/klines?")
        assert seen[0].url.params["symbol"] == "MUUSDT"
        assert batch.raw_payload["endpoint"] == "/fapi/v1/klines"
        with pytest.raises(FetchError, match="unsupported_market"):
            BinanceSource(client).fetch(stream.model_copy(update={"venue": "binance-spot"}), START)
        assert len(seen) == 1


def test_stored_spot_candles_do_not_populate_perpetual_workspace(tmp_path):
    from test_data import batch

    from wheelhouse_service.repository import Repository

    repo = Repository(tmp_path / "identity.sqlite")
    spot = Stream(source="binance", symbol="BTCUSDT", timeframe="1h", venue="binance-spot")
    perpetual = Stream(source="binance", symbol="BTCUSDT", timeframe="1h")
    capture = batch().model_copy(update={"stream": spot})
    repo.ingest(capture)
    arguments = {"market_at": capture.fetched_at, "knowledge_at": capture.fetched_at}
    assert repo.read(spot, **arguments).bars
    assert repo.read(perpetual, **arguments).bars == []
