"""WebSocket collectors for the perp liquidation and trade streams (spec §3.1 and §3.2).

One `Collector` keeps one connection to one topic (P4-R9) and records that connection's coverage.
It is a state machine advanced by `step(now)`; the connection factory, clock, wait and random
source are injected, so tests drive it without threads or network (P4-R4). Times are epoch
seconds. Logs carry fixed codes only, never values.
"""

import json
import logging
import math
import random
import sqlite3
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect as websocket_connect

from .grid import LONGS
from .rows import RawLiquidation, Stream, Trade
from .store import PerpsStore, Venue

SYMBOL = "BTCUSDT"
URLS: dict[Stream, str] = {
    "binance_liq": "wss://fstream.binance.com/market/ws/btcusdt@forceOrder",
    "bybit_liq": "wss://stream.bybit.com/v5/public/linear",
    "bybit_trades": "wss://stream.bybit.com/v5/public/linear",
}
# Bybit topics are subscribed after connecting; Binance's stream is named by the URL path.
TOPICS: dict[Stream, str] = {
    "bybit_liq": "allLiquidation.BTCUSDT",
    "bybit_trades": "publicTrade.BTCUSDT",
}
VENUES: dict[Stream, Venue] = {
    "binance_liq": "binance",
    "bybit_liq": "bybit",
    "bybit_trades": "bybit",
}
# Bybit closes a connection that sends no heartbeat; it answers {"op":"ping","ret_msg":"pong"}.
BYBIT_PING = '{"op":"ping"}'

RECV_TIMEOUT = 1.0
HEARTBEAT = 20.0  # seconds between pings; also the longest wait for a pong or a subscription ack
MARGIN = 2.0  # an interval ends this long before its last proof of life, for clock error
FLUSH_EVERY = 1.0
END_EVERY = 10.0  # the live interval's end is written at least this often
ROTATE_AFTER = 12 * 3600.0
STABLE = 60.0  # a connection that lived this long restarts the reconnect backoff from 1 s
MAX_BACKOFF = 60.0
BUFFER_CAP = 50_000
OPEN_TIMEOUT = 5.0
CLOSE_TIMEOUT = 2.0

logger = logging.getLogger("wheelhouse.perps.collector")


class Connection(Protocol):
    """The part of websockets' sync `ClientConnection` a collector uses."""

    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def send(self, message: str) -> None: ...

    def ping(self) -> threading.Event: ...

    def close(self) -> None: ...


def parse_binance_force_order(msg: Mapping[str, Any]) -> RawLiquidation | None:
    """The BTCUSDT liquidation in a `forceOrder` event, whatever its status `X` (filtered when
    deriving); None for another symbol or event. Raises KeyError, TypeError or ValueError on a
    malformed event."""
    if msg.get("e") != "forceOrder":
        return None
    order = msg["o"]
    if order["s"] != SYMBOL:
        return None
    return _liquidation(order, ("T", "S", "z", "ap"))


def parse_bybit_liquidation(msg: Mapping[str, Any]) -> list[RawLiquidation]:
    """The liquidations in an `allLiquidation.BTCUSDT` message; [] for any other message."""
    if msg.get("topic") != TOPICS["bybit_liq"]:
        return []
    return [_liquidation(item, ("T", "S", "v", "p")) for item in msg["data"]]


def parse_bybit_trades(msg: Mapping[str, Any]) -> list[Trade]:
    """The taker trades in a `publicTrade.BTCUSDT` message, block and RPI trades included; [] for
    any other message."""
    if msg.get("topic") != TOPICS["bybit_trades"]:
        return []
    return [
        Trade(id=item["i"], ts=item["T"] / 1000, side=item["S"], qty=float(item["v"]))
        for item in msg["data"]
    ]


def _liquidation(raw: Mapping[str, Any], key: tuple[str, ...]) -> RawLiquidation:
    return RawLiquidation(
        event_ts=raw["T"] / 1000,
        key="|".join(str(raw[name]) for name in key),
        raw=json.dumps(raw, separators=(",", ":")),
    )


