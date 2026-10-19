"""The perps REST worker: schedule, head and tail gaps, the OI hist/archive split, per-host
backoff, the eight derived payloads, the liquidation direction check and pruning."""

import io
import json
import logging
import shutil
import threading
import time
import zipfile
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from wheelhouse_service import derive
from wheelhouse_service.market import timestamp
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.perps import sync as sync_module
from wheelhouse_service.perps.coinalyze import (
    BASE_ASSET,
    FIELDS,
    KIND_VENUES,
    MARKETS_PATH,
    PATHS,
    STEPS,
    SYMBOLS,
    Coinalyze,
    Interval,
    MarketCheck,
)
from wheelhouse_service.perps.rows import (
    CzKind,
    CzPoint,
    CzVenue,
    Exchange,
    Kline,
    OiPoint,
    RawLiquidation,
    Trade,
)
from wheelhouse_service.perps.sources import (
    ARCHIVE_HOST,
    BINANCE_HOST,
    BYBIT_HOST,
    CZ_HOST,
    PerpsRest,
    RestError,
)
from wheelhouse_service.perps.states import Grid, StatesResult, Window, compute_states
from wheelhouse_service.perps.store import PerpsStore, Venue
from wheelhouse_service.perps.sync import (
    CZ_CALLS_PER_MINUTE,
    CZ_SETTLE,
    DIRECTION_MOVE,
    H4,
    RETENTION_DAYS,
    DirectionCheck,
    Directions,
    HostState,
    PerpsSync,
    StoredStates,
    derive_states,
    derived_key,
    direction_check,
    gaps,
    next_slot,
    stored_markets,
)
from wheelhouse_service.rules import ALL_RULES, Rules

BAR = 300
STEP = 600
DAY = 86_400
NOW = datetime(2026, 10, 17, 12, 2, 30, tzinfo=UTC)
NOW_TS = int(NOW.timestamp())
TODAY = NOW_TS // DAY * DAY
END = NOW_TS + 1  # fetch ranges are half-open and reach now
LAST_BAR = NOW_TS // BAR * BAR - BAR  # the last closed 5m bar opens at 11:55
EXCHANGES: tuple[Exchange, ...] = ("all", "binance", "bybit", "hyperliquid")
WINDOWS: tuple[Window, ...] = ("4h", "8h")
ARCHIVE_SHIFT = 0.5  # archive OI differs from hist OI so that the source of a row shows
M5 = 300
KEY = "test-key-0000"
WINDOW = NOW_TS // H4 * H4  # 12:00, the 4hour window forming at NOW
NEWEST = WINDOW - H4  # 08:00, the newest closed 4hour window
CLOSED_5MIN = NOW_TS // M5 * M5 - M5  # 11:55, the newest closed 5min interval
V1: Rules = frozenset()
O1: Rules = frozenset({"O1"})
O6: Rules = frozenset({"O6"})
O1O6: Rules = frozenset({"O1", "O6"})


def start_of(horizon_days: int) -> int:
    return TODAY - (horizon_days + 1) * DAY


def moment(t: int) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def clock_time(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 17, hour, minute, second, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: float) -> None:
        self.now += timedelta(minutes=minutes)


def close(t: int) -> float:
    """The close of the 5m bar opening at t: 0.5% lower in odd 10m buckets. A 4h window's first
    bucket is even and its last odd, so the window falls 0.5%, short of DIRECTION_MOVE."""
    return 59_700.0 if t // STEP % 2 else 60_000.0


def hist_oi(t: int) -> float:
    return 80_000.0 + t // BAR % 97


