"""The read-only perps API: freshness, collector status and reason codes worked out per request,
the startup flags, and the frontend sample generated from a synthetic grid (P4-R11).

Write the sample again after a contract change with:
    .venv-foundation/bin/python services/analytics/tests/perps/test_perps_api.py
"""

import json
import random
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wheelhouse_service.http import create_app
from wheelhouse_service.perps.api import (
    VIEW_STREAMS,
    collector_status,
    create_router,
    direction,
    states_view,
)
from wheelhouse_service.perps.collector import STREAMS, Collectors
from wheelhouse_service.perps.models import PerpStatesView, freshness
from wheelhouse_service.perps.rows import Exchange, Stream
from wheelhouse_service.perps.sources import ARCHIVE_HOST, BINANCE_HOST, BYBIT_HOST
from wheelhouse_service.perps.states import (
    TABLE_STATES,
    Grid,
    State,
    StatesResult,
    Window,
    compute_states,
)
from wheelhouse_service.perps.store import PerpsStore
from wheelhouse_service.perps.sync import (
    DirectionCheck,
    Directions,
    PerpsSync,
    QtyUnits,
    StoredStates,
    Verdict,
    derived_key,
    stored_hosts,
)
from wheelhouse_service.settings import Settings

PREFIX = "/api/wheelhouse/v1/perps"
STEP = 600
DAY = 86_400
W4 = 24  # buckets in a 4h block
EXCHANGES: tuple[Exchange, ...] = ("all", "binance", "bybit")
WINDOWS: tuple[Window, ...] = ("4h", "8h")
SAMPLE = (
    Path(__file__).resolve().parents[4]
    / "integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse"
    / "perp-states-sample.json"
)

# The sample: 31 days and 11 hours of buckets, the last one closing at 11:00, so 188 whole 4h
# blocks and a forming one. The worker derived it in the 11:05 round; it is read at 11:07.
SAMPLE_START = datetime(2026, 9, 16, tzinfo=UTC)
SAMPLE_LAST = datetime(2026, 10, 17, 10, 50, tzinfo=UTC)
SAMPLE_COMPUTED = datetime(2026, 10, 17, 11, 5, 4, tzinfo=UTC)
SAMPLE_NOW = datetime(2026, 10, 17, 11, 7, tzinfo=UTC)
THROUGH = SAMPLE_LAST + timedelta(minutes=10)
# Three days and seven hours: 20 covered 4h blocks, short of the 42 that end collecting.
SHORT_START = datetime(2026, 10, 14, tzinfo=UTC)

# Every four days of 4h blocks: one block built for each state but chop, the rest chop. Chop
# blocks near a threshold land in other states too.
PATTERN: tuple[State, ...] = (
    "shortsq",
    "chop",
    "chop",
    "longbd",
    "chop",
    "chop",
    "longun",
    "chop",
    "chop",
    "spot",
    "chop",
    "chop",
    "longsq",
    "chop",
    "chop",
    "shortbd",
    "chop",
    "chop",
    "shortun",
    "chop",
    "chop",
    "chop",
    "chop",
    "chop",
)

Values = list[float | None]


def features(state: State, rng: random.Random) -> tuple[float, float, float, float, float]:
    """(dpx %, doi BTC, delta BTC, long liq BTC, short liq BTC) of a block built for `state`.

    Few blocks are large, so each threshold falls among the small values and the large ones
    clear it.
    """

    def u(a: float, b: float) -> float:
        return rng.uniform(a, b)

    def signed(a: float, b: float) -> float:
        return rng.choice((-1.0, 1.0)) * u(a, b)

    longs, shorts = u(0, 40), u(0, 40)
    if state == "shortsq":
        return u(1.5, 3), -u(10, 300), u(100, 400), u(0, 30), u(150, 400)
    if state == "longsq":
        return -u(1.5, 3), -u(10, 300), -u(100, 400), u(150, 400), u(0, 30)
    if state == "longun":
        return -u(0.2, 0.6), -u(800, 2000), -u(100, 400), longs, shorts
    if state == "shortun":
        return u(0.2, 0.6), -u(800, 2000), u(100, 400), longs, shorts
    if state == "longbd":
        return u(0.2, 0.6), u(800, 2000), u(100, 400), longs, shorts
    if state == "shortbd":
        return -u(0.2, 0.6), u(800, 2000), -u(100, 400), longs, shorts
    if state == "spot":
        return signed(1.5, 3), signed(10, 100), signed(0, 250), longs, shorts
    return signed(0.05, 0.8), signed(10, 300), signed(0, 250), longs, shorts