def _readable(venue: Venue, row: RawLiquidation) -> bool:
    """Whether grid.py can read the event: a side it maps, Binance's status `X`, and a finite
    quantity."""
    raw = json.loads(row.raw)
    side = raw.get("S")
    if not isinstance(side, str) or side not in LONGS[venue]:
        return False
    if venue == "binance" and "X" not in raw:
        return False
    try:
        return math.isfinite(float(raw["z" if venue == "binance" else "v"]))
    except (TypeError, ValueError):
        return False


@dataclass
class _Interval:
    """One connection's coverage: from `start` to `safe`, the last proof of life whose events are
    all committed, less the margin."""

    start: float
    proof: float  # the last proof of life; it stops moving once the connection ends
    safe: float
    row: int | None = None  # the coverage row, once written


class Collector:
    """One connection to one stream's topic, and that connection's coverage (spec §3.2)."""

    def __init__(
        self,
        store: PerpsStore,
        stream: Stream,
        conn: int,
        *,
        rotate_gate: Callable[[], bool],
        connect: Callable[..., Connection] = websocket_connect,
        clock: Callable[[], float] = time.time,
        wait: Callable[[float], object] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.store = store
        self.stream = stream
        self.conn = conn
        # Problem codes, never values: dropped events are counted one by one.
        self.counts: Counter[str] = Counter()
        self._venue = VENUES[stream]
        self._rotate_gate = rotate_gate
        self._connect = connect
        self._clock = clock
        self._stopping = threading.Event()
        self._wait: Callable[[float], object] = wait if wait is not None else self._stopping.wait
        self._rng = rng if rng is not None else random.Random()
        self._lock = threading.Lock()
        self._running = False
        self._done = threading.Event()

        self._ws: Connection | None = None
        self._opened_at = 0.0
        self._next_ping = 0.0
        # The pending ping's pong event, and when the ping was sent.
        self._pong: tuple[threading.Event, float] | None = None
        self._failures = 0
        self._retry_at = -math.inf
        self._last_proof: float | None = None
        self._live: _Interval | None = None
        self._ended: list[_Interval] = []  # waiting for their rows to be closed
        self._liquidations: list[RawLiquidation] = []
        self._trades: list[Trade] = []
        self._next_flush = -math.inf
        self._next_end = math.inf
        self._last_step = -math.inf

    @property
    def last_proof(self) -> float | None:
        """The last proof of life (handshake, frame or pong), at the step that saw it."""
        return self._last_proof

    def step(self, now: float) -> None:
        """Connect when due, read one frame, keep the heartbeat, rotate, then commit when due."""
        previous, self._last_step = self._last_step, now
        ws = self._ws
        if ws is None:
            if now >= self._retry_at:
                self._open(now)
        else:
            self._receive(ws, now)
            if self._ws is ws:
                self._heartbeat(ws, now, previous)
            if self._ws is ws:
                self._check_age(now)
        if now >= self._next_flush:
            self._flush(now)
        if ws is not None and self._ws is ws and self._clock() - now > MARGIN:
            # The step stalled (a slow commit): frames queued meanwhile would be credited late,
            # so the connection ends at the proof held before the stall.
            self._fail(now, "stalled")

    def run(self) -> None:
        """Thread entry: step until `stop`, then end the connection and close its interval."""
        with self._lock:
            if self._stopping.is_set():
                return
            self._running = True
        try:
            while not self._stopping.is_set():
                try:
                    self.step(self._clock())
                except Exception:
                    # A fixed code only: the exception may carry values.
                    self._fail(self._clock(), "step_failed")
                if self._ws is None:
                    self._wait(min(RECV_TIMEOUT, max(0.0, self._retry_at - self._clock())))
        finally:
            self._shutdown()
            self._done.set()

    def stop(self, deadline: float) -> None:
        """Ask `run` to end the connection and close its interval, waiting until `deadline`
        (clock time) at most; when `run` is not running, do it here."""
        with self._lock:
            self._stopping.set()
            running = self._running
        if running:
            self._done.wait(max(0.0, deadline - self._clock()))
        else:
            self._shutdown()

    def _shutdown(self) -> None:
        now = self._clock()
        self._close(now, "stopped", retry_at=math.inf)
        self._flush(now)

    def _open(self, now: float) -> None:
        try:
            ws = self._connect(
                URLS[self.stream],
                ping_interval=None,
                open_timeout=OPEN_TIMEOUT,
                close_timeout=CLOSE_TIMEOUT,
                legacy=True,
            )
        except (OSError, WebSocketException):
            self._fail(self._clock(), "connect_failed")
            return
        opened = self._clock()  # the handshake has completed
        self._ws = ws
        self._opened_at = opened
        self._next_ping = opened + HEARTBEAT
        self._prove(opened)
        self._log("connected")
        topic = TOPICS.get(self.stream)
        if topic is None:
            self._begin(opened)  # a path subscription has no ack: covered from the handshake
            return
        try:
            ws.send(json.dumps({"op": "subscribe", "args": [topic]}))
        except (OSError, WebSocketException):
            self._fail(opened, "closed")

    def _receive(self, ws: Connection, now: float) -> None:
        try:
            frame = ws.recv(timeout=RECV_TIMEOUT)
        except TimeoutError:
            return
        except (OSError, WebSocketException):
            self._fail(now, "closed")
            return
        live = self._live
        held = live.proof if live is not None else None  # the proof before this frame
        self._prove(now)
        try:
            msg = json.loads(frame)
            if not isinstance(msg, dict):
                raise TypeError("frame is not an object")
            lost = self._handle(msg, now)
        except (KeyError, TypeError, ValueError):
            self._warn("bad_frame")
            lost = True
        if lost and live is not None and held is not None and self._live is live:
            # A dropped event must not sit in a covered bucket: the interval ends before this
            # frame and a new one starts after it.
            live.proof = held
            self._ended.append(live)
            self._begin(self._clock())

    def _handle(self, msg: dict[str, Any], now: float) -> bool:
        """Buffer the frame's events; True when some were dropped."""
        if self.stream == "binance_liq":
            row = parse_binance_force_order(msg)
            return self._keep([] if row is None else [row])
        if "op" in msg:
            # Bybit's replies: the subscription ack, and the heartbeat's op "ping" / "pong".
            if msg["op"] == "subscribe":
                if msg.get("success") is not True:
                    self._fail(now, "subscribe_rejected")
                elif self._live is None:
                    self._begin(self._clock())  # covered from the ack
            return False
        if self.stream == "bybit_liq":
            return self._keep(parse_bybit_liquidation(msg))
        self._trades.extend(parse_bybit_trades(msg))
        return False

    def _keep(self, rows: list[RawLiquidation]) -> bool:
        """Buffer the events grid.py can read; count the others and return True if any."""
        readable = [row for row in rows if _readable(self._venue, row)]
        if len(readable) < len(rows):
            self._warn("unreadable_liquidation", len(rows) - len(readable))
        self._liquidations.extend(readable)
        return len(readable) < len(rows)

    def _heartbeat(self, ws: Connection, now: float, previous: float) -> None:
        """Ping every 20 s and poll its pong without blocking; none within 20 s means half-open.

        A pong seen now arrived after the previous step's poll (or the ping), so it proves life
        no later than that."""
        if self._pong is not None:
            pong, sent = self._pong
            if pong.is_set():
                self._pong = None
                self._prove(max(sent, previous))
            elif now - sent >= HEARTBEAT:
                self._fail(now, "half_open")
                return
        if now >= self._next_ping:
            self._next_ping = now + HEARTBEAT
            try:
                self._pong = (ws.ping(), now)
                if self.stream in TOPICS:
                    ws.send(BYBIT_PING)
            except (OSError, WebSocketException):
                self._fail(now, "closed")

    def _check_age(self, now: float) -> None:
        age = now - self._opened_at
        if self._live is None:
            if age >= HEARTBEAT:
                self._fail(now, "no_ack")
        elif age >= ROTATE_AFTER and self._rotate_gate():
            self._failures = 0
            self._close(now, "rotated", retry_at=now)

    def _begin(self, start: float) -> None:
        self._live = _Interval(start=start, proof=start, safe=start)
        self._next_end = start + END_EVERY
        self._log("covering")

    def _prove(self, at: float) -> None:
        self._last_proof = at if self._last_proof is None else max(self._last_proof, at)
        if self._live is not None:
            self._live.proof = max(self._live.proof, at)

    def _fail(self, now: float, code: str) -> None:
        """Drop the connection and retry after min(60, 2**n)·U(0.5, 1) seconds, `n` counting the
        failures since the last connection that lived `STABLE` seconds."""
        if self._ws is not None and now - self._opened_at >= STABLE:
            self._failures = 0
        # 2**6 already exceeds the cap; the bound keeps the power small.
        delay = min(MAX_BACKOFF, 2.0 ** min(self._failures, 6)) * self._rng.uniform(0.5, 1.0)
        self._failures += 1
        self._close(now, code, retry_at=now + delay)

    def _close(self, now: float, code: str, *, retry_at: float) -> None:
        """End the connection; its interval closes once the events it delivered are committed."""
        ws, self._ws, self._pong = self._ws, None, None
        if ws is not None:
            with suppress(OSError, WebSocketException):
                ws.close()
        if self._live is not None:
            self._ended.append(self._live)
            self._live = None
        self._retry_at = retry_at
        self._next_flush = min(self._next_flush, now)
        self._log(code)

    def _flush(self, now: float) -> None:
        """Commit the buffered events, then write the coverage they back. A failed write keeps
        everything for the next try, so coverage never moves past an uncommitted event."""
        self._next_flush = now + FLUSH_EVERY  # a failed write is retried a second later
        try:
            if self._liquidations:
                self.store.insert_liquidations(self._venue, self.conn, self._liquidations)
                self._liquidations = []
            if self._trades:
                self.store.record_trades(self._venue, self._trades)
                self._trades = []
            # Every event received so far is stored: each interval is safe up to its proof.
            for ended in self._ended:
                ended.safe = ended.proof
            if self._live is not None:
                self._live.safe = self._live.proof
            while self._ended:
                ended = self._ended[0]
                if ended.row is not None:  # an interval never written claims nothing
                    self.store.close_coverage(ended.row, ended.safe - MARGIN)
                self._ended.pop(0)
            live = self._live
            if live is not None:
                if live.row is None:
                    live.row = self.store.open_coverage(self.stream, self.conn, live.start)
                if now >= self._next_end:
                    self.store.extend_coverage(live.row, live.safe - MARGIN)
                    self._next_end = now + END_EVERY
        except sqlite3.Error:
            self._warn("commit_failed")
            if len(self._liquidations) + len(self._trades) > BUFFER_CAP:
                self._drop_buffer()

    def _drop_buffer(self) -> None:
        """The store failed too long: drop the buffer and end coverage at the last commit."""
        self._warn("buffer_dropped", len(self._liquidations) + len(self._trades))
        self._liquidations, self._trades = [], []
        for ended in self._ended:
            ended.proof = ended.safe
        live = self._live
        if live is not None:
            live.proof = live.safe
            self._ended.append(live)
            # The events received from here on are kept: the hole spans the dropped ones.
            self._begin(self._clock())

    def _warn(self, code: str, n: int = 1) -> None:
        """Count a problem; log it the first time and each time its count doubles."""
        before = self.counts[code]
        self.counts[code] += n
        if before.bit_length() < self.counts[code].bit_length():
            logger.warning(
                "perps_ws_problem stream=%s conn=%d code=%s count=%d",
                self.stream,
                self.conn,
                code,
                self.counts[code],
            )

    def _log(self, event: str) -> None:
        logger.info("perps_ws stream=%s conn=%d event=%s", self.stream, self.conn, event)