def stamps(start: int, end: int) -> range:
    return range(-(-start // BAR) * BAR, end, BAR)


class FakeRest(PerpsRest):
    """The public endpoints over synthetic series, every call recorded.

    Binance keeps 30 days of OI history; every archive day has a file unless it is in `absent`.
    A host in `fail` answers with that code and is backed off for that many seconds.
    """

    def __init__(self, clock: Clock) -> None:
        super().__init__(clock=clock)
        self.calls: list[tuple[object, ...]] = []
        self.fail: dict[str, tuple[str, int]] = {}
        self.absent: set[date] = set()
        self.broken: set[date] = set()  # archive days answered with a 500
        self.bybit_oi_rows = True
        # By 4h window: a factor on the spot closes of its second half, which moves it by more
        # than DIRECTION_MOVE.
        self.moves: dict[int, float] = {}

    def named(self, name: str) -> list[tuple[object, ...]]:
        return [call[1:] for call in self.calls if call[0] == name]

    def hosts_asked(self) -> set[str]:
        hosts = {
            "binance_klines": BINANCE_HOST,
            "binance_oi_hist": BINANCE_HOST,
            "binance_oi_archive": ARCHIVE_HOST,
            "bybit_spot_klines": BYBIT_HOST,
            "bybit_oi": BYBIT_HOST,
        }
        return {hosts[str(call[0])] for call in self.calls}

    def _now(self) -> int:
        return int(self._clock().timestamp())

    def _ask(self, host: str, *call: object) -> None:
        self.calls.append(call)
        until = self.backoff_until(host)
        if until is not None:
            raise RestError(host, "backoff", until)
        if host in self.fail:
            code, seconds = self.fail[host]
            self._until[host] = self._clock() + timedelta(seconds=seconds)
            raise RestError(host, code, self._until[host])

    def binance_klines(self, start: int, end: int) -> list[Kline]:
        self._ask(BINANCE_HOST, "binance_klines", start, end)
        return [
            Kline(t=t, close=close(t), volume=10.0, taker_buy=6.0, source="binance_perp")
            for t in stamps(start, end)
            if t + BAR <= self._now()
        ]

    def binance_oi_hist(self, start: int) -> list[OiPoint]:
        self._ask(BINANCE_HOST, "binance_oi_hist", start)
        kept = self._now() - 30 * DAY
        return [
            OiPoint(t=t, oi=hist_oi(t), source="hist")
            for t in stamps(max(start, kept), self._now() + 1)
        ]

    def binance_oi_archive(self, day: date) -> tuple[list[OiPoint], bool] | None:
        self._ask(ARCHIVE_HOST, "binance_oi_archive", day)
        if day in self.broken:
            raise RestError(ARCHIVE_HOST, "500")
        if day in self.absent:
            return None
        first = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
        points = [
            OiPoint(t=t + BAR, oi=hist_oi(t + BAR) + ARCHIVE_SHIFT, source="archive")
            for t in range(first, first + DAY, BAR)
        ]
        return points, False

    def spot_close(self, t: int) -> float:
        window = t // H4 * H4
        return close(t) * self.moves.get(window, 1.0) if t - window >= H4 // 2 else close(t)

    def bybit_spot_klines(self, start: int, end: int) -> list[Kline]:
        self._ask(BYBIT_HOST, "bybit_spot_klines", start, end)
        return [
            Kline(t=t, close=self.spot_close(t), volume=None, taker_buy=None, source="bybit_spot")
            for t in stamps(start, end)
            if t + BAR <= self._now()
        ]

    def bybit_oi(self, start: int, end: int) -> list[OiPoint]:
        self._ask(BYBIT_HOST, "bybit_oi", start, end)
        if not self.bybit_oi_rows:
            return []
        return [
            OiPoint(t=t, oi=50_000.0 + t // BAR % 89, source="bybit")
            for t in stamps(start, min(end, self._now() + 1))
        ]


@pytest.fixture
def store(tmp_path: Path) -> PerpsStore:
    return PerpsStore(tmp_path / "perps.sqlite3")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def rest(clock: Clock) -> FakeRest:
    return FakeRest(clock)


def clock_ts(hour: int, minute: int) -> int:
    return int(clock_time(hour, minute).timestamp())


def cz_point(t: int, revision: int = 0) -> CzPoint:
    return CzPoint(t=t, a=1.0 + t % 97 + revision, b=2.0 + t % 89)


def seed_cz(store: PerpsStore, first: int, last: int = NEWEST) -> None:
    """Closed 4hour rows of every kind and venue, a window each from `first` to `last`."""
    for kind, venues in KIND_VENUES.items():
        for venue in venues:
            store.upsert_cz(kind, H4, venue, [cz_point(t) for t in range(first, last + 1, H4)])


def liquidate(
    store: PerpsStore, venue: CzVenue, windows: Iterable[int], a: float, b: float
) -> None:
    store.upsert_cz("liq", H4, venue, [CzPoint(t=w, a=a, b=b) for w in windows])


CZ_CHECKS = [
    MarketCheck(venue=venue, symbol=symbol, denominated=BASE_ASSET, buy_sell=True, ok=True)
    for venue, symbol in SYMBOLS.items()
]


class Meter:
    """The worker's monotonic clock and pause, faked: a pause moves the clock instead of
    sleeping, and answers as asked whether the worker is stopping."""

    def __init__(self) -> None:
        self.now = 0.0
        self.pauses: list[float] = []
        self.stop = False

    def __call__(self) -> float:
        return self.now

    def pause(self, seconds: float) -> bool:
        self.pauses.append(seconds)
        self.now += seconds
        return self.stop


class FakeCoinalyze(Coinalyze):
    """Coinalyze over synthetic closed series, every call recorded and no request made.

    `times` holds the meter's time and the symbols charged for each request, markets included;
    each request takes `latency` seconds of it.
    """

    def __init__(self, clock: Clock, meter: Meter, latency: float = 0.0) -> None:
        super().__init__(PerpsRest(clock=clock), KEY, clock)
        self.clock = clock
        self.meter = meter
        self.latency = latency
        self.calls: list[tuple[CzKind, Interval, int, int]] = []
        self.times: list[tuple[float, int]] = []
        self.markets_calls = 0
        self.revision = 0  # added to every value: a later fetch that corrects an earlier one
        self.late: dict[tuple[CzKind, CzVenue], int] = {}  # a venue's data ends at this stamp
        self.checks = CZ_CHECKS
        self.history_error: RestError | None = None
        self.markets_error: RestError | None = None

    def _charge(self, cost: int) -> None:
        self.times.append((self.meter.now, cost))
        self.meter.now += self.latency

    def history(
        self, kind: CzKind, interval: Interval, frm: int, to: int
    ) -> dict[CzVenue, list[CzPoint]]:
        self.calls.append((kind, interval, frm, to))
        self._charge(len(KIND_VENUES[kind]))
        if self.history_error:
            raise self.history_error
        step, now = STEPS[interval], self.clock().timestamp()
        return {
            venue: [
                cz_point(t, self.revision)
                for t in range(-(-frm // step) * step, to + 1, step)
                if t + step <= now and t <= self.late.get((kind, venue), t)
            ]
            for venue in KIND_VENUES[kind]
        }

    def markets(self) -> list[MarketCheck]:
        self.markets_calls += 1
        self._charge(1)
        if self.markets_error:
            raise self.markets_error
        return list(self.checks)


def wire(
    omit_liq: frozenset[str] = frozenset(),
) -> Callable[[httpx.Request], httpx.Response]:
    """Coinalyze's replies in its own shape: every interval from `from` to `to` for each symbol
    asked for, the ones still open at `to` included. The liquidation symbols in `omit_liq` are
    left out, as Coinalyze does for a symbol with nothing to report."""
    paths = {path: kind for kind, path in PATHS.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == MARKETS_PATH:
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": symbol,
                        "oi_lq_vol_denominated_in": BASE_ASSET,
                        "has_buy_sell_data": True,
                    }
                    for symbol in SYMBOLS.values()
                ],
            )
        query = request.url.params
        kind = paths[request.url.path]
        step = STEPS[query["interval"]]
        first, second = FIELDS[kind]
        stamps = range(-(-int(query["from"]) // step) * step, int(query["to"]) + 1, step)
        history = [{"t": t, first: cz_point(t).a, second: cz_point(t).b} for t in stamps]
        left_out = omit_liq if kind == "liq" else frozenset()
        symbols = [symbol for symbol in query["symbols"].split(",") if symbol not in left_out]
        return httpx.Response(
            200, json=[{"symbol": symbol, "history": history} for symbol in symbols]
        )

    return handler


def real_coinalyze(
    clock: Clock, handler: Callable[[httpx.Request], httpx.Response], key: str | None = KEY
) -> tuple[Coinalyze, list[httpx.Request]]:
    """The real client over a handler, and the requests the handler saw."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    rest = PerpsRest(httpx.Client(transport=httpx.MockTransport(record)), clock)
    return Coinalyze(rest, key, clock), seen


def cz_worker(
    store: PerpsStore,
    rest: PerpsRest,
    clock: Clock,
    coinalyze: Coinalyze,
    meter: Meter,
    horizon_days: int = 2,
) -> PerpsSync:
    return PerpsSync(
        store,
        rest,
        clock=clock,
        rules=V1,
        horizon_days=horizon_days,
        coinalyze=coinalyze,
        monotonic=meter,
        pause=meter.pause,
    )


@pytest.fixture
def meter() -> Meter:
    return Meter()


@pytest.fixture
def cz(clock: Clock, meter: Meter) -> FakeCoinalyze:
    return FakeCoinalyze(clock, meter)


def worker(
    store: PerpsStore,
    rest: PerpsRest,
    clock: Clock,
    horizon_days: int = 2,
    rules: Rules = V1,
) -> PerpsSync:
    return PerpsSync(store, rest, clock=clock, rules=rules, horizon_days=horizon_days)


def hosts_of(store: PerpsStore) -> dict[str, HostState]:
    stored = json.loads(store.state()["hosts"] or "{}")
    return {host: HostState.model_validate(value) for host, value in stored.items()}


def payload(store: PerpsStore, exchange: Exchange, window: Window) -> StoredStates:
    found = store.derived(derived_key(exchange, window))
    assert found is not None
    return StoredStates.model_validate_json(found[0])


def liquidation(venue: Venue, ts: int, side: str, qty: str) -> RawLiquidation:
    ms, price = ts * 1000, "59700.0"
    raw: dict[str, object]
    if venue == "binance":
        raw = {"s": "BTCUSDT", "S": side, "ap": price, "X": "FILLED", "z": qty, "T": ms}
    else:
        raw = {"T": ms, "s": "BTCUSDT", "S": side, "v": qty, "p": price}
    return RawLiquidation(event_ts=ts, key=f"{ms}|{side}|{qty}|{price}", raw=json.dumps(raw))


def test_first_run_immediate_then_x5_slots(store: PerpsStore, rest: FakeRest, clock: Clock):
    assert next_slot(clock_time(12, 4, 59)) == clock_time(12, 5)
    assert next_slot(clock_time(12, 5)) == clock_time(12, 15)
    assert next_slot(clock_time(23, 55, 1)) == datetime(2026, 10, 18, 0, 5, tzinfo=UTC)

    sync = worker(store, rest, clock)
    assert sync.run_once() is True  # 12:02:30 is no slot: the first run does not wait for one
    assert store.state()["next_run_at"] == timestamp(clock_time(12, 5))
    for now, due in [
        (clock_time(12, 4, 59), False),
        (clock_time(12, 5), True),
        (clock_time(12, 14, 59), False),
        (clock_time(12, 15), True),
    ]:
        clock.now = now
        asked = len(rest.calls)
        assert sync.run_once() is due
        assert (len(rest.calls) > asked) is due
    assert sync.run_once(now=clock_time(12, 24)) is False
    assert sync.run_once(now=clock_time(12, 25)) is True
    assert store.state()["next_run_at"] == timestamp(clock_time(12, 35))

    # The worker thread runs at once and stops on request.
    fresh = FakeRest(clock)
    threaded = worker(store, fresh, clock)
    threaded.start()
    try:
        deadline = time.monotonic() + 10
        while not fresh.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        assert fresh.calls
    finally:
        threaded.stop()
    assert threaded.thread is not None
    assert threaded.thread.name == "wheelhouse-perps"
    assert not threaded.thread.is_alive()


def test_head_and_tail_gaps_filled_middle_left(store: PerpsStore, rest: FakeRest, clock: Clock):
    start = start_of(2)
    first = start + DAY
    last = TODAY + 10 * 3600
    hole = set(range(start + 2 * DAY, start + 2 * DAY + 6 * 3600, BAR))
    stored = [t for t in range(first, last + 1, BAR) if t not in hole]
    store.upsert_klines(
        "bybit",
        [Kline(t=t, close=1.0, volume=None, taker_buy=None, source="bybit_spot") for t in stored],
    )
    store.upsert_oi("binance", [OiPoint(t=t, oi=1.0, source="hist") for t in stored])

    worker(store, rest, clock).run_once()

    # The head gap up to the first stored row, then the last three stored rows onwards.
    tail = last - 2 * BAR
    assert rest.named("bybit_spot_klines") == [(start, first), (tail, END)]
    assert rest.named("binance_oi_hist") == [(start,), (tail,)]
    # Nothing was stored for these: one range from the horizon's start.
    assert rest.named("bybit_oi") == [(start, END)]
    assert rest.named("binance_klines") == [(start, END)]

    spot = store.klines("bybit", 0)
    oi = store.oi("binance", 0)
    assert set(range(start, first, BAR)) <= spot.keys()
    assert set(range(start, first, BAR)) <= oi.keys()
    # The middle hole is left for QC, although the OI history returned it.
    assert not hole & spot.keys()
    assert not hole & oi.keys()
    assert max(spot) == LAST_BAR
    assert max(oi) == NOW_TS // BAR * BAR
    # The overlap is fetched again; rows before it are not.
    assert spot[tail][0] == close(tail) and spot[last][0] == close(last)
    assert spot[tail - BAR][0] == 1.0
    assert oi[last] == (hist_oi(last), "hist")
    assert oi[tail - BAR] == (1.0, "hist")


def test_backfill_hist_29d_then_archive(
    store: PerpsStore, rest: FakeRest, clock: Clock, monkeypatch: pytest.MonkeyPatch
):
    start = start_of(31)
    # Rounded up to the next 5m stamp: the history is asked for a little less than 29 days.
    boundary = -(-(NOW_TS - 29 * DAY) // BAR) * BAR
    assert boundary > NOW_TS - 29 * DAY
    days = [moment(start).date() + timedelta(days=n) for n in range(4)]
    assert days[-1] == moment(boundary).date()  # archive files run up to the boundary's day
    rest.absent = {days[0]}
    writes: list[Sequence[int]] = []
    upsert = store.upsert_oi

    def spy(venue: Venue, rows: Sequence[OiPoint]) -> None:
        if venue == "binance":
            writes.append([row.t for row in rows])
        upsert(venue, rows)

    monkeypatch.setattr(store, "upsert_oi", spy)
    sync = worker(store, rest, clock, horizon_days=31)
    sync.run_once()

    # Newest first: the last 29 days from the history, then the files back from its first day.
    assert rest.named("binance_oi_hist") == [(boundary,)]
    assert rest.named("binance_oi_archive") == [(day,) for day in reversed(days)]
    assert store.archive_absent(days[0])
    oi = store.oi("binance", 0)
    assert min(oi) == start + DAY + BAR  # the first file's first row; the day before has none
    assert all(oi[t] == (hist_oi(t) + ARCHIVE_SHIFT, "archive") for t in oi if t < boundary)
    # From the boundary on, the history wins over the boundary day's file.
    assert all(oi[t] == (hist_oi(t), "hist") for t in oi if t >= boundary)
    assert {boundary, boundary + BAR, start + 4 * DAY} <= oi.keys()
    # One transaction per day: three archive files, then the history's 30 UTC days (09-18 from
    # 12:00, 28 whole days, 10-17 up to 12:00).
    assert all(max(ts) - min(ts) < DAY for ts in writes)
    assert len(writes) == 3 + 30

    # The missing file is not asked for again, and the history carries on from the overlap.
    rest.calls.clear()
    clock.advance(minutes=10)
    assert sync.run_once()
    assert rest.named("binance_oi_archive") == []
    assert rest.named("binance_oi_hist") == [(max(oi) - 2 * BAR,)]


def test_archive_failure_resumes_without_hole(store: PerpsStore, rest: FakeRest, clock: Clock):
    start = start_of(31)
    days = [moment(start).date() + timedelta(days=n) for n in range(4)]
    rest.broken = {days[2]}
    sync = worker(store, rest, clock, horizon_days=31)
    sync.run_once()

    # Filled newest first, the failure ends the gap: the older days wait for the next round.
    assert rest.named("binance_oi_archive") == [(days[3],), (days[2],)]
    assert hosts_of(store)[ARCHIVE_HOST].error == "500"
    assert min(store.oi("binance", 0)) == start + 3 * DAY + BAR

    rest.broken.clear()
    rest.calls.clear()
    clock.advance(minutes=10)
    sync.run_once()

    assert rest.named("binance_oi_archive") == [(days[2],), (days[1],), (days[0],)]
    assert hosts_of(store)[ARCHIVE_HOST].error is None
    newest = int(clock.now.timestamp()) // BAR * BAR
    assert set(store.oi("binance", 0)) == set(range(start + BAR, newest + 1, BAR))


def test_long_outage_tail_waits_for_the_archive(store: PerpsStore, rest: FakeRest, clock: Clock):
    start = start_of(31)
    days = [moment(start).date() + timedelta(days=n) for n in range(4)]
    # Stored up to 09-16 00:00, more than 29 days ago: the tail needs files, then the history.
    store.upsert_oi(
        "binance", [OiPoint(t=t, oi=1.0, source="hist") for t in range(start, start + DAY + 1, BAR)]
    )
    rest.broken = {days[2]}
    sync = worker(store, rest, clock, horizon_days=31)
    sync.run_once()

    # Oldest first; the failed file ends the gap, so the history does not leave a hole behind.
    assert rest.named("binance_oi_archive") == [(days[0],), (days[1],), (days[2],)]
    assert rest.named("binance_oi_hist") == []
    assert max(store.oi("binance", 0)) == start + 2 * DAY

    rest.broken.clear()
    rest.calls.clear()
    clock.advance(minutes=10)
    sync.run_once()

    assert rest.named("binance_oi_archive") == [(days[1],), (days[2],), (days[3],)]
    newest = int(clock.now.timestamp()) // BAR * BAR
    assert set(store.oi("binance", 0)) == set(range(start, newest + 1, BAR))


def test_binance_backoff_does_not_stop_bybit(store: PerpsStore, rest: FakeRest, clock: Clock):
    rest.fail[BINANCE_HOST] = ("418", 1800)
    sync = worker(store, rest, clock)
    sync.run_once()

    # The first Binance request fails and ends that host's round; Bybit carries on.
    assert len(rest.named("binance_klines")) == 1
    assert rest.named("binance_oi_hist") == []
    assert rest.named("bybit_spot_klines") == [(start_of(2), END)]
    assert rest.named("bybit_oi") == [(start_of(2), END)]
    assert max(store.klines("bybit", 0)) == LAST_BAR
    assert store.oi("bybit", 0)
    assert store.klines("binance", 0) == {}
    hosts = hosts_of(store)
    assert hosts[BINANCE_HOST] == HostState(
        last_success=None, error="418", until=NOW + timedelta(minutes=30)
    )
    assert hosts[BYBIT_HOST] == HostState(last_success=NOW, error=None, until=None)
    assert hosts[ARCHIVE_HOST] == HostState(last_success=None, error=None, until=None)

    # Inside the backoff Binance is not asked, even though it would answer again.
    rest.fail.clear()
    rest.calls.clear()
    clock.advance(minutes=10)
    assert sync.run_once()
    assert rest.hosts_asked() == {BYBIT_HOST}
    assert hosts_of(store)[BINANCE_HOST].error == "418"
    assert hosts_of(store)[BYBIT_HOST].last_success == clock.now

    # A restarted worker keeps the stored backoff, though its client has forgotten it.
    restarted = FakeRest(clock)
    clock.advance(minutes=10)
    assert worker(store, restarted, clock).run_once()
    assert restarted.hosts_asked() == {BYBIT_HOST}

    # The first slot after the backoff asks again, and the success clears the error.
    rest.calls.clear()
    clock.advance(minutes=20)
    assert sync.run_once()
    assert rest.named("binance_klines") == [(start_of(2), END + 40 * 60)]
    assert hosts_of(store)[BINANCE_HOST] == HostState(
        last_success=clock.now, error=None, until=None
    )


def test_bybit_failure_does_not_stop_binance(store: PerpsStore, rest: FakeRest, clock: Clock):
    rest.fail[BYBIT_HOST] = ("403", 600)
    worker(store, rest, clock).run_once()

    # The first Bybit request fails and ends that host's round; Binance carries on in it.
    assert rest.named("bybit_spot_klines") == [(start_of(2), END)]
    assert rest.named("bybit_oi") == []
    assert rest.named("binance_klines") == [(start_of(2), END)]
    assert rest.named("binance_oi_hist") == [(start_of(2),)]
    assert max(store.klines("binance", 0)) == LAST_BAR
    assert max(store.oi("binance", 0)) == NOW_TS // BAR * BAR
    assert store.klines("bybit", 0) == {} and store.oi("bybit", 0) == {}
    hosts = hosts_of(store)
    assert hosts[BYBIT_HOST] == HostState(
        last_success=None, error="403", until=NOW + timedelta(minutes=10)
    )
    assert hosts[BINANCE_HOST] == HostState(last_success=NOW, error=None, until=None)
    assert store.state()["last_error"] is None
    # Every view prices with Bybit spot, so each is stored without it.
    for exchange in EXCHANGES:
        stored = payload(store, exchange, "4h")
        assert stored.states is None
        assert stored.reasons[0] == "series_missing:bybit:price"


def test_unexpected_failure_while_fetching_is_sync_failed(
    store: PerpsStore,
    rest: FakeRest,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    old = (NOW_TS - 126 * DAY) // BAR * BAR
    store.upsert_klines(
        "binance", [Kline(t=old, close=1.0, volume=1.0, taker_buy=0.5, source="binance_perp")]
    )

    def broken(start: int, end: int) -> list[Kline]:
        raise ValueError("unexpected reply 12345")

    monkeypatch.setattr(rest, "binance_klines", broken)
    sync = worker(store, rest, clock)
    with caplog.at_level(logging.INFO, logger="wheelhouse.perps.sync"):
        assert sync.run_once()

    state = store.state()
    assert state["last_error"] == "sync_failed"
    assert (state["last_run_at"], state["next_run_at"]) == (
        timestamp(NOW),
        timestamp(clock_time(12, 5)),
    )
    assert old not in store.klines("binance", 0)  # the prune still ran
    assert store.derived(derived_key("all", "4h")) is None
    messages = [record.getMessage() for record in caplog.records]
    assert "perps_sync_failed code=sync_failed" in messages
    assert not any("12345" in message for message in messages)  # a fixed code, never values

    # The next round runs as usual and clears the error.
    monkeypatch.delattr(rest, "binance_klines")
    clock.now = clock_time(12, 5)
    assert sync.run_once()
    assert store.state()["last_error"] is None
    assert store.derived(derived_key("all", "4h")) is not None


def archive_file(day: date, stale: date) -> bytes:
    """The day's metrics file, as data.binance.vision zips it. On `stale` the 10:55 value
    repeats 10:50's, the pattern the archive quarantine catches."""
    first = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
    lines = [
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio"
    ]
    for t in range(first, first + DAY, BAR):
        repeat = day == stale and t == first + 10 * 3600 + 55 * 60
        value = hist_oi((t - BAR if repeat else t) + BAR) + ARCHIVE_SHIFT
        created = datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"{created},BTCUSDT,{value},1.0,1.0,1.0,1.0,1.0")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"BTCUSDT-metrics-{day.isoformat()}.csv", "\n".join(lines) + "\n")
    return buffer.getvalue()


def test_archive_quarantine_reaches_the_payload_through_the_worker(
    store: PerpsStore, rest: FakeRest, clock: Clock, monkeypatch: pytest.MonkeyPatch
):
    start = start_of(31)
    days = [moment(start).date() + timedelta(days=n) for n in range(4)]
    stale = days[1]

    def files(request: httpx.Request) -> httpx.Response:
        day = date.fromisoformat(request.url.path.removesuffix(".zip")[-10:])
        return httpx.Response(200, content=archive_file(day, stale))

    # The worker reaches the real archive parser; only the files are made up.
    parser = PerpsRest(httpx.Client(transport=httpx.MockTransport(files)), clock=clock)

    def archive(day: date) -> tuple[list[OiPoint], bool] | None:
        rest.calls.append(("binance_oi_archive", day))
        return parser.binance_oi_archive(day)

    monkeypatch.setattr(rest, "binance_oi_archive", archive)
    worker(store, rest, clock, horizon_days=31).run_once()

    assert rest.named("binance_oi_archive") == [(day,) for day in reversed(days)]
    oi = store.oi("binance", 0)
    first = int(datetime(stale.year, stale.month, stale.day, tzinfo=UTC).timestamp())
    # Quarantined from the stale pair's first row (created 10:50, stamped 10:55) to the end.
    quarantined = range(first + 10 * 3600 + 55 * 60, first + DAY + BAR, BAR)
    assert all(oi[t] == (None, "archive") for t in quarantined)
    assert oi[first + 10 * 3600 + 50 * 60] == (
        hist_oi(first + 10 * 3600 + 50 * 60) + ARCHIVE_SHIFT,
        "archive",
    )
    assert {t for t, (value, _) in oi.items() if value is None} == set(quarantined)
    for exchange in ("all", "binance"):
        states = payload(store, exchange, "4h").states
        assert states is not None and "archive_quarantined:1" in states.qc
    bybit = payload(store, "bybit", "4h").states
    assert bybit is not None and not any(code.startswith("archive") for code in bybit.qc)


@pytest.mark.parametrize(
    "stored",
    [
        [],
        [-3 * BAR, -2 * BAR],  # only before the start
        [-2 * BAR, BAR, 2 * BAR],  # a hole at the start
        [-BAR, 0, BAR, 5 * BAR],
        [3 * BAR, 4 * BAR, 9 * BAR],  # a head gap
    ],
)
def test_gaps_from_stamps_equal_gaps_from_all_rows(store: PerpsStore, stored: list[int]):
    start = start_of(2)
    rows = [start + t for t in stored]
    store.upsert_klines(
        "bybit",
        [Kline(t=t, close=1.0, volume=None, taker_buy=None, source="bybit_spot") for t in rows],
    )
    assert gaps(store.stamps("kline", "bybit", start), start, END) == gaps(rows, start, END)


def test_derive_states_stores_eight_payloads(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    cz_worker(store, rest, clock, cz, meter).run_once()

    assert sync_module.EXCHANGES == EXCHANGES
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM derived").fetchone()[0] == 8
    for exchange in EXCHANGES:
        for window in WINDOWS:
            found = store.derived(derived_key(exchange, window))
            assert found is not None
            assert found[1] == NOW
            stored = StoredStates.model_validate_json(found[0])
            assert (stored.exchange, stored.window) == (exchange, window)
            assert stored.start == moment(start_of(2))
            assert stored.reasons == []
            assert stored.states is not None
            assert stored.states.window == window
            # Price reads the bar opening at 11:55, OI the row at 12:00: 11:50 is the last bucket.
            assert stored.states.last == clock_time(11, 50)
            # Every window of Coinalyze's OI is there, the 08:00 one closed by 11:50.
            assert stored.states.qc == []


def test_units_mismatch_excludes_the_venue_and_gives_a_reason(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    start = start_of(2)
    rest.moves = dict.fromkeys(range(start, NEWEST + 1, H4), 0.98)  # every window falls
    cz.checks = [
        check.model_copy(update={"ok": False}) if check.venue == "okx" else check
        for check in CZ_CHECKS
    ]
    cz_worker(store, rest, clock, cz, meter).run_once()

    # OKX's rows are stored, but no view reads them: the two views with OKX in them say why.
    assert store.cz_latest("oi", H4)["okx"] == NEWEST
    for exchange in ("all", "hyperliquid"):
        for window in WINDOWS:
            stored = payload(store, exchange, window)
            assert stored.reasons == ["series_missing:okx:oi", "coinalyze_units:okx"]
            assert stored.states is not None
            assert not any(block.liq_covered for block in stored.states.blocks)
    for exchange in ("binance", "bybit"):
        stored = payload(store, exchange, "4h")
        assert stored.reasons == [] and stored.states is not None
        assert all(block.liq_covered for block in stored.states.blocks)
    # OKX's direction is not checked; the others are.
    check = Directions.model_validate_json(store.state()["direction_check"] or "")
    assert check.okx == DirectionCheck(verdict="pending", samples=0, down=0, long_share=None)
    assert check.binance.samples > 0 and check.bybit.samples > 0

    # Hyperliquid's units fail instead: only its own view reads it.
    checks = [
        check.model_copy(update={"ok": False}) if check.venue == "hyperliquid" else check
        for check in CZ_CHECKS
    ]
    store.set_state(cz_markets=json.dumps([check.model_dump(mode="json") for check in checks]))
    derive_states(store, start=start, at=NOW, rules=V1)
    assert payload(store, "hyperliquid", "4h").reasons == [
        "series_missing:hyperliquid:oi",
        "coinalyze_units:hyperliquid",
    ]
    for exchange in ("all", "binance", "bybit"):
        assert payload(store, exchange, "4h").reasons == []


def test_missing_series_stores_unavailable_marker(store: PerpsStore, rest: FakeRest, clock: Clock):
    rest.bybit_oi_rows = False
    worker(store, rest, clock).run_once()

    for exchange in ("all", "bybit"):
        for window in WINDOWS:
            stored = payload(store, exchange, window)
            assert stored.states is None
            assert stored.reasons == ["series_missing:bybit:oi"]
            assert stored.start == moment(start_of(2))
    for window in WINDOWS:
        assert payload(store, "binance", window).states is not None


def test_direction_check_counts_windows_that_moved_one_percent():
    w = TODAY
    assert DIRECTION_MOVE == 0.01

    def spot(first: float, last: float) -> dict[int, tuple[float, float | None, float | None]]:
        # The window's first and last bucket prices: the bars opening at w+5m and w+4h-5m.
        return {
            w: (1.0, None, None),
            w + BAR: (first, None, None),
            w + H4 - BAR: (last, None, None),
        }

    def samples(liq: CzPoint, prices: dict[int, tuple[float, float | None, float | None]]) -> int:
        return direction_check({w: liq}, prices).samples

    liq = CzPoint(t=w, a=1.0, b=0.0)
    assert samples(liq, spot(100.0, 99.0)) == 1  # 1% exactly
    assert samples(liq, spot(100.0, 101.0)) == 1
    assert samples(liq, spot(100.0, 99.1)) == 0
    assert samples(liq, {w + BAR: (100.0, None, None)}) == 0  # no last price
    # Nothing liquidated, or an interval Coinalyze left out: no sample.
    assert samples(CzPoint(t=w, a=0.0, b=0.0), spot(100.0, 98.0)) == 0
    assert samples(CzPoint(t=w, a=1.0, b=0.0, filled=True), spot(100.0, 98.0)) == 0


def test_direction_check_pending_ok_inverted_per_window(
    store: PerpsStore, rest: FakeRest, clock: Clock
):
    windows = list(range(start_of(10), NEWEST + 1, H4))
    falling = windows[2:52:2]  # 25 windows that fall 2.5%
    rising, flat = windows[1], windows[3]
    rest.moves = dict.fromkeys(falling, 0.98) | {rising: 1.02}
    sides: dict[CzVenue, tuple[float, float]] = {
        "binance": (1.0, 0.1),
        "bybit": (0.0, 1.0),  # shorts on falling prices: that reads as inverted
        "okx": (0.5, 0.5),
    }
    for venue, (longs, shorts) in sides.items():
        liquidate(store, venue, falling[:19], longs, shorts)
    # A rising window is sampled but stays out of the metric; one that moved 0.5% is not.
    liquidate(store, "bybit", [rising, flat], 0.001, 0.0)
    # Nothing liquidated in a falling window: no sample.
    store.upsert_cz("liq", H4, "okx", [CzPoint(t=falling[19], a=0.0, b=0.0, filled=True)])
    sync = worker(store, rest, clock, horizon_days=10)
    sync.run_once()

    check = Directions.model_validate_json(store.state()["direction_check"] or "")
    assert (check.binance.verdict, check.binance.samples, check.binance.down) == (
        "pending",
        19,
        19,
    )
    assert check.binance.long_share == pytest.approx(1 / 1.1)
    assert (check.bybit.verdict, check.bybit.samples, check.bybit.down) == ("pending", 20, 19)
    assert check.bybit.long_share == 0.0
    assert (check.okx.verdict, check.okx.samples, check.okx.down) == ("pending", 19, 19)

    for venue, (longs, shorts) in sides.items():
        liquidate(store, venue, falling[19:], longs, shorts)
    clock.advance(minutes=10)
    sync.run_once()

    check = Directions.model_validate_json(store.state()["direction_check"] or "")
    assert (check.binance.verdict, check.binance.down) == ("ok", 25)
    assert check.binance.long_share == pytest.approx(1 / 1.1)
    assert (check.bybit.verdict, check.bybit.down) == ("inverted", 25)
    # Between 0.4 and 0.6 the sides are not told apart.
    assert (check.okx.verdict, check.okx.down, check.okx.long_share) == ("pending", 25, 0.5)


def test_prune_keeps_125d_and_1h_trade_ids(store: PerpsStore, rest: FakeRest, clock: Clock):
    assert RETENTION_DAYS == 125
    old = (NOW_TS - 126 * DAY) // BAR * BAR
    kept = (NOW_TS - 124 * DAY) // BAR * BAR
    store.upsert_klines(
        "binance",
        [
            Kline(t=t, close=1.0, volume=1.0, taker_buy=0.5, source="binance_perp")
            for t in (old, kept)
        ],
    )
    store.insert_liquidations(
        "bybit",
        0,
        [liquidation("bybit", old, "Buy", "0.001"), liquidation("bybit", kept, "Buy", "0.002")],
    )
    store.record_trades(
        "bybit",
        [
            Trade(id="2h", ts=NOW_TS - 7200, side="Buy", qty=1.0),
            Trade(id="30m", ts=NOW_TS - 1800, side="Sell", qty=1.0),
        ],
    )

    worker(store, rest, clock).run_once()

    klines = store.klines("binance", 0)
    assert old not in klines and kept in klines
    assert [ts for _, ts, _, _ in store.liquidations("bybit", 0)] == [kept]
    with store.connection() as db:
        assert [row[0] for row in db.execute("SELECT id FROM trade_ids")] == ["30m"]
    # Only the ids go after an hour; the 10m sums stay.
    assert len(store.trades("bybit", 0)) == 2


def test_prune_runs_after_a_failed_round(
    store: PerpsStore, rest: FakeRest, clock: Clock, monkeypatch: pytest.MonkeyPatch
):
    old = (NOW_TS - 126 * DAY) // BAR * BAR
    store.upsert_klines(
        "binance", [Kline(t=old, close=1.0, volume=1.0, taker_buy=0.5, source="binance_perp")]
    )

    def broken(*_: object) -> None:
        raise RuntimeError("derive failed")

    monkeypatch.setattr("wheelhouse_service.perps.sync.build_grid", broken)
    assert worker(store, rest, clock).run_once()

    assert store.state()["last_error"] == "sync_failed"
    assert old not in store.klines("binance", 0)


def test_a_stop_abandons_a_round_stuck_in_a_request(
    store: PerpsStore, rest: FakeRest, clock: Clock, monkeypatch: pytest.MonkeyPatch
):
    old = (NOW_TS - 126 * DAY) // BAR * BAR
    store.upsert_klines(
        "binance", [Kline(t=old, close=1.0, volume=1.0, taker_buy=0.5, source="binance_perp")]
    )
    # The archive host failed in an earlier round; this round stops before asking it.
    archive = {"last_success": None, "error": "500", "until": None}
    store.set_state(hosts=json.dumps({ARCHIVE_HOST: archive}))
    sync = worker(store, rest, clock)
    asked = threading.Event()

    def stuck(start: int, end: int) -> list[Kline]:
        rest.calls.append(("binance_klines", start, end))
        asked.set()
        sync.stopping.wait(5)  # a slow request, answered once the stop is asked for
        return []

    monkeypatch.setattr(rest, "binance_klines", stuck)
    ran: list[bool] = []
    thread = threading.Thread(target=lambda: ran.append(sync.run_once()))
    thread.start()
    assert asked.wait(5)
    stopped = time.monotonic()
    sync.stopping.set()
    thread.join(5)

    assert not thread.is_alive() and time.monotonic() - stopped < 1
    assert ran == [True]
    # Nothing is asked after the stuck request and nothing is derived; the prune still runs.
    assert [call[0] for call in rest.calls] == ["bybit_spot_klines", "bybit_oi", "binance_klines"]
    assert all(store.derived(derived_key(e, w)) is None for e in EXCHANGES for w in WINDOWS)
    assert old not in store.klines("binance", 0)
    state = store.state()
    assert "last_run_at" not in state and "direction_check" not in state
    # What the requests found is kept, and the host the round never reached keeps its error.
    hosts = hosts_of(store)
    assert hosts[BYBIT_HOST] == HostState(last_success=NOW, error=None, until=None)
    assert hosts[ARCHIVE_HOST] == HostState.model_validate(archive)


def test_rules_reach_compute_states_and_the_payloads(
    store: PerpsStore, rest: FakeRest, clock: Clock, monkeypatch: pytest.MonkeyPatch
):
    seen: list[Rules] = []

    def spy(grid: Grid, window: Window, *, rules: Rules) -> StatesResult:
        seen.append(rules)
        return compute_states(grid, window, rules=rules)

    monkeypatch.setattr("wheelhouse_service.perps.sync.compute_states", spy)
    # Every rule is on, and O1 and O6 are the ones implemented for the perps.
    worker(store, rest, clock, rules=ALL_RULES).run_once()

    assert seen == [O1O6] * 8
    for exchange in EXCHANGES:
        for window in WINDOWS:
            stored = payload(store, exchange, window)
            assert stored.rules == ["O1", "O6"]
            assert stored.states is not None and stored.states.blocks
            assert all(b.thresholds is not None for b in stored.states.blocks)

    seen.clear()
    clock.advance(minutes=10)
    worker(store, rest, clock, rules=V1).run_once()
    assert seen == [V1] * 8
    stored = payload(store, "all", "4h")
    assert stored.rules == []
    assert stored.states is not None
    assert all(b.thresholds is None for b in stored.states.blocks)


def test_o1_reaches_compute_states_and_leaves_the_forming_block_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    seen: list[Rules] = []

    def spy(grid: Grid, window: Window, *, rules: Rules) -> StatesResult:
        seen.append(rules)
        return compute_states(grid, window, rules=rules)

    monkeypatch.setattr("wheelhouse_service.perps.sync.compute_states", spy)

    def derived(rules: Rules) -> StoredStates:
        # At 14:12:30 the last bucket starts at 14:00: the 4h block from 12:00 is forming.
        clock = Clock(clock_time(14, 12, 30))
        store = PerpsStore(tmp_path / f"{''.join(sorted(rules)) or 'v1'}.sqlite")
        worker(store, FakeRest(clock), clock, rules=rules).run_once()
        return payload(store, "all", "4h")

    v1, o1 = derived(V1), derived(O1)
    assert seen == [V1] * 8 + [O1] * 8
    assert (v1.rules, o1.rules) == ([], ["O1"])
    assert v1.states is not None and o1.states is not None
    forming = o1.states.blocks[-1]
    assert (forming.t0, forming.buckets, forming.forming) == (clock_time(12, 0), 13, True)
    # The forming block is drawn and counted as before, but leaves the price and OI samples.
    assert o1.states.blocks == v1.states.blocks
    assert o1.states.covered_days == v1.states.covered_days
    t1, t0 = o1.states.thresholds, v1.states.thresholds
    assert (t1.n_px, t1.n_oi) == (t0.n_px - 1, t0.n_oi - 1)


def full_round(directory: Path, horizon_days: int | None = None) -> PerpsStore:
    """One v1 round at NOW over Coinalyze's 4hour rows of every kind from 121 days back, with 25
    windows 110 days back, before the 90-day reference, that fell 2.5% with liquidations: mostly
    longs at Binance and OKX, shorts at Bybit. Every other window moved 0.5%."""
    directory.mkdir(parents=True, exist_ok=True)
    store = PerpsStore(directory / "perps.sqlite")
    seed_cz(store, start_of(120))
    old = TODAY - 110 * DAY
    falling = range(old, old + 25 * H4, H4)
    liquidate(store, "binance", falling, 1.0, 0.1)
    liquidate(store, "bybit", falling, 0.0, 1.0)
    liquidate(store, "okx", falling, 1.0, 0.1)
    clock = Clock()
    rest = FakeRest(clock)
    rest.moves = dict.fromkeys(falling, 0.98)
    if horizon_days is None:
        sync = PerpsSync(store, rest, clock=clock, rules=V1)
    else:
        sync = worker(store, rest, clock, horizon_days=horizon_days)
    assert sync.run_once()
    return store


@pytest.fixture(scope="module")
def synced_120(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The store of a round with the default horizon; tests copy it before changing it."""
    return full_round(tmp_path_factory.mktemp("synced-120")).path


def test_round_backfills_121_days_and_checks_directions_over_the_whole_grid(
    synced_120: Path, tmp_path: Path
):
    store = PerpsStore(synced_120)
    assert PerpsSync(store, FakeRest(Clock()), clock=Clock(), rules=V1).horizon_days == 120
    for exchange in EXCHANGES:
        for window in WINDOWS:
            assert payload(store, exchange, window).start == moment(start_of(120))
    assert min(store.klines("bybit", 0)) == start_of(120)

    # The windows 110 days back lie in the grid, though not in the 90-day reference: the
    # direction check reads the whole grid, 121 days, each venue on its own.
    check = Directions.model_validate_json(store.state()["direction_check"] or "")
    assert (check.binance.verdict, check.binance.samples, check.binance.down) == ("ok", 25, 25)
    assert (check.bybit.verdict, check.bybit.samples, check.bybit.down) == ("inverted", 25, 25)
    assert (check.okx.verdict, check.okx.samples, check.okx.down) == ("ok", 25, 25)
    # A 90-day backfill reads 91 days: it saw none of them ...
    store_90 = full_round(tmp_path / "horizon-90", horizon_days=90)
    check_90 = Directions.model_validate_json(store_90.state()["direction_check"] or "")
    assert (check_90.binance.samples, check_90.bybit.samples, check_90.okx.samples) == (0, 0, 0)
    # ... and its v1 states, thresholds and tables are the same as those of the 121 days.
    for exchange in EXCHANGES:
        for window in WINDOWS:
            states = payload(store, exchange, window).states
            assert states is not None
            assert states == payload(store_90, exchange, window).states
    # Coinalyze's rows cover the grid: every view is judged, none lacks a series.
    for exchange in EXCHANGES:
        judged = payload(store, exchange, "4h")
        assert judged.reasons == []
        assert judged.states is not None and not judged.states.collecting


def test_derive_command_keeps_the_grid_start_of_the_stored_payloads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    # A round with a 90-day horizon starts its grid later than the default one would.
    store = full_round(tmp_path / "horizon-90", horizon_days=90)
    OnchainStore(store.path.parent / "onchain.sqlite")  # nothing on-chain was stored
    original = {(e, w): store.derived(derived_key(e, w)) for e in EXCHANGES for w in WINDOWS}
    assert payload(store, "all", "4h").start == moment(start_of(90))

    derive.main(["--data-dir", str(store.path.parent), "--rules", "v1"])

    assert capsys.readouterr().out == "derived perps=v1\n"
    assert {(e, w): store.derived(derived_key(e, w)) for e in EXCHANGES for w in WINDOWS} == (
        original
    )


def test_derive_command_rederives_the_perps_of_a_copy(
    synced_120: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    copy = tmp_path / "copy"
    copy.mkdir()
    shutil.copy(synced_120, copy / "perps.sqlite")
    OnchainStore(copy / "onchain.sqlite")  # nothing on-chain was stored
    original = {
        (e, w): PerpsStore(synced_120).derived(derived_key(e, w))
        for e in EXCHANGES
        for w in WINDOWS
    }
    monkeypatch.delenv("WHEELHOUSE_RULES", raising=False)

    # Under v1, from the stored time: the round's own payloads come out again.
    derive.main(["--data-dir", str(copy), "--rules", "v1"])
    assert capsys.readouterr().out == "derived perps=v1\n"
    store = PerpsStore(copy / "perps.sqlite")
    assert {
        (e, w): store.derived(derived_key(e, w)) for e in EXCHANGES for w in WINDOWS
    } == original

    derive.main(["--data-dir", str(copy), "--rules", "O6"])
    assert capsys.readouterr().out == "derived perps=O6\n"
    for exchange in EXCHANGES:
        for window in WINDOWS:
            found = store.derived(derived_key(exchange, window))
            assert found is not None and found[1] == NOW
            stored = StoredStates.model_validate_json(found[0])
            assert (stored.rules, stored.start) == (["O6"], moment(start_of(120)))
            assert stored.states is not None
            assert all(b.thresholds is not None for b in stored.states.blocks)
    # The direction check is the round's, not the command's.
    assert store.state()["direction_check"] == PerpsStore(synced_120).state()["direction_check"]

    # A copy without perps derives the on-chain views alone, as before.
    bare = tmp_path / "bare"
    bare.mkdir()
    OnchainStore(bare / "onchain.sqlite")
    derive.main(["--data-dir", str(bare), "--rules", "O6"])
    assert capsys.readouterr().out == "derived none\n"
    assert not (bare / "perps.sqlite").exists()


# --- Coinalyze history (proposal §3.2, §3.4, §3.7). ---


def test_without_a_coinalyze_client_nothing_is_fetched_or_recorded(
    store: PerpsStore, rest: FakeRest, clock: Clock
):
    assert worker(store, rest, clock).run_once()

    assert all(store.cz_latest(kind, step) == {} for kind in KIND_VENUES for step in (H4, M5))
    assert stored_markets(store.state()) == []
    assert hosts_of(store)[CZ_HOST] == HostState(last_success=None, error=None, until=None)


def test_first_round_backfills_4hour_from_grid_start_and_5min_from_previous_window(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    start = start_of(2)
    assert H4 == 14_400
    cz_worker(store, rest, clock, cz, meter).run_once()

    # Per kind the 4hour history, then the 5min one; the unit check follows all three.
    assert cz.calls == [
        (kind, interval, frm, NOW_TS)
        for kind in KIND_VENUES
        for interval, frm in (("4hour", start), ("5min", WINDOW - H4))
    ]
    assert len(cz.calls) == 6 and cz.markets_calls == 1
    assert [cost for _, cost in cz.times] == [3, 3, 3, 3, 2, 2, 1]
    for kind, venues in KIND_VENUES.items():
        for venue in venues:
            four = store.cz_series(kind, H4, venue, 0)
            five = store.cz_series(kind, M5, venue, 0)
            assert list(four) == list(range(start, NEWEST + 1, H4))
            assert list(five) == list(range(WINDOW - H4, CLOSED_5MIN + 1, M5))
            assert four[NEWEST] == cz_point(NEWEST) and five[CLOSED_5MIN] == cz_point(CLOSED_5MIN)
        assert store.cz_latest(kind, H4) == dict.fromkeys(venues, NEWEST)
        assert store.cz_latest(kind, M5) == dict.fromkeys(venues, CLOSED_5MIN)
        assert json.loads(store.state()[f"cz_4h:{kind}"] or "") == {"from": start}
    assert stored_markets(store.state()) == CZ_CHECKS
    assert datetime.fromisoformat(store.state()["cz_markets_at"] or "") == NOW
    assert hosts_of(store)[CZ_HOST] == HostState(last_success=NOW, error=None, until=None)
    # The round went on to derive the payloads.
    assert store.derived(derived_key("all", "4h")) is not None


def test_next_round_in_the_same_window_after_settling_fetches_only_5min(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    sync = cz_worker(store, rest, clock, cz, meter)
    sync.run_once()
    cz.calls.clear()

    # 13:05 is more than CZ_SETTLE after the 12:00 close, and the 12:00 window is still forming.
    assert CZ_SETTLE == 3600
    clock.now = clock_time(13, 5)
    assert sync.run_once()

    assert cz.calls == [
        (kind, "5min", WINDOW - H4, clock_ts(13, 5)) for kind in ("liq", "ohlcv", "oi")
    ]
    assert cz.markets_calls == 1
    # The 5min series reaches the newest closed interval.
    assert store.cz_latest("liq", M5) == dict.fromkeys(KIND_VENUES["liq"], clock_ts(13, 0))


def test_rounds_in_the_first_hour_after_a_close_refetch_the_last_three_windows(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    sync = cz_worker(store, rest, clock, cz, meter)
    sync.run_once()

    # The 12:00 close is not settled before 13:00. Each round fetches again the last OVERLAP
    # (3) windows: from min(latest) - 2 * H4.
    for minute in (5, 15, 25, 35, 45, 55):
        cz.calls.clear()
        cz.revision += 1
        clock.now = clock_time(12, minute)
        assert sync.run_once()
        four = [call for call in cz.calls if call[1] == "4hour"]
        assert four == [
            (kind, "4hour", NEWEST - 2 * H4, clock_ts(12, minute)) for kind in KIND_VENUES
        ], minute
    # The corrected windows were replaced, the ones before them left as they were.
    series = store.cz_series("oi", H4, "okx", 0)
    assert series[NEWEST] == cz_point(NEWEST, 6)
    assert series[NEWEST - 2 * H4] == cz_point(NEWEST - 2 * H4, 6)
    assert series[NEWEST - 3 * H4] == cz_point(NEWEST - 3 * H4, 0)

    cz.calls.clear()
    clock.now = clock_time(13, 5)
    assert sync.run_once()
    assert [call for call in cz.calls if call[1] == "4hour"] == []


def test_a_closed_window_is_picked_up_by_the_round_after_it_closes(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    sync = cz_worker(store, rest, clock, cz, meter)
    sync.run_once()
    assert store.cz_latest("liq", H4) == dict.fromkeys(KIND_VENUES["liq"], NEWEST)
    assert max(store.cz_series("liq", M5, "bybit", 0)) == CLOSED_5MIN

    # The next window closes at 16:00. Nothing was kept back that could skip it: the round at
    # 16:05 fetches it as a correction, and the 5min from 12:00 on.
    cz.calls.clear()
    clock.now = clock_time(16, 5)
    assert sync.run_once()

    assert ("liq", "4hour", NEWEST - 2 * H4, clock_ts(16, 5)) in cz.calls
    assert ("liq", "5min", WINDOW, clock_ts(16, 5)) in cz.calls
    assert store.cz_latest("liq", H4) == dict.fromkeys(KIND_VENUES["liq"], WINDOW)
    assert max(store.cz_series("liq", M5, "bybit", 0)) == clock_ts(16, 0)


def test_a_venue_behind_the_newest_window_pulls_a_correction_after_settling(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    sync = cz_worker(store, rest, clock, cz, meter)
    cz.late[("ohlcv", "okx")] = NEWEST - H4  # OKX's volume is a window late
    sync.run_once()
    clock.now = clock_time(13, 5)
    cz.calls.clear()
    assert sync.run_once()

    # Settled, but OKX's volume has no row for the newest window: fetched again from three
    # windows before its newest, and only that kind.
    assert [call for call in cz.calls if call[1] == "4hour"] == [
        ("ohlcv", "4hour", NEWEST - H4 - 2 * H4, clock_ts(13, 5))
    ]
    assert store.cz_latest("ohlcv", H4) == {
        "bybit": NEWEST,
        "okx": NEWEST - H4,
        "hyperliquid": NEWEST,
    }

    del cz.late[("ohlcv", "okx")]
    clock.now = clock_time(13, 15)
    cz.calls.clear()
    assert sync.run_once()
    assert len([call for call in cz.calls if call[1] == "4hour"]) == 1
    assert store.cz_latest("ohlcv", H4)["okx"] == NEWEST

    clock.now = clock_time(13, 25)
    cz.calls.clear()
    assert sync.run_once()
    assert [call for call in cz.calls if call[1] == "4hour"] == []


def test_4hour_is_backfilled_again_without_a_marker_from_a_later_start_or_with_a_venue_missing(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    start = start_of(2)
    cz.late[("ohlcv", "hyperliquid")] = start - 1  # nothing in the grid: no rows at all
    sync = cz_worker(store, rest, clock, cz, meter)
    sync.run_once()
    assert store.cz_latest("ohlcv", H4).keys() == {"bybit", "okx"}

    def four(minutes: int) -> list[tuple[CzKind, Interval, int, int]]:
        cz.calls.clear()
        clock.now = clock_time(13, minutes)
        assert sync.run_once()
        return [call for call in cz.calls if call[1] == "4hour"]

    # A venue without rows is fetched from the grid start, round after round.
    assert four(5) == [("ohlcv", "4hour", start, clock_ts(13, 5))]
    assert four(15) == [("ohlcv", "4hour", start, clock_ts(13, 15))]
    del cz.late[("ohlcv", "hyperliquid")]
    assert four(25) == [("ohlcv", "4hour", start, clock_ts(13, 25))]
    assert four(35) == []

    # No marker: that kind starts over.
    store.set_state(**{"cz_4h:oi": None})
    assert four(45) == [("oi", "4hour", start, clock_ts(13, 45))]
    assert json.loads(store.state()["cz_4h:oi"] or "") == {"from": start}
    assert four(55) == []

    # A marker from a later start than the grid's, as after a longer horizon is configured.
    store.set_state(**{"cz_4h:liq": json.dumps({"from": start + DAY})})
    clock.now = clock_time(14, 5)
    cz.calls.clear()
    assert sync.run_once()
    assert [call for call in cz.calls if call[1] == "4hour"] == [
        ("liq", "4hour", start, clock_ts(14, 5))
    ]
    assert json.loads(store.state()["cz_4h:liq"] or "") == {"from": start}

    # A marker from an earlier start is enough: the grid moves forward each day.
    store.set_state(**{"cz_4h:liq": json.dumps({"from": start - DAY})})
    clock.now = clock_time(14, 15)
    cz.calls.clear()
    assert sync.run_once()
    assert [call for call in cz.calls if call[1] == "4hour"] == []


def test_open_bars_are_never_stored(store: PerpsStore, rest: FakeRest, clock: Clock):
    # Coinalyze's replies reach to `to`, so they hold the intervals still open: 12:00 of both
    # steps. OKX's liquidations are left out, as for a symbol with nothing to report.
    client, _ = real_coinalyze(clock, wire(omit_liq=frozenset({SYMBOLS["okx"]})))
    sync = cz_worker(store, rest, clock, client, Meter())
    sync.run_once()

    start = start_of(2)
    for kind, venues in KIND_VENUES.items():
        for venue in venues:
            assert max(store.cz_series(kind, H4, venue, 0)) == NEWEST, (kind, venue)
            assert max(store.cz_series(kind, M5, venue, 0)) == CLOSED_5MIN, (kind, venue)
    # Zero only where Coinalyze left a closed interval out of a liquidation range.
    for step, first, last in ((H4, start, NEWEST), (M5, WINDOW - H4, CLOSED_5MIN)):
        okx = store.cz_series("liq", step, "okx", 0)
        assert list(okx) == list(range(first, last + 1, step))
        assert all(p.filled and (p.a, p.b) == (0.0, 0.0) for p in okx.values())
        binance = store.cz_series("liq", step, "binance", 0)
        assert not any(p.filled for p in binance.values())
    assert max(store.cz_series("oi", M5, "okx", 0)) == CLOSED_5MIN

    # They are stored once they have closed.
    clock.now = clock_time(16, 5)
    sync.run_once()
    assert max(store.cz_series("liq", H4, "binance", 0)) == WINDOW
    assert max(store.cz_series("liq", M5, "binance", 0)) == clock_ts(16, 0)
    assert store.cz_series("liq", M5, "binance", 0)[WINDOW] == cz_point(WINDOW)


def test_coinalyze_calls_are_paced(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    sync = cz_worker(store, rest, clock, cz, meter)
    sync.run_once()

    # A first round costs 8 + 8 + 1 = 17 symbol-calls, under the limit: no wait.
    assert CZ_CALLS_PER_MINUTE == 20
    assert sum(cost for _, cost in cz.times) == 17
    assert meter.pauses == []

    # A second one in the same minute, past the settling hour, adds the 8 of the 5min series.
    clock.now = clock_time(13, 5)
    assert sync.run_once()

    assert sum(cost for _, cost in cz.times) == 25 > CZ_CALLS_PER_MINUTE
    # The first of them fits (17 + 3 = 20). The next would be 23: it waits for the minute to
    # pass, then the rest go.
    assert meter.pauses == [60.0]
    assert [at for at, _ in cz.times[-3:]] == [0.0, 60.0, 60.0]
    for at, _ in cz.times:
        spent = sum(cost for t, cost in cz.times if at - 60 < t <= at)
        assert spent <= CZ_CALLS_PER_MINUTE, at
    assert store.cz_latest("oi", M5) == dict.fromkeys(KIND_VENUES["oi"], clock_ts(13, 0))


def test_a_host_that_is_closed_is_not_waited_for(
    store: PerpsStore,
    rest: FakeRest,
    clock: Clock,
    cz: FakeCoinalyze,
    meter: Meter,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(sync_module, "CZ_CALLS_PER_MINUTE", 18)
    sync = cz_worker(store, rest, clock, cz, meter)
    sync.run_once()  # 17 of the 18 are spent
    asked = len(cz.times)

    # Backed off by an earlier 429: the next request would have to wait, but none is made.
    until = timestamp(clock_time(14, 0))
    store.set_state(
        hosts=json.dumps({CZ_HOST: {"last_success": None, "error": "429", "until": until}})
    )
    clock.now = clock_time(13, 5)
    assert sync.run_once()

    assert len(cz.times) == asked and meter.pauses == []
    assert hosts_of(store)[CZ_HOST].error == "429"


def test_a_pause_lasts_only_until_enough_calls_have_left_the_minute(
    store: PerpsStore,
    rest: FakeRest,
    clock: Clock,
    meter: Meter,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(sync_module, "CZ_CALLS_PER_MINUTE", 7)
    cz = FakeCoinalyze(clock, meter, latency=10.0)  # a request takes ten seconds
    cz_worker(store, rest, clock, cz, meter).run_once()

    # Costs 3, 3, 3, 3, 2, 2, 1 against 7 a minute. The first two requests (at 0 and 10) take 6.
    # The third, ready at 20, needs only the first to leave the minute: 60 - 20 = 40 s, not the
    # 50 s that would empty it. The fifth is ready at 80 with the third and fourth in the minute
    # (60 and 70) and waits for the third to leave: 60 + 60 - 80 = 40 s.
    assert meter.pauses == [40.0, 40.0]
    assert [at for at, _ in cz.times] == [0.0, 10.0, 60.0, 70.0, 120.0, 130.0, 140.0]
    for at, _ in cz.times:
        assert sum(cost for t, cost in cz.times if at - 60 < t <= at) <= 7, at
    # Every request went out: the waits only delayed them.
    assert len(cz.calls) == 6 and cz.markets_calls == 1


def test_a_stop_while_pacing_abandons_the_round_before_the_next_request(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    sync = cz_worker(store, rest, clock, cz, meter)
    sync.run_once()
    last_run = store.state()["last_run_at"]
    cz.calls.clear()

    # In the second round the second request has to wait, and the worker is stopping.
    meter.stop = True
    clock.now = clock_time(13, 5)
    assert sync.run_once()

    assert meter.pauses == [60.0]
    assert cz.calls == [("liq", "5min", WINDOW - H4, clock_ts(13, 5))]  # nothing after the wait
    assert store.cz_latest("liq", M5) == dict.fromkeys(KIND_VENUES["liq"], clock_ts(13, 0))
    assert store.cz_latest("ohlcv", M5) == dict.fromkeys(KIND_VENUES["ohlcv"], CLOSED_5MIN)
    assert store.cz_latest("oi", M5) == dict.fromkeys(KIND_VENUES["oi"], CLOSED_5MIN)
    # A stopped round is neither a failure nor a finished round.
    state = store.state()
    assert state["last_run_at"] == last_run and state["last_error"] is None
    found = store.derived(derived_key("all", "4h"))
    assert found is not None and found[1] == NOW

    # Not stopping any more, the next call carries the round through.
    meter.stop = False
    cz.calls.clear()
    assert sync.run_once()
    assert [call[0] for call in cz.calls] == ["liq", "ohlcv", "oi"]
    assert store.cz_latest("oi", M5) == dict.fromkeys(KIND_VENUES["oi"], clock_ts(13, 0))
    assert store.state()["last_run_at"] != last_run


def test_the_default_pause_is_the_stop_event_wait(store: PerpsStore, rest: FakeRest, clock: Clock):
    sync = PerpsSync(store, rest, clock=clock, rules=V1)
    sync.stopping.set()
    # Event.wait: True at once when the worker is stopping.
    assert sync.pause(60.0) is True


def test_coinalyze_429_closes_only_its_host(store: PerpsStore, rest: FakeRest, clock: Clock):
    client, seen = real_coinalyze(clock, lambda request: httpx.Response(429))
    sync = cz_worker(store, rest, clock, client, Meter())
    assert sync.run_once()

    # The first request failed, which ended Coinalyze's round.
    assert len(seen) == 1
    hosts = hosts_of(store)
    cz_host = hosts[CZ_HOST]
    assert cz_host.error == "429" and cz_host.last_success is None
    assert cz_host.until is not None and cz_host.until >= NOW + timedelta(seconds=60)
    assert store.cz_latest("liq", H4) == {}
    # The exchanges' rows and the payloads are written as in any other round.
    assert hosts[BINANCE_HOST] == HostState(last_success=NOW, error=None, until=None)
    assert hosts[BYBIT_HOST] == HostState(last_success=NOW, error=None, until=None)
    assert max(store.klines("binance", 0)) == LAST_BAR
    assert max(store.klines("bybit", 0)) == LAST_BAR
    assert max(store.oi("bybit", 0)) == NOW_TS // BAR * BAR
    assert store.state()["last_error"] is None
    assert payload(store, "all", "4h").states is not None

    # A restarted worker keeps the stored backoff though its client forgot it ...
    again, again_seen = real_coinalyze(clock, wire())
    restarted = cz_worker(store, FakeRest(clock), clock, again, Meter())
    clock.now = NOW + timedelta(seconds=30)
    assert restarted.run_once()
    assert again_seen == []
    assert hosts_of(store)[CZ_HOST] == cz_host

    # ... and asks once it is over: the success clears the error.
    clock.now = clock_time(12, 5)
    assert restarted.run_once()
    assert len(again_seen) > 1
    assert hosts_of(store)[CZ_HOST] == HostState(last_success=clock.now, error=None, until=None)
    assert store.cz_latest("liq", H4)


def test_key_missing_records_host_error(store: PerpsStore, rest: FakeRest, clock: Clock):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a request went out without a key")

    for key in (None, ""):
        client, seen = real_coinalyze(clock, refuse, key=key)
        assert cz_worker(store, rest, clock, client, Meter()).run_once()

        assert seen == []
        assert hosts_of(store)[CZ_HOST] == HostState(
            last_success=None, error="key_missing", until=None
        )
        assert store.cz_latest("liq", H4) == {}
        assert stored_markets(store.state()) == []
        assert max(store.klines("bybit", 0)) == int(clock.now.timestamp()) // BAR * BAR - BAR
        assert payload(store, "all", "4h").states is not None
        clock.now = clock_time(12, 5)


def test_401_does_not_hold_the_host_into_the_next_round(
    store: PerpsStore, rest: FakeRest, clock: Clock
):
    status = {"code": 401}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401) if status["code"] == 401 else wire()(request)

    client, seen = real_coinalyze(clock, handler)
    sync = cz_worker(store, rest, clock, client, Meter())
    assert sync.run_once()

    # Given up on for the round, with no backoff to carry over.
    assert len(seen) == 1
    assert hosts_of(store)[CZ_HOST] == HostState(last_success=None, error="401", until=None)

    # A new key works at the next round, not ten minutes after it.
    status["code"] = 200
    clock.now = clock_time(12, 5)
    assert sync.run_once()
    assert len(seen) > 1
    assert hosts_of(store)[CZ_HOST] == HostState(last_success=clock.now, error=None, until=None)
    assert store.cz_latest("liq", H4)


def test_markets_checked_once_a_day(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    sync = cz_worker(store, rest, clock, cz, meter)
    assert stored_markets(store.state()) == []
    sync.run_once()
    assert cz.markets_calls == 1

    for now in (clock_time(13, 5), clock_time(20, 5), NOW + timedelta(days=1, seconds=-1)):
        clock.now = now
        assert sync.run_once()
    assert cz.markets_calls == 1

    # A day on, it is read again, and the new result replaces the old one.
    cz.checks = [
        check.model_copy(update={"ok": False}) if check.venue == "okx" else check
        for check in CZ_CHECKS
    ]
    clock.now = clock_time(12, 5) + timedelta(days=1)
    assert sync.run_once()
    assert cz.markets_calls == 2
    assert stored_markets(store.state()) == cz.checks
    assert datetime.fromisoformat(store.state()["cz_markets_at"] or "") == clock.now

    # A failed read keeps the last result, and is tried again at the next round.
    before = dict(store.state())
    cz.markets_error = RestError(CZ_HOST, "500")
    clock.now = clock_time(12, 5) + timedelta(days=2)
    assert sync.run_once()
    assert cz.markets_calls == 3
    assert stored_markets(store.state()) == cz.checks
    assert store.state()["cz_markets_at"] == before["cz_markets_at"]
    assert hosts_of(store)[CZ_HOST].error == "500"

    cz.markets_error = None
    cz.checks = CZ_CHECKS
    clock.now += timedelta(minutes=10)
    assert sync.run_once()
    assert cz.markets_calls == 4
    assert stored_markets(store.state()) == CZ_CHECKS
    assert hosts_of(store)[CZ_HOST].error is None


def test_markets_are_not_read_after_a_failed_history_request(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    cz.history_error = RestError(CZ_HOST, "500")
    assert cz_worker(store, rest, clock, cz, meter).run_once()

    # The host is closed for the rest of the round: one request, no unit check.
    assert len(cz.calls) == 1 and cz.markets_calls == 0
    assert hosts_of(store)[CZ_HOST].error == "500"
    assert store.cz_latest("liq", H4) == {}
    assert "cz_4h:liq" not in store.state()


def test_round_prunes_cz_5min_after_a_day_and_4hour_after_125(
    store: PerpsStore, rest: FakeRest, clock: Clock, cz: FakeCoinalyze, meter: Meter
):
    old_5min = (NOW_TS - 2 * DAY) // M5 * M5
    kept_5min = (NOW_TS - DAY + 2 * 3600) // M5 * M5
    old_4h = (NOW_TS - 126 * DAY) // H4 * H4
    kept_4h = (NOW_TS - 124 * DAY) // H4 * H4
    store.upsert_cz("oi", M5, "okx", [cz_point(old_5min), cz_point(kept_5min)])
    store.upsert_cz("oi", H4, "okx", [cz_point(old_4h), cz_point(kept_4h)])

    cz_worker(store, rest, clock, cz, meter).run_once()

    assert old_5min not in store.cz_series("oi", M5, "okx", 0)
    assert kept_5min in store.cz_series("oi", M5, "okx", 0)
    assert old_4h not in store.cz_series("oi", H4, "okx", 0)
    assert kept_4h in store.cz_series("oi", H4, "okx", 0)
