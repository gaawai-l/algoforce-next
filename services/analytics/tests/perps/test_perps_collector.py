"""The WebSocket collector: message parsing, and the step-driven connection and coverage machine.

No threads and no network: a fake connection plays scripted frames, the test sets the clock and
calls `step(now)` (P4-R4).
"""

import json
import logging
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosedError

from wheelhouse_service.perps import collector as collector_module
from wheelhouse_service.perps.collector import (
    BUFFER_CAP,
    ROTATE_AFTER,
    Collector,
    parse_binance_force_order,
    parse_bybit_liquidation,
    parse_bybit_trades,
)
from wheelhouse_service.perps.rows import Stream, Trade
from wheelhouse_service.perps.store import PerpsStore

FIXTURES = Path(__file__).parent / "fixtures" / "ws"
BINANCE_URL = "wss://fstream.binance.com/market/ws/btcusdt@forceOrder"
BYBIT_URL = "wss://stream.bybit.com/v5/public/linear"


def text(name: str) -> str:
    return (FIXTURES / name).read_text().strip()


def lines(name: str) -> list[str]:
    return text(name).splitlines()


BTC_FORCE_ORDER = text("binance_force_order_btc.json")
BYBIT_LIQUIDATION = text("bybit_all_liquidation.json")
ACK, PONG = lines("bybit_control.jsonl")
TRADES = lines("bybit_public_trade.jsonl")


def edited(frame: str, **fields: Any) -> str:
    """A Binance event with fields of its `o` object replaced (a None value removes the field)."""
    msg = json.loads(frame)
    msg["o"] = {k: v for k, v in {**msg["o"], **fields}.items() if v is not None}
    return json.dumps(msg)


class FakeWs:
    """Plays its frames one per `recv`; an exception is raised and a callable is called (then the
    read times out). An empty script times out."""

    def __init__(self, *frames: str | BaseException | Callable[[], object]) -> None:
        self.frames = list(frames)
        self.answer_pings = True
        self.sent: list[str] = []
        self.pings: list[threading.Event] = []
        self.closed = False
        self.recv_calls = 0

    def recv(self, timeout: float | None = None) -> str:
        assert timeout is not None and 0 < timeout <= 1
        self.recv_calls += 1
        if not self.frames:
            raise TimeoutError
        frame = self.frames.pop(0)
        if isinstance(frame, BaseException):
            raise frame
        if callable(frame):
            frame()
            raise TimeoutError
        return frame

    def send(self, message: str) -> None:
        self.sent.append(message)

    def ping(self) -> threading.Event:
        pong = threading.Event()
        if self.answer_pings:
            pong.set()
        self.pings.append(pong)
        return pong

    def close(self) -> None:
        self.closed = True


class Uniform:
    """Stands in for random.Random: returns the point `fraction` of the way through the range."""

    def __init__(self, fraction: float) -> None:
        self.fraction = fraction
        self.ranges: list[tuple[float, float]] = []

    def uniform(self, a: float, b: float) -> float:
        self.ranges.append((a, b))
        return a + (b - a) * self.fraction


class Rig:
    """A collector with a settable clock and a connect that hands out scripted results."""

    def __init__(
        self,
        store: PerpsStore,
        stream: Stream,
        *results: FakeWs | Exception,
        conn: int = 0,
        fraction: float = 1.0,
        handshake: float = 0.0,
        gate: Callable[[], bool] = lambda: True,
    ) -> None:
        self.t = 0.0
        self.results = list(results)
        self.handshake = handshake
        self.calls: list[tuple[float, str, dict[str, Any]]] = []
        self.rng = Uniform(fraction)
        self.collector = Collector(
            store,
            stream,
            conn,
            rotate_gate=gate,
            connect=self.connect,
            clock=lambda: self.t,
            wait=self.wait,
            rng=self.rng,
        )

    def connect(self, url: str, **kwargs: Any) -> FakeWs:
        self.calls.append((self.t, url, kwargs))
        self.t += self.handshake
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def wait(self, seconds: float) -> None:
        raise AssertionError("run() must not wait while connected")

    def at(self, *times: float) -> None:
        for t in times:
            self.t = t
            self.collector.step(t)

    def quiet(self, until: float) -> None:
        """Step once a second up to `until`, then at `until`. `run` steps at least once a second
        while connected (a quiet read waits its second), so a longer gap is a suspension."""
        while self.t + 1 < until:
            self.at(self.t + 1)
        self.at(until)

    def connected_at(self) -> list[float]:
        return [t for t, _, _ in self.calls]