def spread(total: float, w: int, rng: random.Random, share: float) -> Values:
    """`total` over `w` buckets, each one taking part with probability `share` (one at least)."""
    weights = [rng.random() if rng.random() < share else 0.0 for _ in range(w)]
    if not any(weights):
        weights[rng.randrange(w)] = 1.0
    weight = sum(weights)
    return [round(total * x / weight, 3) for x in weights]


def synthetic_grid(start: datetime, last: datetime, seed: int = 20261017) -> Grid:
    """An all-venues grid, fully covered, whose 4h blocks follow PATTERN. Inputs are rounded like
    exchange data; only + - * / and the seeded generator are used, so it is the same anywhere."""
    rng = random.Random(seed)
    t0 = int(start.timestamp())
    n = (int(last.timestamp()) - t0) // STEP + 1
    price: Values = []
    oi: Values = []
    vd: Values = []
    longs: Values = []
    shorts: Values = []
    p, o = 62_000.0, 160_000.0
    for block, first in enumerate(range(0, n, W4)):
        w = min(W4, n - first)
        dpx, doi, delta, lliq, sliq = features(PATTERN[block % len(PATTERN)], rng)
        for k in range(w):
            f = k / (W4 - 1)
            inner = 0 < k < W4 - 1  # the block's own moves sit on its first and last bucket
            price.append(
                round(p * (1 + dpx / 100 * f + (rng.uniform(-1, 1) / 800 if inner else 0)), 1)
            )
            oi.append(round(o + doi * f + (rng.uniform(-40, 40) if inner else 0), 1))
        vd += spread(delta, w, rng, 1.0)
        longs += spread(lliq, w, rng, 0.3)
        shorts += spread(sliq, w, rng, 0.3)
        p = (price[-1] or p) * (1 + rng.uniform(-1, 1) / 1000)
        o = (oi[-1] or o) + rng.uniform(-30, 30)
    return Grid(
        start=t0,
        last=int(last.timestamp()),
        price=price,
        oi=oi,
        vd=vd,
        long_liq=longs,
        short_liq=shorts,
        liq_covered=[True] * n,
        vd_covered=[True] * n,
        # QC reads only where these are null, and nothing is.
        rest_series={"bybit:price": price, "binance:oi": oi, "binance:kline": vd, "bybit:oi": oi},
        quarantined_days=0,
    )


def sample_view() -> PerpStatesView:
    """The all-venues 4h view as the API would serve it at SAMPLE_NOW, every stream live."""
    states = compute_states(synthetic_grid(SAMPLE_START, SAMPLE_LAST), "4h")
    stored = StoredStates(
        exchange="all", window="4h", start=SAMPLE_START, reasons=[], states=states
    )
    now = SAMPLE_NOW.timestamp()
    spans = [(SAMPLE_START.timestamp(), now - 6.0)]
    collectors = [collector_status(stream, spans, SAMPLE_NOW, {}) for stream in STREAMS]
    return states_view(
        "all", "4h", (stored, SAMPLE_COMPUTED), collectors, stored_hosts({}), SAMPLE_NOW
    )


