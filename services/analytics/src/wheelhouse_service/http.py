"""HTTP adapter for the versioned local foundation contract."""

import json
import logging
import platform
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib.metadata import version
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .contracts import ErrorBody, Integrations, ServiceStatus

PREFIX = "/api/wheelhouse/v1"
logger = logging.getLogger("wheelhouse.requests")


def create_app() -> FastAPI:
    app = FastAPI(
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
                message="Endpoint or HTTP method unavailable",
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
                broker="not_connected", market_data="not_connected", analytics="not_implemented"
            ),
            capabilities=["service_status"],
        )

    return app
