import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onchain_fixture import brk_transport

from wheelhouse_service.http import create_app
from wheelhouse_service.onchain.api import create_router
from wheelhouse_service.onchain.brk import BrkClient
from wheelhouse_service.onchain.models import day1_state
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import OnchainSync

PREFIX = "/api/wheelhouse/v1/onchain"
NOW = datetime(2026, 10, 16, 10, 40, tzinfo=UTC)
LINES = {"true_mean", "short_term", "average", "long_term", "median"}


def blocked_client() -> tuple[BrkClient, list[str]]:
    """A BRK client whose every request fails, and the paths it was asked for."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        raise httpx.ConnectError("network is blocked in this test", request=request)

    return BrkClient(httpx.Client(transport=httpx.MockTransport(handler))), seen


def synced(tmp_path: Path, **transport_options: Any) -> Path:
    """Run one sync against the fixture BRK at NOW and return the store path."""
    path = tmp_path / "onchain.sqlite"
    transport, _ = brk_transport(**transport_options)
    client = BrkClient(httpx.Client(transport=transport), clock=lambda: NOW)
    OnchainSync(OnchainStore(path), client).run_once(now=NOW)
    return path


def router_app(path: Path, now: datetime = NOW, *, start_worker: bool = False) -> FastAPI:
    """Only the on-chain router, with a fixed clock and a client that cannot reach the network."""
    client, _ = blocked_client()
    app = FastAPI()
    app.include_router(create_router(path, client, start_worker=start_worker, clock=lambda: now))
    return app


def test_empty_store_is_unavailable_with_200(tmp_path: Path):
    client, seen = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client)
    with TestClient(app) as http:
        cycle = http.get(f"{PREFIX}/cycle")
        levels = http.get(f"{PREFIX}/levels")
        status = http.get(f"{PREFIX}/status")

    assert (cycle.status_code, levels.status_code, status.status_code) == (200, 200, 200)
    assert cycle.json()["data_state"] == "unavailable"
    assert levels.json()["data_state"] == "unavailable"
    # Missing data is absent, never a zero or an empty-looking value.
    assert cycle.json()["state"] is None
    assert cycle.json()["as_of"] is None
    assert cycle.json()["forming_at"] is None
    assert cycle.json()["components"] == []
    assert cycle.json()["episodes"] == []
    assert cycle.json()["changes"] is None
    assert cycle.json()["reasons"]
    assert levels.json()["lines"] == []
    assert levels.json()["onchain_close"] is None
    assert levels.json()["reasons"]
    body = status.json()
    assert body["brk_version"] is None
    assert body["refreshing"] is False
    assert body["last_success_at"] is None
    assert [(item["name"], item["data_state"]) for item in body["datasets"]] == [
        ("day1", "unavailable"),
        ("urpd", "unavailable"),
    ]
    assert all(item["last_at"] is None and item["reasons"] for item in body["datasets"])
    assert seen == []


def test_read_routes_never_touch_network(tmp_path: Path):
    synced(tmp_path)
    client, seen = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client)
    with TestClient(app) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        levels = http.get(f"{PREFIX}/levels").json()
        status = http.get(f"{PREFIX}/status").json()

    assert cycle["state"] == "breakout"
    assert cycle["as_of"] == "2026-10-16"
    assert cycle["brk_version"] == "0.12.2"
    assert len(cycle["components"]) == 3
    assert {line["name"] for line in levels["lines"]} == LINES
    assert levels["urpd_date"] == "2026-10-16"
    assert levels["brk_version"] == "0.12.2"
    assert status["brk_version"] == "0.12.2"
    assert seen == []


def test_views_carry_state_and_forming_at(tmp_path: Path):
    path = synced(tmp_path)

    def read(now: datetime) -> dict[str, Any]:
        with TestClient(router_app(path, now)) as http:
            return {name: http.get(f"{PREFIX}/{name}").json() for name in ("cycle", "levels")}

    today = read(NOW)
    for view in today.values():
        assert view["data_state"] == "fresh"
        assert view["reasons"] == []
        assert view["refreshing"] is False
        assert datetime.fromisoformat(view["forming_at"]) == datetime(2026, 10, 16, tzinfo=UTC)
    assert datetime.fromisoformat(today["levels"]["as_of"]) == datetime(2026, 10, 16, tzinfo=UTC)

    # Just after midnight BRK has no row for the new day yet: still fresh, nothing is forming.
    grace = read(datetime(2026, 10, 17, 1, 30, tzinfo=UTC))
    for view in grace.values():
        assert view["data_state"] == "fresh"
        assert view["forming_at"] is None

    later = read(datetime(2026, 10, 17, 10, 0, tzinfo=UTC))
    for view in later.values():
        assert view["data_state"] == "stale"
        assert view["forming_at"] is None
    # Stale data is still served, not hidden.
    assert later["cycle"]["state"] == "breakout"
    assert len(later["levels"]["lines"]) == 5


def test_status_reports_each_dataset(tmp_path: Path):
    path = synced(tmp_path)
    with TestClient(router_app(path, NOW)) as http:
        status = http.get(f"{PREFIX}/status").json()

    assert status["brk_version"] == "0.12.2"
    assert status["refreshing"] is False
    assert status["last_error"] is None
    assert datetime.fromisoformat(status["last_success_at"]).date() == date(2026, 10, 16)
    day1, urpd = status["datasets"]
    assert (day1["name"], day1["data_state"], day1["reasons"]) == ("day1", "fresh", [])
    assert (urpd["name"], urpd["data_state"], urpd["reasons"]) == ("urpd", "fresh", [])
    assert datetime.fromisoformat(day1["last_at"]) == datetime(2026, 10, 16, tzinfo=UTC)
    assert datetime.fromisoformat(urpd["last_at"]) == datetime(2026, 10, 16, tzinfo=UTC)


def test_missing_urpd_only_shows_in_reasons(tmp_path: Path):
    path = synced(tmp_path, urpd_dates=set())
    with TestClient(router_app(path, NOW)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        levels = http.get(f"{PREFIX}/levels").json()
        status = http.get(f"{PREFIX}/status").json()

    # The cycle does not use URPD, so it stays healthy and says nothing about it.
    assert cycle["data_state"] == "fresh"
    assert cycle["reasons"] == []
    assert cycle["changes"] == 48
    assert levels["data_state"] == "fresh"
    assert levels["reasons"] == ["urpd_missing"]
    assert levels["urpd_date"] is None
    assert levels["onchain_close"] is None
    assert {line["name"] for line in levels["lines"]} == LINES - {"median"}
    day1, urpd = status["datasets"]
    assert day1["data_state"] == "fresh"
    assert (urpd["data_state"], urpd["last_at"]) == ("unavailable", None)
    assert urpd["reasons"] == ["urpd_missing"]


def test_urpd_outage_does_not_leak_into_the_cycle(tmp_path: Path):
    path = synced(tmp_path, fail_paths={"/api/urpd"})
    with TestClient(router_app(path, NOW)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        levels = http.get(f"{PREFIX}/levels").json()
        status = http.get(f"{PREFIX}/status").json()

    # The cycle does not use URPD: a URPD-only failure must not make it look unavailable.
    assert cycle["data_state"] == "fresh"
    assert cycle["reasons"] == []
    assert cycle["state"] == "breakout"
    assert levels["data_state"] == "fresh"
    assert levels["reasons"] == ["urpd_missing"]
    assert {line["name"] for line in levels["lines"]} == LINES - {"median"}
    # The failure itself stays visible on the status endpoint.
    assert status["last_error"] == "brk_unavailable"
    day1, urpd = status["datasets"]
    assert (day1["data_state"], day1["reasons"]) == ("fresh", [])
    assert (urpd["data_state"], urpd["reasons"]) == ("unavailable", ["urpd_missing"])


def test_urpd_outage_with_a_recent_snapshot_keeps_its_date(tmp_path: Path):
    path = synced(tmp_path, urpd_dates={date(2026, 10, 15)})
    later = NOW + timedelta(hours=1)
    outage, _ = brk_transport(fail_paths={"/api/urpd"})
    client = BrkClient(httpx.Client(transport=outage), clock=lambda: later)
    OnchainSync(OnchainStore(path), client).run_once(now=later)

    with TestClient(router_app(path, later)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        levels = http.get(f"{PREFIX}/levels").json()
        status = http.get(f"{PREFIX}/status").json()

    assert cycle["reasons"] == []
    assert levels["reasons"] == []
    assert levels["urpd_date"] == "2026-10-15"
    assert {line["name"] for line in levels["lines"]} == LINES
    assert status["last_error"] == "brk_unavailable"
    # The snapshot is a day behind the series, and the status says so.
    assert status["datasets"][1]["data_state"] == "stale"


def test_missing_cycle_series_only_concerns_the_cycle(tmp_path: Path):
    missing = "utxos_1d_to_1w_old_realized_price"
    path = synced(tmp_path, missing={missing})
    with TestClient(router_app(path, NOW)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        levels = http.get(f"{PREFIX}/levels").json()

    assert cycle["data_state"] == "unavailable"
    assert cycle["reasons"] == [f"series_missing:{missing}"]
    assert cycle["changes"] is None
    assert levels["data_state"] == "fresh"
    assert levels["reasons"] == []
    assert {line["name"] for line in levels["lines"]} == LINES


def test_missing_line_series_only_concerns_the_levels(tmp_path: Path):
    missing = "lth_realized_price"
    path = synced(tmp_path, missing={missing})
    with TestClient(router_app(path, NOW)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        levels = http.get(f"{PREFIX}/levels").json()

    assert levels["data_state"] == "unavailable"
    assert levels["reasons"] == [f"series_missing:{missing}"]
    assert levels["lines"] == []
    assert cycle["data_state"] == "fresh"
    assert cycle["reasons"] == []
    assert cycle["state"] == "breakout"


def test_failed_first_sync_is_unavailable_with_reason(tmp_path: Path):
    path = synced(tmp_path, fail_paths={"/version"})
    with TestClient(router_app(path, NOW)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        status = http.get(f"{PREFIX}/status").json()

    assert cycle["data_state"] == "unavailable"
    assert cycle["reasons"] == ["brk_unavailable"]
    assert status["last_error"] == "brk_unavailable"
    assert status["last_success_at"] is None


def test_refreshing_flag_is_exposed(tmp_path: Path):
    path = synced(tmp_path)
    OnchainStore(path).set_state(refreshing="true")
    with TestClient(router_app(path, NOW)) as http:
        views = [http.get(f"{PREFIX}/{name}").json() for name in ("cycle", "levels", "status")]

    assert [view["refreshing"] for view in views] == [True, True, True]


@pytest.mark.parametrize(
    ("now", "last", "expected"),
    [
        (datetime(2026, 10, 17, 1, 30, tzinfo=UTC), date(2026, 10, 16), "fresh"),
        (datetime(2026, 10, 17, 2, 30, tzinfo=UTC), date(2026, 10, 16), "stale"),
        (datetime(2026, 10, 17, 2, 0, tzinfo=UTC), date(2026, 10, 16), "stale"),
        (datetime(2026, 10, 16, 0, 0, tzinfo=UTC), date(2026, 10, 16), "fresh"),
        (datetime(2026, 10, 16, 23, 59, tzinfo=UTC), date(2026, 10, 16), "fresh"),
        (datetime(2026, 10, 17, 1, 30, tzinfo=UTC), date(2026, 10, 15), "stale"),
        (datetime(2026, 10, 17, 1, 30, tzinfo=UTC), None, "unavailable"),
        (datetime(2026, 10, 17, 10, 0, tzinfo=UTC), None, "unavailable"),
    ],
)
def test_day1_state_midnight_grace(now: datetime, last: date | None, expected: str):
    assert day1_state(last, now) == expected


def test_worker_not_started_when_disabled(tmp_path: Path):
    client, seen = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client)
    with TestClient(app):
        names = {thread.name for thread in threading.enumerate()}

    assert "wheelhouse-onchain" not in names
    assert seen == []


def test_worker_runs_only_while_the_app_runs(tmp_path: Path):
    with TestClient(router_app(tmp_path / "onchain.sqlite", start_worker=True)):
        assert "wheelhouse-onchain" in {thread.name for thread in threading.enumerate()}

    assert "wheelhouse-onchain" not in {thread.name for thread in threading.enumerate()}


def test_capability_and_get_only_schema(tmp_path: Path):
    client, _ = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client)
    with TestClient(app) as http:
        capabilities = http.get("/api/wheelhouse/v1/status").json()["capabilities"]
        paths = http.get("/api/wheelhouse/v1/openapi.json").json()["paths"]

    assert "onchain" in capabilities
    onchain = {path: set(methods) for path, methods in paths.items() if "/onchain/" in path}
    assert set(onchain) == {f"{PREFIX}/status", f"{PREFIX}/cycle", f"{PREFIX}/levels"}
    assert all(methods == {"get"} for methods in onchain.values())
