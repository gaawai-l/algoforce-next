"""Hourly BRK refresh: keeps the private series store current and derives the on-chain views."""

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from threading import Event, Thread

from ..market import timestamp
from ..rules import Rules, View, rules_for_view
from .agecohorts import INPUTS as AGE_INPUTS
from .agecohorts import age_cohorts
from .brk import (
    AGE_FLOOR_SERIES,
    AGE_ONLY_SERIES,
    AGE_URPD_COHORTS,
    DAY1_SERIES,
    HOUR1_BACKFILL,
    HOUR1_SERIES,
    SELL_SIDE_SERIES,
    START,
    URPD_AGG,
    URPD_COHORT,
    URPD_SET,
    BrkClient,
    BrkError,
    Index,
    Urpd,
)
from .costbasis import (
    BUCKETS,
    COHORTS,
    PAST_DAYS,
    BucketCostBasis,
    StoredCostBasis,
    cost_basis,
    line_order,
)
from .costflow import GRIDS, WINDOWS, StoredCostFlow, cost_flow
from .cycle import classify
from .levels import ModelLine, last_complete, model_lines
from .models import closed_day, day_start, final_from
from .pressure import V1_LOOKBACK, lookback, seller_pressure
from .sellside import INPUTS, sell_side
from .store import OnchainStore

logger = logging.getLogger("wheelhouse.onchain")

# Rows are (date, W, STH, TMM, price_close), in the order `classify` expects.
CYCLE_SERIES = (
    "utxos_1d_to_1w_old_realized_price",
    "sth_realized_price",
    "true_market_mean",
    "price_close",
)
# The day1 series fetched: the modules' own, then the daily range Chart 4's age floor reads.
DAY1_FETCH = (*DAY1_SERIES, *AGE_FLOOR_SERIES)
# Where a full fetch of each index starts. hour1 asks for its last points: from a date it would ask
# for years of hourly data.
BACKFILL: dict[Index, int | date] = {"day1": START, "hour1": -HOUR1_BACKFILL}
# Refreshes are due at HH:12 UTC.
SLOT_MINUTE = 12
RETRY_AFTER = timedelta(minutes=5)
# Re-fetch a few positions behind the stored end, so trailing NULLs and revisions are covered.
OVERLAP = 3
IDLE_SECONDS = 30
STOP_TIMEOUT_SECONDS = 25
# The derived views: those from the day1 series and URPD, then the hour1 ones.
DAY1_VIEWS: tuple[View, ...] = ("cycle", "levels", "costbasis", "costflow")
VIEWS: tuple[View, ...] = (*DAY1_VIEWS, "pressure", "sellside", "agecohorts")


def next_slot(at: datetime) -> datetime:
    """The first HH:12 UTC strictly after `at`."""
    slot = at.astimezone(UTC).replace(minute=SLOT_MINUTE, second=0, microsecond=0)
    return slot if slot > at else slot + timedelta(hours=1)


def closed_days(at: datetime) -> list[date]:
    """The days whose URPD snapshots O1 needs at `at`, in the order they are fetched.

    First the closed day C and the day before, the two days F can be, then the past days of
    either's grid, newest first.
    """
    closed = closed_day(at)
    anchors = [closed, closed - timedelta(days=1)]
    past = {day - timedelta(days=n) for day in anchors for n in PAST_DAYS} - set(anchors)
    return [*anchors, *sorted(past, reverse=True)]


