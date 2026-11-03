import json
from collections.abc import Sequence
from datetime import UTC, date, datetime

import httpx
import pytest
from onchain_fixture import FIXTURES, brk_transport, load_series

from wheelhouse_service.onchain.brk import (
    AGE_COHORTS,
    AGE_SERIES,
    DAY1_SERIES,
    HOUR1_BACKFILL,
    HOUR1_SERIES,
    MAX_SERIES,
    MAX_SERIES_CHARS,
    SIZE_BANDS,
    START,
    BrkClient,
    BrkError,
    Urpd,
    remote_names,
)

NOW = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)


def client_for(transport: httpx.MockTransport) -> BrkClient:
    return BrkClient(httpx.Client(transport=transport), clock=lambda: NOW)


def wire(names: Sequence[str]) -> list[str]:
    """The names a request for `names` carries."""
    return [part for name in names for part in remote_names(name)]


def test_day1_backfill_is_split_by_weight():
    transport, calls = brk_transport()
    batch = client_for(transport).series(DAY1_SERIES, "day1", START)

    # 5,037 days per series: three series are 15,111 points (<= 18,000), four would be 20,148.
    bulk = [params for path, params in calls if path == "/api/series/bulk"]
    assert len(bulk) == 2
    assert [params["series"].split(",") for params in bulk] == [
        wire(DAY1_SERIES[:3]),
        wire(DAY1_SERIES[3:]),
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
        ("/api/series/bulk", ",".join(wire(DAY1_SERIES)), "6494")
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
    three = [wire(DAY1_SERIES[:3]), wire(DAY1_SERIES[3:])]
    four = [wire(DAY1_SERIES[:4]), wire(DAY1_SERIES[4:])]

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
    assert requested == [[name] for name in wire(DAY1_SERIES)]


def test_chunks_also_stay_under_the_series_length_limit():
    client, requested = hour1_client()
    # 32 of BRK's names stay under the limit (1,785 characters for its longest on 2026-11-04), so
    # these are longer than any of them: 100 characters, a request holds 19.
    names = [f"{n:03d}".ljust(100, "x") for n in range(64)]
    client.series(names, "hour1", 155_930)

    assert [name for chunk in requested for name in chunk] == names
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
        wire(HOUR1_SERIES[:6]),
        wire(HOUR1_SERIES[6:]),
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
        wire(DAY1_SERIES[:3]),
        wire(DAY1_SERIES[3:]),
        ["lth_realized_price"],
        ["realized_price"],
        ["age_1d_to_1w_realized_price"],
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


UPGRADE = FIXTURES.parent / "brk-2026-11-04"


def recording_client(
    data: dict[str, list[float | None]],
) -> tuple[BrkClient, list[list[str]]]:
    """A BRK after the upgrade: no `stamp`, `series_not_found` for a name not in `data`."""
    requested: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        names = request.url.params["series"].split(",")
        requested.append(names)
        if any(name not in data for name in names):
            return httpx.Response(404, json={"error": {"code": "series_not_found"}})
        body = [
            {"version": n + 1, "index": "hour1", "start": 10, "end": 13, "data": data[name]}
            for n, name in enumerate(names)
        ]
        return httpx.Response(200, json=body)

    return client_for(httpx.MockTransport(handler)), requested


def test_requests_use_the_upgraded_cohort_names_and_answer_with_the_local_ones():
    client, requested = recording_client(
        {
            "sth_supply_in_loss": [1.0, 2.0, 3.0],
            "age_under_1h_supply_in_loss": [4.0, 5.0, 6.0],
            "balance_1k_to_10k_sats_realized_cap": [7.0, 8.0, 9.0],
        }
    )
    batch = client.series(
        [
            "sth_supply_in_loss",
            "utxos_under_1h_old_supply_in_loss",
            "addrs_1k_sats_to_10k_sats_realized_cap",
        ],
        "hour1",
        -3,
    )

    assert requested == [
        ["sth_supply_in_loss", "age_under_1h_supply_in_loss", "balance_1k_to_10k_sats_realized_cap"]
    ]
    assert batch.missing == []
    assert batch.found["utxos_under_1h_old_supply_in_loss"].data == [4.0, 5.0, 6.0]
    assert batch.found["addrs_1k_sats_to_10k_sats_realized_cap"].data == [7.0, 8.0, 9.0]


def test_every_cohort_maps_to_one_upgraded_name_except_under_1k_sats():
    assert remote_names("utxos_1d_to_1w_old_realized_price") == ("age_1d_to_1w_realized_price",)
    assert remote_names("utxos_over_15y_old") == ("age_over_15y",)
    assert remote_names("addrs_10m_sats_to_1btc_supply") == ("balance_10m_to_100m_sats_supply",)
    assert remote_names("addrs_1btc_to_10btc_supply") == ("balance_1_to_10_btc_supply",)
    assert remote_names("addrs_under_1k_sats_supply") == (
        "balance_1_to_10_sats_supply",
        "balance_10_to_100_sats_supply",
        "balance_100_to_1k_sats_supply",
    )
    assert remote_names("price_close") == ("price_close",)
    # A cohort is matched whole: `sth` is not a prefix of anything renamed.
    assert remote_names("sth_realized_price") == ("sth_realized_price",)
    for cohort in AGE_COHORTS:
        assert len(remote_names(cohort)) == 1
    assert [len(remote_names(band)) for band in SIZE_BANDS] == [3] + [1] * 11


def test_under_1k_sats_is_the_sum_of_its_three_bands():
    client, requested = recording_client(
        {
            "balance_1_to_10_sats_supply": [0.01, None, 0.03],
            "balance_10_to_100_sats_supply": [0.1, 0.2, 0.3],
            "balance_100_to_1k_sats_supply": [30.0, 31.0, 32.0],
        }
    )
    batch = client.series(["addrs_under_1k_sats_supply"], "hour1", -3)

    assert requested == [
        [
            "balance_1_to_10_sats_supply",
            "balance_10_to_100_sats_supply",
            "balance_100_to_1k_sats_supply",
        ]
    ]
    summed = batch.found["addrs_under_1k_sats_supply"]
    # A part without a value leaves the sum without one; never counted as 0.
    assert summed.data == [pytest.approx(30.11), None, pytest.approx(32.33)]
    assert (summed.start, summed.end) == (10, 13)
    # Any part changing its version changes the sum's.
    assert summed.version == 1 + 2 + 3


def test_under_1k_sats_is_missing_when_one_of_its_bands_is():
    client, _ = recording_client(
        {
            "balance_1_to_10_sats_supply": [1.0, 1.0, 1.0],
            "balance_100_to_1k_sats_supply": [1.0, 1.0, 1.0],
            "price_close": [1.0, 1.0, 1.0],
        }
    )
    batch = client.series(["price_close", "addrs_under_1k_sats_supply"], "hour1", -3)

    assert batch.missing == ["addrs_under_1k_sats_supply"]
    assert set(batch.found) == {"price_close"}


def test_chunks_hold_at_most_32_series():
    client, requested = hour1_client()
    # Nine points a series, so neither the weight nor the length decides: BRK's count cap does.
    client.series(AGE_SERIES, "hour1", 155_930)

    assert len(AGE_SERIES) == 138
    assert [len(chunk) for chunk in requested] == [MAX_SERIES] * 4 + [138 - 4 * MAX_SERIES]
    assert MAX_SERIES == 32


def test_upgraded_series_response_without_stamp_parses():
    body = json.loads((UPGRADE / "bulk_hour1_156376.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    batch = client_for(httpx.MockTransport(handler)).series(
        ["price_close", "utxos_under_1h_old_supply_in_loss"], "hour1", 156_376
    )
    assert batch.found["price_close"].data == [77498.62, 77596.43]
    assert batch.found["utxos_under_1h_old_supply_in_loss"].start == 156_376


def test_upgraded_urpd_columns_become_buckets_under_the_local_cohort():
    def handler(request: httpx.Request) -> httpx.Response:
        _, _, _, cohort, day = request.url.path.split("/")
        return httpx.Response(
            200, content=(UPGRADE / f"urpd_{cohort}_lin500_{day}.json").read_bytes()
        )

    client = client_for(httpx.MockTransport(handler))
    day = date(2026, 11, 2)
    urpd = client.urpd("all", day)
    raw = json.loads((UPGRADE / "urpd_all_lin500_2026-11-02.json").read_text())

    assert urpd is not None
    assert (urpd.cohort, urpd.date, urpd.aggregation) == ("all", day, "lin500")
    assert urpd.total_supply == raw["supply"]
    assert [b.price_floor for b in urpd.buckets] == raw["buckets"]["price"]
    assert [b.supply for b in urpd.buckets] == raw["buckets"]["supply"]
    assert urpd.buckets[0].realized_cap == raw["buckets"]["realized_cap"][0]
    assert urpd.buckets[-1].unrealized_pnl == raw["buckets"]["unrealized_pnl"][-1]

    # An age cohort is asked for by its new name and stored under the old one.
    young = client.urpd("utxos_under_1h_old", day)
    assert young is not None and young.cohort == "utxos_under_1h_old"
    assert young.total_supply == pytest.approx(18476.77494155)
