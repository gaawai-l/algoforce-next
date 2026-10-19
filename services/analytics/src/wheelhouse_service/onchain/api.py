"""Read-only on-chain endpoints. They only read the private store: no network, no computation."""

import json
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI
from pydantic import AwareDatetime

from ..market import Model
from ..rules import Rule, Rules, View, rules_for_view
from .agecohorts import INPUTS as AGE_INPUTS
from .agecohorts import AgeBands, AgeCohorts
from .brk import DAY1_SERIES, HOUR1_SERIES, BrkClient
from .costbasis import StoredCostBasis
from .cycle import Cycle
from .levels import ModelLine, line_series
from .models import (
    AgeCohortsView,
    CostBasisView,
    CycleView,
    DatasetStatus,
    HourState,
    LevelsView,
    OnchainStatus,
    SellerPressureView,
    SellSideView,
    day1_state,
    day_start,
    hour1_state,
)
from .pressure import HOUR, SHOWN_HOURS, Pressure
from .sellside import INPUTS, SellSide, SellSideLegs
from .store import OnchainStore
from .sync import CYCLE_SERIES, OnchainSync

# `price_close` is in both indexes: the daily code stays as it was, the hourly one says `hour1`.
DAY1_REASONS = (*(f"series_missing:{name}" for name in DAY1_SERIES), "brk_unavailable")
URPD_REASONS = ("urpd_missing", "urpd_not_final", "brk_unavailable")
PRESSURE_REASONS = (*(f"series_missing:hour1:{name}" for name in HOUR1_SERIES), "brk_unavailable")
SELL_SIDE_REASONS = (*(f"series_missing:hour1:{name}" for name in INPUTS), "brk_unavailable")
AGE_REASONS = (*(f"series_missing:hour1:{name}" for name in AGE_INPUTS), "brk_unavailable")
CYCLE_REASONS = (*(f"series_missing:{name}" for name in CYCLE_SERIES), "brk_unavailable")


def levels_reasons(rules: Rules) -> tuple[str, ...]:
    """The shared reasons that concern the levels derived under `rules`: O5 adds a line series."""
    return (
        *(f"series_missing:{name}" for name in line_series(rules).values()),
        "urpd_missing",
        "urpd_not_final",
        "brk_unavailable",
    )


def cost_basis_shared(rules: Rules) -> tuple[str, ...]:
    """The shared reasons that concern the cost basis derived under `rules`.

    The snapshot-level codes are stored with the result, not shared: see `StoredCostBasis.reasons`.
    """
    return (
        "urpd_missing",
        "urpd_not_final",
        *(f"series_missing:{name}" for name in line_series(rules).values()),
        "brk_unavailable",
    )


class StoredLevels(Model):
    """The `levels` payload that the sync worker derives and stores."""

    as_of: AwareDatetime
    urpd_date: date | None
    onchain_close: float | None
    lines: list[ModelLine]
    # The rules it was derived under; payloads stored before rules existed read as none.
    rules: list[Rule] = []
    # The newest day with every series line, and D, the newest snapshot, whatever the rules: how
    # fresh the data is follows them, while `as_of` and `urpd_date` are the days the readings are
    # of. Payloads stored before they existed read as None.
    latest_day: date | None = None
    latest_urpd_day: date | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def forming_at(row: datetime, now: datetime) -> datetime | None:
    """The time of the latest row while it is today's, and therefore still in progress."""
    return row if row.astimezone(UTC).date() == now.astimezone(UTC).date() else None


def stored_reasons(state: dict[str, str | None]) -> list[str]:
    reasons: list[str] = json.loads(state["reasons"] or "[]")
    return reasons


def only(reasons: Iterable[str], relevant: Iterable[str]) -> list[str]:
    """The reasons that concern one module, in their stored order."""
    keep = set(relevant)
    return [reason for reason in reasons if reason in keep]


