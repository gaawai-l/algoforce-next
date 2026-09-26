"""Read-only brokerage queries and local analytical annotations; no trading endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query
from pydantic import AwareDatetime, Field

from ..market import Model
from .broker import BrokerUnavailable, MoomooReader
from .demo import load_demo
from .ledger import calculate_cycle
from .models import (
    Amount,
    Cycle,
    CycleResult,
    FxRate,
    Instrument,
    LedgerEvent,
    PortfolioCapture,
    Quote,
    RiskResult,
    Source,
    SyncRequest,
)
from .risk import calculate_risk
from .store import PortfolioStore
from .sync import BrokerSync, SyncJob


class NewCycle(Model):
    source: Source
    account_id: str = Field(min_length=1, max_length=80)
    underlying: str = Field(min_length=1, max_length=80)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=120)


class Annotation(Model):
    source: Source
    account_id: str = Field(min_length=1, max_length=80)
    author: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    instrument: Instrument | None = None
    quote: Quote | None = None
    fx: FxRate | None = None


class FeeCorrection(Model):
    event_id: str
    fee: Amount
    author: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)


class FillReconciliation(Model):
    event_id: str
    record_id: str
    at: AwareDatetime
    fee: Amount | None = None
    author: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)


class PortfolioWorkspace(Model):
    capture: PortfolioCapture | None
    cycles: list[CycleResult]
    risk: RiskResult | None
    records: list[dict[str, Any]]
    audit: list[dict[str, Any]]
    state: Literal["available", "stale", "unavailable", "simulated"]
    issues: list[str]


def create_router(
    path: Path, reader: MoomooReader | None = None, *, start_worker: bool = True
) -> APIRouter:
    collector = reader or MoomooReader()
    manager: BrokerSync | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal manager
        manager = BrokerSync(PortfolioStore(path), collector)
        if start_worker:
            manager.start()
        yield
        manager.stop()

    router = APIRouter(prefix="/api/wheelhouse/v1/portfolio", tags=["portfolio"], lifespan=lifespan)

    def syncer() -> BrokerSync:
        assert manager is not None, "Portfolio lifespan has not started"
        return manager

    def store() -> PortfolioStore:
        return PortfolioStore(path)

    @router.get("/connection")
    def connection() -> dict[str, Any]:
        return collector.status()

    @router.get("/accounts")
    def accounts() -> list[dict[str, Any]]:
        return store().accounts()

    @router.post("/discover")
    def discover() -> list[dict[str, Any]]:
        try:
            return collector.accounts()
        except BrokerUnavailable as exc:
            raise HTTPException(
                503, "OpenD unavailable; start and sign in through official OpenD"
            ) from exc

    @router.post("/sync", response_model=SyncJob, status_code=202)
    def sync(
        request: SyncRequest, idempotency_key: str = Header(min_length=1, max_length=128)
    ) -> SyncJob:
        readiness = collector.status()
        if not readiness["gateway_reachable"] or not readiness["sdk_installed"]:
            raise HTTPException(503, "OpenD unavailable; start and sign in through official OpenD")
        return syncer().submit(request, idempotency_key, now=datetime.now(UTC))

    @router.get("/sync-jobs/{job_id}", response_model=SyncJob)
    def sync_job(job_id: str) -> SyncJob:
        return syncer().job(job_id)

    @router.get("/sync-status", response_model=SyncJob | None)
    def sync_status(account_id: str = Query(pattern=r"^[0-9]+$")) -> SyncJob | None:
        return syncer().latest(account_id)

    @router.post("/demo")
    def demo() -> dict[str, str]:
        load_demo(store())
        return {"source": "demo", "account_id": "wheelhouse-demo"}

    @router.get("/workspace", response_model=PortfolioWorkspace)
    def workspace(
        source: Source, account_id: str = Query(min_length=1, max_length=80)
    ) -> PortfolioWorkspace:
        persistence = store()
        capture = persistence.capture(source, account_id)
        now = datetime.now(UTC)
        stale = bool(
            capture
            and source != "demo"
            and (now - (capture.snapshot_observed_at or capture.captured_at)).total_seconds() > 900
        )
        marks = (
            {
                p.code: p.mark
                for p in capture.positions
                if p.mark is not None
                and (source == "demo" or 0 <= (now - p.observed_at).total_seconds() <= 900)
            }
            if capture and not stale
            else {}
        )
        results = [
            calculate_cycle(cycle, persistence.events(cycle.cycle_id), marks=marks)
            for cycle in persistence.cycles(source, account_id)
        ]
        risk = (
            calculate_risk(capture, at=capture.captured_at if source == "demo" else now)
            if capture
            else None
        )
        issues = (
            list(capture.errors.values())
            if capture
            else ["No account capture; connect OpenD or explicitly load demo"]
        )
        if capture:
            from decimal import Decimal

            accounted: dict[str, Decimal] = {}
            for result in results:
                for lot in result.lots:
                    accounted[lot.code] = accounted.get(lot.code, Decimal(0)) + Decimal(
                        lot.quantity
                    )
            actual = {p.code: Decimal(p.quantity) for p in capture.positions}
            for code in set(accounted) | set(actual):
                if accounted.get(code, Decimal(0)) != actual.get(code, Decimal(0)):
                    issues.append(
                        f"Cycle lots do not reconcile to snapshot for {code}; "
                        "unassigned positions or missing history"
                    )
        if stale:
            issues.append("Broker snapshot is stale; refresh before relying on current exposure")
        return PortfolioWorkspace(
            capture=capture,
            cycles=results,
            risk=risk,
            records=persistence.records(source, account_id),
            audit=persistence.audit(source, account_id),
            state="simulated"
            if capture and source == "demo"
            else "stale"
            if stale
            else "available"
            if capture
            else "unavailable",
            issues=issues,
        )

    @router.post("/cycles", response_model=Cycle)
    def cycle(request: NewCycle) -> Cycle:
        if store().capture(request.source, request.account_id) is None:
            raise HTTPException(409, "Import an account capture first")
        return store().create_cycle(
            Cycle(cycle_id=uuid4().hex, created_at=datetime.now(UTC), **request.model_dump())
        )

    @router.post("/events", response_model=CycleResult)
    def event(request: LedgerEvent) -> CycleResult:
        if request.at > datetime.now(UTC):
            raise HTTPException(422, "Event cannot be in the future")
        try:
            return store().append_event(request)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/annotations")
    def annotation(request: Annotation) -> dict[str, str]:
        values = [
            (kind, getattr(request, kind))
            for kind in ("instrument", "quote", "fx")
            if getattr(request, kind) is not None
        ]
        if len(values) != 1:
            raise HTTPException(422, "Provide exactly one metadata or quote annotation")
        if store().capture(request.source, request.account_id) is None:
            raise HTTPException(409, "Import an account capture first")
        kind, value = values[0]
        store().annotate(
            request.source, request.account_id, kind, value, request.author, request.reason
        )
        return {"status": "saved", "kind": kind}

    @router.post("/fee-corrections")
    def fee_correction(request: FeeCorrection) -> dict[str, str]:
        from decimal import Decimal

        if Decimal(request.fee) < 0:
            raise HTTPException(422, "Fee must be nonnegative")
        store().correct_fee(request.event_id, request.fee, request.author, request.reason)
        return {"status": "saved"}

    @router.post("/reconcile-fill")
    def reconcile(request: FillReconciliation) -> dict[str, str]:
        from decimal import Decimal

        if request.at > datetime.now(UTC) or request.fee is not None and Decimal(request.fee) < 0:
            raise HTTPException(422, "Invalid event time or fee")
        try:
            store().reconcile_fill(
                request.event_id,
                request.record_id,
                request.at,
                request.fee,
                request.author,
                request.reason,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "saved"}

    return router