def render_sample() -> str:
    return json.dumps(sample_view().model_dump(mode="json"), indent=2) + "\n"


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def blocked() -> tuple[httpx.Client, Callable[..., Any], list[str]]:
    """A REST client and a WebSocket factory that both fail, and what they were asked for."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        raise httpx.ConnectError("network is blocked in this test", request=request)

    def connect(url: str, **_: object) -> Any:
        seen.append(url)
        raise OSError("network is blocked in this test")

    return httpx.Client(transport=httpx.MockTransport(handler)), connect, seen


def router_app(
    path: Path,
    clock: Callable[[], datetime],
    *,
    start_worker: bool = False,
    http: httpx.Client | None = None,
    connect: Callable[..., Any] | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_router(path, http, start_worker=start_worker, connect=connect, clock=clock)
    )
    return app


def save(
    store: PerpsStore,
    exchange: Exchange,
    window: Window,
    states: StatesResult | None,
    reasons: list[str] | None = None,
    computed_at: datetime = SAMPLE_COMPUTED,
) -> None:
    stored = StoredStates(
        exchange=exchange,
        window=window,
        start=SAMPLE_START,
        reasons=reasons or [],
        states=states,
    )
    store.save_derived(derived_key(exchange, window), stored.model_dump_json(), computed_at)


def cover(store: PerpsStore, stream: Stream, start: float, end: float, conn: int = 0) -> None:
    store.extend_coverage(store.open_coverage(stream, conn, start), end)


def host(error: str | None, until: datetime | None = None, success: datetime | None = None) -> Any:
    return {
        "last_success": None if success is None else success.isoformat(),
        "error": error,
        "until": None if until is None else until.isoformat(),
    }


def get_states(http: TestClient, exchange: Exchange, window: Window = "4h") -> dict[str, Any]:
    response = http.get(f"{PREFIX}/states", params={"exchange": exchange, "window": window})
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def iso(at: datetime | None) -> str | None:
    return None if at is None else at.isoformat().replace("+00:00", "Z")


@contextmanager
def other_workers_held() -> Iterator[None]:
    """The market, broker and on-chain workers do not start: these tests are about perps."""
    with (
        patch("wheelhouse_service.http.Runtime.start"),
        patch("wheelhouse_service.portfolio.api.BrokerSync.start"),
        patch("wheelhouse_service.onchain.api.OnchainSync.start"),
    ):
        yield


@contextmanager
def perps_spied() -> Iterator[tuple[MagicMock, MagicMock]]:
    with (
        patch("wheelhouse_service.perps.api.PerpsSync.start") as worker,
        patch("wheelhouse_service.perps.api.Collectors.start") as collectors,
    ):
        yield worker, collectors


def test_freshness_at_request_time(tmp_path: Path):
    path = tmp_path / "perps.sqlite"
    save(
        PerpsStore(path),
        "all",
        "4h",
        compute_states(synthetic_grid(SHORT_START, SAMPLE_LAST), "4h"),
    )
    clock = Clock(THROUGH + timedelta(minutes=20))

    with TestClient(router_app(path, clock)) as http:
        first = get_states(http, "all")
        clock.now = THROUGH + timedelta(minutes=40)
        later = get_states(http, "all")
        clock.now = THROUGH + timedelta(hours=3)
        old = get_states(http, "all")

    # One stored payload, judged again on every request.
    assert [body["data_state"] for body in (first, later, old)] == ["fresh", "delayed", "stale"]
    assert {body["computed_at"] for body in (first, later, old)} == {iso(SAMPLE_COMPUTED)}
    assert {body["last"] for body in (first, later, old)} == {iso(SAMPLE_LAST)}


def test_freshness_boundaries():
    tick = timedelta(microseconds=1)
    fresh, delayed = timedelta(minutes=30), timedelta(hours=2)

    # Judged from the end of the last bucket, last + 10m, and inclusive at each bound.
    assert freshness(SAMPLE_LAST, SAMPLE_LAST + timedelta(minutes=40)) == "fresh"
    assert freshness(SAMPLE_LAST, THROUGH + fresh) == "fresh"
    assert freshness(SAMPLE_LAST, THROUGH + fresh + tick) == "delayed"
    assert freshness(SAMPLE_LAST, THROUGH + delayed) == "delayed"
    assert freshness(SAMPLE_LAST, THROUGH + delayed + tick) == "stale"
    assert freshness(None, THROUGH) == "unavailable"


def test_reason_codes(tmp_path: Path):
    path = tmp_path / "perps.sqlite"
    store = PerpsStore(path)
    now = SAMPLE_NOW
    t = now.timestamp()
    # 20 covered 4h blocks: 3.33 days, short of 7.
    short = compute_states(
        synthetic_grid(SHORT_START, datetime(2026, 10, 17, 6, 50, tzinfo=UTC)), "4h"
    )
    assert short.collecting and short.covered_days == pytest.approx(20 / 6)
    save(store, "all", "4h", short, ["series_missing:bybit:oi"])
    save(store, "binance", "4h", short)
    save(store, "bybit", "4h", short)
    store.set_state(
        hosts=json.dumps(
            {
                BINANCE_HOST: host("418", now + timedelta(minutes=20)),
                ARCHIVE_HOST: host("500"),
                BYBIT_HOST: host("retcode:10006", now + timedelta(minutes=5)),
            }
        )
    )
    cover(store, "binance_liq", t - DAY, t - 10)
    cover(store, "bybit_liq", t - DAY, t - 120)
    cover(store, "bybit_trades", t - DAY, t - 10)

    # Perps run in this process (their loops are never started), so a stale stream is down.
    client, connect, seen = blocked()
    with perps_spied():
        app = router_app(path, Clock(now), start_worker=True, http=client, connect=connect)
        with TestClient(app) as http:
            views = {exchange: get_states(http, exchange) for exchange in EXCHANGES}
    assert seen == []

    assert views["all"]["reasons"] == [
        "series_missing:bybit:oi",
        "rest_error:fapi.binance.com:418",
        "rest_error:data.binance.vision:500",
        "rest_error:api.bybit.com:retcode:10006",
        "collector_down:bybit_liq",
        "collecting:3.3",
    ]
    # Each view only names the hosts and streams it reads; every view prices with Bybit spot.
    assert views["binance"]["reasons"] == [
        "rest_error:fapi.binance.com:418",
        "rest_error:data.binance.vision:500",
        "rest_error:api.bybit.com:retcode:10006",
        "collecting:3.3",
    ]
    assert views["bybit"]["reasons"] == [
        "rest_error:api.bybit.com:retcode:10006",
        "collector_down:bybit_liq",
        "collecting:3.3",
    ]
    assert all(view["collecting"] is True for view in views.values())


def test_unavailable_while_perps_are_off(tmp_path: Path):
    path = tmp_path / "perps.sqlite"
    store = PerpsStore(path)
    never = {
        "live": False,
        "last_proof": None,
        "down_since": None,
        "covered_days": 0.0,
        "since": None,
        "problems": {},  # the collectors do not run here
    }

    with TestClient(router_app(path, Clock(SAMPLE_NOW))) as http:
        views = {(e, w): get_states(http, e, w) for e in EXCHANGES for w in WINDOWS}
        status = http.get(f"{PREFIX}/status").json()
        save(store, "bybit", "4h", None, ["series_missing:bybit:oi"])
        marker = get_states(http, "bybit")

    for (exchange, window), body in views.items():
        streams = VIEW_STREAMS[exchange]
        assert body == {
            "exchange": exchange,
            "window": window,
            "data_state": "unavailable",
            # No worker runs in this process, so nothing will be derived: not "not_derived", and
            # no collector is down, since none is meant to run.
            "reasons": ["perps_disabled"],
            "computed_at": None,
            "last": None,
            "thresholds": None,
            "blocks": [],
            "tail": None,
            "tables": [],
            "covered_days": None,
            "collecting": None,
            "qc": [],
            "series_missing": [],
            "collectors": [{"stream": stream, **never} for stream in streams],
        }
    assert status == {
        "last_run_at": None,
        "last_error": None,
        "hosts": [
            {"host": name, "last_success": None, "error": None, "backoff_until": None}
            for name in (BINANCE_HOST, ARCHIVE_HOST, BYBIT_HOST)
        ],
        "collectors": [{"stream": stream, **never} for stream in STREAMS],
        "direction": "pending",
        "direction_check": None,
    }
    # The worker's marker for a view missing a series: derived, still unavailable.
    assert marker["data_state"] == "unavailable"
    assert marker["computed_at"] == iso(SAMPLE_COMPUTED)
    assert marker["reasons"][0] == "series_missing:bybit:oi"
    assert (marker["last"], marker["blocks"], marker["collecting"]) == (None, [], None)


def test_not_derived_before_the_first_round_while_perps_run(tmp_path: Path):
    path = tmp_path / "perps.sqlite"
    client, connect, seen = blocked()
    # The worker and the collectors are made but never run: no round has derived anything.
    with perps_spied() as (worker, collectors):
        app = router_app(path, Clock(SAMPLE_NOW), start_worker=True, http=client, connect=connect)
        with TestClient(app) as http:
            views = {exchange: get_states(http, exchange) for exchange in EXCHANGES}
    worker.assert_called_once()
    collectors.assert_called_once()

    for exchange, view in views.items():
        assert view["data_state"] == "unavailable"
        assert view["reasons"] == [
            "not_derived",
            *(f"collector_down:{stream}" for stream in VIEW_STREAMS[exchange]),
        ]
    assert seen == []


def test_reads_with_perps_off_open_no_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "perps.sqlite"
    store = PerpsStore(path)
    for exchange in EXCHANGES:
        for window in WINDOWS:
            save(
                store,
                exchange,
                window,
                compute_states(synthetic_grid(SHORT_START, SAMPLE_LAST), window),
            )
    t = SAMPLE_NOW.timestamp()
    for stream in STREAMS:
        cover(store, stream, t - DAY, t)
    attempts: list[object] = []

    def refuse(*args: object, **kwargs: object) -> Any:
        attempts.append(args)
        raise OSError("network is blocked in this test")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    # The block holds: a connection out is refused and seen.
    with pytest.raises(OSError):
        socket.create_connection(("fapi.binance.com", 443))
    assert len(attempts) == 1
    attempts.clear()

    with TestClient(router_app(path, Clock(SAMPLE_NOW), start_worker=False)) as http:
        views = [get_states(http, e, w) for e in EXCHANGES for w in WINDOWS]
        status = http.get(f"{PREFIX}/status")

    assert all(view["last"] == iso(SAMPLE_LAST) for view in views)
    assert status.status_code == 200
    assert attempts == []


def test_start_perps_false_starts_nothing(tmp_path: Path):
    client, connect, seen = blocked()

    for options in ({"start_perps": False}, {"start_perps": True, "start_worker": False}):
        with other_workers_held(), perps_spied() as (worker, collectors):
            app = create_app(
                tmp_path / "m.sqlite", perps_http=client, perps_connect=connect, **options
            )
            with TestClient(app) as http:
                assert http.get(f"{PREFIX}/status").status_code == 200
        worker.assert_not_called()
        collectors.assert_not_called()
    assert seen == []


@pytest.mark.parametrize(
    ("value", "enabled"),
    [
        (None, True),
        ("1", True),
        ("true", True),
        ("on", True),
        ("ON", True),
        ("0", False),
        ("false", False),
        ("off", False),
        ("False", False),
    ],
)
def test_settings_perps_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str | None, enabled: bool
):
    if value is None:
        monkeypatch.delenv("WHEELHOUSE_PERPS", raising=False)
    else:
        monkeypatch.setenv("WHEELHOUSE_PERPS", value)
    assert Settings.from_env().perps_enabled is enabled

    # Without `start_perps`, the setting decides whether the app starts the worker.
    client, connect, seen = blocked()
    with other_workers_held(), perps_spied() as (worker, collectors):
        app = create_app(tmp_path / "m.sqlite", perps_http=client, perps_connect=connect)
        with TestClient(app):
            pass
    assert worker.call_count == collectors.call_count == int(enabled)
    assert seen == []


def test_settings_perps_rejects_other_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WHEELHOUSE_PERPS", "yes")
    with pytest.raises(ValueError, match="WHEELHOUSE_PERPS"):
        Settings.from_env()


def test_perps_run_only_while_the_app_runs(tmp_path: Path):
    client, connect, seen = blocked()
    app = router_app(
        tmp_path / "perps.sqlite",
        Clock(SAMPLE_NOW),
        start_worker=True,
        http=client,
        connect=connect,
    )
    names = {
        "wheelhouse-perps",
        *(f"perps-{stream}-{conn}" for stream in STREAMS for conn in (0, 1)),
    }

    with TestClient(app):
        deadline = time.monotonic() + 10
        while not (BINANCE_HOST in seen and any(url.startswith("wss://") for url in seen)):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert names <= {thread.name for thread in threading.enumerate()}

    assert not names & {thread.name for thread in threading.enumerate()}


def test_shutdown_tells_the_worker_before_stopping_the_collectors(tmp_path: Path):
    client, connect, seen = blocked()
    workers: list[PerpsSync] = []
    order: list[tuple[str, bool]] = []

    def stop_collectors(_: Collectors, *args: object) -> None:
        order.append(("collectors", workers[0].stopping.is_set()))

    def stop_worker(worker: PerpsSync) -> None:
        order.append(("worker", worker.stopping.is_set()))

    with (
        patch.object(PerpsSync, "start", autospec=True, side_effect=workers.append),
        patch.object(PerpsSync, "stop", autospec=True, side_effect=stop_worker),
        patch.object(Collectors, "start", autospec=True),
        patch.object(Collectors, "stop", autospec=True, side_effect=stop_collectors),
    ):
        app = router_app(
            tmp_path / "perps.sqlite",
            Clock(SAMPLE_NOW),
            start_worker=True,
            http=client,
            connect=connect,
        )
        with TestClient(app):
            assert not workers[0].stopping.is_set()

    # The worker winds its round down while the collectors close their coverage.
    assert order == [("collectors", True), ("worker", True)]
    assert seen == []


def test_status_counts_the_running_collectors_problems(tmp_path: Path):
    client, connect, _ = blocked()
    app = router_app(
        tmp_path / "perps.sqlite",
        Clock(SAMPLE_NOW),
        start_worker=True,
        http=client,
        connect=connect,
    )

    with TestClient(app) as http:
        deadline = time.monotonic() + 10
        # Each stream's first connection fails at once; the second waits a minute.
        while True:
            status = http.get(f"{PREFIX}/status").json()
            if all(item["problems"].get("connect_failed") for item in status["collectors"]):
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        bybit = get_states(http, "bybit")

    assert [item["stream"] for item in status["collectors"]] == list(STREAMS)
    assert all(set(item["problems"]) == {"connect_failed"} for item in status["collectors"])
    assert [item["stream"] for item in bybit["collectors"]] == ["bybit_liq", "bybit_trades"]
    assert all(item["problems"]["connect_failed"] >= 1 for item in bybit["collectors"])


def test_collector_status_from_store(tmp_path: Path):
    path = tmp_path / "perps.sqlite"
    store = PerpsStore(path)
    t = SAMPLE_NOW.timestamp()
    # Two connections overlap; the later one proved life exactly 60 s ago: still live.
    cover(store, "binance_liq", t - 3 * DAY, t - 2 * DAY, conn=0)
    cover(store, "binance_liq", t - 2.5 * DAY, t - 60, conn=1)
    # 61 s ago is down; days before the 90-day window are not counted.
    cover(store, "bybit_liq", t - 100 * DAY, t - 95 * DAY, conn=0)
    cover(store, "bybit_liq", t - DAY, t - 61, conn=1)

    with TestClient(router_app(path, Clock(SAMPLE_NOW))) as http:
        status = http.get(f"{PREFIX}/status").json()
        binance = get_states(http, "binance")
        bybit = get_states(http, "bybit")

    def at(seconds: float) -> str | None:
        return iso(datetime.fromtimestamp(seconds, UTC))

    assert status["collectors"] == [
        {
            "stream": "binance_liq",
            "live": True,
            "last_proof": at(t - 60),
            "down_since": None,
            "covered_days": pytest.approx(3 - 60 / DAY),
            "since": at(t - 3 * DAY),
            "problems": {},
        },
        {
            "stream": "bybit_liq",
            "live": False,
            "last_proof": at(t - 61),
            "down_since": at(t - 61),
            "covered_days": pytest.approx(1 - 61 / DAY),
            "since": at(t - 100 * DAY),
            "problems": {},
        },
        {
            "stream": "bybit_trades",
            "live": False,
            "last_proof": None,
            "down_since": None,
            "covered_days": 0.0,
            "since": None,
            "problems": {},
        },
    ]
    # A view lists only the streams it reads; with perps off, none of them is reported down.
    assert binance["collectors"] == status["collectors"][:1]
    assert binance["reasons"] == ["perps_disabled"]
    assert bybit["collectors"] == status["collectors"][1:]
    assert bybit["reasons"] == ["perps_disabled"]


def check(verdict: Verdict) -> DirectionCheck:
    return DirectionCheck(verdict=verdict, samples=30, down=25, long_share=0.5)


def test_status_reports_hosts_and_direction(tmp_path: Path):
    path = tmp_path / "perps.sqlite"
    store = PerpsStore(path)
    now = SAMPLE_NOW
    units = QtyUnits(
        events=0,
        min_qty=None,
        min_notional=None,
        max_notional=None,
        notional_in_range=None,
        min_qty_matches=None,
    )
    store.set_state(
        last_run_at=SAMPLE_COMPUTED.isoformat(),
        last_error="sync_failed",
        hosts=json.dumps(
            {
                BINANCE_HOST: host("418", now + timedelta(minutes=20)),
                # The deadline has passed: the error stays until a success, the backoff does not.
                BYBIT_HOST: host("retcode:10006", now - timedelta(minutes=1)),
                ARCHIVE_HOST: host(None, success=SAMPLE_COMPUTED),
            }
        ),
        direction_check=Directions(
            binance=check("ok"), bybit=check("pending"), bybit_qty=units
        ).model_dump_json(),
    )

    with TestClient(router_app(path, Clock(now))) as http:
        status = http.get(f"{PREFIX}/status").json()

    assert (status["last_run_at"], status["last_error"]) == (iso(SAMPLE_COMPUTED), "sync_failed")
    assert status["hosts"] == [
        {
            "host": BINANCE_HOST,
            "last_success": None,
            "error": "418",
            "backoff_until": iso(now + timedelta(minutes=20)),
        },
        {
            "host": ARCHIVE_HOST,
            "last_success": iso(SAMPLE_COMPUTED),
            "error": None,
            "backoff_until": None,
        },
        {"host": BYBIT_HOST, "last_success": None, "error": "retcode:10006", "backoff_until": None},
    ]
    assert status["direction"] == "pending"
    assert status["direction_check"]["binance"]["verdict"] == "ok"
    assert status["direction_check"]["bybit_qty"]["notional_in_range"] is None

    def both(binance: Verdict, bybit: Verdict) -> Verdict:
        return direction(Directions(binance=check(binance), bybit=check(bybit), bybit_qty=units))

    assert both("ok", "ok") == "ok"
    assert both("ok", "pending") == "pending"
    assert both("ok", "inverted") == both("inverted", "pending") == "inverted"
    assert direction(None) == "pending"


def test_capability_and_get_only_routes(tmp_path: Path):
    app = create_app(tmp_path / "m.sqlite", start_worker=False, start_perps=False)
    with TestClient(app) as http:
        capabilities = http.get("/api/wheelhouse/v1/status").json()["capabilities"]
        paths = http.get("/api/wheelhouse/v1/openapi.json").json()["paths"]
        bad = http.get(f"{PREFIX}/states", params={"exchange": "okx"})
        defaults = http.get(f"{PREFIX}/states").json()

    assert "perps" in capabilities
    perps = {path: set(methods) for path, methods in paths.items() if "/perps/" in path}
    assert perps == {f"{PREFIX}/states": {"get"}, f"{PREFIX}/status": {"get"}}
    assert bad.status_code == 422
    assert (defaults["exchange"], defaults["window"]) == ("all", "4h")


def test_sample_json_regenerates_identically(tmp_path: Path):
    view = sample_view()

    # Every state is in both tables, nothing is collecting or failing, and a block is forming.
    for table in view.tables:
        assert all(row.count > 0 for row in table.rows), table.show_days
        assert [row.state for row in table.rows] == list(TABLE_STATES)
    assert (view.data_state, view.reasons, view.qc, view.collecting) == ("fresh", [], [], False)
    assert view.blocks[-1].forming and view.tail is None
    assert all(status.live for status in view.collectors)
    assert SAMPLE.read_text() == render_sample()

    # The route serves the same body from the same stored payload and coverage.
    path = tmp_path / "perps.sqlite"
    store = PerpsStore(path)
    save(store, "all", "4h", compute_states(synthetic_grid(SAMPLE_START, SAMPLE_LAST), "4h"))
    for stream in STREAMS:
        cover(store, stream, SAMPLE_START.timestamp(), SAMPLE_NOW.timestamp() - 6.0)
    with TestClient(router_app(path, Clock(SAMPLE_NOW))) as http:
        assert get_states(http, "all") == json.loads(SAMPLE.read_text())


if __name__ == "__main__":
    SAMPLE.write_text(render_sample())
