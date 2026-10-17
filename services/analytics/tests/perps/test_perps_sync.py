"""The perps REST worker: schedule, head and tail gaps, the OI hist/archive split, per-host
backoff, the six derived payloads, the liquidation direction check and pruning."""

import json
import math
import random
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from wheelhouse_service.market import timestamp
from wheelhouse_service.perps.rows import Exchange, Kline, OiPoint, RawLiquidation, Trade
from wheelhouse_service.perps.sources import (
    ARCHIVE_HOST,
    BINANCE_HOST,
    BYBIT_HOST,
    PerpsRest,
    RestError,
)
from wheelhouse_service.perps.states import Window
from wheelhouse_service.perps.store import PerpsStore, Venue
from wheelhouse_service.perps.sync import (
    Directions,
    HostState,
    PerpsSync,
    QtyUnits,
    StoredStates,
    derived_key,
    next_slot,
    qty_units,
)

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


def worker(store: PerpsStore, rest: PerpsRest, clock: Clock, horizon_days: int = 2) -> PerpsSync:
    return PerpsSync(store, rest, clock=clock, horizon_days=horizon_days)


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
    assert json.loads(store.state()["reasons"] or "") == ["rest_error:fapi.binance.com:418"]

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
    assert json.loads(store.state()["reasons"] or "") == []


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


def test_prune_keeps_120d_and_1h_trade_ids(store: PerpsStore, rest: FakeRest, clock: Clock):
    old = (NOW_TS - 121 * DAY) // BAR * BAR
    kept = (NOW_TS - 119 * DAY) // BAR * BAR
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
    old = (NOW_TS - 121 * DAY) // BAR * BAR
    store.upsert_klines(
        "binance", [Kline(t=old, close=1.0, volume=1.0, taker_buy=0.5, source="binance_perp")]
    )

    def broken(*_: object) -> None:
        raise RuntimeError("derive failed")

    monkeypatch.setattr("wheelhouse_service.perps.sync.build_grid", broken)
    assert worker(store, rest, clock).run_once()

    assert store.state()["last_error"] == "sync_failed"
    assert old not in store.klines("binance", 0)
