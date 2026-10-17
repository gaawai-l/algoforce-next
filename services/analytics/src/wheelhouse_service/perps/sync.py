"""REST worker for the perp states: backfills and refreshes the public series, derives the six
state payloads, checks the liquidation direction and prunes (spec §2, §3.1, §3.7, §3.8, §6)."""

import json
import logging
import math
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
from threading import Event, Thread
from typing import Literal, NamedTuple

from pydantic import AwareDatetime

from ..market import Model, timestamp
from .grid import BAR, build_grid, read_liquidations
from .rows import Exchange, Kline, OiPoint
from .sources import ARCHIVE_HOST, BINANCE_HOST, BYBIT_HOST, PerpsRest, RestError
from .states import DAY, STEP, Grid, StatesResult, Window, compute_states
from .store import LiquidationSizes, PerpsStore, Venue

logger = logging.getLogger("wheelhouse.perps.sync")

HOSTS = (BINANCE_HOST, ARCHIVE_HOST, BYBIT_HOST)
EXCHANGES: tuple[Exchange, ...] = ("all", "binance", "bybit")
WINDOWS: tuple[Window, ...] = ("4h", "8h")
# Binance keeps about 30 days of openInterestHist; older OI comes from the daily archive files.
HIST_DAYS = 29
# Each round fetches the last few stored records of every series again, as onchain's OVERLAP.
OVERLAP = 3
RETENTION_DAYS = 120
TRADE_IDS_SECONDS = 3600
# Rounds run at HH:05, HH:15, ...: Binance publishes its history rows 2-4 minutes late.
SLOT_OFFSET = 300
IDLE_SECONDS = 30
STOP_TIMEOUT_SECONDS = 25

# The liquidation direction check (spec §6): buckets whose price moved at least this much in
# 10 minutes and that have liquidations; the verdict needs this many falling ones.
DIRECTION_MOVE = 0.003
DIRECTION_MIN_DOWN = 20
DIRECTION_OK_ABOVE = 0.6
DIRECTION_INVERTED_BELOW = 0.4
# Bybit `v` in BTC: a single liquidation's notional lies in this range, and the smallest size is
# the minimum order quantity.
NOTIONAL_RANGE = (10.0, 50_000_000.0)
MIN_QTY = 0.001


