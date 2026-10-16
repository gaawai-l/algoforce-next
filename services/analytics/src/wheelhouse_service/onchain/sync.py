"""Hourly BRK refresh: keeps the private series store current and derives the on-chain views."""

import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from threading import Event, Thread

from ..market import timestamp
from .brk import DAY1_SERIES, HOUR1_BACKFILL, HOUR1_SERIES, START, BrkClient, BrkError, Index, Urpd
from .costbasis import (
    BUCKETS,
    COHORTS,
    LINE_ORDER,
    PAST_DAYS,
    BucketCostBasis,
    StoredCostBasis,
    cost_basis,
)
from .cycle import classify
from .levels import ModelLine, last_complete, model_lines
from .models import GRACE_END
from .pressure import LOOKBACK, seller_pressure
from .store import OnchainStore

logger = logging.getLogger("wheelhouse.onchain")

# Rows are (date, W, STH, TMM, price_close), in the order `classify` expects.
CYCLE_SERIES = (
    "utxos_1d_to_1w_old_realized_price",
    "sth_realized_price",
    "true_market_mean",
    "price_close",
)
# Where a full fetch of each index starts. hour1 asks for its last points: from a date it would ask
# for years of hourly data.
BACKFILL: dict[Index, int | date] = {"day1": START, "hour1": -HOUR1_BACKFILL}
URPD_COHORT = "all"
URPD_AGG = "lin500"
# The snapshots the cost basis needs: every cohort at every bucket width. The first one gives the
# median line and the day D that the others are fetched for.
URPD_SET: tuple[tuple[str, str], ...] = (
    (URPD_COHORT, URPD_AGG),
    ("sth", "lin500"),
    ("lth", "lin500"),
    ("all", "lin200"),
    ("sth", "lin200"),
    ("lth", "lin200"),
    ("all", "lin1000"),
    ("sth", "lin1000"),
    ("lth", "lin1000"),
)
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
            stage_error = self._refresh(at, clock)
        except BrkError as exc:
            self._fail(clock(), exc.code, retry=exc.retryable, brk=True)
        except Exception:
            # Never log the exception: it may carry values. A fixed code is enough here.
            self._fail(clock(), "sync_failed", retry=False, brk=False)
        else:
            if stage_error is not None:
                # Only the hour1 or URPD stage failed, so the shared reasons (and with them the
                # cycle view) stay clean; `last_error` still records it.
                self._fail(clock(), stage_error.code, retry=stage_error.retryable, brk=False)
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

    def _refresh(self, at: datetime, clock: Callable[[], datetime]) -> BrkError | None:
        """Run one refresh; return the error of the hour1 or URPD stage when only those failed."""
        version = self.client.version()
        missing: set[str] = set()
        if version != self.store.state()["brk_version"]:
            # Every series is rebuilt in one transaction; the old data stays readable until then.
            self.store.set_state(refreshing="true")
            self._replace(DAY1_SERIES, "day1", at, missing)
        else:
            self._increment(DAY1_SERIES, "day1", at, missing)
        # The series stage is done, so nothing is being rebuilt any more.
        self.store.set_state(brk_version=version, refreshing="false")

        # hour1 follows its series' own versions rather than BRK's: any series that changed is
        # fetched again in full. A failure here leaves the day1 modules and URPD untouched.
        hour1_missing: set[str] = set()
        hour1_error: BrkError | None = None
        hour1_done: datetime | None = None
        try:
            self._increment(HOUR1_SERIES, "hour1", at, hour1_missing)
            # The pressure is as of now: the URPD fetch below can take long enough to cross the
            # hour, and the last row would then look closed when it was computed.
            hour1_done = clock()
        except BrkError as exc:
            hour1_error = exc
            # What a failed request could not tell stands as it was, and so does the pressure.
            hour1_missing = self._stored_hour1_missing()

        urpd_error: BrkError | None = None
        try:
            urpd = self._urpd(at)
        except BrkError as exc:
            # The series are fresh whatever happens to URPD, so still derive from them, with a
            # recent stored snapshot if there is one. The run is then recorded as failed.
            urpd_error = exc
            urpd = self._recent_urpd(at)

        done = clock()
        self._derive(urpd, done, hour1_missing, hour1_done)
        absent = [name for name in DAY1_SERIES if name in missing]
        absent_hour1 = [name for name in HOUR1_SERIES if name in hour1_missing]
        # `price_close` is in both indexes, so day1 reasons keep their form and hour1 ones add it.
        reasons = [f"series_missing:{name}" for name in absent]
        reasons += [f"series_missing:hour1:{name}" for name in absent_hour1]
        if urpd is None:
            reasons.append("urpd_missing")
        self.store.set_state(
            missing_series=json.dumps(
                [f"day1:{name}" for name in absent] + [f"hour1:{name}" for name in absent_hour1]
            ),
            reasons=json.dumps(reasons),
        )
        errors = [error for error in (hour1_error, urpd_error) if error is not None]
        if errors:
            # Retrying soon is worth it when any one of the failed stages can be retried.
            return next((error for error in errors if error.retryable), errors[0])
        self.store.set_state(
            last_success_at=timestamp(done),
            last_error=None,
            next_due=timestamp(next_slot(done)),
        )
        return None

    def _replace(self, names: Sequence[str], index: Index, at: datetime, missing: set[str]) -> None:
        """Re-fetch `names` in full and replace them, except series that come back empty."""
        batch = self.client.series(names, index, BACKFILL[index])
        usable = {name: data for name, data in batch.found.items() if data.data}
        # An empty series would wipe the stored history, so keep the old one and report it.
        missing.update(batch.missing)
        missing.update(set(batch.found) - set(usable))
        if usable:
            self.store.replace_series(usable, index, at)

    def _increment(
        self, names: Sequence[str], index: Index, at: datetime, missing: set[str]
    ) -> None:
        refetch: set[str] = set()
        starts: dict[int, list[str]] = {}
        for name in names:
            last = self.store.last_position(name, index)
            if last is None:
                refetch.add(name)
            else:
                starts.setdefault(max(last - OVERLAP, 0), []).append(name)
        for start, group in starts.items():
            batch = self.client.series(group, index, start)
            missing.update(batch.missing)
            for name, data in batch.found.items():
                if data.version == self.store.series_version(name, index):
                    self.store.merge_series(name, index, data, at)
                else:
                    refetch.add(name)
        if refetch:
            self._replace([name for name in names if name in refetch], index, at, missing)

    def _stored_hour1_missing(self) -> set[str]:
        """The hour1 series the last run found missing."""
        entries: list[str] = json.loads(self.store.state()["missing_series"] or "[]")
        return {entry.removeprefix("hour1:") for entry in entries if entry.startswith("hour1:")}

    def _urpd(self, at: datetime) -> Urpd | None:
        """Today's snapshot, or yesterday's while today's does not exist yet.

        The rest of URPD_SET is fetched for the same day D, and so are the past snapshots the
        cost-basis grid needs while they are missing or not final. All are stored, and the days no
        longer needed are pruned.
        """
        today = at.astimezone(UTC).date()
        urpd: Urpd | None = None
        for day in (today, today - timedelta(days=1)):
            urpd = self.client.urpd(URPD_COHORT, day, URPD_AGG)
            if urpd is not None:
                break
        if urpd is None:
            # Without D nothing else is asked for, and nothing is pruned.
            return None
        self.store.save_urpd(urpd, at)
        for cohort, agg in URPD_SET[1:]:
            # A failure here fails the stage, like one of `all lin500`.
            self._save_urpd(cohort, urpd.date, agg, at)
        past = [urpd.date - timedelta(days=n) for n in PAST_DAYS]
        for day in past:
            # Fetched before the day closed, plus the grace day1 rows get, it may have been forming.
            final = datetime.combine(day + timedelta(days=1), GRACE_END, tzinfo=UTC)
            for cohort, agg in URPD_SET:
                fetched_at = self.store.urpd_fetched_at(cohort, day, agg)
                if fetched_at is not None and fetched_at >= final:
                    continue
                try:
                    self._save_urpd(cohort, day, agg, at)
                except BrkError as exc:
                    # Past snapshots only widen the grid: the derived reasons tell what is missing.
                    logger.warning("onchain_urpd_past_failed code=%s", exc.code)
        self.store.prune_urpd({today, today - timedelta(days=1), urpd.date, *past})
        return urpd

    def _save_urpd(self, cohort: str, day: date, agg: str, at: datetime) -> None:
        urpd = self.client.urpd(cohort, day, agg)
        if urpd is not None:
            self.store.save_urpd(urpd, at)

    def _recent_urpd(self, at: datetime) -> Urpd | None:
        """The stored snapshot, unless it is older than yesterday: that would pass for current."""
        stored = self.store.latest_urpd(URPD_COHORT, URPD_AGG)
        oldest = at.astimezone(UTC).date() - timedelta(days=1)
        return stored if stored is not None and stored.date >= oldest else None

    def _derive(
        self,
        urpd: Urpd | None,
        at: datetime,
        hour1_missing: set[str],
        hour1_at: datetime | None,
    ) -> None:
        """Derive every view; stamp the pressure `hour1_at`, None when the hour1 stage failed."""
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
            self.store.clear_derived("costbasis")
        else:
            as_of, values = last
            lines = model_lines(values, urpd)
            levels = {
                "as_of": as_of.isoformat(),
                "urpd_date": urpd.date.isoformat() if urpd else None,
                "onchain_close": urpd.close if urpd else None,
                "lines": [line.model_dump() for line in lines],
            }
            self.store.save_derived("levels", json.dumps(levels, allow_nan=False), at)
            if urpd is None or len(lines) < len(LINE_ORDER):
                # Without all five lines the bands would quietly change, so there is none.
                self.store.clear_derived("costbasis")
            else:
                stored = self._cost_basis(urpd.date, as_of.date(), lines)
                self.store.save_derived("costbasis", stored.model_dump_json(), at)

        if hour1_at is None:
            # The stored pressure stays, with the time it was computed, until hour1 is fetched.
            return
        pressure = None
        if not hour1_missing:
            # An absent series is not a zero: with any of them gone there is no pressure at all.
            pressure = seller_pressure(
                {
                    name: self.store.read_series(name, "hour1", tail=LOOKBACK + 1)
                    for name in HOUR1_SERIES
                }
            )
        if pressure is None:
            self.store.clear_derived("pressure")
        else:
            self.store.save_derived("pressure", pressure.model_dump_json(), hour1_at)

    def _cost_basis(self, day: date, lines_as_of: date, lines: list[ModelLine]) -> StoredCostBasis:
        """Every bucket width whose snapshots of `day` are all stored; the reasons say what is not.

        Only the store is read, so what was fetched in this run does not matter.
        """
        buckets: list[BucketCostBasis] = []
        reasons: list[str] = []
        used: list[tuple[str, str]] = []
        for bucket in BUCKETS:
            agg = f"lin{bucket}"
            today: dict[str, Urpd] = {}
            for cohort in COHORTS:
                snapshot = self.store.urpd(cohort, day, agg)
                if snapshot is None:
                    reasons.append(f"urpd_missing:{cohort}:{agg}")
                else:
                    today[cohort] = snapshot
            if len(today) < len(COHORTS):
                continue
            past = [
                self.store.urpd(cohort, day - timedelta(days=n), agg)
                for n in PAST_DAYS
                for cohort in COHORTS
            ]
            found = [snapshot for snapshot in past if snapshot is not None]
            if len(found) < len(past):
                # The grid is built from the days there are.
                reasons.append(f"urpd_grid_partial:{agg}")
            result = cost_basis(today, found, bucket, lines)
            if result is None:
                reasons.append(f"urpd_empty:{agg}")
            else:
                buckets.append(result)
                used += [(cohort, agg) for cohort in COHORTS]
        # Without a usable width, the snapshot the median came from.
        stamps = [
            self.store.urpd_fetched_at(cohort, day, agg)
            for cohort, agg in used or [(URPD_COHORT, URPD_AGG)]
        ]
        return StoredCostBasis(
            urpd_date=day,
            lines_as_of=lines_as_of,
            snapshot_at=min(stamp for stamp in stamps if stamp is not None),
            buckets=buckets,
            reasons=reasons,
        )

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
