"""Public perp REST data: paging, closed bars, the daily OI archive and per-host backoff."""

import io
import json
import threading
import time
import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from wheelhouse_service.perps.grid import build_grid
from wheelhouse_service.perps.rows import Kline, OiPoint
from wheelhouse_service.perps.sources import (
    ARCHIVE_HOST,
    BINANCE_HOST,
    BYBIT_HOST,
    PerpsRest,
    RestError,
)
from wheelhouse_service.perps.states import Grid
from wheelhouse_service.perps.store import PerpsStore

STEP = 600
T0 = 1_792_022_400  # 2026-10-15 00:00 UTC
DAY_END = T0 + 86_400
FIXTURE = Path(__file__).parent / "fixtures" / "public-2026-10-15"
# After the whole of 2026-10-15 has closed.
NOW = datetime(2026, 10, 16, 7, 0, tzinfo=UTC)


def at(hm: str) -> int:
    hours, minutes = hm.split(":")
    return T0 + int(hours) * 3600 + int(minutes) * 60


def idx(hm: str) -> int:
    return (at(hm) - T0) // STEP


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def clock_at(hm: str) -> Clock:
    return Clock(datetime.fromtimestamp(at(hm), UTC))


def hist_reply(rows: list[dict[str, Any]], query: Mapping[str, str]) -> list[dict[str, Any]]:
    """openInterestHist as the live endpoint answers: with no endTime the latest `limit` rows,
    whatever the startTime; with both ends the rows in [startTime, endTime], oldest first."""
    limit = int(query["limit"])
    if "endTime" not in query:
        return rows[-limit:]
    window = [r for r in rows if int(query["startTime"]) <= r["timestamp"] <= int(query["endTime"])]
    return window[:limit]


