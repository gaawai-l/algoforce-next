"""REST worker for the perp states: backfills and refreshes the public series and Coinalyze's,
derives the eight state payloads, checks the liquidation direction and prunes (spec §2, §3.1,
§3.7, §3.8, §6; proposal §3)."""

import json
import logging
import math
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
from threading import Event, Thread
from typing import Literal, NamedTuple

from pydantic import AwareDatetime

from ..market import Model, timestamp
from ..rules import Rule, Rules, rules_for_view
from .coinalyze import KIND_VENUES, STEPS, Coinalyze, Interval, MarketCheck
from .grid import BAR, VIEW_VENUES, build_grid
from .rows import CzKind, CzPoint, CzVenue, Exchange, Kline, OiPoint
from .sources import ARCHIVE_HOST, BINANCE_HOST, BYBIT_HOST, CZ_HOST, PerpsRest, RestError
from .states import DAY, STEP, Grid, StatesResult, Window, compute_states
from .store import PerpsStore

logger = logging.getLogger("wheelhouse.perps.sync")

HOSTS = (BINANCE_HOST, ARCHIVE_HOST, BYBIT_HOST, CZ_HOST)
EXCHANGES: tuple[Exchange, ...] = ("all", "binance", "bybit", "hyperliquid")
WINDOWS: tuple[Window, ...] = ("4h", "8h")
# Binance keeps about 30 days of openInterestHist; older OI comes from the daily archive files.
HIST_DAYS = 29
# Each round fetches the last few stored records of every series again, as onchain's OVERLAP.
OVERLAP = 3
# A round fetches from HORIZON_DAYS + 1 UTC days back, enough for O6 to rank the earliest block
# in the 30-day view against the 90 days before it; the same whatever the rules, so switching
# them needs no backfill (P5-R9).
HORIZON_DAYS = 120
RETENTION_DAYS = 125
TRADE_IDS_SECONDS = 3600
# Coinalyze (proposal §3.2). A closed 4hour window is fetched again every round for CZ_SETTLE
# after it closes: its value may not be complete at once. 5min intervals are kept for a day.
H4 = STEPS["4hour"]
CZ_SETTLE = 3600
CZ_5MIN_KEEP = DAY
# This process's share of the key's 40 calls a minute: a second process may use the rest.
CZ_CALLS_PER_MINUTE = 20
CZ_MINUTE = 60.0
# The market list (units, buy/sell data) is read again after this long.
CZ_MARKETS_EVERY = DAY
# Rounds run at HH:05, HH:15, ...: Binance publishes its history rows 2-4 minutes late.
SLOT_OFFSET = 300
IDLE_SECONDS = 30
STOP_TIMEOUT_SECONDS = 25

# The liquidation direction check (spec §6, proposal §3.3): closed 4h windows with liquidations
# whose price moved at least this much from their first bucket to their last; the verdict needs
# this many falling ones.
DIRECTION_MOVE = 0.01
DIRECTION_MIN_DOWN = 20
DIRECTION_OK_ABOVE = 0.6
DIRECTION_INVERTED_BELOW = 0.4


