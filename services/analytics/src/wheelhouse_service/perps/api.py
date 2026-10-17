"""Read-only perps endpoints. They only read the private store: freshness, collector status and
reason codes are worked out per request (spec §3.7, §4; P4-R10)."""

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI
from websockets.sync.client import connect as websocket_connect

from .collector import LIVE_WITHIN, STREAMS, Collectors, Connection
from .models import CollectorStatus, HostStatus, PerpsStatus, PerpStatesView, freshness
from .rows import Exchange, Stream
from .sources import ARCHIVE_HOST, BINANCE_HOST, BYBIT_HOST, PerpsRest
from .states import DAY, REFERENCE_DAYS, Window
from .store import PerpsStore
from .sync import HOSTS, Directions, HostState, PerpsSync, StoredStates, Verdict, derived_key

# What each view reads; only these give it a `collector_down` or `rest_error` reason. Every view
# prices with Bybit spot; Binance's OI comes from its history and its archive files.
VIEW_STREAMS: dict[Exchange, tuple[Stream, ...]] = {
    "all": STREAMS,
    "binance": ("binance_liq",),
    "bybit": ("bybit_liq", "bybit_trades"),
}
VIEW_HOSTS: dict[Exchange, tuple[str, ...]] = {
    "all": (BINANCE_HOST, ARCHIVE_HOST, BYBIT_HOST),
    "binance": (BINANCE_HOST, ARCHIVE_HOST, BYBIT_HOST),
    "bybit": (BYBIT_HOST,),
}
# Before the worker's first derive there is no payload, whatever else is wrong.
NOT_DERIVED = "not_derived"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _at(t: float) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def collector_status(
    stream: Stream,
    spans: Sequence[tuple[float, float]],
    now: datetime,
    problems: Mapping[str, int],
) -> CollectorStatus:
    """A stream's status at `now` from the union of its connections' coverage spans, with the
    problem counts of this process's collectors."""
    if not spans:
        return CollectorStatus(
            stream=stream,
            live=False,
            last_proof=None,
            down_since=None,
            covered_days=0.0,
            since=None,
            problems=dict(problems),
        )
    t = now.timestamp()
    last = max(end for _, end in spans)
    live = t - last <= LIVE_WITHIN
    frm = t - REFERENCE_DAYS * DAY
    covered = sum(max(0.0, min(end, t) - max(start, frm)) for start, end in spans)
    return CollectorStatus(
        stream=stream,
        live=live,
        last_proof=_at(last),
        down_since=None if live else _at(last),
        covered_days=covered / DAY,
        since=_at(min(start for start, _ in spans)),
        problems=dict(problems),
    )


def stored_hosts(state: Mapping[str, str | None]) -> dict[str, HostState]:
    """Each host's state as the worker stored it; empty for a host it has not recorded."""
    stored = json.loads(state.get("hosts") or "{}")
    empty = HostState(last_success=None, error=None, until=None)
    return {
        host: HostState.model_validate(stored[host]) if host in stored else empty for host in HOSTS
    }


def states_view(
    exchange: Exchange,
    window: Window,
    derived: tuple[StoredStates, datetime] | None,
    collectors: Sequence[CollectorStatus],
    hosts: Mapping[str, HostState],
    now: datetime,
) -> PerpStatesView:
    """The stored payload of one view, with its freshness and reason codes at `now`.

    Reasons in order: series_missing, rest_error, collector_down, collecting (spec §3.7).
    """
    stored, computed_at = derived if derived is not None else (None, None)
    states = stored.states if stored is not None else None
    reasons = list(stored.reasons) if stored is not None else [NOT_DERIVED]
    errors = [(host, hosts[host].error) for host in VIEW_HOSTS[exchange]]
    reasons += [f"rest_error:{host}:{error}" for host, error in errors if error]
    reasons += [f"collector_down:{status.stream}" for status in collectors if not status.live]
    fields: dict[str, Any]
    if states is None:
        fields = {
            "last": None,
            "thresholds": None,
            "blocks": [],
            "tail": None,
            "tables": [],
            "covered_days": None,
            "collecting": None,
            "qc": [],
            "series_missing": [],
        }
    else:
        if states.collecting:
            reasons.append(f"collecting:{states.covered_days:.1f}")
        fields = {name: value for name, value in states if name != "window"}
    return PerpStatesView(
        exchange=exchange,
        window=window,
        data_state=freshness(None if states is None else states.last, now),
        reasons=reasons,
        computed_at=computed_at,
        collectors=list(collectors),
        **fields,
    )


def direction(check: Directions | None) -> Verdict:
    """Both venues together: ok only when both are, inverted when either is."""
    if check is None:
        return "pending"
    verdicts = {check.binance.verdict, check.bybit.verdict}
    if "inverted" in verdicts:
        return "inverted"
    return "ok" if verdicts == {"ok"} else "pending"


def create_router(
    path: Path,
    http: httpx.Client | None = None,
    *,
    start_worker: bool = True,
    connect: Callable[..., Connection] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> APIRouter:
    """`start_worker` runs the REST worker and the collectors; `http` and `connect` replace the
    REST client and the WebSocket connection factory."""
    store: PerpsStore | None = None
    collectors: Collectors | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal store, collectors
        store = PerpsStore(path)
        worker = None
        if start_worker:
            collectors = Collectors(store, connect=connect or websocket_connect)
            worker = PerpsSync(store, PerpsRest(http), clock=utc_now)
            collectors.start()
            worker.start()
        yield
        # Collectors first: stopping closes their coverage at the last committed proof.
        if collectors:
            collectors.stop()
        if worker:
            worker.stop()

    router = APIRouter(prefix="/api/wheelhouse/v1/perps", tags=["perps"], lifespan=lifespan)

    def db() -> PerpsStore:
        assert store is not None, "Perps lifespan has not started"
        return store

    def problems(stream: Stream) -> dict[str, int]:
        """The counts of the collectors running in this process; none when they do not run."""
        return {} if collectors is None else collectors.problems(stream)

    def statuses(streams: Sequence[Stream], now: datetime) -> list[CollectorStatus]:
        return [
            collector_status(stream, db().coverage(stream, 0), now, problems(stream))
            for stream in streams
        ]

    @router.get("/states", response_model=PerpStatesView)
    def states(exchange: Exchange = "all", window: Window = "4h") -> PerpStatesView:
        now = clock()
        found = db().derived(derived_key(exchange, window))
        derived = None if found is None else (StoredStates.model_validate_json(found[0]), found[1])
        return states_view(
            exchange,
            window,
            derived,
            statuses(VIEW_STREAMS[exchange], now),
            stored_hosts(db().state()),
            now,
        )

    @router.get("/status", response_model=PerpsStatus)
    def status() -> PerpsStatus:
        now = clock()
        stored = db().state()
        hosts = stored_hosts(stored)
        check = stored.get("direction_check")
        directions = None if check is None else Directions.model_validate_json(check)
        last_run_at = stored.get("last_run_at")
        return PerpsStatus(
            last_run_at=None if last_run_at is None else datetime.fromisoformat(last_run_at),
            last_error=stored.get("last_error"),
            hosts=[
                HostStatus(
                    host=host,
                    last_success=state.last_success,
                    error=state.error,
                    backoff_until=state.until if state.until and state.until > now else None,
                )
                for host, state in hosts.items()
            ],
            collectors=statuses(STREAMS, now),
            direction=direction(directions),
            direction_check=directions,
        )

    return router