class Exchange:
    """The 2026-10-15 fixtures behind the hosts' routes, honouring the paging parameters."""

    def __init__(self, archive: bytes | None = None, oi_rows: int = 5) -> None:
        self.requests: list[httpx.Request] = []
        self.archive = archive
        self.klines = json.loads((FIXTURE / "binance_klines_5m.json").read_text())
        self.hist = json.loads((FIXTURE / "binance_oi_hist_5m.json").read_text())
        self.spot = json.loads((FIXTURE / "bybit_spot_klines_5m.json").read_text())
        # Bybit OI, newest first; `openInterest` counts both sides, as the real field does.
        self.bybit_oi = [
            {
                "openInterest": str(2 * (1000 + i)),
                "singleOpenInterest": str(1000 + i),
                "timestamp": str((T0 + i * 300) * 1000),
            }
            for i in reversed(range(oi_rows))
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path, query = request.url.host, request.url.path, request.url.params
        if (host, path) == (BINANCE_HOST, "/fapi/v1/klines"):
            rows = [
                row
                for row in self.klines
                if int(query["startTime"]) <= row[0] <= int(query["endTime"])
            ]
            return httpx.Response(200, json=rows[: int(query["limit"])])
        if (host, path) == (BINANCE_HOST, "/futures/data/openInterestHist"):
            return httpx.Response(200, json=hist_reply(self.hist, query))
        if (host, path) == (BYBIT_HOST, "/v5/market/kline"):
            # Live behaviour (checked 2026-10-16): of the rows in [start, end] it returns the
            # NEWEST `limit`, newest first - not the oldest `limit` of the range.
            rows = sorted(
                (
                    row
                    for row in self.spot["result"]["list"]
                    if int(query["start"]) <= int(row[0]) <= int(query["end"])
                ),
                key=lambda row: int(row[0]),
                reverse=True,
            )
            result = {**self.spot["result"], "list": rows[: int(query["limit"])]}
            return httpx.Response(200, json={**self.spot, "result": result})
        if (host, path) == (BYBIT_HOST, "/v5/market/open-interest"):
            offset, limit = int(query.get("cursor", "0")), int(query["limit"])
            following = offset + limit
            result = {
                "category": "linear",
                "symbol": "BTCUSDT",
                "list": self.bybit_oi[offset:following],
                "nextPageCursor": str(following) if following < len(self.bybit_oi) else "",
            }
            return httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": result})
        if host == ARCHIVE_HOST:
            if self.archive is None:
                return httpx.Response(404)
            return httpx.Response(200, content=self.archive)
        raise AssertionError(f"unexpected request {request.url}")


def rest_of(
    handler: Callable[[httpx.Request], httpx.Response],
    clock: Clock | None = None,
    **limits: int,
) -> PerpsRest:
    return PerpsRest(
        httpx.Client(transport=httpx.MockTransport(handler)),
        clock or Clock(),
        page_limits=limits,
    )


def scripted(
    respond: Callable[[int], httpx.Response], sent: list[httpx.Request]
) -> Callable[[httpx.Request], httpx.Response]:
    """A handler answering the n-th request with `respond(n)`, recording each in `sent`."""

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return respond(len(sent) - 1)

    return handler


def empty_ok(_: int) -> httpx.Response:
    return httpx.Response(200, json=[])


def bybit_ok(result: object) -> httpx.Response:
    return httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": result})


# --- Paging and closed bars. ---


def test_binance_klines_pages_and_maps_fields():
    exchange = Exchange()
    rest = rest_of(exchange, binance_klines=100)

    klines = rest.binance_klines(T0, DAY_END)

    assert len(klines) == 288
    assert [k.t for k in klines] == list(range(T0, DAY_END, 300))
    assert klines[0] == Kline(
        t=T0, close=81783.4, volume=352.686, taker_buy=205.552, source="binance_perp"
    )
    assert len(exchange.requests) == 3
    first, second, third = (r.url.params for r in exchange.requests)
    assert (first["symbol"], first["interval"], first["limit"]) == ("BTCUSDT", "5m", "100")
    assert first["startTime"] == str(T0 * 1000)
    assert first["endTime"] == str(DAY_END * 1000 - 1)  # `end` is exclusive
    assert second["startTime"] == str((T0 + 100 * 300) * 1000)
    assert third["startTime"] == str((T0 + 200 * 300) * 1000)
    assert exchange.requests[0].extensions["timeout"]["read"] == 20.0


def windows_of(exchange: Exchange) -> list[tuple[int, int]]:
    """(startTime, endTime) in ms of each request."""
    return [
        (int(r.url.params["startTime"]), int(r.url.params["endTime"])) for r in exchange.requests
    ]


def test_binance_oi_hist_pages_in_explicit_windows():
    exchange = Exchange()
    rest = rest_of(exchange, clock_at("23:55"), binance_oi_hist=100)

    points = rest.binance_oi_hist(T0)

    assert [p.t for p in points] == list(range(T0, DAY_END, 300))
    assert points[0] == OiPoint(t=T0, oi=93117.263, source="hist")
    # Every request names both ends. The windows are half-open, `limit` periods wide, and tile
    # without a gap or an overlap.
    span = 100 * 300 * 1000
    assert windows_of(exchange) == [
        (T0 * 1000 + span * i, T0 * 1000 + span * (i + 1) - 1) for i in range(3)
    ]
    assert {(r.url.params["period"], r.url.params["limit"]) for r in exchange.requests} == {
        ("5m", "100")
    }


def test_binance_oi_hist_unaligned_start_loses_no_period():
    exchange = Exchange()
    rest = rest_of(exchange, clock_at("23:55"), binance_oi_hist=10)

    points = rest.binance_oi_hist(T0 + 100)

    # Every period stamped after the start, though no window edge falls on one.
    assert [p.t for p in points] == list(range(T0 + 300, DAY_END, 300))
    windows = windows_of(exchange)
    assert windows[0][0] == (T0 + 100) * 1000
    assert all(end - start + 1 == 10 * 300 * 1000 for start, end in windows)
    assert all(b[0] == a[1] + 1 for a, b in zip(windows, windows[1:], strict=False))


def test_binance_oi_hist_does_not_rely_on_start_time_alone():
    # Periods 4-7 have no record: an empty window must not stop or stall the paging.
    present = [0, 1, 2, 3, 8, 9]
    rows = [{"timestamp": (T0 + i * 300) * 1000, "sumOpenInterest": str(100 + i)} for i in present]
    # The mimic is the live endpoint: asked from T0 with no endTime it skips straight to the end.
    assert [r["sumOpenInterest"] for r in hist_reply(rows, {"startTime": "0", "limit": "4"})] == [
        "102",
        "103",
        "108",
        "109",
    ]
    sent: list[httpx.Request] = []
    rest = rest_of(
        scripted(lambda n: httpx.Response(200, json=hist_reply(rows, sent[n].url.params)), sent),
        Clock(datetime.fromtimestamp(T0 + 9 * 300, UTC)),
        binance_oi_hist=4,
    )

    points = rest.binance_oi_hist(T0)

    assert [(p.t, p.oi) for p in points] == [(T0 + i * 300, 100.0 + i) for i in present]
    assert len(sent) == 3  # periods 0-3, 4-7 (empty), 8-11
    assert all("endTime" in r.url.params for r in sent)


def test_bybit_spot_klines_page_back_and_return_oldest_first():
    exchange = Exchange()
    rest = rest_of(exchange, bybit_spot_klines=100)

    klines = rest.bybit_spot_klines(T0, DAY_END)

    assert [k.t for k in klines] == list(range(T0, DAY_END, 300))
    assert klines[1] == Kline(
        t=T0 + 300, close=81741.4, volume=None, taker_buy=None, source="bybit_spot"
    )
    assert len(exchange.requests) == 3
    first, second, _ = (r.url.params for r in exchange.requests)
    assert (first["category"], first["interval"]) == ("spot", "5")
    assert first["end"] == str(DAY_END * 1000 - 1)
    # The next page ends just before the oldest row of the previous one.
    assert second["end"] == str((DAY_END - 100 * 300) * 1000 - 1)


def test_bybit_oi_follows_cursor_and_uses_single_sided_oi():
    exchange = Exchange(oi_rows=5)
    rest = rest_of(exchange, bybit_oi=2)

    points = rest.bybit_oi(T0, T0 + 3600)

    assert points == [OiPoint(t=T0 + i * 300, oi=1000.0 + i, source="bybit") for i in range(5)]
    assert [r.url.params.get("cursor") for r in exchange.requests] == [None, "2", "4"]
    params = exchange.requests[0].url.params
    assert (params["category"], params["intervalTime"], params["limit"]) == ("linear", "5min", "2")
    assert params["startTime"] == str(T0 * 1000)
    assert params["endTime"] == str((T0 + 3600) * 1000 - 1)


@pytest.mark.parametrize("fetch", ["binance_klines", "bybit_spot_klines"])
def test_unclosed_klines_filtered_with_injected_clock(fetch: str):
    # 12:05's bar closes at 12:10, after the clock.
    rest = rest_of(Exchange(), clock_at("12:07"))
    klines = getattr(rest, fetch)(at("11:50"), DAY_END)
    assert [k.t for k in klines] == [at("11:50"), at("11:55"), at("12:00")]

    # A bar is closed from the instant it ends.
    rest = rest_of(Exchange(), clock_at("12:10"))
    klines = getattr(rest, fetch)(at("11:50"), DAY_END)
    assert klines[-1].t == at("12:05")


# --- The daily OI archive. ---


def zip_of(csv_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTCUSDT-metrics-2026-10-15.csv", csv_text)
    return buffer.getvalue()


def metrics_csv(rows: list[tuple[str, float]]) -> str:
    """A daily file with the real header; `rows` are (HH:MM:SS, sum_open_interest) in file order."""
    head = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio"
    )
    lines = [f"2026-10-15 {hms},BTCUSDT,{oi},1.0,1.0,1.0,1.0,1.0" for hms, oi in rows]
    return "\n".join([head, *lines]) + "\n"


def archive_of(rows: list[tuple[str, float]]) -> tuple[list[OiPoint], bool]:
    result = rest_of(Exchange(zip_of(metrics_csv(rows)))).binance_oi_archive(date(2026, 10, 15))
    assert result is not None
    return result


def test_archive_missing_day_is_none():
    exchange = Exchange(archive=None)
    assert rest_of(exchange).binance_oi_archive(date(2026, 10, 16)) is None
    request = exchange.requests[0]
    assert request.url.host == ARCHIVE_HOST
    assert request.url.path == (
        "/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-10-16.zip"
    )


def test_archive_dedupes_and_sorts():
    # Unsorted, with the 00:05 row twice: de-duplicated before looking for equal values.
    points, quarantined = archive_of(
        [("00:10:00", 102.0), ("00:00:00", 100.0), ("00:05:00", 101.0)]
        + [("00:05:00", 101.0), ("00:15:00", 103.0)]
    )

    assert not quarantined
    # Stamped like hist: create_time + 5m.
    assert points == [
        OiPoint(t=T0 + 300 + i * 300, oi=100.0 + i, source="archive") for i in range(4)
    ]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        pytest.param([100, 101, 0, 102, 103], [100, 101, None, None, None], id="zero"),
        pytest.param([-1, 100, 101], [None, None, None], id="negative"),
        # The quarantine starts at the first row of the equal pair, not the second.
        pytest.param([100, 101, 101, 102, 103], [100, None, None, None, None], id="equal-pair"),
        pytest.param([100, 101, 101, 101, 102], [100, None, None, None, None], id="equal-run"),
        pytest.param([100, 101, 100, 101, 100], [100, 101, 100, 101, 100], id="not-adjacent"),
    ],
)
def test_archive_quarantines_from_the_first_anomaly(
    values: list[float], expected: list[float | None]
):
    rows = [(f"00:{5 * i:02d}:00", float(v)) for i, v in enumerate(values)]

    points, quarantined = archive_of(rows)

    assert [p.oi for p in points] == expected
    assert quarantined == (None in expected)
    assert [p.t for p in points] == [T0 + 300 + 300 * i for i in range(len(values))]


