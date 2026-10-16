from datetime import timedelta

import httpx
import pytest
from test_data import START, batch

from wheelhouse_service.market import Stream
from wheelhouse_service.repository import Repository
from wheelhouse_service.sources import BybitSource, FetchError


def payload(rows):
    return {"retCode": 0, "result": {"category": "spot", "symbol": "BTCUSDT", "list": rows}}


def test_bybit_reverses_rows_and_keeps_forming_bar_out_of_closed_results():
    start = int(START.timestamp() * 1000)
    rows = [
        [str(start + 3600000), "100", "103", "99", "102", "3.123", "306"],
        [str(start), "99", "101", "98", "100", "2.456", "246"],
    ]
    stream = Stream(source="bybit", symbol="BTCUSDT", timeframe="1h")
    normalized = BybitSource.normalize(
        stream,
        rows,
        START + timedelta(hours=1, minutes=10),
        closed_before=START + timedelta(hours=1),
    )
    assert stream.venue == "bybit-spot"
    assert normalized.bars[0].open_time == START
    assert normalized.bars[0].close_time == START + timedelta(hours=1)
    assert normalized.bars[0].is_closed
    assert not normalized.bars[1].is_closed
    assert normalized.bars[0].volume == "2.456"
    assert normalized.raw_payload["category"] == "spot"


@pytest.mark.parametrize(
    ("timeframe", "interval"),
    [("5m", "5"), ("15m", "15"), ("1h", "60"), ("4h", "240"), ("1d", "D")],
)
def test_bybit_uses_spot_endpoint_with_correct_interval(timeframe, interval):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=payload(
                [[str(int(START.timestamp() * 1000)), "99", "101", "98", "100", "2", "200"]]
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        BybitSource(client).fetch(
            Stream(source="bybit", symbol="BTCUSDT", timeframe=timeframe), START
        )
    assert requests[0].url.host == "api.bybit.com"
    assert requests[0].url.path == "/v5/market/kline"
    assert requests[0].url.params["category"] == "spot"
    assert requests[0].url.params["interval"] == interval


@pytest.mark.parametrize(
    "body",
    [
        {"retCode": 10001},
        {"retCode": 0, "result": {"category": "linear", "symbol": "BTCUSDT", "list": []}},
        {"retCode": 0, "result": {"category": "spot", "symbol": "ETHUSDT", "list": []}},
    ],
)
def test_bybit_errors_or_wrong_instrument_do_not_fall_back(body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(FetchError):
            BybitSource(client).fetch(
                Stream(source="bybit", symbol="BTCUSDT", timeframe="1h"), START
            )


def test_bybit_and_binance_history_are_separate(tmp_path):
    repo = Repository(tmp_path / "isolation.sqlite")
    bybit = Stream(source="bybit", symbol="BTCUSDT", timeframe="1h")
    binance = Stream(source="binance", symbol="BTCUSDT", timeframe="1h")
    capture = batch().model_copy(update={"stream": binance})
    repo.ingest(capture)
    assert (
        repo.read(bybit, market_at=capture.fetched_at, knowledge_at=capture.fetched_at).bars == []
    )
    assert bybit.key != binance.key


def test_default_workspace_routes_btc_to_bybit_and_mu_eth_to_binance(tmp_path):
    from fastapi.testclient import TestClient

    from wheelhouse_service.http import create_app

    with TestClient(create_app(tmp_path / "api.sqlite", start_worker=False)) as client:
        for symbol, source, venue in [
            ("BTCUSDT", "bybit", "bybit-spot"),
            ("ETHUSDT", "binance", "binance-usdm-perpetual"),
            ("MUUSDT", "binance", "binance-usdm-perpetual"),
        ]:
            response = client.get("/api/wheelhouse/v1/workspace", params={"symbol": symbol})
            assert response.status_code == 200
            assert response.json()["stream"]["source"] == source
            assert response.json()["stream"]["venue"] == venue


@pytest.mark.parametrize(
    ("status", "body"), [(429, {}), (200, {"retCode": 10006}), (200, {"retCode": 10016})]
)
def test_transient_bybit_errors_remain_retryable(status, body):
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body))
    ) as client:
        with pytest.raises(FetchError) as caught:
            BybitSource(client).fetch(
                Stream(source="bybit", symbol="BTCUSDT", timeframe="1h"), START
            )
        assert caught.value.retryable
