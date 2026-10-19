import json
from datetime import UTC, date, datetime

import httpx
import pytest
from onchain_fixture import FIXTURES, brk_transport, load_series

from wheelhouse_service.onchain.brk import (
    AGE_SERIES,
    DAY1_SERIES,
    HOUR1_BACKFILL,
    HOUR1_SERIES,
    MAX_SERIES_CHARS,
    START,
    BrkClient,
    BrkError,
    Urpd,
)

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


def test_chunks_also_stay_under_the_series_length_limit():
    client, requested = hour1_client()
    # Incremental: 9 points a series would allow 2,000 names a request, so the length decides.
    client.series(AGE_SERIES, "hour1", 155_930)

    assert [name for chunk in requested for name in chunk] == list(AGE_SERIES)
    assert len(requested) == 4
    assert all(len(",".join(chunk)) <= MAX_SERIES_CHARS for chunk in requested)
    # Each chunk is as long as it can be: the next name would have taken it over the limit.
    assert all(
        len(",".join([*chunk, after[0]])) > MAX_SERIES_CHARS
        for chunk, after in zip(requested, requested[1:], strict=False)
    )


def test_hour1_series_are_the_eleven_planned_names():
    assert HOUR1_BACKFILL == 3000
    assert len(HOUR1_SERIES) == len(set(HOUR1_SERIES)) == 11
    # Time comes from the position, so no timestamp series is fetched.
    assert "timestamp" not in HOUR1_SERIES
    assert "price_close" in HOUR1_SERIES


def test_hour1_fixtures_end_at_the_same_hour_with_the_same_gaps():
    loaded = {name: load_series(name, "hour1") for name in HOUR1_SERIES}

    # Position 155,937 is 2026-10-16T09:00Z; hours without a block are null in every series.
    assert {(data.start, data.end) for data in loaded.values()} == {(153_338, 155_938)}
    gaps = {
        tuple(i for i, value in enumerate(data.data) if value is None) for data in loaded.values()
    }
    assert len(gaps) == 1
    assert len(next(iter(gaps))) == 11
    assert all(data.data[-1] is not None for data in loaded.values())


def test_hour1_backfill_uses_negative_start_and_two_chunks():
    transport, calls = brk_transport()
    batch = client_for(transport).series(HOUR1_SERIES, "hour1", -3000)

    # 3,000 points per series: six series are 18,000 points (the cap), so 11 names are 6 + 5.
    bulk = [params for path, params in calls if path == "/api/series/bulk"]
    assert len(bulk) == 2
    assert [params["series"].split(",") for params in bulk] == [
        list(HOUR1_SERIES[:6]),
        list(HOUR1_SERIES[6:]),
    ]
    assert all(params["index"] == "hour1" and params["start"] == "-3000" for params in bulk)
    assert set(batch.found) == set(HOUR1_SERIES)
    assert batch.missing == []
    # The fixtures hold 2,600 hours, so the replay returns everything it has.
    for name in HOUR1_SERIES:
        assert batch.found[name].start == 153_338
        assert batch.found[name].data == load_series(name, "hour1").data


def test_negative_start_points_estimate():
    # The clock does not matter: a negative start is "the last N points".
    for now in (NOW, datetime(2030, 1, 1, tzinfo=UTC)):
        client = BrkClient(clock=lambda now=now: now)
        assert client._points("hour1", -3000) == 3000
        assert client._points("day1", -3000) == 3000
    # A non-negative position still counts up to the latest one: 155,938 - 155,934 + 1.
    assert BrkClient(clock=lambda: NOW)._points("hour1", 155_934) == 5


def test_negative_start_replay_returns_last_rows_at_their_absolute_position():
    transport, _ = brk_transport()
    with httpx.Client(transport=transport, base_url="https://brk.test") as http:
        response = http.get(
            "/api/series/bulk",
            params={"series": "price_close,sth_supply_in_loss", "index": "hour1", "start": "-4"},
        )
        too_heavy = http.get(
            "/api/series/bulk",
            params={
                "series": ",".join(HOUR1_SERIES[:7]),
                "index": "hour1",
                "start": "-3000",
            },
        )

    body = response.json()
    assert [(item["start"], item["end"]) for item in body] == [(155_934, 155_938)] * 2
    assert body[0]["data"] == load_series("price_close", "hour1").data[-4:]
    assert body[1]["data"] == load_series("sth_supply_in_loss", "hour1").data[-4:]
    # 7 series x 3,000 points x 16 weight is over the 320,000 cap, as on the live API.
    assert too_heavy.status_code == 400
    assert too_heavy.json()["error"]["code"] == "weight_exceeded"


def test_replay_serves_a_request_older_than_the_fixture_from_its_own_start():
    transport, _ = brk_transport()
    batch = client_for(transport).series(["price_close"], "hour1", 140_000)

    # The fixture holds 2,600 hours; the body says where its first row really is.
    assert batch.found["price_close"].start == 153_338
    assert batch.found["price_close"].data == load_series("price_close", "hour1").data


def test_fail_index_fails_only_that_index_with_a_retryable_error():
    transport, calls = brk_transport(fail_index={"hour1"})
    client = client_for(transport)

    with pytest.raises(BrkError) as raised:
        client.series(HOUR1_SERIES, "hour1", -3000)
    assert (raised.value.code, raised.value.retryable) == ("brk_unavailable", True)
    assert [params["index"] for _, params in calls] == ["hour1"]

    assert set(client.series(DAY1_SERIES, "day1", 6494).found) == set(DAY1_SERIES)


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
