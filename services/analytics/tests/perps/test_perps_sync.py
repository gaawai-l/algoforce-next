"""The perps REST worker: schedule, head and tail gaps, the OI hist/archive split, per-host
backoff, the six derived payloads, the liquidation direction check and pruning."""

import io
import json
import logging
import math
import random
import shutil
import threading
import time
import zipfile
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from wheelhouse_service import derive
from wheelhouse_service.market import timestamp
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.perps.rows import Exchange, Kline, OiPoint, RawLiquidation, Trade
from wheelhouse_service.perps.sources import (
    ARCHIVE_HOST,
    BINANCE_HOST,
    BYBIT_HOST,
    PerpsRest,
    RestError,
)
from wheelhouse_service.perps.states import Grid, StatesResult, Window, compute_states
from wheelhouse_service.perps.store import PerpsStore, Venue
from wheelhouse_service.perps.sync import (
    RETENTION_DAYS,
    Directions,
    HostState,
    PerpsSync,
    QtyUnits,
    StoredStates,
    derived_key,
    gaps,
    next_slot,
    qty_units,
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
EXCHANGES: tuple[Exchange, ...] = ("all", "binance", "bybit")
WINDOWS: tuple[Window, ...] = ("4h", "8h")
ARCHIVE_SHIFT = 0.5  # archive OI differs from hist OI so that the source of a row shows
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
    """The close of the 5m bar opening at t: 0.5% lower in odd 10m buckets, so every bucket moves
    by more than 0.3% and the odd ones fall."""
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

    def bybit_spot_klines(self, start: int, end: int) -> list[Kline]:
        self._ask(BYBIT_HOST, "bybit_spot_klines", start, end)
        return [
            Kline(t=t, close=close(t), volume=None, taker_buy=None, source="bybit_spot")
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


def test_derives_six_payloads(store: PerpsStore, rest: FakeRest, clock: Clock):
    worker(store, rest, clock).run_once()

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


def test_direction_check_pending_ok_inverted_and_v_units(
    store: PerpsStore, rest: FakeRest, clock: Clock
):
    start = start_of(2)
    for stream in ("binance_liq", "bybit_liq"):
        store.extend_coverage(store.open_coverage(stream, 0, start), NOW_TS)
    falling = [start + (2 * k + 1) * STEP for k in range(25)]  # odd buckets fall 0.5%
    rising = start + 2 * STEP

    def liquidate(buckets: list[int]) -> None:
        for t in buckets:
            store.insert_liquidations(
                "binance",
                0,
                [
                    liquidation("binance", t + 60, "SELL", "1.000"),
                    liquidation("binance", t + 120, "BUY", "0.100"),
                ],
            )
            # Bybit `Sell` maps to shorts: on falling prices that reads as inverted.
            store.insert_liquidations("bybit", 0, [liquidation("bybit", t + 60, "Sell", "1.000")])

    liquidate(falling[:19])
    # A rising bucket is sampled but stays out of the metric.
    store.insert_liquidations("bybit", 0, [liquidation("bybit", rising + 60, "Buy", "0.001")])
    sync = worker(store, rest, clock)
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

    liquidate(falling[19:])
    clock.advance(minutes=10)
    sync.run_once()

    check = Directions.model_validate_json(store.state()["direction_check"] or "")
    assert (check.binance.verdict, check.binance.down) == ("ok", 25)
    assert check.binance.long_share == pytest.approx(1 / 1.1)
    assert (check.bybit.verdict, check.bybit.down) == ("inverted", 25)
    units = check.bybit_qty
    assert (units.events, units.min_qty) == (26, 0.001)
    assert units.min_notional == pytest.approx(59.7)
    assert units.max_notional == pytest.approx(59_700.0)
    assert units.notional_in_range and units.min_qty_matches

    # A size in contracts of $1 would show as an implausible notional.
    store.insert_liquidations("bybit", 0, [liquidation("bybit", rising + 120, "Buy", "1000.000")])
    clock.advance(minutes=10)
    sync.run_once()

    units = Directions.model_validate_json(store.state()["direction_check"] or "").bybit_qty
    assert units.max_notional == pytest.approx(59_700_000.0)
    assert not units.notional_in_range
    assert units.min_qty_matches


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


def test_qty_units_unknown_without_events(store: PerpsStore):
    units = qty_units(store.liquidation_sizes(0))

    # Nothing to check yet: the checks are unknown, not failed.
    assert units.events == 0
    assert (units.min_qty, units.min_notional, units.max_notional) == (None, None, None)
    assert units.notional_in_range is None
    assert units.min_qty_matches is None


def reference_qty_units(events: Sequence[tuple[int, float, str, str]]) -> QtyUnits:
    """The check as it was before the fields were stored: every Bybit event parsed in Python."""
    sizes: dict[str, tuple[float, float]] = {}
    for _, _, raw_json, key in events:
        raw = json.loads(raw_json)
        try:
            qty, price = float(raw["v"]), float(raw["p"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(qty) and math.isfinite(price):
            sizes[key] = (qty, qty * price)
    qtys = [qty for qty, _ in sizes.values()]
    notionals = [notional for _, notional in sizes.values()]
    return QtyUnits(
        events=len(sizes),
        min_qty=min(qtys, default=None),
        min_notional=min(notionals, default=None),
        max_notional=max(notionals, default=None),
        notional_in_range=10 <= min(notionals) and max(notionals) <= 5e7 if sizes else None,
        min_qty_matches=math.isclose(min(qtys), 0.001) if sizes else None,
    )


def test_qty_units_from_sql_equals_the_python_check(store: PerpsStore):
    start = start_of(2)
    rng = random.Random(7)

    def event(ts: int, qty: str, price: str | None) -> RawLiquidation:
        raw: dict[str, object] = {"T": ts * 1000, "s": "BTCUSDT", "S": "Buy", "v": qty}
        if price is not None:
            raw["p"] = price
        return RawLiquidation(
            event_ts=ts, key=f"{ts * 1000}|Buy|{qty}|{price}", raw=json.dumps(raw)
        )

    for n in range(200):
        ts = start + rng.randrange(-DAY, 2 * DAY)
        qty = rng.choice(("0.001", "0.002", "0.150", "3.000", "1000.000"))
        price = rng.choice(("59700.0", "61234.5", "0.5", "n/a", None))
        row = event(ts, qty, price)
        for conn in rng.choice(((0,), (1,), (0, 1), (0, 0))):
            store.insert_liquidations("bybit", conn, [row])
        if n == 100:
            # Every case so far, and again once more events have come in.
            assert qty_units(store.liquidation_sizes(start)) == reference_qty_units(
                store.liquidations("bybit", start)
            )
    units = qty_units(store.liquidation_sizes(start))
    assert units == reference_qty_units(store.liquidations("bybit", start))
    assert units.events > 50 and units.notional_in_range is False


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

    assert seen == [O1O6] * 6
    for exchange in EXCHANGES:
        for window in WINDOWS:
            stored = payload(store, exchange, window)
            assert stored.rules == ["O1", "O6"]
            assert stored.states is not None and stored.states.blocks
            assert all(b.thresholds is not None for b in stored.states.blocks)

    seen.clear()
    clock.advance(minutes=10)
    worker(store, rest, clock, rules=V1).run_once()
    assert seen == [V1] * 6
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
    assert seen == [V1] * 6 + [O1] * 6
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
    """One v1 round at NOW, with both liquidation streams covered from 121 days back and 25
    falling buckets with liquidations 110 days back, before the 90-day reference."""
    directory.mkdir(parents=True, exist_ok=True)
    store = PerpsStore(directory / "perps.sqlite")
    start = start_of(120)
    for stream in ("binance_liq", "bybit_liq"):
        store.extend_coverage(store.open_coverage(stream, 0, start), NOW_TS)
    old = TODAY - 110 * DAY
    for t in (old + (2 * k + 1) * STEP for k in range(25)):  # odd buckets fall 0.5%
        store.insert_liquidations(
            "binance",
            0,
            [
                liquidation("binance", t + 60, "SELL", "1.000"),
                liquidation("binance", t + 120, "BUY", "0.100"),
            ],
        )
        store.insert_liquidations("bybit", 0, [liquidation("bybit", t + 60, "Sell", "1.000")])
    clock = Clock()
    if horizon_days is None:
        sync = PerpsSync(store, FakeRest(clock), clock=clock, rules=V1)
    else:
        sync = worker(store, FakeRest(clock), clock, horizon_days=horizon_days)
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

    # The liquidations 110 days back lie in the grid, though not in the 90-day reference: the
    # direction check and Bybit's size units now read the whole grid, 121 days.
    check = Directions.model_validate_json(store.state()["direction_check"] or "")
    assert (check.binance.verdict, check.binance.down) == ("ok", 25)
    assert (check.bybit.verdict, check.bybit.down) == ("inverted", 25)
    assert check.bybit_qty.events == 25
    # A 90-day backfill reads 91 days: it saw none of them ...
    store_90 = full_round(tmp_path / "horizon-90", horizon_days=90)
    check_90 = Directions.model_validate_json(store_90.state()["direction_check"] or "")
    assert (check_90.binance.samples, check_90.bybit.samples, check_90.bybit_qty.events) == (
        0,
        0,
        0,
    )
    # ... and its v1 states, thresholds and tables are the same as those of the 121 days.
    for exchange in EXCHANGES:
        for window in WINDOWS:
            states = payload(store, exchange, window).states
            assert states is not None
            assert states == payload(store_90, exchange, window).states
    judged = payload(store, "binance", "4h").states
    assert judged is not None and not judged.collecting


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
