"""The Coinalyze client: field mapping, closed bars, liquidation zero-fill, the key header,
per-host backoff and the unit check. Every request goes through httpx.MockTransport."""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from wheelhouse_service import settings as settings_module
from wheelhouse_service.perps.coinalyze import (
    CZ_HOST,
    KIND_VENUES,
    STEPS,
    SYMBOLS,
    Coinalyze,
    CzKind,
    Interval,
)
from wheelhouse_service.perps.rows import CzPoint
from wheelhouse_service.perps.sources import BINANCE_HOST, PerpsRest, RestError
from wheelhouse_service.settings import Settings

KEY = "test-key-0000"
FIXTURE = Path(__file__).parent / "fixtures" / "coinalyze"
# The moment the V1 responses behind the fixtures were fetched: in them the last 4hour point
# (04:00) and the last 5min point (07:40) are not closed yet.
NOW = datetime(2026, 10, 19, 7, 42, tzinfo=UTC)
NOW_TS = int(NOW.timestamp())
T0 = 1_792_310_400  # 2026-10-18 08:00 UTC, on both the 4hour and the 5min grid
H4 = STEPS["4hour"]
M5 = STEPS["5min"]


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


Handler = Callable[[httpx.Request], httpx.Response]


def build(
    handler: Handler, clock: Clock | None = None, key: str | None = KEY
) -> tuple[Coinalyze, PerpsRest, list[httpx.Request]]:
    """A client over `handler`, the REST layer under it and every request the handler saw."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    clock = clock or Clock()
    rest = PerpsRest(httpx.Client(transport=httpx.MockTransport(record)), clock)
    return Coinalyze(rest, key, clock), rest, seen


def load(name: str) -> Any:
    return json.loads((FIXTURE / name).read_text())


def replying(body: Any) -> Handler:
    return lambda request: httpx.Response(200, json=body)


def entry(symbol: str, *points: dict[str, float]) -> dict[str, Any]:
    return {"symbol": symbol, "history": list(points)}


# The two fields each kind maps to CzPoint.a and CzPoint.b.
FIELDS: dict[str, tuple[str, str]] = {"liq": ("l", "s"), "ohlcv": ("v", "bv"), "oi": ("o", "c")}


def point(kind: str, t: int, a: float = 1.5, b: float = 2.5) -> dict[str, float]:
    first, second = FIELDS[kind]
    return {"t": t, first: a, second: b}


def liq(t: int, longs: float = 1.5, shorts: float = 2.5) -> dict[str, float]:
    return point("liq", t, longs, shorts)


# --- Shape of the data. ---


def test_constants_follow_the_plan():
    assert SYMBOLS == {
        "binance": "BTCUSDT_PERP.A",
        "bybit": "BTCUSDT.6",
        "okx": "BTCUSDT_PERP.3",
        "hyperliquid": "BTC.H",
    }
    assert KIND_VENUES == {
        "liq": ("binance", "bybit", "okx"),
        "ohlcv": ("bybit", "okx", "hyperliquid"),
        "oi": ("okx", "hyperliquid"),
    }
    assert STEPS == {"5min": 300, "4hour": 14_400}
    assert CZ_HOST == "api.coinalyze.net"


def test_history_maps_fields_and_drops_open_bars():
    cz, _, seen = build(replying(load("liquidation-history-4hour.json")))

    got = cz.history("liq", "4hour", T0, NOW_TS)

    assert len(seen) == 1
    assert set(got) == {"binance", "bybit", "okx"}
    assert all(p.t + H4 <= NOW_TS for points in got.values() for p in points)
    # The 04:00 bar closes at 08:00, so the 00:00 bar is the last one kept.
    assert all([p.t for p in points] == [T0 + i * H4 for i in range(5)] for points in got.values())
    assert not any(p.filled for points in got.values() for p in points)
    assert got["binance"][-1] == CzPoint(
        t=1_792_368_000, a=0.30000000000000004, b=25.49800000000001
    )
    assert got["bybit"][-1] == CzPoint(t=1_792_368_000, a=0.001, b=13.496)
    assert got["okx"][-1] == CzPoint(t=1_792_368_000, a=0.0, b=4.6770000000000005)


def test_ohlcv_maps_volume_and_taker_buy():
    cz, _, _ = build(replying(load("ohlcv-history-5min.json")))

    got = cz.history("ohlcv", "5min", NOW_TS - 900, NOW_TS)

    assert set(got) == {"bybit", "okx", "hyperliquid"}
    # The 07:40 bar closes at 07:45.
    assert all(
        [p.t for p in points] == [1_792_394_700, 1_792_395_000, 1_792_395_300]
        for points in got.values()
    )
    assert got["bybit"][-1] == CzPoint(t=1_792_395_300, a=588.6320000000001, b=155.42000000000004)
    assert got["okx"][-1] == CzPoint(t=1_792_395_300, a=494.86239999999947, b=137.23810000000006)
    assert got["hyperliquid"][-1] == CzPoint(
        t=1_792_395_300, a=164.13935000000012, b=77.83278000000003
    )


def test_oi_maps_open_and_close():
    cz, _, _ = build(replying(load("open-interest-history-4hour.json")))

    got = cz.history("oi", "4hour", 1_792_353_600, NOW_TS)

    assert set(got) == {"okx", "hyperliquid"}
    assert all([p.t for p in points] == [1_792_353_600, 1_792_368_000] for points in got.values())
    assert got["okx"][-1] == CzPoint(t=1_792_368_000, a=30114.157100000106, b=30327.260800000142)
    assert got["hyperliquid"][-1] == CzPoint(t=1_792_368_000, a=39116.3263, b=39606.47074)


def test_points_come_back_oldest_first_without_duplicates():
    body = [entry("BTCUSDT.6", liq(T0 + 2 * H4), liq(T0), liq(T0 + H4), liq(T0, 9.0, 8.0))]
    cz, _, _ = build(replying(body))

    points = cz.history("liq", "4hour", T0, T0 + 2 * H4)["bybit"]

    assert [p.t for p in points] == [T0, T0 + H4, T0 + 2 * H4]
    assert points[0] == CzPoint(t=T0, a=9.0, b=8.0)


@pytest.mark.parametrize(
    ("kind", "interval", "path", "symbols", "convert"),
    [
        pytest.param(
            "liq",
            "4hour",
            "/v1/liquidation-history",
            "BTCUSDT_PERP.A,BTCUSDT.6,BTCUSDT_PERP.3",
            "false",
            id="liq",
        ),
        pytest.param(
            "ohlcv", "5min", "/v1/ohlcv-history", "BTCUSDT.6,BTCUSDT_PERP.3,BTC.H", None, id="ohlcv"
        ),
        pytest.param(
            "oi", "4hour", "/v1/open-interest-history", "BTCUSDT_PERP.3,BTC.H", "false", id="oi"
        ),
    ],
)
def test_one_request_carries_all_symbols_of_the_kind(
    kind: CzKind, interval: Interval, path: str, symbols: str, convert: str | None
):
    cz, _, seen = build(replying([]))

    cz.history(kind, interval, T0, T0 + H4)

    assert len(seen) == 1
    request = seen[0]
    assert (request.method, request.url.host, request.url.path) == ("GET", CZ_HOST, path)
    assert dict(request.url.params) == {
        "symbols": symbols,
        "interval": interval,
        "from": str(T0),
        "to": str(T0 + H4),
        **({} if convert is None else {"convert_to_usd": convert}),
    }


# --- Zero-fill (liquidations only, spec 3.4). ---


def test_liquidation_gaps_inside_the_closed_range_are_filled():
    body = [entry("BTCUSDT_PERP.A", liq(T0), liq(T0 + 2 * H4))]
    cz, _, _ = build(replying(body))

    points = cz.history("liq", "4hour", T0, T0 + 3 * H4)["binance"]

    assert points == [
        CzPoint(t=T0, a=1.5, b=2.5),
        CzPoint(t=T0 + H4, a=0.0, b=0.0, filled=True),
        CzPoint(t=T0 + 2 * H4, a=1.5, b=2.5),
        CzPoint(t=T0 + 3 * H4, a=0.0, b=0.0, filled=True),
    ]


def test_symbol_absent_from_reply_is_filled():
    # Coinalyze answered with Bybit only for OKX on 2026-10-10 09:15 to 13:15.
    cz, _, _ = build(replying([entry("BTCUSDT.6", liq(T0))]))

    got = cz.history("liq", "5min", T0, T0 + 3 * M5)

    assert set(got) == {"binance", "bybit", "okx"}
    for venue in ("binance", "okx"):
        assert [p.t for p in got[venue]] == [T0 + i * M5 for i in range(4)]
        assert [p.filled for p in got[venue]] == [True] * 4
        assert {p.a + p.b for p in got[venue]} == {0.0}
    assert [p.filled for p in got["bybit"]] == [False, True, True, True]


def test_empty_reply_fills_every_closed_interval_of_every_venue():
    cz, _, _ = build(replying([]))

    got = cz.history("liq", "4hour", T0, T0 + 2 * H4)

    for points in got.values():
        assert [(p.t, p.filled) for p in points] == [
            (T0, True),
            (T0 + H4, True),
            (T0 + 2 * H4, True),
        ]


def test_fill_starts_at_the_first_boundary_and_ends_at_to():
    cz, _, _ = build(replying([]))

    got = cz.history("liq", "5min", T0 + 1, T0 + 2 * M5 + 7)

    assert all([p.t for p in points] == [T0 + M5, T0 + 2 * M5] for points in got.values())


def test_fill_stops_at_the_last_closed_interval():
    cz, _, _ = build(replying([]))

    five = cz.history("liq", "5min", 1_792_395_000, NOW_TS)
    four = cz.history("liq", "4hour", 1_792_368_000, NOW_TS)

    # The 07:40 five-minute bar and the 04:00 four-hour bar are still open.
    assert all([p.t for p in points] == [1_792_395_000, 1_792_395_300] for points in five.values())
    assert all([p.t for p in points] == [1_792_368_000] for points in four.values())


@pytest.mark.parametrize(("kind", "interval"), [("ohlcv", "5min"), ("oi", "4hour")])
def test_ohlcv_and_oi_are_never_filled(kind: CzKind, interval: Interval):
    step = STEPS[interval]
    first, *others = KIND_VENUES[kind]
    body = [entry(SYMBOLS[first], point(kind, T0), point(kind, T0 + 2 * step))]
    cz, _, _ = build(replying(body))

    got = cz.history(kind, interval, T0, T0 + 3 * step)

    assert set(got) == set(KIND_VENUES[kind])
    assert [(p.t, p.filled) for p in got[first]] == [(T0, False), (T0 + 2 * step, False)]
    assert all(got[venue] == [] for venue in others)


def test_open_bars_are_dropped_before_the_zero_fill_not_filled():
    body = [entry("BTCUSDT_PERP.A", liq(1_792_368_000), liq(1_792_382_400))]
    cz, _, _ = build(replying(body))

    points = cz.history("liq", "4hour", 1_792_368_000, NOW_TS)["binance"]

    assert points == [CzPoint(t=1_792_368_000, a=1.5, b=2.5)]


# --- The key. ---


def test_key_never_in_url_or_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    cz, _, seen = build(replying(load("open-interest-history-4hour.json")))

    cz.history("oi", "4hour", T0, NOW_TS)

    request = seen[0]
    assert request.headers["api_key"] == KEY
    assert KEY not in str(request.url)
    assert caplog.records
    assert all(KEY not in record.getMessage() for record in caplog.records)
    assert KEY not in repr(Settings(coinalyze_key=KEY))


def test_key_is_sent_to_coinalyze_only():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    cz, rest, seen = build(handler)

    cz.history("liq", "5min", T0, T0 + M5)
    rest.binance_klines(T0, T0 + M5)

    assert [request.url.host for request in seen] == [CZ_HOST, BINANCE_HOST]
    assert "api_key" in seen[0].headers
    assert "api_key" not in seen[1].headers


def test_key_never_in_an_error():
    cz, _, _ = build(lambda request: httpx.Response(401))

    with pytest.raises(RestError) as exc:
        cz.history("liq", "5min", T0, T0 + M5)

    assert KEY not in str(exc.value) and KEY not in repr(exc.value)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda cz: cz.history("liq", "5min", T0, T0 + M5), id="history"),
        pytest.param(lambda cz: cz.markets(), id="markets"),
    ],
)
def test_missing_key_sends_nothing(call: Callable[[Coinalyze], object]):
    cz, _, seen = build(replying([]), key=None)

    with pytest.raises(RestError) as exc:
        call(cz)

    assert (exc.value.host, exc.value.code, exc.value.until) == (CZ_HOST, "key_missing", None)
    assert seen == []


# --- Errors and backoff. ---


@pytest.mark.parametrize(
    ("status", "retry_after", "seconds"),
    [
        pytest.param(429, None, 60, id="429-table"),
        pytest.param(429, "28.723", 60, id="429-fraction-shorter-than-table"),
        pytest.param(429, "90.5", 90.5, id="429-fraction-longer"),
        pytest.param(429, "600", 600, id="429-integer"),
        pytest.param(429, "nan", 60, id="429-nan-ignored"),
        pytest.param(429, "inf", 60, id="429-inf-ignored"),
        pytest.param(429, "1e400", 60, id="429-overflow-ignored"),
        pytest.param(429, "-5", 60, id="429-negative-ignored"),
        pytest.param(429, "1e20", 3 * 86_400, id="429-capped-at-three-days"),
        pytest.param(
            429, format_datetime(NOW + timedelta(minutes=45), usegmt=True), 2700, id="429-http-date"
        ),
        pytest.param(403, None, 600, id="403-table"),
        pytest.param(403, "5", 600, id="403-shorter-than-table"),
    ],
)
def test_backoff_per_status_and_retry_after(status: int, retry_after: str | None, seconds: float):
    clock = Clock()
    headers = {} if retry_after is None else {"Retry-After": retry_after}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == CZ_HOST:
            return httpx.Response(status, headers=headers)
        return httpx.Response(200, json=[])

    cz, rest, seen = build(handler, clock)

    with pytest.raises(RestError) as caught:
        cz.history("liq", "5min", T0, T0 + M5)

    until = NOW + timedelta(seconds=seconds)
    assert (caught.value.host, caught.value.code, caught.value.until) == (
        CZ_HOST,
        str(status),
        until,
    )
    assert rest.backoff_until(CZ_HOST) == until

    # The other hosts stay open, and Coinalyze sees nothing until the deadline.
    assert rest.backoff_until(BINANCE_HOST) is None
    assert rest.binance_klines(T0, T0 + M5) == []
    clock.now = until - timedelta(seconds=1)
    with pytest.raises(RestError) as again:
        cz.history("liq", "5min", T0, T0 + M5)
    assert (again.value.code, again.value.until) == ("backoff", until)
    assert [request.url.host for request in seen] == [CZ_HOST, BINANCE_HOST]

    clock.now = until
    with pytest.raises(RestError) as after:
        cz.history("liq", "5min", T0, T0 + M5)
    assert after.value.code == str(status)
    assert len(seen) == 3


@pytest.mark.parametrize("status", [401, 404, 500])
def test_other_statuses_give_up_without_a_backoff(status: int):
    cz, rest, seen = build(lambda request: httpx.Response(status, headers={"Retry-After": "300"}))

    for attempt in (1, 2):
        with pytest.raises(RestError) as caught:
            cz.history("liq", "5min", T0, T0 + M5)

        assert (caught.value.host, caught.value.code, caught.value.until) == (
            CZ_HOST,
            str(status),
            None,
        )
        assert rest.backoff_until(CZ_HOST) is None
        assert len(seen) == attempt  # the next round asks again


def test_network_error_is_a_rest_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    cz, _, _ = build(handler)

    with pytest.raises(RestError) as caught:
        cz.history("liq", "5min", T0, T0 + M5)

    assert (caught.value.host, caught.value.code, caught.value.until) == (CZ_HOST, "network", None)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"message": "nope"}, id="object"),
        pytest.param("text", id="string"),
        pytest.param([1], id="entry-not-an-object"),
        pytest.param([{"history": []}], id="no-symbol"),
        pytest.param([{"symbol": "BTCUSDT.6"}], id="no-history"),
        pytest.param([{"symbol": "BTCUSDT.6", "history": {"t": 1}}], id="history-not-a-list"),
        pytest.param([{"symbol": "BTCUSDT.6", "history": [5]}], id="point-not-an-object"),
        pytest.param([entry("BTCUSDT.6", {"t": T0, "l": 1.0})], id="field-missing"),
        pytest.param([entry("BTCUSDT.6", {"t": T0, "l": None, "s": 1.0})], id="field-null"),
        pytest.param([entry("BTCUSDT.6", {"t": T0, "l": "x", "s": 1.0})], id="field-text"),
        pytest.param([entry("BTCUSDT.6", {"t": "soon", "l": 1.0, "s": 1.0})], id="time-text"),
    ],
)
def test_malformed_reply_is_a_bad_response(body: Any):
    cz, _, _ = build(replying(body))

    with pytest.raises(RestError) as caught:
        cz.history("liq", "4hour", T0, T0 + H4)

    assert (caught.value.host, caught.value.code, caught.value.until) == (
        CZ_HOST,
        "bad_response",
        None,
    )


def test_reply_that_is_not_json_is_a_bad_response():
    cz, _, _ = build(lambda request: httpx.Response(200, text="<html>Cloudflare</html>"))

    with pytest.raises(RestError) as caught:
        cz.history("liq", "4hour", T0, T0 + H4)

    assert caught.value.code == "bad_response"


# --- The unit check. ---


def listed() -> list[dict[str, Any]]:
    return load("future-markets.json")


def test_markets_checks_units():
    cz, _, seen = build(replying(listed()))

    checks = cz.markets()

    assert [c.venue for c in checks] == ["binance", "bybit", "okx", "hyperliquid"]
    assert [c.symbol for c in checks] == [
        "BTCUSDT_PERP.A",
        "BTCUSDT.6",
        "BTCUSDT_PERP.3",
        "BTC.H",
    ]
    assert all(c.denominated == "BASE_ASSET" and c.buy_sell is True and c.ok for c in checks)
    assert [(r.method, r.url.host, r.url.path) for r in seen] == [
        ("GET", CZ_HOST, "/v1/future-markets")
    ]
    assert seen[0].headers["api_key"] == KEY


def change(symbol: str, **fields: Any) -> list[dict[str, Any]]:
    return [{**m, **fields} if m["symbol"] == symbol else m for m in listed()]


def test_markets_okx_in_quote_asset_is_not_ok():
    cz, _, _ = build(replying(change("BTCUSDT_PERP.3", oi_lq_vol_denominated_in="QUOTE_ASSET")))

    checks = {c.venue: c for c in cz.markets()}

    assert (checks["okx"].denominated, checks["okx"].ok) == ("QUOTE_ASSET", False)
    assert [v for v, c in checks.items() if c.ok] == ["binance", "bybit", "hyperliquid"]


def test_markets_without_buy_sell_data_is_not_ok_where_ohlcv_reads_it():
    cz, _, _ = build(replying(change("BTC.H", has_buy_sell_data=False)))

    hyperliquid = {c.venue: c for c in cz.markets()}["hyperliquid"]

    assert (hyperliquid.denominated, hyperliquid.buy_sell, hyperliquid.ok) == (
        "BASE_ASSET",
        False,
        False,
    )


def test_markets_buy_sell_data_is_not_required_where_ohlcv_is_not_read():
    # Binance's volumes come from the exchange, not from Coinalyze.
    cz, _, _ = build(replying(change("BTCUSDT_PERP.A", has_buy_sell_data=False)))

    binance = {c.venue: c for c in cz.markets()}["binance"]

    assert (binance.buy_sell, binance.ok) == (False, True)


def test_markets_symbol_missing_from_the_list_is_not_ok():
    cz, _, _ = build(replying([m for m in listed() if m["symbol"] != "BTCUSDT.6"]))

    checks = {c.venue: c for c in cz.markets()}

    assert (checks["bybit"].symbol, checks["bybit"].denominated, checks["bybit"].buy_sell) == (
        "BTCUSDT.6",
        None,
        None,
    )
    assert checks["bybit"].ok is False
    assert all(checks[v].ok for v in ("binance", "okx", "hyperliquid"))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"message": "nope"}, id="object"),
        pytest.param([1], id="entry-not-an-object"),
        pytest.param([{"exchange": "6"}], id="no-symbol"),
        pytest.param([{"symbol": "BTCUSDT.6", "has_buy_sell_data": True}], id="no-denomination"),
    ],
)
def test_markets_malformed_reply_is_a_bad_response(body: Any):
    cz, _, _ = build(replying(body))

    with pytest.raises(RestError) as caught:
        cz.markets()

    assert (caught.value.host, caught.value.code) == (CZ_HOST, "bad_response")


# --- Where the key comes from. ---


def test_settings_key_from_env_then_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    dotenv = tmp_path / ".env"
    monkeypatch.setattr(settings_module, "DOTENV", dotenv)
    monkeypatch.delenv("WHEELHOUSE_COINALYZE_KEY", raising=False)

    # Neither the environment nor the file.
    assert Settings.from_env().coinalyze_key is None

    # The file, as the probe reads it: comments skipped, `export ` and the quotes removed.
    dotenv.write_text(
        "# WHEELHOUSE_COINALYZE_KEY=commented\n"
        "OTHER_KEY=other\n"
        'export WHEELHOUSE_COINALYZE_KEY="abc"\n'
    )
    assert Settings.from_env().coinalyze_key == "abc"
    dotenv.write_text("WHEELHOUSE_COINALYZE_KEY='single'\n")
    assert Settings.from_env().coinalyze_key == "single"
    dotenv.write_text("OTHER_KEY=other\n")
    assert Settings.from_env().coinalyze_key is None

    # The environment wins whenever the variable is present, and an empty one means missing.
    dotenv.write_text('WHEELHOUSE_COINALYZE_KEY="from-file"\n')
    monkeypatch.setenv("WHEELHOUSE_COINALYZE_KEY", "abc")
    assert Settings.from_env().coinalyze_key == "abc"
    monkeypatch.setenv("WHEELHOUSE_COINALYZE_KEY", "")
    assert Settings.from_env().coinalyze_key is None


def test_settings_default_has_no_key_and_hides_it_from_repr():
    assert Settings().coinalyze_key is None
    assert "coinalyze_key" not in repr(Settings(coinalyze_key=KEY))
