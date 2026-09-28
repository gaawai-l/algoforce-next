"""HTTP adapter for the versioned local foundation contract."""

import json
import logging
import platform
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi import HTTPException as APIException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .calculation import data_state
from .context import MarketContext, build_context
from .contracts import ErrorBody, Integrations, ServiceStatus
from .market import (
    DURATIONS,
    Analysis,
    Batch,
    Job,
    JobEvent,
    JobRequest,
    Schedule,
    ScheduleRequest,
    SnapshotSummary,
    Source,
    StorageStats,
    Stream,
    Timeframe,
    Workspace,
)
from .portfolio.api import create_router as portfolio_router
from .repository import Repository
from .runtime import Runtime
from .settings import Settings

PREFIX = "/api/wheelhouse/v1"
logger = logging.getLogger("wheelhouse.requests")


def create_app(
    database: Path | None = None,
    *,
    start_worker: bool = True,
    start_broker_worker: bool | None = None,
) -> FastAPI:
    repository: Repository | None = None

    def repo() -> Repository:
        assert repository is not None, "Application lifespan has not started"
        return repository

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal repository
        repository = Repository(database or Settings.from_env().data_dir / "analytics.sqlite")
        runtime = Runtime(repository)
        if start_worker:
            runtime.start()
        yield
        runtime.stop()

    app = FastAPI(
        lifespan=lifespan,
        title="Wheelhouse Python foundation",
        version=version("wheelhouse-service"),
        openapi_url=f"{PREFIX}/openapi.json",
        docs_url=f"{PREFIX}/docs",
        redoc_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def trace(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = monotonic()
        request.state.request_id = uuid4().hex
        try:
            response: Response
            origin = request.headers.get("origin")
            if request.method not in {"GET", "HEAD", "OPTIONS"} and origin not in {
                None,
                "http://127.0.0.1:1420",
                "http://localhost:1420",
            }:
                response = JSONResponse(
                    status_code=403,
                    content={
                        "code": "origin_rejected",
                        "message": "Only the local workspace may start work",
                        "request_id": request.state.request_id,
                    },
                )
            else:
                response = await call_next(request)
        except Exception:
            # Error details may contain user data; never include them in responses or logs.
            response = JSONResponse(
                status_code=500,
                content=ErrorBody(
                    code="internal_error",
                    message="Python service could not complete the request",
                    request_id=request.state.request_id,
                ).model_dump(),
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "request_id": request.state.request_id,
                    "route": getattr(route, "name", "unmatched"),
                    "status": response.status_code,
                    "duration_ms": round((monotonic() - started) * 1000, 2),
                }
            )
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorBody(
                code=f"http_{exc.status_code}",
                message=(
                    str(exc.detail)
                    if request.url.path.startswith("/api/wheelhouse/v1/portfolio/")
                    else "Endpoint or HTTP method unavailable"
                ),
                request_id=request.state.request_id,
            ).model_dump(),
            headers=exc.headers,
        )

    @app.get(f"{PREFIX}/status", response_model=ServiceStatus)
    def status() -> ServiceStatus:
        return ServiceStatus(
            service="wheelhouse-python",
            status="ready",
            contract_version="1",
            service_version=version("wheelhouse-service"),
            python_version=platform.python_version(),
            checked_at=datetime.now(UTC),
            read_only=True,
            integrations=Integrations(
                broker="not_connected",
                market_data="available" if repo().stats().batches else "not_connected",
                analytics="baseline_ready",
            ),
            capabilities=[
                "service_status",
                "versioned_market_data",
                "baseline_analysis",
                "demark_sequential_basic",
                "historical_replay",
                "durable_jobs",
                "scheduled_refresh",
                "market_context",
            ],
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorBody(
                code="invalid_request",
                message="Invalid request fields; check the versioned API contract",
                request_id=request.state.request_id,
            ).model_dump(),
        )

    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ErrorBody(
                code="not_found", message="Record not found", request_id=request.state.request_id
            ).model_dump(),
        )

    @app.exception_handler(ValueError)
    async def invalid_value(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=ErrorBody(
                code="conflict",
                message="Request conflicts with stored history or idempotency key",
                request_id=request.state.request_id,
            ).model_dump(),
        )

    def stream_params(source: Source, symbol: str, timeframe: Timeframe) -> Stream:
        if symbol not in {"BTCUSDT", "ETHUSDT", "MUUSDT"}:
            raise APIException(422)
        return Stream(source=source, symbol=symbol, timeframe=timeframe)  # type: ignore[arg-type]

    @app.post(f"{PREFIX}/jobs", response_model=Job, status_code=202)
    def submit(
        request: JobRequest, idempotency_key: str = Header(min_length=1, max_length=128)
    ) -> Job:
        now = datetime.now(UTC)
        if any(value and value > now for value in (request.market_at, request.knowledge_at)):
            raise APIException(422)
        return repo().enqueue(request, idempotency_key, now=now)

    @app.get(f"{PREFIX}/jobs/{{job_id}}", response_model=Job)
    def job(job_id: str) -> Job:
        return repo().job(job_id)

    @app.get(f"{PREFIX}/jobs/{{job_id}}/events", response_model=list[JobEvent])
    def events(job_id: str) -> list[JobEvent]:
        return repo().job_events(job_id)

    @app.get(f"{PREFIX}/market-context", response_model=MarketContext)
    def market_context(
        source: Source = "binance",
        symbol: str = "BTCUSDT",
        market_at: datetime | None = None,
        knowledge_at: datetime | None = None,
    ) -> MarketContext:
        if symbol not in {"BTCUSDT", "ETHUSDT", "MUUSDT"}:
            raise APIException(422)
        if (market_at is None) != (knowledge_at is None):
            raise APIException(422)
        now = datetime.now(UTC)
        market = market_at or now
        knowledge = knowledge_at or now
        if market.tzinfo is None or knowledge.tzinfo is None or market > now or knowledge > now:
            raise APIException(422)
        return build_context(
            repo(),
            source,
            symbol,  # type: ignore[arg-type]
            market_at=market,
            knowledge_at=knowledge,
            checked_at=now,
        )

    @app.get(f"{PREFIX}/workspace", response_model=Workspace)
    def workspace(
        source: Source = "binance", symbol: str = "BTCUSDT", timeframe: Timeframe = "1h"
    ) -> Workspace:
        stream = stream_params(source, symbol, timeframe)
        snapshot = repo().live_snapshot(stream)
        at = datetime.now(UTC)
        state = data_state(
            source,
            snapshot.closed_bar_time if snapshot else None,
            at,
            DURATIONS[timeframe],
            valid=snapshot is not None and snapshot.data_state != "unavailable",
        )
        return Workspace(
            stream=stream,
            checked_at=at,
            current_state=state,
            snapshot=snapshot,
            latest_job=repo().latest_job(stream),
            refresh_job=repo().latest_job(stream, refresh_only=True),
            schedule=repo().schedule(stream),
        )

    @app.get(f"{PREFIX}/snapshots", response_model=list[SnapshotSummary])
    def snapshots(
        source: Source = "binance",
        symbol: str = "BTCUSDT",
        timeframe: Timeframe = "1h",
        limit: int = Query(default=30, ge=1, le=100),
    ) -> list[SnapshotSummary]:
        return repo().snapshots(stream_params(source, symbol, timeframe), limit)

    @app.get(f"{PREFIX}/snapshots/{{snapshot_id}}", response_model=Analysis)
    def snapshot(snapshot_id: str) -> Analysis:
        return repo().snapshot(snapshot_id)

    @app.get(f"{PREFIX}/batches/{{batch_id}}", response_model=Batch)
    def batch(batch_id: str) -> Batch:
        return repo().batch(batch_id)

    @app.post(f"{PREFIX}/schedule", response_model=Schedule)
    def schedule(request: ScheduleRequest) -> Schedule:
        return repo().set_schedule(request, now=datetime.now(UTC))

    @app.get(f"{PREFIX}/storage", response_model=StorageStats)
    def storage() -> StorageStats:
        return repo().stats()

    app.include_router(
        portfolio_router(
            (database.parent if database else Settings.from_env().data_dir) / "portfolio.sqlite",
            start_worker=start_worker if start_broker_worker is None else start_broker_worker,
        )
    )
    return app