class FlakyStore(PerpsStore):
    """Every write fails with "database is locked" while `failing` is set."""

    def __init__(self, path: Path) -> None:
        self.failing = False
        self.failed_writes = 0
        super().__init__(path)

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if write and self.failing:
            self.failed_writes += 1
            raise sqlite3.OperationalError("database is locked")
        with super().connection(write=write) as db:
            yield db


class RecordingStore(PerpsStore):
    """Records each write as (name, value, liquidations stored at the time)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.writes: list[tuple[str, Any, int]] = []

    def _record(self, name: str, value: Any) -> None:
        with self.connection() as db:
            stored = int(db.execute("SELECT COUNT(*) FROM liquidations").fetchone()[0])
        self.writes.append((name, value, stored))

    def insert_liquidations(self, venue: Any, conn: int, rows: Any) -> None:
        self._record("insert_liquidations", len(rows))
        super().insert_liquidations(venue, conn, rows)

    def record_trades(self, venue: Any, trades: Any) -> None:
        self._record("record_trades", len(trades))
        super().record_trades(venue, trades)

    def open_coverage(self, stream: Any, conn: int, start: float) -> int:
        self._record("open_coverage", start)
        return super().open_coverage(stream, conn, start)

    def extend_coverage(self, row_id: int, end: float) -> None:
        self._record("extend_coverage", end)
        super().extend_coverage(row_id, end)


class SlowStore(PerpsStore):
    """While `rig` is set, each write waits `delay` seconds for the lock on the rig's clock."""

    rig: "Rig | None" = None
    delay = 10.0

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        if write and self.rig is not None:
            self.rig.t += self.delay
        with super().connection(write=write) as db:
            yield db


def coverage_rows(store: PerpsStore) -> list[tuple[str, int, float, float, int]]:
    with store.connection() as db:
        return [
            tuple(row)
            for row in db.execute("SELECT stream, conn, start, end, open FROM coverage ORDER BY id")
        ]


# --- parsing (real samples; the BTC liquidations follow the real or documented shape) ---


def test_parse_binance_force_order_keeps_btc_whatever_its_status():
    msg = json.loads(BTC_FORCE_ORDER)
    row = parse_binance_force_order(msg)
    assert row is not None
    assert row.event_ts == 1792186100.113
    assert row.key == "1792186100113|SELL|0.250|81598.40"
    assert json.loads(row.raw) == msg["o"]
    # X is filtered when deriving, not here.
    assert parse_binance_force_order(json.loads(edited(BTC_FORCE_ORDER, X="NEW"))) is not None
    # Live events of other symbols are skipped.
    for line in lines("binance_force_order.jsonl"):
        assert parse_binance_force_order(json.loads(line)) is None


def test_parse_bybit_liquidation_doc_shape():
    msg = json.loads(BYBIT_LIQUIDATION)
    rows = parse_bybit_liquidation(msg)
    assert [(row.event_ts, row.key) for row in rows] == [
        (1792186200.052, "1792186200052|Buy|0.513|81602.30"),
        (1792186200.118, "1792186200118|Sell|0.020|81610.00"),
    ]
    assert [json.loads(row.raw) for row in rows] == msg["data"]
    assert parse_bybit_liquidation({**msg, "topic": "allLiquidation.ETHUSDT"}) == []
    assert parse_bybit_liquidation(json.loads(ACK)) == []
    assert parse_bybit_liquidation(json.loads(TRADES[0])) == []


