"""Hourly BRK refresh: keeps the private series store current and derives cycle and levels."""

import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

from ..market import timestamp
from .brk import DAY1_SERIES, START, BrkClient, BrkError, Urpd
from .cycle import classify
from .levels import last_complete, model_lines
from .store import OnchainStore

logger = logging.getLogger("wheelhouse.onchain")

# Rows are (date, W, STH, TMM, price_close), in the order `classify` expects.
CYCLE_SERIES = (
    "utxos_1d_to_1w_old_realized_price",
    "sth_realized_price",
    "true_market_mean",
    "price_close",
)
URPD_COHORT = "all"
URPD_AGG = "lin500"
# Refreshes are due at HH:12 UTC.
SLOT_MINUTE = 12
RETRY_AFTER = timedelta(minutes=5)
# Re-fetch a few positions behind the stored end, so trailing NULLs and revisions are covered.
OVERLAP = 3
IDLE_SECONDS = 30
STOP_TIMEOUT_SECONDS = 25


def next_slot(at: datetime) -> datetime:
    """The first HH:12 UTC strictly after `at`."""
    slot = at.astimezone(UTC).replace(minute=SLOT_MINUTE, second=0, microsecond=0)
    return slot if slot > at else slot + timedelta(hours=1)


class OnchainSync:
    def __init__(self, store: OnchainStore, client: BrkClient) -> None:
        self.store = store
        self.client = client
        self.stopping = Event()
        self.thread: Thread | None = None

    def run_once(self, *, now: datetime | None = None) -> bool:
        """Refresh if due and return True; return False when the next refresh is not due yet."""

        def clock() -> datetime:
            return now if now is not None else datetime.now(UTC)

        at = clock()
        due = self.store.state()["next_due"]
        if due is not None and datetime.fromisoformat(due) > at:
            return False
        started = time.perf_counter()
        try:
            self._refresh(at, clock)
        except BrkError as exc:
            self._fail(clock(), exc.code, retry=exc.retryable, brk=True)
        except Exception:
            # Never log the exception: it may carry values. A fixed code is enough here.
            self._fail(clock(), "sync_failed", retry=False, brk=False)
        else:
            duration_ms = round((time.perf_counter() - started) * 1000)
            logger.info("onchain_sync_ok duration_ms=%d", duration_ms)
        return True

    def start(self) -> None:
        def loop() -> None:
            while not self.stopping.is_set():
                try:
                    worked = self.run_once()
                except Exception:
                    logger.error("onchain_worker_iteration_failed")
                    worked = False
                if not worked:
                    self.stopping.wait(IDLE_SECONDS)

        self.thread = Thread(target=loop, name="wheelhouse-onchain", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=STOP_TIMEOUT_SECONDS)

    def _refresh(self, at: datetime, clock: Callable[[], datetime]) -> None:
        version = self.client.version()
        missing: set[str] = set()
        if version != self.store.state()["brk_version"]:
            # Every series is rebuilt in one transaction; the old data stays readable until then.
            self.store.set_state(refreshing="true")
            self._replace(DAY1_SERIES, at, missing)
        else:
            self._increment(at, missing)
        # The series stage is done, so nothing is being rebuilt any more.
        self.store.set_state(brk_version=version, refreshing="false")

        urpd_error: BrkError | None = None
        try:
            urpd = self._urpd(at)
        except BrkError as exc:
            # The series are fresh whatever happens to URPD, so still derive from them, with the
            # latest snapshot on hand. The run is then recorded as failed.
            urpd_error = exc
            urpd = self.store.latest_urpd(URPD_COHORT, URPD_AGG)

        done = clock()
        self._derive(urpd, done)
        absent = [name for name in DAY1_SERIES if name in missing]
        reasons = [f"series_missing:{name}" for name in absent]
        if urpd is None:
            reasons.append("urpd_missing")
        self.store.set_state(missing_series=json.dumps(absent), reasons=json.dumps(reasons))
        if urpd_error is not None:
            raise urpd_error
        self.store.set_state(
            last_success_at=timestamp(done),
            last_error=None,
            next_due=timestamp(next_slot(done)),
        )

    def _replace(self, names: Sequence[str], at: datetime, missing: set[str]) -> None:
        """Re-fetch `names` from START and replace them, except series that come back empty."""
        batch = self.client.series(names, "day1", START)
        usable = {name: data for name, data in batch.found.items() if data.data}
        # An empty series would wipe the stored history, so keep the old one and report it.
        missing.update(batch.missing)
        missing.update(set(batch.found) - set(usable))
        if usable:
            self.store.replace_series(usable, "day1", at)

    def _increment(self, at: datetime, missing: set[str]) -> None:
        refetch: set[str] = set()
        starts: dict[int, list[str]] = {}
        for name in DAY1_SERIES:
            last = self.store.last_position(name, "day1")
            if last is None:
                refetch.add(name)
            else:
                starts.setdefault(max(last - OVERLAP, 0), []).append(name)
        for start, names in starts.items():
            batch = self.client.series(names, "day1", start)
            missing.update(batch.missing)
            for name, data in batch.found.items():
                if data.version == self.store.series_version(name, "day1"):
                    self.store.merge_series(name, "day1", data, at)
                else:
                    refetch.add(name)
        if refetch:
            self._replace([name for name in DAY1_SERIES if name in refetch], at, missing)

    def _urpd(self, at: datetime) -> Urpd | None:
        """Today's snapshot, or yesterday's while today's does not exist yet."""
        today = at.astimezone(UTC).date()
        for day in (today, today - timedelta(days=1)):
            urpd = self.client.urpd(URPD_COHORT, day, URPD_AGG)
            if urpd is not None:
                self.store.save_urpd(urpd, at)
                return urpd
        return None

    def _derive(self, urpd: Urpd | None, at: datetime) -> None:
        rows = {name: self.store.read_series(name, "day1") for name in DAY1_SERIES}

        w, sth, tmm, close = (
            {moment.date(): value for moment, value in rows[name]} for name in CYCLE_SERIES
        )
        days = sorted(w.keys() | sth.keys() | tmm.keys() | close.keys())
        cycle = classify(
            [(day, w.get(day), sth.get(day), tmm.get(day), close.get(day)) for day in days]
        )
        if cycle is None:
            self.store.clear_derived("cycle")
        else:
            self.store.save_derived("cycle", cycle.model_dump_json(), at)

        last = last_complete(rows)
        if last is None:
            self.store.clear_derived("levels")
            return
        as_of, values = last
        levels = {
            "as_of": as_of.isoformat(),
            "urpd_date": urpd.date.isoformat() if urpd else None,
            "onchain_close": urpd.close if urpd else None,
            "lines": [line.model_dump() for line in model_lines(values, urpd)],
        }
        self.store.save_derived("levels", json.dumps(levels, allow_nan=False), at)

    def _fail(self, at: datetime, code: str, *, retry: bool, brk: bool) -> None:
        """Record a failed run; `last_success_at` keeps meaning the last complete refresh."""
        logger.warning("onchain_sync_failed code=%s", code)
        state = self.store.state()
        reasons: list[str] = json.loads(state["reasons"] or "[]")
        if brk and "brk_unavailable" not in reasons:
            reasons.append("brk_unavailable")
        self.store.set_state(
            last_error=code,
            next_due=timestamp(at + RETRY_AFTER if retry else next_slot(at)),
            reasons=json.dumps(reasons),
        )