def test_archive_quarantine_1015(tmp_path: Path):
    exchange = Exchange(archive=zip_of((FIXTURE / "BTCUSDT-metrics-2026-10-15.csv").read_text()))
    rest = rest_of(exchange)

    result = rest.binance_oi_archive(date(2026, 10, 15))

    assert result is not None
    points, quarantined = result
    assert quarantined
    assert [p.t for p in points] == list(range(T0 + 300, DAY_END + 300, 300))
    assert {p.source for p in points} == {"archive"}
    hist = {row["timestamp"] // 1000: float(row["sumOpenInterest"]) for row in exchange.hist}
    # The stale value starts at create_time 10:50, i.e. oi.t 10:55.
    assert [p.t for p in points if p.oi is None] == list(range(at("10:55"), DAY_END + 300, 300))
    assert all(p.oi == hist[p.t] for p in points if p.oi is not None)

    # With only the archive feeding Binance OI the grid is null from bucket 10:50 on,
    # and equal to hist at bucket 10:40.
    store = PerpsStore(tmp_path / "perps.sqlite3")
    store.upsert_klines("binance", rest.binance_klines(T0, DAY_END))
    store.upsert_klines("bybit", rest.bybit_spot_klines(T0, DAY_END))
    store.upsert_oi("binance", points)
    grid = build_grid(store, "binance", T0)
    assert isinstance(grid, Grid), grid
    assert grid.last == at("23:50")
    assert grid.oi[idx("10:40")] == hist[at("10:50")]
    assert grid.oi[idx("10:50") :] == [None] * (idx("23:50") - idx("10:50") + 1)
    assert grid.quarantined_days == 1


# --- Etiquette: one request at a time, per-host backoff. ---


@pytest.mark.parametrize(("status", "minutes"), [(429, 2), (418, 30), (403, 30)])
def test_binance_429_403_418_backoff(status: int, minutes: int):
    clock, sent = Clock(), []
    rest = rest_of(
        scripted(lambda n: httpx.Response(status) if n == 0 else empty_ok(n), sent), clock
    )

    with pytest.raises(RestError) as caught:
        rest.binance_klines(T0, T0 + STEP)

    until = NOW + timedelta(minutes=minutes)
    assert (caught.value.host, caught.value.code, caught.value.until) == (
        BINANCE_HOST,
        str(status),
        until,
    )
    assert rest.backoff_until(BINANCE_HOST) == until

    # Until the deadline every call for the host raises and nothing is sent.
    clock.now = until - timedelta(seconds=1)
    for call in (lambda: rest.binance_klines(T0, T0 + STEP), lambda: rest.binance_oi_hist(T0)):
        with pytest.raises(RestError) as again:
            call()
        assert (again.value.host, again.value.until) == (BINANCE_HOST, until)
    assert len(sent) == 1

    clock.now = until
    assert rest.backoff_until(BINANCE_HOST) is None
    assert rest.binance_klines(T0, T0 + STEP) == []
    assert len(sent) == 2


@pytest.mark.parametrize(
    ("retry_after", "minutes"),
    [
        pytest.param("600", 10, id="seconds-longer"),
        pytest.param("30", 2, id="seconds-shorter-than-table"),
        pytest.param(format_datetime(NOW + timedelta(minutes=45), usegmt=True), 45, id="http-date"),
        pytest.param("soon", 2, id="unparseable"),
    ],
)
def test_retry_after_wins_when_longer(retry_after: str, minutes: int):
    sent: list[httpx.Request] = []
    rest = rest_of(
        scripted(lambda n: httpx.Response(429, headers={"Retry-After": retry_after}), sent)
    )

    with pytest.raises(RestError) as caught:
        rest.binance_oi_hist(T0)

    assert caught.value.until == NOW + timedelta(minutes=minutes)


def test_backoff_is_per_host():
    clock = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == BINANCE_HOST:
            return httpx.Response(429)
        if host == BYBIT_HOST:
            return httpx.Response(403)
        return httpx.Response(404)

    rest = rest_of(handler, clock)
    with pytest.raises(RestError):
        rest.binance_klines(T0, T0 + STEP)
    with pytest.raises(RestError):
        rest.bybit_oi(T0, T0 + STEP)

    assert rest.backoff_until(BINANCE_HOST) == NOW + timedelta(minutes=2)
    assert rest.backoff_until(BYBIT_HOST) == NOW + timedelta(minutes=10)
    assert rest.backoff_until(ARCHIVE_HOST) is None
    # The archive host is neither of the backed off ones.
    assert rest.binance_oi_archive(date(2026, 10, 15)) is None

    clock.now = NOW + timedelta(minutes=3)
    assert rest.backoff_until(BINANCE_HOST) is None
    assert rest.backoff_until(BYBIT_HOST) == NOW + timedelta(minutes=10)


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        pytest.param(lambda: httpx.Response(403), "403", id="http-403"),
        pytest.param(lambda: httpx.Response(429), "429", id="http-429"),
        pytest.param(
            lambda: httpx.Response(200, json={"retCode": 10006, "retMsg": "Too many visits"}),
            "retcode:10006",
            id="retcode-10006",
        ),
        pytest.param(
            lambda: httpx.Response(200, json={"retCode": 10018, "retMsg": "IP rate limit"}),
            "retcode:10018",
            id="retcode-10018",
        ),
    ],
)
def test_bybit_403_and_ratelimit_retcode_back_off_10m(
    reply: Callable[[], httpx.Response], code: str
):
    sent: list[httpx.Request] = []
    rest = rest_of(scripted(lambda n: reply(), sent))

    with pytest.raises(RestError) as caught:
        rest.bybit_oi(T0, T0 + STEP)

    until = NOW + timedelta(minutes=10)
    assert (caught.value.host, caught.value.code, caught.value.until) == (BYBIT_HOST, code, until)
    assert rest.backoff_until(BYBIT_HOST) == until
    with pytest.raises(RestError) as again:
        rest.bybit_spot_klines(T0, T0 + STEP)
    assert again.value.until == until
    assert len(sent) == 1


