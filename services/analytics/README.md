# Wheelhouse Python foundation

An independently packaged FastAPI service for the Wealthfolio host. Current capability: versioned service status only. No market feed, brokerage connection, strategy calculation or trade execution is exposed.

From the repository root:

```sh
make setup
make dev
make doctor
make check
```

To run only Python:

```sh
.venv-foundation/bin/python -m wheelhouse_service
```

The service binds `127.0.0.1:8787`. `WHEELHOUSE_PORT` and `WHEELHOUSE_LOG_LEVEL` configure the local process. Status: `/api/wheelhouse/v1/status`; OpenAPI: `/api/wheelhouse/v1/openapi.json`. Requests receive a generated `X-Request-ID`; status responses are never cached. Errors omit exception data.

`src/wheelhouse_service/contracts.py` defines the HTTP contract. Run `make contract` after changing it. The earlier `backend/wheelhouse` package is an experiment and is not imported by this service.