def next_slot(at: datetime) -> datetime:
    """The first HH:x5:00 UTC strictly after `at`."""
    t = math.floor(at.timestamp())
    return datetime.fromtimestamp((t - SLOT_OFFSET) // STEP * STEP + SLOT_OFFSET + STEP, UTC)


def derived_key(exchange: Exchange, window: Window) -> str:
    return f"states:{exchange}:{window}"


class StoredStates(Model):
    """One exchange view and window as the worker derives it.

    `states` is None when the view lacks a required REST series from `start` on; `reasons` then
    name those series, and otherwise the ones with no value in the reference window.
    """

    exchange: Exchange
    window: Window
    start: AwareDatetime  # the grid's first bucket
    reasons: list[str]  # series_missing:<venue>:<series>
    states: StatesResult | None


class HostState(Model):
    last_success: AwareDatetime | None
    error: str | None  # RestError.code of the host's last failure, until it succeeds again
    until: AwareDatetime | None  # backed off until then


Verdict = Literal["ok", "inverted", "pending"]


class DirectionCheck(Model):
    """One venue's liquidation sides against the price (spec §6), as currently mapped."""

    verdict: Verdict
    samples: int  # buckets that moved at least DIRECTION_MOVE and have liquidations
    down: int  # of those, the falling ones
    long_share: float | None  # Σlong / (Σlong + Σshort) over the falling ones


class QtyUnits(Model):
    """Bybit's liquidation size `v` checked as BTC: notionals v·p and the smallest size."""

    events: int
    min_qty: float | None
    min_notional: float | None
    max_notional: float | None
    # None while there are no events: nothing has been checked, which is not a failed check.
    notional_in_range: bool | None
    min_qty_matches: bool | None


class Directions(Model):
    binance: DirectionCheck
    bybit: DirectionCheck
    bybit_qty: QtyUnits


def stored_hosts(state: Mapping[str, str | None]) -> dict[str, HostState]:
    """Each host's state as the worker stored it; empty for a host it has not recorded."""
    stored = json.loads(state.get("hosts") or "{}")
    empty = HostState(last_success=None, error=None, until=None)
    return {
        host: HostState.model_validate(stored[host]) if host in stored else empty for host in HOSTS
    }


class Gap(NamedTuple):
    """Stamps [a, b) of one series to fetch. A backward gap ends where the stored rows begin and
    is filled newest first, so that whatever a failure leaves stays joined to them."""

    a: int
    b: int
    backward: bool


def gaps(stored: Iterable[int], start: int, end: int) -> list[Gap]:
    """What a round fetches of a series: the head gap from `start` to the first stored stamp and
    the last OVERLAP stored records onwards. Holes in between are left for QC to count."""
    stamps = list(stored)
    if not stamps:
        return [Gap(start, end, backward=True)]
    first, last = min(stamps), max(stamps)
    tail = max(start, last - (OVERLAP - 1) * BAR)
    if first <= start:
        return [Gap(tail, end, backward=False)]
    if tail <= first:
        return [Gap(start, end, backward=True)]
    return [Gap(start, first, backward=True), Gap(tail, end, backward=False)]


def _days[R: (Kline, OiPoint)](rows: Sequence[R], gap: Gap) -> list[list[R]]:
    """The rows stamped inside the gap, one list per UTC day, in the order they are written."""
    days: dict[int, list[R]] = defaultdict(list)
    for row in rows:
        if gap.a <= row.t < gap.b:
            days[row.t // DAY].append(row)
    order = sorted(days, reverse=gap.backward)
    return [days[day] for day in order]


def direction_check(grid: Grid) -> DirectionCheck:
    """Over one venue's grid: the 10m buckets whose price moved by DIRECTION_MOVE or more and
    that have liquidations, and the long share of those where it fell."""
    samples = down = 0
    longs = shorts = 0.0
    for i in range(1, len(grid.price)):
        before, after = grid.price[i - 1], grid.price[i]
        lliq, sliq = grid.long_liq[i], grid.short_liq[i]
        if before is None or after is None or before <= 0 or lliq is None or sliq is None:
            continue
        move = after / before - 1
        if abs(move) < DIRECTION_MOVE or lliq + sliq <= 0:
            continue
        samples += 1
        if move < 0:
            down += 1
            longs += lliq
            shorts += sliq
    share = longs / (longs + shorts) if down else None
    verdict: Verdict = "pending"
    if share is not None and down >= DIRECTION_MIN_DOWN:
        if share > DIRECTION_OK_ABOVE:
            verdict = "ok"
        elif share < DIRECTION_INVERTED_BELOW:
            verdict = "inverted"
    return DirectionCheck(verdict=verdict, samples=samples, down=down, long_share=share)


def qty_units(sizes: LiquidationSizes) -> QtyUnits:
    """Sizes and notionals of the distinct Bybit liquidations whose `v` and `p` are numbers."""
    low, high = NOTIONAL_RANGE
    qty, lowest, highest = sizes.min_qty, sizes.min_notional, sizes.max_notional
    # All three are None exactly when there are no events.
    return QtyUnits(
        events=sizes.events,
        min_qty=qty,
        min_notional=lowest,
        max_notional=highest,
        notional_in_range=(
            None if lowest is None or highest is None else low <= lowest and highest <= high
        ),
        min_qty_matches=None if qty is None else math.isclose(qty, MIN_QTY),
    )


class _Stopped(Exception):
    """The worker is stopping: its round is abandoned before the next request."""


class _Round:
    """One round's hosts: one that fails or is backed off is not asked again in the round."""

    def __init__(self, held: set[str]) -> None:
        self.held = held
        self.asked: set[str] = set()
        self.failed: dict[str, RestError] = {}

    def open(self, host: str) -> bool:
        return host not in self.held and host not in self.failed


class PerpsSync:
    def __init__(
        self,
        store: PerpsStore,
        rest: PerpsRest,
        *,
        clock: Callable[[], datetime],
        horizon_days: int = 90,
    ) -> None:
        self.store = store
        self.rest = rest
        self.clock = clock
        self.horizon_days = horizon_days
        self.stopping = Event()
        self.thread: Thread | None = None
        self._next: datetime | None = None  # None until the first run, which is not delayed

    def run_once(self, *, now: datetime | None = None) -> bool:
        """Run a round if one is due and return True; False when the next slot is still ahead."""

        def clock() -> datetime:
            return now if now is not None else self.clock()

        at = clock()
        if self._next is not None and at < self._next:
            return False
        started = time.perf_counter()
        error: str | None = None
        try:
            self._round(at, clock)
        except _Stopped:
            # Neither a failure nor a finished round: the stored state stays as it was.
            logger.info("perps_sync_stopped")
            return True
        except Exception:
            # Never log the exception: it may carry values. A fixed code is enough here.
            error = "sync_failed"
            logger.warning("perps_sync_failed code=%s", error)
        else:
            logger.info(
                "perps_sync_ok duration_ms=%d", round((time.perf_counter() - started) * 1000)
            )
        done = clock()
        self._next = next_slot(done)
        self.store.set_state(
            last_run_at=timestamp(done), next_run_at=timestamp(self._next), last_error=error
        )
        return True

    def start(self) -> None:
        def loop() -> None:
            while not self.stopping.is_set():
                try:
                    worked = self.run_once()
                except Exception:
                    logger.error("perps_worker_iteration_failed")
                    worked = False
                if not worked:
                    self.stopping.wait(self._idle_seconds())

        self.thread = Thread(target=loop, name="wheelhouse-perps", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=STOP_TIMEOUT_SECONDS)

    def _idle_seconds(self) -> float:
        """Until the next slot, but never long: the clock may be stepped meanwhile."""
        if self._next is None:
            return IDLE_SECONDS
        left = (self._next - self.clock()).total_seconds()
        return min(IDLE_SECONDS, max(1.0, left))

    def _round(self, at: datetime, clock: Callable[[], datetime]) -> None:
        now = int(at.timestamp())
        start = (now // DAY - (self.horizon_days + 1)) * DAY
        hosts = stored_hosts(self.store.state())
        # The stored deadline outlives a restart, which the client's own one does not.
        run = _Round(
            {
                host
                for host, state in hosts.items()
                if self.rest.backoff_until(host) is not None
                or (state.until is not None and state.until > at)
            }
        )
        try:
            try:
                self._fetch(run, start, now)
            except _Stopped:
                # What the requests so far found is kept, a backoff above all.
                self._record_hosts(run, hosts, clock(), finished=False)
                raise
            self._record_hosts(run, hosts, clock())
            if self.stopping.is_set():
                raise _Stopped  # nothing is derived once a stop is asked for
            grids = self._derive(start, clock())
            self._check_directions(grids, start)
        finally:
            # Retention holds even when a step above fails unexpectedly.
            self.store.prune(now - RETENTION_DAYS * DAY, now - TRADE_IDS_SECONDS)

    def _fetch(self, run: _Round, start: int, now: int) -> None:
        end = now + 1  # ranges are half-open and reach now
        self._fill_series(
            run,
            BYBIT_HOST,
            self.store.stamps("kline", "bybit", start),
            self.rest.bybit_spot_klines,
            partial(self.store.upsert_klines, "bybit"),
            start,
            end,
        )
        self._fill_series(
            run,
            BYBIT_HOST,
            self.store.stamps("oi", "bybit", start),
            self.rest.bybit_oi,
            partial(self.store.upsert_oi, "bybit"),
            start,
            end,
        )
        self._fill_series(
            run,
            BINANCE_HOST,
            self.store.stamps("kline", "binance", start),
            self.rest.binance_klines,
            partial(self.store.upsert_klines, "binance"),
            start,
            end,
        )
        self._binance_oi(run, start, end)

    def _ask[T](self, run: _Round, host: str, call: Callable[[], T]) -> T | None:
        """The call's result; None without asking when the host is closed for the round, or when
        it fails, which closes it. Raises _Stopped instead of asking once the worker is stopping."""
        if self.stopping.is_set():
            raise _Stopped
        if not run.open(host):
            return None
        run.asked.add(host)
        try:
            return call()
        except RestError as exc:
            run.failed.setdefault(exc.host, exc)
            logger.warning("perps_host_failed host=%s code=%s", exc.host, exc.code)
            return None

    def _fill[R: (Kline, OiPoint)](
        self,
        run: _Round,
        host: str,
        gap: Gap,
        fetch: Callable[[], Sequence[R]],
        write: Callable[[list[R]], None],
    ) -> bool:
        """Fetch one gap and write it a day per transaction; False if the host failed."""
        rows = self._ask(run, host, fetch)
        if rows is None:
            return False
        for day in _days(rows, gap):
            write(day)
        return True

    def _fill_series[R: (Kline, OiPoint)](
        self,
        run: _Round,
        host: str,
        stored: Iterable[int],
        fetch: Callable[[int, int], Sequence[R]],
        write: Callable[[list[R]], None],
        start: int,
        end: int,
    ) -> None:
        for gap in gaps(stored, start, end):
            if not self._fill(run, host, gap, partial(fetch, gap.a, gap.b), write):
                return

    def _binance_oi(self, run: _Round, start: int, end: int) -> None:
        """Binance OI: the history for the last HIST_DAYS days, archive files before that up to
        the boundary's day. At one stamp the history wins (the store sees to it)."""
        stored = self.store.stamps("oi", "binance", start)
        # Rounded up to a 5m stamp: a margin inside the history Binance keeps.
        boundary = -(-(end - 1 - HIST_DAYS * DAY) // BAR) * BAR
        write = partial(self.store.upsert_oi, "binance")
        for gap in gaps(stored, start, end):
            steps: list[Callable[[], bool]] = []
            if gap.a < boundary:
                if gap.b > boundary:
                    last_day = boundary // DAY
                else:
                    # A head gap ends at the first stored row: its file was fetched already if
                    # the row came from it; a history row does not cover the day before it.
                    last_day = (gap.b - BAR) // DAY - (
                        self.store.oi_source("binance", gap.b) == "archive"
                    )
                # The file of day D holds the stamps (D 00:05, D+1 00:00].
                first_day = max(start, gap.a - BAR) // DAY
                steps += [
                    partial(self._archive_day, run, gap, day)
                    for day in range(first_day, last_day + 1)
                ]
            if gap.b > boundary:
                fetch = partial(self.rest.binance_oi_hist, max(gap.a, boundary))
                steps.append(partial(self._fill, run, BINANCE_HOST, gap, fetch, write))
            # The gap is filled from the end that touches stored rows, and stops at a failure:
            # history and files then never leave a hole between them.
            for step in reversed(steps) if gap.backward else steps:
                if not step():
                    return

    def _archive_day(self, run: _Round, gap: Gap, day: int) -> bool:
        """One archive file; False if its host failed. A day without a file is remembered."""
        when = datetime.fromtimestamp(day * DAY, UTC).date()
        if self.store.archive_absent(when):
            return True
        found = self._ask(run, ARCHIVE_HOST, partial(self.rest.binance_oi_archive, when))
        if not run.open(ARCHIVE_HOST):
            return False
        if found is None:
            self.store.mark_archive_absent(when)
            return True
        points, _ = found
        self.store.upsert_oi("binance", [point for point in points if gap.a <= point.t < gap.b])
        return True

    def _record_hosts(
        self,
        run: _Round,
        before: Mapping[str, HostState],
        at: datetime,
        *,
        finished: bool = True,
    ) -> None:
        """A failure keeps its code and deadline until the host succeeds; a host that was backed
        off keeps its state; one with nothing to fetch has no error left, unless the round was
        stopped before it got there."""
        hosts: dict[str, HostState] = {}
        for host in HOSTS:
            old = before[host]
            if host in run.failed:
                exc = run.failed[host]
                hosts[host] = HostState(
                    last_success=old.last_success, error=exc.code, until=exc.until
                )
            elif host in run.held:
                hosts[host] = old
            elif host in run.asked:
                hosts[host] = HostState(last_success=at, error=None, until=None)
            elif not finished:
                hosts[host] = old
            else:
                hosts[host] = HostState(last_success=old.last_success, error=None, until=None)
        self.store.set_state(
            hosts=json.dumps({host: state.model_dump(mode="json") for host, state in hosts.items()})
        )

    def _derive(self, start: int, at: datetime) -> dict[Exchange, Grid | list[str]]:
        """Store the six payloads; return each view's grid, or the series it lacks."""
        grids: dict[Exchange, Grid | list[str]] = {}
        # Each venue's liquidations are read once: the All view reuses them.
        venues: tuple[Venue, ...] = ("binance", "bybit")
        liquidations = {venue: read_liquidations(self.store, venue, start) for venue in venues}
        for exchange in EXCHANGES:
            grid = build_grid(self.store, exchange, start, liquidations)
            grids[exchange] = grid
            for window in WINDOWS:
                states: StatesResult | None = None
                missing = grid if isinstance(grid, list) else []
                if isinstance(grid, Grid):
                    states = compute_states(grid, window)
                    missing = states.series_missing
                stored = StoredStates(
                    exchange=exchange,
                    window=window,
                    start=datetime.fromtimestamp(start, UTC),
                    reasons=[f"series_missing:{key}" for key in missing],
                    states=states,
                )
                self.store.save_derived(derived_key(exchange, window), stored.model_dump_json(), at)
        return grids

    def _check_directions(self, grids: Mapping[Exchange, Grid | list[str]], start: int) -> None:
        checks: dict[Venue, DirectionCheck] = {}
        for venue in ("binance", "bybit"):
            grid = grids[venue]
            checks[venue] = (
                direction_check(grid)
                if isinstance(grid, Grid)
                else DirectionCheck(verdict="pending", samples=0, down=0, long_share=None)
            )
        result = Directions(
            binance=checks["binance"],
            bybit=checks["bybit"],
            bybit_qty=qty_units(self.store.liquidation_sizes(start)),
        )
        self.store.set_state(direction_check=result.model_dump_json())