def instant(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def create_router(
    path: Path,
    client: BrkClient | None = None,
    *,
    rules: Rules,
    start_worker: bool = True,
    clock: Callable[[], datetime] = utc_now,
) -> APIRouter:
    store: OnchainStore | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal store
        store = OnchainStore(path)
        worker = OnchainSync(store, client or BrkClient(), rules=rules) if start_worker else None
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    router = APIRouter(prefix="/api/wheelhouse/v1/onchain", tags=["onchain"], lifespan=lifespan)

    def db() -> OnchainStore:
        assert store is not None, "On-chain lifespan has not started"
        return store

    # Without a payload the views' reasons follow the configured rules, which the worker derives
    # under; a payload's follow the rules it was derived under.
    levels_shared = levels_reasons(frozenset(rules_for_view("levels", rules)))
    cost_shared = cost_basis_shared(frozenset(rules_for_view("costbasis", rules)))

    def pending(view: View, stored: list[Rule]) -> bool:
        """Whether a payload was derived under other rules than the configured ones, which the
        worker derives it under. A process without the worker never derives it again."""
        return start_worker and set(stored) != set(rules_for_view(view, rules))

    def stored_cycle() -> Cycle | None:
        derived = db().derived("cycle")
        return None if derived is None else Cycle.model_validate_json(derived[0])

    def stored_levels() -> StoredLevels | None:
        derived = db().derived("levels")
        return None if derived is None else StoredLevels.model_validate_json(derived[0])

    def stored_cost_basis() -> tuple[StoredCostBasis, datetime] | None:
        derived = db().derived("costbasis")
        if derived is None:
            return None
        return StoredCostBasis.model_validate_json(derived[0]), derived[1]

    def stored_pressure() -> tuple[Pressure, datetime] | None:
        derived = db().derived("pressure")
        return None if derived is None else (Pressure.model_validate_json(derived[0]), derived[1])

    def stored_sell_side() -> tuple[SellSide, datetime] | None:
        derived = db().derived("sellside")
        return None if derived is None else (SellSide.model_validate_json(derived[0]), derived[1])

    def stored_age_cohorts() -> tuple[AgeCohorts, datetime] | None:
        derived = db().derived("agecohorts")
        if derived is None:
            return None
        return AgeCohorts.model_validate_json(derived[0]), derived[1]

    @router.get("/status", response_model=OnchainStatus)
    def status() -> OnchainStatus:
        now = clock()
        state = db().state()
        reasons = stored_reasons(state)
        current_cycle = stored_cycle()
        current_levels = stored_levels()
        current_cost_basis = stored_cost_basis()
        current_pressure = stored_pressure()

        # The newest day the data has, rather than a closed day the reading may be of.
        days = [current_cycle.latest_day or current_cycle.as_of] if current_cycle else []
        if current_levels:
            days.append(current_levels.latest_day or current_levels.as_of.astimezone(UTC).date())
        urpd_date = (
            (current_levels.latest_urpd_day or current_levels.urpd_date) if current_levels else None
        )

        def dataset(
            name: Literal["day1", "urpd", "hour1"],
            data_state: HourState,
            last_at: datetime | None,
            shown: list[str],
            fallback: str,
        ) -> DatasetStatus:
            return DatasetStatus(
                name=name,
                data_state=data_state,
                last_at=last_at,
                # An absent dataset always says why, even before any sync has recorded a reason.
                reasons=shown or ([fallback] if last_at is None else []),
            )

        day1_last = max(days, default=None)
        hour1_last = current_pressure[0].last_at if current_pressure else None
        # Freshness follows the newest hour BRK has, which an hour without a block can leave out
        # of the charts; `last_at` still names the last row they show.
        hour1_latest = current_pressure[0].latest_at if current_pressure else None

        return OnchainStatus(
            brk_version=state["brk_version"],
            refreshing=state["refreshing"] == "true",
            last_success_at=instant(state["last_success_at"]),
            last_error=state["last_error"],
            datasets=[
                dataset(
                    "day1",
                    day1_state(day1_last, now),
                    None if day1_last is None else day_start(day1_last),
                    only(reasons, DAY1_REASONS),
                    "brk_unavailable",
                ),
                dataset(
                    "urpd",
                    day1_state(urpd_date, now),
                    None if urpd_date is None else day_start(urpd_date),
                    only(reasons, URPD_REASONS)
                    + (current_cost_basis[0].reasons if current_cost_basis else []),
                    "urpd_missing",
                ),
                dataset(
                    "hour1",
                    hour1_state(hour1_latest or hour1_last, now),
                    hour1_last,
                    only(reasons, PRESSURE_REASONS),
                    "brk_unavailable",
                ),
            ],
        )

    @router.get("/cycle", response_model=CycleView)
    def cycle() -> CycleView:
        now = clock()
        state = db().state()
        reasons = only(stored_reasons(state), CYCLE_REASONS)
        refreshing = state["refreshing"] == "true"
        result = stored_cycle()
        if result is None:
            return CycleView(
                data_state="unavailable",
                reasons=reasons or ["brk_unavailable"],
                refreshing=refreshing,
                forming_at=None,
                as_of=None,
                state=None,
                since=None,
                day=None,
                components=[],
                episodes=[],
                changes=None,
                brk_version=state["brk_version"],
                rules=[],
                rules_pending=False,
            )
        return CycleView(
            **result.model_dump(exclude={"latest_day"}),
            # Fresh while the data is, also when the reading is of an earlier, closed day.
            data_state=day1_state(result.latest_day or result.as_of, now),
            reasons=reasons,
            refreshing=refreshing,
            # Under O1 the reading is of a closed day, so nothing in it is forming.
            forming_at=None if "O1" in result.rules else forming_at(day_start(result.as_of), now),
            brk_version=state["brk_version"],
            rules_pending=pending("cycle", result.rules),
        )

    @router.get("/levels", response_model=LevelsView)
    def levels() -> LevelsView:
        now = clock()
        state = db().state()
        result = stored_levels()
        shared = levels_shared if result is None else levels_reasons(frozenset(result.rules))
        reasons = only(stored_reasons(state), shared)
        refreshing = state["refreshing"] == "true"
        if result is None:
            return LevelsView(
                data_state="unavailable",
                reasons=reasons or ["brk_unavailable"],
                refreshing=refreshing,
                forming_at=None,
                as_of=None,
                urpd_date=None,
                onchain_close=None,
                lines=[],
                brk_version=state["brk_version"],
                rules=[],
                rules_pending=False,
            )
        return LevelsView(
            **result.model_dump(exclude={"latest_day", "latest_urpd_day"}),
            # Fresh while the data is, also when the reading is of an earlier, closed day.
            data_state=day1_state(result.latest_day or result.as_of.astimezone(UTC).date(), now),
            reasons=reasons,
            refreshing=refreshing,
            forming_at=forming_at(result.as_of, now),
            brk_version=state["brk_version"],
            rules_pending=pending("levels", result.rules),
        )

    @router.get("/cost-basis", response_model=CostBasisView)
    def cost_basis() -> CostBasisView:
        now = clock()
        state = db().state()
        stored = stored_cost_basis()
        shared = cost_shared if stored is None else cost_basis_shared(frozenset(stored[0].rules))
        reasons = only(stored_reasons(state), shared)
        refreshing = state["refreshing"] == "true"
        if stored is None:
            return CostBasisView(
                data_state="unavailable",
                reasons=reasons or ["brk_unavailable"],
                refreshing=refreshing,
                forming_at=None,
                urpd_date=None,
                lines_as_of=None,
                snapshot_at=None,
                computed_at=None,
                buckets=[],
                brk_version=state["brk_version"],
                rules=[],
                rules_pending=False,
            )
        result, computed_at = stored
        # A day is still forming when the data for it was fetched before it ended.
        forming = [
            day
            for day, fetched_at in (
                (result.urpd_date, result.snapshot_at),
                (result.lines_as_of, computed_at),
            )
            if fetched_at < day_start(day + timedelta(days=1))
        ]
        return CostBasisView(
            **result.model_dump(exclude={"reasons", "latest_day"}),
            data_state=day1_state(
                result.latest_day or min(result.urpd_date, result.lines_as_of), now
            ),
            reasons=[*reasons, *result.reasons],
            refreshing=refreshing,
            forming_at=day_start(max(forming)) if forming else None,
            computed_at=computed_at,
            brk_version=state["brk_version"],
            rules_pending=pending("costbasis", result.rules),
        )

    @router.get("/seller-pressure", response_model=SellerPressureView)
    def seller_pressure() -> SellerPressureView:
        now = clock()
        state = db().state()
        reasons = only(stored_reasons(state), PRESSURE_REASONS)
        refreshing = state["refreshing"] == "true"
        stored = stored_pressure()
        if stored is None:
            return SellerPressureView(
                data_state="unavailable",
                reasons=reasons or ["brk_unavailable"],
                refreshing=refreshing,
                forming_at=None,
                last_at=None,
                loss=[],
                share=[],
                supply=[],
                price=[],
                loss_levels=None,
                share_levels=None,
                supply_levels=None,
                xgap=None,
                qc=[],
                brk_version=state["brk_version"],
                rules=[],
                rules_pending=False,
                closed_at=None,
                loss_run=None,
                share_run=None,
                supply_run=None,
            )
        result, computed_at = stored
        return SellerPressureView(
            # The newest hour BRK has, even when it was dropped from the charts.
            data_state=hour1_state(result.latest_at or result.last_at, now),
            reasons=reasons,
            refreshing=refreshing,
            # The last row was still open when this was computed, however long ago that was.
            forming_at=result.last_at if computed_at < result.last_at + HOUR else None,
            last_at=result.last_at,
            loss=result.loss[-SHOWN_HOURS:],
            share=result.share[-SHOWN_HOURS:],
            supply=result.supply[-SHOWN_HOURS:],
            price=result.price[-SHOWN_HOURS:],
            loss_levels=result.loss_levels,
            share_levels=result.share_levels,
            supply_levels=result.supply_levels,
            xgap=result.xgap,
            qc=result.qc,
            brk_version=state["brk_version"],
            rules=result.rules,
            rules_pending=pending("pressure", result.rules),
            closed_at=result.closed_at,
            loss_run=result.loss_run,
            share_run=result.share_run,
            supply_run=result.supply_run,
        )

    @router.get("/sell-side", response_model=SellSideView)
    def sell_side() -> SellSideView:
        now = clock()
        state = db().state()
        reasons = only(stored_reasons(state), SELL_SIDE_REASONS)
        refreshing = state["refreshing"] == "true"
        stored = stored_sell_side()
        if stored is None:
            empty = SellSideLegs.model_validate({leg: [] for leg in SellSideLegs.model_fields})
            return SellSideView(
                data_state="unavailable",
                reasons=reasons or ["brk_unavailable"],
                refreshing=refreshing,
                forming_at=None,
                last_at=None,
                at=[],
                price=[],
                pnl=empty,
                volb=empty,
                volu=empty,
                xgap=None,
                qc=[],
                brk_version=state["brk_version"],
                rules=[],
                rules_pending=False,
            )
        result, computed_at = stored
        return SellSideView(
            data_state=hour1_state(result.latest_at, now),
            reasons=reasons,
            refreshing=refreshing,
            forming_at=result.last_at if computed_at < result.last_at + HOUR else None,
            last_at=result.last_at,
            at=result.at,
            price=result.price,
            pnl=result.pnl,
            volb=result.volb,
            volu=result.volu,
            xgap=result.xgap,
            qc=result.qc,
            brk_version=state["brk_version"],
            rules=result.rules,
            rules_pending=pending("sellside", result.rules),
        )

    @router.get("/age-cohorts", response_model=AgeCohortsView)
    def age_cohorts() -> AgeCohortsView:
        now = clock()
        state = db().state()
        reasons = only(stored_reasons(state), AGE_REASONS)
        refreshing = state["refreshing"] == "true"
        stored = stored_age_cohorts()
        if stored is None:
            empty = AgeBands(profit=[], loss=[])
            return AgeCohortsView(
                data_state="unavailable",
                reasons=reasons or ["brk_unavailable"],
                refreshing=refreshing,
                forming_at=None,
                last_at=None,
                at=[],
                price=[],
                pnl=empty,
                volb=empty,
                volu=empty,
                brk_version=state["brk_version"],
                rules=[],
                rules_pending=False,
            )
        result, computed_at = stored
        return AgeCohortsView(
            data_state=hour1_state(result.latest_at, now),
            reasons=reasons,
            refreshing=refreshing,
            forming_at=result.last_at if computed_at < result.last_at + HOUR else None,
            last_at=result.last_at,
            at=result.at,
            price=result.price,
            pnl=result.pnl,
            volb=result.volb,
            volu=result.volu,
            brk_version=state["brk_version"],
            rules=result.rules,
            rules_pending=pending("agecohorts", result.rules),
        )

    return router