def test_parse_bybit_trades_live_sample():
    trades = [trade for line in TRADES for trade in parse_bybit_trades(json.loads(line))]
    assert len(trades) == 16
    assert trades[0] == Trade(
        id="079f035e-92d6-5ccd-a929-31aeb42d362e", ts=1792185755.674, side="Sell", qty=0.001
    )
    assert sum(t.qty for t in trades if t.side == "Buy") == pytest.approx(0.637)
    assert sum(t.qty for t in trades if t.side == "Sell") == pytest.approx(0.075)
    assert parse_bybit_trades(json.loads(PONG)) == []
    assert parse_bybit_trades(json.loads(BYBIT_LIQUIDATION)) == []


# --- the collector ---


def test_coverage_start_bybit_ack_binance_handshake(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    binance_ws = FakeWs()
    binance = Rig(store, "binance_liq", binance_ws, handshake=0.4)
    binance.at(100)
    assert binance.calls == [
        (
            100,
            BINANCE_URL,
            {"ping_interval": None, "open_timeout": 5.0, "close_timeout": 2.0, "legacy": True},
        )
    ]
    assert binance_ws.sent == []  # the stream is named by the path
    assert coverage_rows(store) == [("binance_liq", 0, 100.4, 100.4, 1)]

    bybit_ws = FakeWs(TimeoutError(), ACK)
    bybit = Rig(store, "bybit_liq", bybit_ws, conn=1, handshake=0.4)
    bybit.at(100, 101)
    assert bybit.calls[0][1] == BYBIT_URL
    assert bybit.calls[0][2]["ping_interval"] is None
    assert [json.loads(m) for m in bybit_ws.sent] == [
        {"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]}
    ]
    assert len(coverage_rows(store)) == 1  # no ack yet, nothing covered
    bybit.at(103)
    assert coverage_rows(store)[1] == ("bybit_liq", 1, 103, 103, 1)


def test_bybit_without_ack_reconnects(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    first = FakeWs()
    rig = Rig(store, "bybit_trades", first, FakeWs(ACK))
    rig.at(0)
    rig.quiet(19.75)
    assert not first.closed
    rig.at(20)
    assert first.closed
    rig.at(20.75, 21, 22)  # backoff 1 s
    assert rig.connected_at() == [0, 21]
    assert coverage_rows(store) == [("bybit_trades", 0, 22, 22, 1)]


def test_bybit_sends_app_ping_and_counts_its_reply_as_proof(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    ws = FakeWs(ACK)
    rig = Rig(store, "bybit_liq", ws)
    rig.at(0, 0.5)
    rig.quiet(20)
    assert ws.sent[1:] == ['{"op":"ping"}']
    assert len(ws.pings) == 1
    ws.frames.append(PONG)
    ws.answer_pings = False
    rig.at(20.5)  # the protocol pong (answered at once) and the app reply both land here
    assert rig.collector.last_proof == 20.5
    rig.quiet(40)
    assert ws.sent[1:] == ['{"op":"ping"}', '{"op":"ping"}']
    assert rig.collector.counts == Counter()
    assert store.liquidations("bybit", 0) == []


def test_half_open_ends_coverage_at_last_proof_minus_2s_and_reconnects(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    ws = FakeWs()
    rig = Rig(store, "binance_liq", ws, FakeWs())
    rig.at(0)
    rig.quiet(21)  # ping at 20, its pong seen at 21 but credited no later than 20
    assert rig.collector.last_proof == 20
    rig.quiet(29)
    ws.frames.append(BTC_FORCE_ORDER)
    rig.at(30)
    ws.answer_pings = False
    rig.quiet(59)  # ping at 40 unanswered, still within 20 s
    assert not ws.closed
    rig.at(60)
    assert ws.closed
    assert rig.collector.last_proof == 30
    assert coverage_rows(store) == [("binance_liq", 0, 0, 28, 0)]
    assert len(store.liquidations("binance", 0)) == 1
    # The connection lived 60 s, so the backoff starts again at 1 s.
    rig.at(60.5, 61)
    assert rig.connected_at() == [0, 61]
    assert coverage_rows(store)[1] == ("binance_liq", 0, 61, 61, 1)


def test_events_committed_before_coverage_end_advances(tmp_path: Path):
    store = RecordingStore(tmp_path / "perps.sqlite3")
    ws = FakeWs(ACK)
    rig = Rig(store, "bybit_liq", ws)
    rig.at(0, 0.5, 1)
    rig.quiet(9.5)  # the flush is due again at 10.5
    ws.frames.append(BYBIT_LIQUIDATION)
    rig.at(10.5)  # the end is due in the same step the events arrive
    assert store.writes == [
        ("open_coverage", 0.5, 0),
        ("insert_liquidations", 2, 0),
        ("extend_coverage", 8.5, 2),  # the events were stored before the end moved
    ]


def test_rotation_after_12h(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert ROTATE_AFTER == 12 * 3600
    # Stepped once a second as `run` does, so the age is shortened to keep the test quick.
    monkeypatch.setattr(collector_module, "ROTATE_AFTER", 120.0)
    store = PerpsStore(tmp_path / "perps.sqlite3")
    gate_open = False
    asked: list[float] = []

    def gate() -> bool:
        asked.append(rig.t)
        return gate_open

    first = FakeWs()
    rig = Rig(store, "binance_liq", first, FakeWs(), gate=gate)
    rig.at(0)
    rig.quiet(119)
    assert asked == []
    rig.quiet(123)  # old enough, but the gate holds the rotation
    assert asked == [120, 121, 122, 123]
    assert not first.closed
    gate_open = True
    rig.at(124)
    assert first.closed
    rig.at(125)  # no backoff after a rotation
    assert rig.connected_at() == [0, 125]
    # The last proof was the pong to the ping at 120, seen at 121 and credited at 120.
    assert coverage_rows(store) == [
        ("binance_liq", 0, 0, 118, 0),
        ("binance_liq", 0, 125, 125, 1),
    ]


@pytest.mark.parametrize(
    ("fraction", "attempts"),
    [
        (1.0, [0, 1, 3, 7, 15, 31, 63, 123, 183]),  # 1, 2, 4, ... 32, then capped at 60
        (0.0, [0, 0.5, 1.5, 3.5, 7.5, 15.5, 31.5, 61.5, 91.5]),
    ],
)
def test_backoff_with_jitter_bounds(tmp_path: Path, fraction: float, attempts: list[float]):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    rig = Rig(store, "bybit_trades", *[OSError("refused")] * len(attempts), fraction=fraction)
    for quarter in range(int(attempts[-1] * 4) + 1):
        rig.at(quarter / 4)
    assert rig.connected_at() == attempts
    assert set(rig.rng.ranges) == {(0.5, 1.0)}
    assert coverage_rows(store) == []


def test_backoff_restarts_after_a_stable_connection(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    stable, short = FakeWs(), FakeWs(ConnectionClosedError(None, None))
    rig = Rig(store, "binance_liq", OSError(), OSError(), stable, short, OSError(), OSError())
    for quarter in range(78 * 4 + 1):
        if quarter == 70 * 4:
            stable.frames.append(ConnectionClosedError(None, None))
        rig.at(quarter / 4)
    # Fails at 0 (1 s) and 1 (2 s); `stable` lives 3–70, so 1 s again; `short` dies at its first
    # read, 71.25 (2 s); then 4 s.
    assert rig.connected_at() == [0, 1, 3, 71, 73.25, 77.25]


def test_trades_recorded_in_batches(tmp_path: Path):
    store = RecordingStore(tmp_path / "perps.sqlite3")
    ws = FakeWs(ACK, *TRADES[:3], PONG, *TRADES[3:])
    rig = Rig(store, "bybit_trades", ws)
    rig.at(0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2)
    assert json.loads(ws.sent[0]) == {"op": "subscribe", "args": ["publicTrade.BTCUSDT"]}
    assert [(name, n) for name, n, _ in store.writes if name == "record_trades"] == [
        ("record_trades", 8),
        ("record_trades", 8),
    ]
    [(buy, sell)] = store.trades("bybit", 0).values()
    assert (buy, sell) == (pytest.approx(0.637), pytest.approx(0.075))


def test_commit_failure_keeps_buffer_and_does_not_advance_coverage(tmp_path: Path):
    store = FlakyStore(tmp_path / "perps.sqlite3")
    ws = FakeWs(ACK)
    rig = Rig(store, "bybit_trades", ws)
    rig.at(0, 0.5, 1)
    assert coverage_rows(store) == [("bybit_trades", 0, 0.5, 0.5, 1)]

    store.failing = True
    ws.frames.append(TRADES[0])
    rig.at(2)
    assert store.failed_writes == 1
    rig.at(2.25)  # retried once a second, not at every step
    assert store.failed_writes == 1
    rig.at(3)
    assert store.failed_writes == 2
    rig.quiet(10.5)
    rig.at(11)  # the end is due, but the events are not stored
    assert coverage_rows(store) == [("bybit_trades", 0, 0.5, 0.5, 1)]
    assert store.trades("bybit", 0) == {}

    store.failing = False
    ws.frames.append(TRADES[1])
    rig.at(12)
    [(buy, sell)] = store.trades("bybit", 0).values()
    assert (buy, sell) == (pytest.approx(0.614), pytest.approx(0.001))
    assert coverage_rows(store) == [("bybit_trades", 0, 0.5, 10, 1)]
    # Retried at 2 and 3, each second from 4 to 10, then at 11.
    assert rig.collector.counts == Counter({"commit_failed": 10})


def test_buffer_cap_drops_and_ends_coverage(tmp_path: Path):
    store = FlakyStore(tmp_path / "perps.sqlite3")
    ws = FakeWs(ACK)
    rig = Rig(store, "bybit_trades", ws)
    rig.at(0, 0.5, 1)  # covered from 0.5
    rig.quiet(9.5)  # the flush is due again at 10.5
    ws.frames.append(TRADES[0])
    rig.at(10.5)  # the end written here is 8.5
    ws.frames.append(TRADES[1])
    rig.at(12)  # committed, so the interval is safe up to 12 - 2; the end is next due at 20.5
    assert coverage_rows(store) == [("bybit_trades", 0, 0.5, 8.5, 1)]

    store.failing = True
    flood = {
        "topic": "publicTrade.BTCUSDT",
        "type": "snapshot",
        "ts": 1792185800000,
        "data": [
            {"T": 1792185800000, "s": "BTCUSDT", "S": "Buy", "v": "0.001", "p": "1", "i": str(n)}
            for n in range(BUFFER_CAP + 1)
        ],
    }
    ws.frames.append(json.dumps(flood))
    rig.at(13)  # the commit fails with more than 50,000 events buffered: they are dropped
    assert rig.collector.counts["buffer_dropped"] == BUFFER_CAP + 1
    rig.at(14)
    store.failing = False
    rig.at(15)
    # The first interval ends at the last commit; a new one starts where the drop happened.
    assert coverage_rows(store) == [
        ("bybit_trades", 0, 0.5, 10, 0),
        ("bybit_trades", 0, 13, 13, 1),
    ]
    [(buy, sell)] = store.trades("bybit", 0).values()
    assert (buy, sell) == (pytest.approx(0.614), pytest.approx(0.001))


def test_unreadable_liquidations_are_dropped_and_counted(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    binance = Rig(
        store,
        "binance_liq",
        FakeWs(
            edited(BTC_FORCE_ORDER, S="SHORT"),
            edited(BTC_FORCE_ORDER, X=None),
            edited(BTC_FORCE_ORDER, z="n/a", T=1792186100114),
            lines("binance_force_order.jsonl")[0],  # another symbol: skipped, not counted
            edited(BTC_FORCE_ORDER, X="PARTIALLY_FILLED", T=1792186100115),
            BTC_FORCE_ORDER,
            "not json",
        ),
    )
    binance.at(0, 1, 2, 3, 4, 5, 6, 7)
    stored = store.liquidations("binance", 0)
    assert sorted(json.loads(raw)["X"] for _, _, raw, _ in stored) == ["FILLED", "PARTIALLY_FILLED"]
    # Each lost frame also splits the coverage (it starts at the handshake).
    assert binance.collector.counts == Counter(
        {"unreadable_liquidation": 3, "bad_frame": 1, "coverage_split": 4}
    )

    msg = json.loads(BYBIT_LIQUIDATION)
    msg["data"][0]["S"] = "Long"
    bybit = Rig(store, "bybit_liq", FakeWs(ACK, json.dumps(msg)))
    bybit.at(0, 1, 2)
    assert [key for _, _, _, key in store.liquidations("bybit", 0)] == [
        "1792186200118|Sell|0.020|81610.00"
    ]
    assert bybit.collector.counts == Counter({"unreadable_liquidation": 1, "coverage_split": 1})


def test_run_steps_until_stop_and_closes_coverage(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")

    def tick() -> None:
        rig.t += 1  # each read waits its 1 s

    def stop() -> None:
        rig.collector.stop(rig.t)

    ws = FakeWs(tick, tick, tick, tick, BTC_FORCE_ORDER, tick, stop)
    rig = Rig(store, "binance_liq", ws)
    rig.t = 100
    rig.collector.run()
    assert ws.closed
    assert coverage_rows(store) == [("binance_liq", 0, 100, 102, 0)]
    assert len(store.liquidations("binance", 0)) == 1

    # Without a running loop, stop closes the interval itself.
    other = Rig(store, "binance_liq", FakeWs(), conn=1)
    other.at(200, 201)
    other.collector.stop(201)
    assert coverage_rows(store)[1] == ("binance_liq", 1, 200, 200, 0)


def test_subscribe_rejected_reconnects(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    rejected = json.dumps({**json.loads(ACK), "success": False, "ret_msg": "error"})
    first = FakeWs(rejected)
    rig = Rig(store, "bybit_liq", first, FakeWs(ACK))
    rig.at(0, 1)
    assert first.closed
    rig.at(1.5, 2, 3)  # backoff 1 s
    assert rig.connected_at() == [0, 2]
    assert coverage_rows(store) == [("bybit_liq", 0, 3, 3, 1)]


def test_stall_drops_the_connection_and_claims_nothing_after_it(tmp_path: Path):
    store = SlowStore(tmp_path / "perps.sqlite3")
    first = FakeWs(ACK)
    rig = Rig(store, "bybit_trades", first, FakeWs())
    rig.at(0, 0.5, 1)
    rig.quiet(4)
    first.frames.extend([*TRADES[:5], ConnectionClosedError(None, None)])
    store.rig = rig
    rig.at(5)  # the commit waits 10 s on the lock: the clock reads 15 after it
    store.rig = None
    assert first.closed
    assert len(first.frames) == 5  # the frames queued during the stall are never read
    rig.at(16)
    assert coverage_rows(store) == [("bybit_trades", 0, 0.5, 3, 0)]
    [(buy, sell)] = store.trades("bybit", 0).values()
    assert (buy, sell) == (0, pytest.approx(0.001))


def test_stall_in_the_connect_step_claims_nothing(tmp_path: Path):
    store = SlowStore(tmp_path / "perps.sqlite3")
    other_symbol = lines("binance_force_order.jsonl")[0]
    first = FakeWs(other_symbol, ConnectionClosedError(None, None))
    rig = Rig(store, "binance_liq", first, FakeWs())
    store.rig = rig
    rig.at(0)  # opening the coverage row waits 10 s on the lock: the clock reads 10 after it
    store.rig = None
    assert first.closed
    assert len(first.frames) == 2  # the frame queued during the stall proves nothing
    rig.at(10.5)
    assert coverage_rows(store) == [
        ("binance_liq", 0, 0, 0, 0),
        ("binance_liq", 0, 10.5, 10.5, 1),
    ]


@pytest.mark.parametrize(("delay", "dropped"), [(1.2, False), (2.5, True)])
def test_stall_guard_times_the_commit_alone(tmp_path: Path, delay: float, dropped: bool):
    store = SlowStore(tmp_path / "perps.sqlite3")
    store.delay = delay

    def wait_out_read() -> None:
        rig.t += 1  # a read on a quiet stream waits its full second

    ws = FakeWs(*[wait_out_read] * 30)
    rig = Rig(store, "binance_liq", ws)
    rig.at(0)
    store.rig = rig  # from here each write takes `delay`; the end is written at 10 and 20
    while rig.t < 25 and not ws.closed:
        rig.at(rig.t)  # each step starts where the last one ended, as `run` does
    assert ws.closed is dropped


def test_suspension_between_steps_ends_coverage_before_it(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    first = FakeWs()
    rig = Rig(store, "binance_liq", first, FakeWs())
    rig.at(0)
    rig.quiet(4)
    first.frames.append(BTC_FORCE_ORDER)
    rig.at(5, 6)  # the last proof of life is at 5
    # The process sleeps from 6 to 100: a frame queued meanwhile must not prove life at 100.
    first.frames.append(BTC_FORCE_ORDER)
    rig.at(100)
    assert first.closed
    assert len(first.frames) == 1
    assert coverage_rows(store) == [
        ("binance_liq", 0, 0, 3, 0),
        ("binance_liq", 0, 100, 100, 1),
    ]
    assert len(store.liquidations("binance", 0)) == 1

    # A slow handshake is no suspension: the gap counts from the open.
    slow_ws = FakeWs()
    slow = Rig(store, "binance_liq", slow_ws, conn=1, handshake=2.5)
    slow.at(0, 3.5, 4.5)
    assert not slow_ws.closed


def test_dropped_event_splits_coverage_around_it(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    base = 1792186090.0  # the fixture event's T is base + 10.113
    ws = FakeWs()
    rig = Rig(store, "binance_liq", ws)
    rig.at(base)
    rig.quiet(base + 7)
    ws.frames.append(edited(BTC_FORCE_ORDER, T=1792186097000))
    rig.at(base + 8)
    ws.frames.append(edited(BTC_FORCE_ORDER, S="SHORT"))
    rig.at(base + 10.5)
    rows = coverage_rows(store)
    assert rows == [
        ("binance_liq", 0, base, base + 6, 0),
        ("binance_liq", 0, base + 10.5, base + 10.5, 1),
    ]
    assert rows[0][3] < 1792186100.113 < rows[1][2]

    # A frame that cannot be parsed splits the same way.
    rig.at(base + 12)
    ws.frames.append(edited(BTC_FORCE_ORDER, T=1792186103000))
    rig.at(base + 14)
    ws.frames.append("not json")
    rig.at(base + 16)
    assert coverage_rows(store)[1:] == [
        ("binance_liq", 0, base + 10.5, base + 12, 0),
        ("binance_liq", 0, base + 16, base + 16, 1),
    ]
    assert rig.collector.counts == Counter(
        {"unreadable_liquidation": 1, "bad_frame": 1, "coverage_split": 2}
    )
    assert len(store.liquidations("binance", 0)) == 2


def test_coverage_splits_logged_when_their_count_doubles(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    rig = Rig(store, "binance_liq", FakeWs(*["not json"] * 8))
    with caplog.at_level(logging.INFO, logger="wheelhouse.perps.collector"):
        rig.at(*range(9))
    messages = [record.getMessage() for record in caplog.records]
    assert sum("event=covering" in m for m in messages) == 1  # the connection's first interval
    assert [m.split()[-1] for m in messages if "code=coverage_split" in m] == [
        "count=1",
        "count=2",
        "count=4",
        "count=8",
    ]
    assert rig.collector.counts == Counter({"bad_frame": 8, "coverage_split": 8})


def test_default_wait_is_interrupted_by_stop(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    attempted = threading.Event()

    def refuse(url: str, **kwargs: Any) -> FakeWs:
        attempted.set()
        raise OSError("refused")

    collector = Collector(
        store, "binance_liq", 0, rotate_gate=lambda: True, connect=refuse, rng=Uniform(1.0)
    )
    thread = threading.Thread(target=collector.run, daemon=True)
    thread.start()
    assert attempted.wait(5)
    time.sleep(0.05)  # now in its 1 s backoff wait
    started = time.monotonic()
    collector.stop(time.time() + 5)
    assert time.monotonic() - started < 0.5
    thread.join(1)
    assert not thread.is_alive()
