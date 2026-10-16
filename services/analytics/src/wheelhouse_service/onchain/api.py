"""Read-only on-chain endpoints. They only read the private store: no network, no computation."""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI
from pydantic import AwareDatetime

from ..market import Model
from .brk import BrkClient
from .cycle import Cycle
from .levels import ModelLine
from .models import CycleView, DatasetStatus, LevelsView, OnchainStatus, day1_state
from .store import OnchainStore
from .sync import OnchainSync

URPD_REASONS = ("urpd_missing", "brk_unavailable")


class StoredLevels(Model):
    """The `levels` payload that the sync worker derives and stores."""

    as_of: AwareDatetime
    urpd_date: date | None
    onchain_close: float | None
    lines: list[ModelLine]


def utc_now() -> datetime:
    return datetime.now(UTC)


def day_start(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


def forming_at(row: datetime, now: datetime) -> datetime | None:
    """The time of the latest row while it is today's, and therefore still in progress."""
    return row if row.astimezone(UTC).date() == now.astimezone(UTC).date() else None


def stored_reasons(state: dict[str, str | None]) -> list[str]:
    reasons: list[str] = json.loads(state["reasons"] or "[]")
    return reasons


def instant(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def create_router(
    path: Path,
    client: BrkClient | None = None,
    *,
    start_worker: bool = True,
    clock: Callable[[], datetime] = utc_now,
) -> APIRouter:
    store: OnchainStore | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal store
        store = OnchainStore(path)
        worker = OnchainSync(store, client or BrkClient()) if start_worker else None
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    router = APIRouter(prefix="/api/wheelhouse/v1/onchain", tags=["onchain"], lifespan=lifespan)

    def db() -> OnchainStore:
        assert store is not None, "On-chain lifespan has not started"
        return store

    def stored_cycle() -> Cycle | None:
        derived = db().derived("cycle")
        return None if derived is None else Cycle.model_validate_json(derived[0])

    def stored_levels() -> StoredLevels | None:
        derived = db().derived("levels")
        return None if derived is None else StoredLevels.model_validate_json(derived[0])

    @router.get("/status", response_model=OnchainStatus)
    def status() -> OnchainStatus:
        now = clock()
        state = db().state()
        reasons = stored_reasons(state)
        current_cycle = stored_cycle()
        current_levels = stored_levels()

        days = [current_cycle.as_of] if current_cycle else []
        if current_levels:
            days.append(current_levels.as_of.astimezone(UTC).date())
        urpd_date = current_levels.urpd_date if current_levels else None

        def dataset(
            name: Literal["day1", "urpd"], last: date | None, shown: list[str], fallback: str
        ) -> DatasetStatus:
            return DatasetStatus(
                name=name,
                data_state=day1_state(last, now),
                last_at=None if last is None else day_start(last),
                # An absent dataset always says why, even before any sync has recorded a reason.
                reasons=shown or ([fallback] if last is None else []),
            )

        return OnchainStatus(
            brk_version=state["brk_version"],
            refreshing=state["refreshing"] == "true",
            last_success_at=instant(state["last_success_at"]),
            last_error=state["last_error"],
            datasets=[
                dataset(
                    "day1",
                    max(days, default=None),
                    [reason for reason in reasons if reason != "urpd_missing"],
                    "brk_unavailable",
                ),
                dataset(
                    "urpd",
                    urpd_date,
                    [reason for reason in reasons if reason in URPD_REASONS],
                    "urpd_missing",
                ),
            ],
        )

    @router.get("/cycle", response_model=CycleView)
    def cycle() -> CycleView:
        now = clock()
        state = db().state()
        reasons = stored_reasons(state)
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
                changes=0,
                brk_version=state["brk_version"],
            )
        return CycleView(
            **result.model_dump(),
            data_state=day1_state(result.as_of, now),
            reasons=reasons,
            refreshing=refreshing,
            forming_at=forming_at(day_start(result.as_of), now),
            brk_version=state["brk_version"],
        )

    @router.get("/levels", response_model=LevelsView)
    def levels() -> LevelsView:
        now = clock()
        state = db().state()
        reasons = stored_reasons(state)
        refreshing = state["refreshing"] == "true"
        result = stored_levels()
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
            )
        return LevelsView(
            **result.model_dump(),
            data_state=day1_state(result.as_of.astimezone(UTC).date(), now),
            reasons=reasons,
            refreshing=refreshing,
            forming_at=forming_at(result.as_of, now),
            brk_version=state["brk_version"],
        )

    return router
