import json
from datetime import UTC, date, datetime

import httpx
import pytest
from onchain_fixture import FIXTURES, brk_transport, load_series

from wheelhouse_service.onchain.brk import DAY1_SERIES, START, BrkClient, BrkError, Urpd

NOW = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)


def client_for(transport: httpx.MockTransport) -> BrkClient:
    return BrkClient(httpx.Client(transport=transport), clock=lambda: NOW)


def test_day1_backfill_is_split_by_weight():
    transport, calls = brk_transport()
    batch = client_for(transport).series(DAY1_SERIES, "day1", START)

    # 5,037 days per series: three series are 15,111 points (<= 18,000), four would be 20,148.
    bulk = [params for path, params in calls if path == "/api/series/bulk"]
    assert len(bulk) == 2
    assert [params["series"].split(",") for params in bulk] == [
        list(DAY1_SERIES[:3]),
        list(DAY1_SERIES[3:]),
    ]
    assert all(params["index"] == "day1" and params["start"] == "2013-01-01" for params in bulk)
    assert set(batch.found) == set(DAY1_SERIES)
    assert batch.missing == []
    # The array comes back without names; each series must be matched to its own request slot.
    for name in DAY1_SERIES:
        assert batch.found[name].start == 1461
        assert batch.found[name].data == load_series(name, "day1").data


def test_incremental_start_position_estimates_points():
    transport, calls = brk_transport()
    batch = client_for(transport).series(DAY1_SERIES, "day1", 6494)

    # Positions 6494..6497 (today) are 4 points, so all six series fit in one request.
    assert [(path, params["series"], params["start"]) for path, params in calls] == [
        ("/api/series/bulk", ",".join(DAY1_SERIES), "6494")
    ]
    assert set(batch.found) == set(DAY1_SERIES)
    assert batch.found["price_close"].start == 6494
    assert batch.found["price_close"].data == load_series("price_close", "day1").data[-4:]


def hour1_client() -> tuple[BrkClient, list[list[str]]]:
    """A BRK that answers every hour1 request with empty series; records the names asked."""
    requested: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        names = request.url.params["series"].split(",")
        requested.append(names)
        empty = {"version": 1, "index": "hour1", "start": 0, "end": 0, "stamp": "2026-10-16T10:00Z"}
        return httpx.Response(200, json=[{**empty, "data": []} for _ in names])

    return client_for(httpx.MockTransport(handler)), requested


def test_chunk_size_follows_the_point_estimate():
    three = [list(DAY1_SERIES[:3]), list(DAY1_SERIES[3:])]
    four = [list(DAY1_SERIES[:4]), list(DAY1_SERIES[4:])]

    # Today is day1 position 6497: 4,500 points still allow 4 series per request, 4,501 only 3.
    for start, expected in ((1998, four), (1997, three)):
        transport, calls = brk_transport()
        client_for(transport).series(DAY1_SERIES, "day1", start)
        assert [params["series"].split(",") for _, params in calls] == expected

    # At 10:00Z the latest hour1 position is 6497 * 24 + 10 = 155,938.
    for start, expected in ((151_439, four), (151_438, three)):
        client, requested = hour1_client()
        client.series(DAY1_SERIES, "hour1", start)
        assert requested == expected

    # A date start counts in hours too: 2013-01-01 is ~120,000 points, so one series per request.
    client, requested = hour1_client()
    client.series(DAY1_SERIES, "hour1", START)
    assert requested == [[name] for name in DAY1_SERIES]


def test_bulk_series_not_found_retries_each_series():
    transport, calls = brk_transport(missing={"lth_realized_price"})
    batch = client_for(transport).series(DAY1_SERIES, "day1", START)

    assert batch.missing == ["lth_realized_price"]
    assert set(batch.found) == set(DAY1_SERIES) - {"lth_realized_price"}
    # The first slice succeeds; the slice holding the unknown name fails, then each name goes alone.
    assert [params["series"].split(",") for _, params in calls] == [
        list(DAY1_SERIES[:3]),
        list(DAY1_SERIES[3:]),
        ["lth_realized_price"],
        ["realized_price"],
        ["utxos_1d_to_1w_old_realized_price"],
    ]


def test_unreachable_brk_raises_retryable_error():
    transport, _ = brk_transport(fail_paths={"/"})
    with pytest.raises(BrkError) as raised:
        client_for(transport).series(DAY1_SERIES, "day1", START)
    assert raised.value.code == "brk_unavailable"
    assert raised.value.retryable is True


def test_urpd_404_returns_none_and_parses_buckets():
    transport, calls = brk_transport(urpd_dates={date(2026, 10, 16)})
    client = client_for(transport)

    assert client.urpd("all", date(2026, 10, 17)) is None

    urpd = client.urpd("all", date(2026, 10, 16))
    assert isinstance(urpd, Urpd)
    assert calls[-1] == ("/api/urpd/all/2026-10-16", {"agg": "lin500"})
    assert (urpd.cohort, urpd.date, urpd.aggregation) == ("all", date(2026, 10, 16), "lin500")
    # The captured response carries a `weight` field the client does not model.
    assert json.loads((FIXTURES / "urpd_all_lin500.json").read_text())["weight"] == "raw"
    assert not hasattr(urpd, "weight")
    floors = [bucket.price_floor for bucket in urpd.buckets]
    assert len(floors) > 1
    assert {later - earlier for earlier, later in zip(floors, floors[1:], strict=False)} == {500.0}


def test_http_failures_map_to_retryable_and_bad_request_errors():
    assert client_for(brk_transport(version="0.12.2")[0]).version() == "0.12.2"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def weight_exceeded(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "weight_exceeded"}})

    cases = [
        (lambda request: httpx.Response(429), "brk_unavailable", True),
        (lambda request: httpx.Response(500), "brk_unavailable", True),
        (timeout, "brk_unavailable", True),
        (lambda request: httpx.Response(200, json={"not": "a list"}), "brk_unavailable", True),
        (lambda request: httpx.Response(200, json=[]), "brk_unavailable", True),
        (weight_exceeded, "brk_bad_request", False),
        (
            lambda request: httpx.Response(404, json={"error": {"code": "not_found"}}),
            "brk_bad_request",
            False,
        ),
    ]
    for handler, code, retryable in cases:
        client = client_for(httpx.MockTransport(handler))
        with pytest.raises(BrkError) as raised:
            client.series(["price_close"], "day1", 6494)
        assert (raised.value.code, raised.value.retryable) == (code, retryable)