def test_bybit_other_retcode_error_without_backoff():
    sent: list[httpx.Request] = []
    rest = rest_of(
        scripted(
            lambda n: (
                httpx.Response(200, json={"retCode": 10001, "retMsg": "params error"})
                if n == 0
                else bybit_ok({"list": [], "nextPageCursor": ""})
            ),
            sent,
        )
    )

    with pytest.raises(RestError) as caught:
        rest.bybit_oi(T0, T0 + STEP)

    assert (caught.value.host, caught.value.code, caught.value.until) == (
        BYBIT_HOST,
        "retcode:10001",
        None,
    )
    assert rest.backoff_until(BYBIT_HOST) is None
    assert rest.bybit_oi(T0, T0 + STEP) == []
    assert len(sent) == 2


def raise_timeout(_: int) -> httpx.Response:
    raise httpx.ConnectTimeout("slow")


@pytest.mark.parametrize(
    ("respond", "code"),
    [
        pytest.param(lambda n: httpx.Response(500), "500", id="server-error"),
        pytest.param(raise_timeout, "network", id="timeout"),
        pytest.param(
            lambda n: httpx.Response(200, content=b"<html>"), "bad_response", id="not-json"
        ),
        pytest.param(lambda n: httpx.Response(200, json={"a": 1}), "bad_response", id="not-a-list"),
        pytest.param(lambda n: httpx.Response(200, json=[[1]]), "bad_response", id="short-row"),
    ],
)
def test_other_failures_raise_without_backoff(respond: Callable[[int], httpx.Response], code: str):
    sent: list[httpx.Request] = []
    rest = rest_of(scripted(respond, sent))

    with pytest.raises(RestError) as caught:
        rest.binance_klines(T0, T0 + STEP)

    assert (caught.value.host, caught.value.code, caught.value.until) == (BINANCE_HOST, code, None)
    assert rest.backoff_until(BINANCE_HOST) is None