class OnchainSync:
    def __init__(self, store: OnchainStore, client: BrkClient, *, rules: Rules) -> None:
        self.store = store
        self.client = client
        self.rules = rules
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
                # Only an hour1 or the URPD stage failed, so the shared reasons (and with them the
                # cycle view) stay clean; `last_error` still records it.
                self._fail(clock(), stage_error.code, retry=stage_error.retryable, brk=False)
            else:
                duration_ms = round((time.perf_counter() - started) * 1000)
                logger.info("onchain_sync_ok duration_ms=%d", duration_ms)
        return True

    def start(self) -> None:
        def loop() -> None:
            try:
                self.rederive_if_rules_changed(datetime.now(UTC))
            except Exception:
                # Never log the exception: it may carry values. The next refresh derives anyway.
                logger.error("onchain_rederive_failed")
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

    def rederive_if_rules_changed(self, now: datetime) -> bool:
        """Re-derive from the store when a stored payload was derived under other rules.

        The next refresh is then due at `now`, so what the new rules need is fetched at once.
        """
        changed = any(
            set(json.loads(derived[0]).get("rules", [])) != set(rules_for_view(view, self.rules))
            for view in VIEWS
            if (derived := self.store.derived(view)) is not None
        )
        if not changed:
            return False
        # Due first: should deriving fail, the next refresh still runs at once and derives anyway.
        self.store.set_state(next_due=timestamp(now))
        self.derive_from_store()
        return True

    def derive_from_store(self) -> None:
        """Derive every stored view again under `self.rules`, reading only the store.

        Each view keeps the time it was computed: the day1 ones the latest of theirs, which also
        gives their closed day, the seller pressure its own and so do the age cohorts. A view group
        with nothing stored is left alone.
        """
        stamps = [
            derived[1] for view in DAY1_VIEWS if (derived := self.store.derived(view)) is not None
        ]
        pressure = self.store.derived("pressure")
        hour1_at = pressure[1] if pressure else None
        hour1_missing = self._stored_hour1_missing()
        if stamps:
            at = max(stamps)
            # The shared reasons stay as they are: the refresh due at once after this sets them.
            self._derive(self._recent_urpd(at), at, hour1_missing, hour1_at, closed=closed_day(at))
        else:
            self._derive_pressure(hour1_missing, hour1_at)
            self._derive_sell_side(hour1_missing, hour1_at)
        ages = self.store.derived("agecohorts")
        self._derive_age_cohorts(hour1_missing, ages[1] if ages else None)

    def _refresh(self, at: datetime, clock: Callable[[], datetime]) -> BrkError | None:
        """Run one refresh; return the error of an hour1 or URPD stage when only those failed."""
        # The closed day is that of the round's start, so a round that crosses GRACE_END does not
        # take a day BRK could still revise for closed.
        closed = closed_day(at)
        version = self.client.version()
        missing: set[str] = set()
        if version != self.store.state()["brk_version"]:
            # Every series is rebuilt in one transaction; the old data stays readable until then.
            self.store.set_state(refreshing="true")
            self._replace(DAY1_FETCH, "day1", at, missing)
        else:
            self._increment(DAY1_FETCH, "day1", at, missing)
        # The series stage is done, so nothing is being rebuilt any more.
        self.store.set_state(brk_version=version, refreshing="false")

        # hour1 follows its series' own versions rather than BRK's: any series that changed is
        # fetched again in full. A failure here leaves the day1 modules and URPD untouched.
        hour1_missing: set[str] = set()
        hour1_error: BrkError | None = None
        hour1_done: datetime | None = None
        try:
            self._increment((*HOUR1_SERIES, *SELL_SIDE_SERIES), "hour1", at, hour1_missing)
            # The pressure is as of now: the URPD fetch below can take long enough to cross the
            # hour, and the last row would then look closed when it was computed.
            hour1_done = clock()
        except BrkError as exc:
            hour1_error = exc
            # What a failed request could not tell stands as it was, and so does the pressure.
            hour1_missing = self._stored_hour1_missing() - set(AGE_ONLY_SERIES)

        # The age cohorts' own series take several requests more, so they have a stage of their
        # own: when it fails, only the age-cohort chart stays as it was.
        age_missing: set[str] = set()
        age_error: BrkError | None = None
        try:
            self._increment(AGE_ONLY_SERIES, "hour1", at, age_missing)
        except BrkError as exc:
            age_error = exc
            age_missing = self._stored_hour1_missing() & set(AGE_ONLY_SERIES)
        hour1_missing |= age_missing

        urpd_error: BrkError | None = None
        try:
            urpd = self._urpd(at)
        except BrkError as exc:
            # The series are fresh whatever happens to URPD, so still derive from them, with a
            # recent stored snapshot if there is one. The run is then recorded as failed.
            urpd_error = exc
            urpd = self._recent_urpd(at)
        # F does not depend on D, so its snapshots are fetched whatever happened above.
        self._urpd_closed(at)

        done = clock()
        not_final = self._derive(urpd, done, hour1_missing, hour1_done, closed=closed)
        # The age cohorts read the first stage's series too: they are derived only when both stages
        # fetched, and are as of the first, like the pressure.
        self._derive_age_cohorts(hour1_missing, None if age_error else hour1_done)
        absent = [name for name in DAY1_FETCH if name in missing]
        absent_hour1 = [
            name
            for name in (*HOUR1_SERIES, *SELL_SIDE_SERIES, *AGE_ONLY_SERIES)
            if name in hour1_missing
        ]
        # `price_close` is in both indexes, so day1 reasons keep their form and hour1 ones add it.
        reasons = [f"series_missing:{name}" for name in absent]
        reasons += [f"series_missing:hour1:{name}" for name in absent_hour1]
        if urpd is None:
            reasons.append("urpd_missing")
        if not_final:
            reasons.append("urpd_not_final")
        self.store.set_state(
            missing_series=json.dumps(
                [f"day1:{name}" for name in absent] + [f"hour1:{name}" for name in absent_hour1]
            ),
            reasons=json.dumps(reasons),
        )
        errors = [error for error in (hour1_error, age_error, urpd_error) if error is not None]
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

        The rest of URPD_SET is fetched for the same day D, then D's age snapshots (`_flow_set`),
        and so are the past snapshots the cost-basis grid needs while they are missing or not
        final. All are stored, and the days no longer needed are pruned, also when a same-day
        request fails the stage. Returns D as `_flow_set` leaves it.
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
        past = [urpd.date - timedelta(days=n) for n in PAST_DAYS]
        # Under O1 the closed days are kept too: F and its grid are read from them.
        keep = {today, today - timedelta(days=1), urpd.date, *past, *self._closed_days(at)}
        fetched: dict[tuple[str, str], Urpd | None] = {}
        try:
            for cohort, agg in URPD_SET[1:]:
                # A failure here fails the stage, like one of `all lin500`.
                fetched[(cohort, agg)] = self._save_urpd(cohort, urpd.date, agg, at)
            # So does one fetching `all lin500` again in `_flow_set`.
            urpd = self._flow_set(urpd, fetched, at)
        except BrkError:
            # A lasting outage of one endpoint must not keep the table growing.
            self.store.prune_urpd(keep)
            raise
        for day in past:
            # Fetched before the day closed, plus the grace day1 rows get, it may have been forming.
            final = final_from(day)
            for cohort, agg in URPD_SET:
                fetched_at = self.store.urpd_fetched_at(cohort, day, agg)
                if fetched_at is not None and fetched_at >= final:
                    continue
                try:
                    self._save_urpd(cohort, day, agg, at)
                except BrkError as exc:
                    # Past snapshots only widen the grid: the derived reasons tell what is missing.
                    logger.warning("onchain_urpd_past_failed code=%s", exc.code)
        self.store.prune_urpd(keep)
        return urpd

    def _closed_days(self, at: datetime) -> list[date]:
        """The closed days under O1, whose snapshots F and its grid are read from; else none."""
        return closed_days(at) if "O1" in rules_for_view("levels", self.rules) else []

    def _urpd_closed(self, at: datetime) -> None:
        """Fetch the snapshots of the closed days that are missing or not final.

        A failure ends this step without failing the stage: F stays with what is stored, and the
        next refresh fetches the rest. A snapshot BRK does not have is skipped.
        """
        try:
            for day in self._closed_days(at):
                for cohort, agg in self.store.urpd_not_final(day):
                    self._save_urpd(cohort, day, agg, at)
        except BrkError as exc:
            logger.warning("onchain_urpd_closed_failed code=%s", exc.code)

    def _flow_set(
        self, urpd: Urpd, fetched: Mapping[tuple[str, str], Urpd | None], at: datetime
    ) -> Urpd:
        """Fetch D's age snapshots, and the cost flow's set of D once more when it is not one
        snapshot; return the D to use.

        `fetched` holds what this round got of URPD_SET[1:], None where BRK had nothing. The cost
        flow reads D's lin500 and lin200 grids and its age snapshots, and all must share D's close:
        BRK may have moved on to a new block while they were fetched. A failure among the age
        snapshots, or among those fetched again, ends them without failing the stage.
        """
        day = urpd.date
        grids = [
            (cohort, agg)
            for agg, _ in GRIDS
            for cohort in COHORTS
            if (cohort, agg) != (URPD_COHORT, URPD_AGG)
        ]
        found: list[Urpd | None] = []
        for cohort, agg in grids:
            snapshot = fetched[(cohort, agg)]
            # One BRK did not have this time: the stored one is what the cost flow would read.
            found.append(snapshot if snapshot is not None else self.store.urpd(cohort, day, agg))
        found += self._save_ages(day, at)
        if all(snapshot.close == urpd.close for snapshot in found if snapshot is not None):
            return urpd
        # Once more, and only once: what still differs is left out when the cost flow is derived.
        # When BRK no longer has D, the first one stays.
        again = self.client.urpd(URPD_COHORT, day, URPD_AGG)
        if again is not None:
            self.store.save_urpd(again, at)
            urpd = again
        try:
            for cohort, agg in grids:
                self._save_urpd(cohort, day, agg, at)
        except BrkError as exc:
            logger.warning("onchain_urpd_age_failed code=%s", exc.code)
        else:
            self._save_ages(day, at)
        return urpd

    def _save_ages(self, day: date, at: datetime) -> list[Urpd]:
        """Fetch and store the age snapshots of `day`; return those BRK had.

        A failure ends them without failing the stage: the cost flow then names what is missing.
        """
        found: list[Urpd] = []
        try:
            for cohort in AGE_URPD_COHORTS:
                urpd = self._save_urpd(cohort, day, URPD_AGG, at)
                if urpd is not None:
                    found.append(urpd)
        except BrkError as exc:
            logger.warning("onchain_urpd_age_failed code=%s", exc.code)
        return found

    def _save_urpd(self, cohort: str, day: date, agg: str, at: datetime) -> Urpd | None:
        urpd = self.client.urpd(cohort, day, agg)
        if urpd is not None:
            self.store.save_urpd(urpd, at)
        return urpd

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
        *,
        closed: date,
    ) -> bool:
        """Derive every view; stamp the pressure `hour1_at`, None when the hour1 stage failed.

        `urpd` is D, the newest `all lin500` snapshot. `closed` is the latest closed day: under O1
        nothing dated after it is read, and the levels and the cost basis use the snapshots of F,
        the first of the closed day and the day before whose URPD_SET is all stored and final.
        Returns True when O1 found no such day.
        """
        rows = {name: self.store.read_series(name, "day1") for name in DAY1_SERIES}

        w, sth, tmm, close = (
            {moment.date(): value for moment, value in rows[name]} for name in CYCLE_SERIES
        )
        days = sorted(w.keys() | sth.keys() | tmm.keys() | close.keys())
        # Only the rules the payload records are applied.
        cycle_rules = rules_for_view("cycle", self.rules)
        cycle = classify(
            [(day, w.get(day), sth.get(day), tmm.get(day), close.get(day)) for day in days],
            rules=frozenset(cycle_rules),
            closed_day=closed,
        )
        if cycle is None:
            self.store.clear_derived("cycle")
        else:
            cycle = cycle.model_copy(update={"rules": cycle_rules})
            self.store.save_derived("cycle", cycle.model_dump_json(), at)

        levels_rules = rules_for_view("levels", self.rules)
        # The snapshot the levels and the cost basis are read from: D, or F under O1.
        snapshot = urpd
        not_final = False
        if "O1" in levels_rules:
            candidates = (closed, closed - timedelta(days=1))
            final = self.store.final_urpd_day(candidates)
            not_final = final is None
            snapshot = None if final is None else self.store.urpd(URPD_COHORT, final, URPD_AGG)
            if final is None:
                for day in candidates:
                    # The snapshot kinds only, never a value.
                    kinds = ",".join(f"{c}:{a}" for c, a in self.store.urpd_not_final(day))
                    logger.warning("onchain_urpd_not_final day=%s kinds=%s", day, kinds)
        last = last_complete(rows, rules=frozenset(levels_rules), through=closed)
        # The newest complete point whatever the closed day: how fresh the levels are follows it.
        latest = last_complete(rows, rules=frozenset(levels_rules), through=None)
        if last is None or latest is None:
            self.store.clear_derived("levels")
            self.store.clear_derived("costbasis")
        else:
            as_of, values = last
            latest_day = latest[0].date()
            lines = model_lines(values, snapshot, rules=frozenset(levels_rules))
            levels = {
                "as_of": as_of.isoformat(),
                "urpd_date": snapshot.date.isoformat() if snapshot else None,
                "onchain_close": snapshot.close if snapshot else None,
                "lines": [line.model_dump() for line in lines],
                "rules": levels_rules,
                "latest_day": latest_day.isoformat(),
                "latest_urpd_day": urpd.date.isoformat() if urpd else None,
            }
            self.store.save_derived("levels", json.dumps(levels, allow_nan=False), at)
            costbasis_rules = frozenset(rules_for_view("costbasis", self.rules))
            if snapshot is None or len(lines) < len(line_order(costbasis_rules)):
                # Without every line the bands would quietly change, so there is none.
                self.store.clear_derived("costbasis")
            else:
                try:
                    payload = self._cost_basis(
                        snapshot.date,
                        as_of.date(),
                        lines,
                        latest_day=min(latest_day, urpd.date) if urpd else None,
                    ).model_dump_json()
                except Exception:
                    # The pressure and the run's state must not depend on the cost basis. Never
                    # log the exception: it may carry values. A fixed code is enough here.
                    logger.warning("onchain_derive_failed code=costbasis_failed")
                    self.store.clear_derived("costbasis")
                else:
                    self.store.save_derived("costbasis", payload, at)
        self._derive_cost_flow(urpd, at)
        self._derive_pressure(hour1_missing, hour1_at)
        self._derive_sell_side(hour1_missing, hour1_at)
        return not_final

    def _derive_cost_flow(self, urpd: Urpd | None, at: datetime) -> None:
        """Derive the inputs of Charts 3 and 4 for D = `urpd` and stamp them `at`."""
        result = None
        if urpd is not None:
            try:
                result = self._cost_flow(urpd.date)
            except Exception:
                # The other views and the run's state must not depend on the cost flow. Never log
                # the exception: it may carry values. A fixed code is enough here.
                logger.warning("onchain_derive_failed code=costflow_failed")
        if result is None:
            self.store.clear_derived("costflow")
        else:
            self.store.save_derived("costflow", result.model_dump_json(), at)

    def _derive_pressure(self, hour1_missing: set[str], hour1_at: datetime | None) -> None:
        """Derive the seller pressure and stamp it `hour1_at`.

        With `hour1_at` None the stored pressure is kept as it is, with the time it was computed.
        """
        if hour1_at is None:
            # The stored pressure stays, with the time it was computed, until hour1 is fetched.
            return
        pressure = None
        # Only the rules the payload records are applied.
        rules = rules_for_view("pressure", self.rules)
        applied = frozenset(rules)
        if not hour1_missing.intersection(HOUR1_SERIES):
            # An absent series is not a zero: with any of them gone there is no pressure at all.
            # Under O1 a row has closed once its hour was over when hour1 was read.
            pressure = seller_pressure(
                {
                    name: self.store.read_series(name, "hour1", tail=lookback(applied) + 1)
                    for name in HOUR1_SERIES
                },
                rules=applied,
                computed_at=hour1_at,
            )
        if pressure is None:
            self.store.clear_derived("pressure")
        else:
            pressure = pressure.model_copy(update={"rules": rules})
            self.store.save_derived("pressure", pressure.model_dump_json(), hour1_at)

    def _derive_sell_side(self, hour1_missing: set[str], hour1_at: datetime | None) -> None:
        """Derive the sell-side legs and stamp them `hour1_at`, like the seller pressure."""
        if hour1_at is None:
            return
        result = None
        if not hour1_missing.intersection(INPUTS):
            try:
                result = sell_side(
                    {
                        name: self.store.read_series(name, "hour1", tail=V1_LOOKBACK + 1)
                        for name in INPUTS
                    }
                )
            except Exception:
                # The other views and the run's state must not depend on the sell side. Never
                # log the exception: it may carry values. A fixed code is enough here.
                logger.warning("onchain_derive_failed code=sellside_failed")
        if result is None:
            self.store.clear_derived("sellside")
        else:
            self.store.save_derived("sellside", result.model_dump_json(), hour1_at)

    def _derive_age_cohorts(self, hour1_missing: set[str], at: datetime | None) -> None:
        """Derive the age-cohort bands and stamp them `at`.

        With `at` None the stored bands are kept as they are, unless one of their series is known
        to be missing: an absent series is not a zero, so there are then no bands at all.
        """
        missing = hour1_missing.intersection(AGE_INPUTS)
        if at is None and not missing:
            return
        result = None
        if not missing:
            try:
                result = age_cohorts(
                    {
                        name: self.store.read_series(name, "hour1", tail=V1_LOOKBACK + 1)
                        for name in AGE_INPUTS
                    }
                )
            except Exception:
                # The other views and the run's state must not depend on the age cohorts. Never
                # log the exception: it may carry values. A fixed code is enough here.
                logger.warning("onchain_derive_failed code=agecohorts_failed")
        if result is None or at is None:
            self.store.clear_derived("agecohorts")
        else:
            self.store.save_derived("agecohorts", result.model_dump_json(), at)

    def _cost_basis(
        self, day: date, lines_as_of: date, lines: list[ModelLine], *, latest_day: date | None
    ) -> StoredCostBasis:
        """Every bucket width whose snapshots of `day` are all stored; the reasons say what is not.

        Only the store is read, so what was fetched in this run does not matter.
        """
        rules = rules_for_view("costbasis", self.rules)
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
            result = cost_basis(today, found, bucket, lines, rules=frozenset(rules))
            if result is None:
                # Also O5's ±50% domain without a row: unreachable with contiguous URPD buckets.
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
            rules=rules,
            latest_day=latest_day,
        )

    def _cost_flow(self, day: date) -> StoredCostFlow | None:
        """The inputs of Charts 3 and 4 for D = `day`, read from the store alone.

        A then day's snapshot counts once that day had closed when it was fetched; `final_from`
        only decides when it is fetched again. One fetched before GRACE_END may lack blocks BRK
        adds late, until that refetch.
        """
        snapshot_at = self.store.urpd_fetched_at(URPD_COHORT, day, URPD_AGG)
        if snapshot_at is None:
            return None
        snapshots: dict[tuple[str, str, date], Urpd] = {}
        for agg, _ in GRIDS:
            for cohort in COHORTS:
                now = self.store.urpd(cohort, day, agg)
                if now is not None:
                    snapshots[(cohort, agg, day)] = now
                for n in WINDOWS.values():
                    then = day - timedelta(days=n)
                    fetched_at = self.store.urpd_fetched_at(cohort, then, agg)
                    if fetched_at is None or fetched_at < day_start(then + timedelta(days=1)):
                        continue
                    past = self.store.urpd(cohort, then, agg)
                    if past is not None:
                        snapshots[(cohort, agg, then)] = past
        ages = {
            cohort: urpd
            for cohort in AGE_URPD_COHORTS
            if (urpd := self.store.urpd(cohort, day, URPD_AGG)) is not None
        }
        high, low = (self.store.read_series(name, "day1") for name in AGE_FLOOR_SERIES)
        return cost_flow(day, snapshots, ages, high, low, snapshot_at=snapshot_at)

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
