# Wheelhouse Python foundation

An independently packaged FastAPI service for the Wealthfolio host. Includes normalized public/fixture market data, append-only revisions, immutable snapshots, durable tasks, closed-bar scheduling, and one deterministic baseline calculation pipeline for live and replay. No brokerage connection, full DeMark strategy or trade execution is exposed.

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

The service binds `127.0.0.1:8787`. `WHEELHOUSE_DATA_DIR` sets the independent SQLite location (default `.local/analytics`); `WHEELHOUSE_PORT` and `WHEELHOUSE_LOG_LEVEL` configure the local process. Status: `/api/wheelhouse/v1/status`; OpenAPI: `/api/wheelhouse/v1/openapi.json`. Requests receive a generated `X-Request-ID`; status responses are never cached. Errors omit exception data.

`src/wheelhouse_service/contracts.py` defines the HTTP contract. Run `make contract` after changing it. The earlier `backend/wheelhouse` package is an experiment and is not imported by this service.

The `market`, `repository`, `calculation`, `sources`, and `runtime` modules own domain contracts, persistence, pure analysis, provider adapters, and work coordination respectively. Migrations ship as package data and are checksum-verified. See [A2–A5 acceptance](../../docs/architecture/a2-a5-acceptance.md) for temporal, recovery, and validation guarantees.