def test_one_request_in_flight():
    guard = threading.Lock()
    active = peak = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with guard:
            active -= 1
        return httpx.Response(200, json=[])

    rest = rest_of(handler)
    threads = [threading.Thread(target=rest.binance_klines, args=(T0, T0 + STEP)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1


# --- Hardening: failures stay RestErrors, paging cannot run away, waits are capped. ---


def test_bybit_oi_stops_on_a_repeated_cursor():
    page = {
        "list": [{"timestamp": str(T0 * 1000), "openInterest": "2", "singleOpenInterest": "1"}],
        "nextPageCursor": "again",
    }
    sent: list[httpx.Request] = []

    def respond(n: int) -> httpx.Response:
        assert n < 10, "paging ran away"
        return bybit_ok(page)

    rest = rest_of(scripted(respond, sent), bybit_oi=1)

    assert rest.bybit_oi(T0, T0 + 3600) == [OiPoint(t=T0, oi=1.0, source="bybit")]
    assert len(sent) == 2  # the cursor it just used came back


def corrupt_stream(data: bytes) -> bytes:
    """`data` with a byte of the deflated member flipped."""
    start = 30 + len("BTCUSDT-metrics-2026-10-15.csv") + 8
    return data[:start] + bytes([data[start] ^ 0xFF]) + data[start + 1 :]


def archive_bytes(kind: str) -> bytes:
    good = zip_of(metrics_csv([(f"00:{5 * i:02d}:00", 100.0 + i) for i in range(12)]))
    if kind == "not-a-zip":
        return b"<html>denied</html>"
    if kind == "truncated":
        return good[:40]
    if kind == "corrupt-stream":
        return corrupt_stream(good)
    if kind == "missing-member":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("README.txt", "hello")
        return buffer.getvalue()
    csv_text = {
        "no-rows": metrics_csv([]),
        "no-oi-column": "create_time,symbol\n2026-10-15 00:00:00,BTCUSDT\n",
        "bad-time": "create_time,sum_open_interest\nyesterday,1.0\n",
    }[kind]
    return zip_of(csv_text)


@pytest.mark.parametrize(
    "kind",
    [
        "not-a-zip",
        "truncated",
        "corrupt-stream",
        "missing-member",
        "no-rows",
        "no-oi-column",
        "bad-time",
    ],
)
def test_archive_that_is_not_a_daily_file_is_a_bad_response(kind: str):
    rest = rest_of(lambda request: httpx.Response(200, content=archive_bytes(kind)))

    with pytest.raises(RestError) as caught:
        rest.binance_oi_archive(date(2026, 10, 15))

    assert (caught.value.host, caught.value.code, caught.value.until) == (
        ARCHIVE_HOST,
        "bad_response",
        None,
    )


@pytest.mark.parametrize(("status", "minutes"), [(429, 2), (418, 30), (403, 30)])
def test_archive_host_backs_off_on_its_own(status: int, minutes: int):
    sent: list[httpx.Request] = []

    def respond(n: int) -> httpx.Response:
        return httpx.Response(status) if sent[n].url.host == ARCHIVE_HOST else empty_ok(n)

    rest = rest_of(scripted(respond, sent))

    with pytest.raises(RestError) as caught:
        rest.binance_oi_archive(date(2026, 10, 15))

    until = NOW + timedelta(minutes=minutes)
    assert (caught.value.host, caught.value.code, caught.value.until) == (
        ARCHIVE_HOST,
        str(status),
        until,
    )
    assert rest.backoff_until(ARCHIVE_HOST) == until
    assert rest.backoff_until(BINANCE_HOST) is None
    with pytest.raises(RestError) as again:
        rest.binance_oi_archive(date(2026, 10, 14))
    assert again.value.until == until
    assert len(sent) == 1  # nothing was sent while backed off
    assert rest.binance_klines(T0, T0 + STEP) == []  # fapi.binance.com is unaffected
    assert len(sent) == 2


@pytest.mark.parametrize(
    ("reply", "fetch"),
    [
        pytest.param(lambda: httpx.Response(200, content=b"<html>"), "bybit_oi", id="not-json"),
        pytest.param(lambda: httpx.Response(200, json=[]), "bybit_oi", id="not-an-object"),
        pytest.param(
            lambda: httpx.Response(200, json={"retMsg": "OK"}), "bybit_oi", id="no-retcode"
        ),
        pytest.param(lambda: bybit_ok(None), "bybit_oi", id="no-result"),
        pytest.param(lambda: bybit_ok({"nextPageCursor": ""}), "bybit_oi", id="no-list"),
        pytest.param(
            lambda: bybit_ok({"list": [{"timestamp": "1"}], "nextPageCursor": ""}),
            "bybit_oi",
            id="oi-row-without-value",
        ),
        pytest.param(
            lambda: bybit_ok({"list": [["x"]]}), "bybit_spot_klines", id="short-kline-row"
        ),
    ],
)
def test_bybit_reply_of_the_wrong_shape_is_a_bad_response(
    reply: Callable[[], httpx.Response], fetch: str
):
    rest = rest_of(lambda request: reply())

    with pytest.raises(RestError) as caught:
        getattr(rest, fetch)(T0, T0 + STEP)

    assert (caught.value.host, caught.value.code, caught.value.until) == (
        BYBIT_HOST,
        "bad_response",
        None,
    )
    assert rest.backoff_until(BYBIT_HOST) is None


@pytest.mark.parametrize(
    ("call", "host"),
    [
        pytest.param(lambda rest: rest.binance_klines(T0, DAY_END), BINANCE_HOST, id="klines"),
        pytest.param(lambda rest: rest.binance_oi_hist(T0), BINANCE_HOST, id="oi-hist"),
        pytest.param(lambda rest: rest.bybit_spot_klines(T0, DAY_END), BYBIT_HOST, id="spot"),
        pytest.param(lambda rest: rest.bybit_oi(T0, DAY_END), BYBIT_HOST, id="bybit-oi"),
    ],
)
def test_error_mid_pagination_raises_without_partial_rows(
    call: Callable[[PerpsRest], object], host: str
):
    exchange = Exchange(oi_rows=5)
    sent: list[httpx.Request] = []
    rest = rest_of(
        scripted(lambda n: exchange(sent[n]) if n == 0 else httpx.Response(429), sent),
        clock_at("23:55"),
        binance_klines=100,
        binance_oi_hist=100,
        bybit_spot_klines=100,
        bybit_oi=2,
    )

    with pytest.raises(RestError) as caught:
        call(rest)

    assert (caught.value.host, caught.value.code) == (host, "429")
    assert len(sent) == 2


@pytest.mark.parametrize("fetch", ["binance_klines", "bybit_spot_klines"])
@pytest.mark.parametrize(("slack", "requests"), [(0, 2), (3600, 3)])
def test_klines_page_boundary_on_an_exact_multiple(fetch: str, slack: int, requests: int):
    """288 rows in pages of 144: a full last page is followed by a request only if the window
    reaches past it."""
    exchange = Exchange()
    rest = rest_of(exchange, binance_klines=144, bybit_spot_klines=144)
    first, last = (T0 - slack, DAY_END) if fetch == "bybit_spot_klines" else (T0, DAY_END + slack)

    klines = getattr(rest, fetch)(first, last)

    assert [k.t for k in klines] == list(range(T0, DAY_END, 300))
    assert len(exchange.requests) == requests


@pytest.mark.parametrize(
    ("retry_after", "days"),
    [
        pytest.param("1" + "0" * 20, 3, id="seconds-beyond-timedelta"),
        pytest.param("864000", 3, id="ten-days"),
        pytest.param(format_datetime(datetime(2100, 1, 1, tzinfo=UTC), usegmt=True), 3, id="date"),
        pytest.param("172800", 2, id="two-days-kept"),
    ],
)
def test_backoff_is_capped_at_three_days(retry_after: str, days: int):
    rest = rest_of(lambda request: httpx.Response(418, headers={"Retry-After": retry_after}))

    with pytest.raises(RestError) as caught:
        rest.binance_klines(T0, T0 + STEP)

    assert caught.value.until == NOW + timedelta(days=days)