def next_slot(at: datetime) -> datetime:
    """The first HH:x5:00 UTC strictly after `at`."""
    t = math.floor(at.timestamp())
    return datetime.fromtimestamp((t - SLOT_OFFSET) // STEP * STEP + SLOT_OFFSET + STEP, UTC)


def derived_key(exchange: Exchange, window: Window) -> str:
    return f"states:{exchange}:{window}"


def grid_start(at: datetime, horizon_days: int = HORIZON_DAYS) -> int:
    """The first bucket a round at `at` fetches and derives from: `horizon_days` + 1 UTC days
    before its date."""
    return (int(at.timestamp()) // DAY - (horizon_days + 1)) * DAY


class StoredStates(Model):
    """One exchange view and window as the worker derives it.

    `states` is None when the view lacks a required REST series from `start` on; `reasons` then
    name those series, and otherwise the ones with no value in the reference window; then the
    venues it reads whose Coinalyze units failed their check.
    """

    exchange: Exchange
    window: Window
    start: AwareDatetime  # the grid's first bucket
    reasons: list[str]  # series_missing:<venue>:<series>, coinalyze_units:<venue>
    states: StatesResult | None
    # The rules it was derived under; payloads stored before rules existed read as none.
    rules: list[Rule] = []


class HostState(Model):
    last_success: AwareDatetime | None
    error: str | None  # RestError.code of the host's last failure, until it succeeds again
    until: AwareDatetime | None  # backed off until then


Verdict = Literal["ok", "inverted", "pending"]


class DirectionCheck(Model):
    """One venue's liquidation sides against the price (spec §6, proposal §3.3)."""

    verdict: Verdict
    samples: int  # 4h windows that moved at least DIRECTION_MOVE and have liquidations
    down: int  # of those, the falling ones
    long_share: float | None  # Σlong / (Σlong + Σshort) over the falling ones


class Directions(Model):
    """Each venue whose liquidations Coinalyze reports; pending for one excluded by its units."""

    binance: DirectionCheck
    bybit: DirectionCheck
    okx: DirectionCheck


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


def direction_check(
    liq: Mapping[int, CzPoint], spot: Mapping[int, tuple[float, float | None, float | None]]
) -> DirectionCheck:
    """Over one venue's closed 4h windows: those with liquidations whose price, the closes of the
    spot bars opening at w+5m and w+4h-5m (its first and last bucket), moved by DIRECTION_MOVE or
    more, and the long share of those where it fell. Filled windows are left out."""
    samples = down = 0
    longs = shorts = 0.0
    for w, point in sorted(liq.items()):
        first, last = spot.get(w + BAR), spot.get(w + H4 - BAR)
        if point.filled or first is None or last is None or first[0] <= 0:
            continue
        move = last[0] / first[0] - 1
        if abs(move) < DIRECTION_MOVE or point.a + point.b <= 0:
            continue
        samples += 1
        if move < 0:
            down += 1
            longs += point.a
            shorts += point.b
    share = longs / (longs + shorts) if down else None
    verdict: Verdict = "pending"
    if share is not None and down >= DIRECTION_MIN_DOWN:
        if share > DIRECTION_OK_ABOVE:
            verdict = "ok"
        elif share < DIRECTION_INVERTED_BELOW:
            verdict = "inverted"
    return DirectionCheck(verdict=verdict, samples=samples, down=down, long_share=share)


def stored_markets(state: Mapping[str, str | None]) -> list[MarketCheck]:
    """The last unit check of the Coinalyze symbols; empty until one has been read."""
    stored = state.get("cz_markets")
    return [MarketCheck.model_validate(check) for check in json.loads(stored)] if stored else []


def _excluded(state: Mapping[str, str | None]) -> frozenset[CzVenue]:
    """The venues whose Coinalyze data is not used: their last unit check failed. Empty before a
    check has been read (proposal §3.2)."""
    return frozenset(check.venue for check in stored_markets(state) if not check.ok)


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
        rules: Rules,
        horizon_days: int = HORIZON_DAYS,
        coinalyze: Coinalyze | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        pause: Callable[[float], bool] | None = None,
    ) -> None:
        """`coinalyze` is None when the history is not fetched. `monotonic` times the pacing of
        its requests and `pause(seconds)` waits between them, answering whether the worker is
        stopping; it defaults to waiting on the stop event."""
        self.store = store
        self.rest = rest
        self.clock = clock
        self.rules = rules
        self.horizon_days = horizon_days
        self.coinalyze = coinalyze
        self.monotonic = monotonic
        self.stopping = Event()
        self.pause = pause if pause is not None else self.stopping.wait
        # (monotonic time, symbols) of the Coinalyze requests made in the last minute.
        self._cz_spent: deque[tuple[float, int]] = deque()
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
        start = grid_start(at, self.horizon_days)
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
            self._derive(start, clock())
            self._check_directions(start)
        finally:
            # Retention holds even when a step above fails unexpectedly.
            self.store.prune(
                now - RETENTION_DAYS * DAY, now - TRADE_IDS_SECONDS, now - CZ_5MIN_KEEP
            )

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
        self._coinalyze(run, start, now)

    def _coinalyze(self, run: _Round, start: int, now: int) -> None:
        """Fetch the Coinalyze history (proposal §3.2) and store it; the first failure closes the
        host and ends this part of the round.

        Per kind: the 4hour series from `start` when it needs a backfill, or the last OVERLAP
        windows when one is settling or a venue is behind, and the 5min series from the window
        before the current one every round. A bar that closed while a request was in flight was
        left out by the client, and a later round fetches it: no cursor skips it. Once all kinds
        are in, the unit check is read if a day has passed.
        """
        client = self.coinalyze
        if client is None:
            return
        state = self.store.state()
        newest = now // H4 * H4 - H4  # the newest closed 4hour window
        for kind, venues in KIND_VENUES.items():
            latest = self.store.cz_latest(kind, H4)
            marker = state.get(f"cz_4h:{kind}")
            backfilled_from = None if marker is None else int(json.loads(marker)["from"])
            backfill = (
                backfilled_from is None
                or backfilled_from > start
                or any(venue not in latest for venue in venues)
            )
            frm: int | None = None
            if backfill:
                frm = start
            elif now - (newest + H4) < CZ_SETTLE or any(latest[v] < newest for v in venues):
                frm = max(start, min(latest[v] for v in venues) - (OVERLAP - 1) * H4)
            if frm is not None:
                if not self._cz_history(run, client, kind, "4hour", frm, now):
                    return
                if backfill:
                    self.store.set_state(**{f"cz_4h:{kind}": json.dumps({"from": start})})
            if not self._cz_history(run, client, kind, "5min", newest, now):
                return
        self._cz_markets(run, client, state, now)

    def _cz_history(
        self, run: _Round, client: Coinalyze, kind: CzKind, interval: Interval, frm: int, to: int
    ) -> bool:
        """Fetch one history request and store it per venue; False if the host failed."""
        found = self._cz_ask(
            run, len(KIND_VENUES[kind]), partial(client.history, kind, interval, frm, to)
        )
        if found is None:
            return False
        for venue, points in found.items():
            self.store.upsert_cz(kind, STEPS[interval], venue, points)
        return True

    def _cz_markets(
        self, run: _Round, client: Coinalyze, state: Mapping[str, str | None], now: int
    ) -> None:
        """Read the market list when none is stored or its read is CZ_MARKETS_EVERY old; a
        failed read keeps the old result."""
        read = state.get("cz_markets_at")
        if read is not None and now - datetime.fromisoformat(read).timestamp() < CZ_MARKETS_EVERY:
            return
        checks = self._cz_ask(run, 1, client.markets)
        if checks is not None:
            self.store.set_state(
                cz_markets=json.dumps([check.model_dump(mode="json") for check in checks]),
                cz_markets_at=timestamp(datetime.fromtimestamp(now, UTC)),
            )

    def _cz_ask[T](self, run: _Round, cost: int, call: Callable[[], T]) -> T | None:
        """`_ask` for Coinalyze, after waiting until `cost` more symbol-calls fit in the minute."""
        if run.open(CZ_HOST):
            self._pace(cost)
        return self._ask(run, CZ_HOST, call)

    def _pace(self, cost: int) -> None:
        """Record a request of `cost` symbol-calls, first waiting until no 60 s window would
        hold more than CZ_CALLS_PER_MINUTE. Raises _Stopped if the wait says the worker stops."""
        while True:
            at = self.monotonic()
            while self._cz_spent and self._cz_spent[0][0] <= at - CZ_MINUTE:
                self._cz_spent.popleft()
            excess = sum(spent for _, spent in self._cz_spent) + cost - CZ_CALLS_PER_MINUTE
            if excess <= 0 or not self._cz_spent:
                break
            # Until enough of the oldest requests have left the minute.
            wait, freed = 0.0, 0
            for sent, spent in self._cz_spent:
                freed += spent
                wait = sent + CZ_MINUTE - at
                if freed >= excess:
                    break
            if self.pause(wait):
                raise _Stopped
        self._cz_spent.append((at, cost))

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
        return derive_states(self.store, start=start, at=at, rules=self.rules)

    def _check_directions(self, start: int) -> None:
        """Each venue's check over the 4hour liquidations of the whole grid."""
        excluded = _excluded(self.store.state())
        spot = self.store.klines("bybit", start)

        def check(venue: CzVenue) -> DirectionCheck:
            if venue in excluded:
                return DirectionCheck(verdict="pending", samples=0, down=0, long_share=None)
            return direction_check(self.store.cz_series("liq", H4, venue, start), spot)

        result = Directions(binance=check("binance"), bybit=check("bybit"), okx=check("okx"))
        self.store.set_state(direction_check=result.model_dump_json())


def derive_states(
    store: PerpsStore, *, start: int, at: datetime, rules: Rules
) -> dict[Exchange, Grid | list[str]]:
    """Store the eight payloads, derived from bucket `start` under `rules` and computed at `at`;
    return each view's grid, or the series it lacks. A venue whose stored unit check failed is
    left out of every view, and those that read it say so."""
    # Only the rules the payload records are applied.
    applied = rules_for_view("perps", rules)
    excluded = _excluded(store.state())
    grids: dict[Exchange, Grid | list[str]] = {}
    for exchange in EXCHANGES:
        grid = build_grid(store, exchange, start, excluded)
        grids[exchange] = grid
        units = [f"coinalyze_units:{v}" for v in VIEW_VENUES[exchange] if v in excluded]
        for window in WINDOWS:
            states: StatesResult | None = None
            missing = grid if isinstance(grid, list) else []
            if isinstance(grid, Grid):
                states = compute_states(grid, window, rules=frozenset(applied))
                missing = states.series_missing
            stored = StoredStates(
                exchange=exchange,
                window=window,
                start=datetime.fromtimestamp(start, UTC),
                reasons=[f"series_missing:{key}" for key in missing] + units,
                states=states,
                rules=applied,
            )
            store.save_derived(derived_key(exchange, window), stored.model_dump_json(), at)
    return grids
