import json
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
from wheelhouse_service.onchain.brk import HOUR1_SERIES, BrkClient
from wheelhouse_service.onchain.costbasis import StoredCostBasis
from wheelhouse_service.onchain.models import day1_state, hour1_state
from wheelhouse_service.onchain.pressure import Pressure, seller_pressure
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import OnchainSync

PREFIX = "/api/wheelhouse/v1/onchain"
NOW = datetime(2026, 10, 16, 10, 40, tzinfo=UTC)
LINES = {"true_mean", "short_term", "average", "long_term", "median"}
# The cost-basis golden sample: its URPD set has every cohort and bucket width.
GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-16T1829Z"


def blocked_client() -> tuple[BrkClient, list[str]]:
    """A BRK client whose every request fails, and the paths it was asked for."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        raise httpx.ConnectError("network is blocked in this test", request=request)

    return BrkClient(httpx.Client(transport=httpx.MockTransport(handler))), seen


def synced(tmp_path: Path, *, at: datetime = NOW, **transport_options: Any) -> Path:
    """Run one sync against the fixture BRK at `at` and return the store path."""
    path = tmp_path / "onchain.sqlite"
    transport, _ = brk_transport(**transport_options)
    client = BrkClient(httpx.Client(transport=transport), clock=lambda: at)
    OnchainSync(OnchainStore(path), client).run_once(now=at)
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
        ("hour1", "unavailable"),
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
        pressure = http.get(f"{PREFIX}/seller-pressure").json()
        status = http.get(f"{PREFIX}/status").json()

    assert cycle["state"] == "breakout"
    assert cycle["as_of"] == "2026-10-16"
    assert cycle["brk_version"] == "0.12.2"
    # This app runs on the real clock, so how fresh the fixture's rows are is not asserted here.
    assert datetime.fromisoformat(pressure["last_at"]) == datetime(2026, 10, 16, 9, tzinfo=UTC)
    assert len(pressure["loss"]) > 0
    assert pressure["brk_version"] == "0.12.2"
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
    day1, urpd, hour1 = status["datasets"]
    assert (day1["name"], day1["data_state"], day1["reasons"]) == ("day1", "fresh", [])
    assert (urpd["name"], urpd["data_state"], urpd["reasons"]) == ("urpd", "fresh", [])
    assert (hour1["name"], hour1["data_state"], hour1["reasons"]) == ("hour1", "fresh", [])
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
    day1, urpd, _ = status["datasets"]
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
    day1, urpd, _ = status["datasets"]
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
        names = ("cycle", "levels", "seller-pressure", "cost-basis", "status")
        views = [http.get(f"{PREFIX}/{name}").json() for name in names]

    assert [view["refreshing"] for view in views] == [True, True, True, True, True]


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
    assert set(onchain) == {
        f"{PREFIX}/status",
        f"{PREFIX}/cycle",
        f"{PREFIX}/levels",
        f"{PREFIX}/seller-pressure",
        f"{PREFIX}/cost-basis",
    }
    assert all(methods == {"get"} for methods in onchain.values())


# The fixture's last hourly row is 09:00 UTC on the 16th. A sync at 09:12 sees it still forming.
LAST_ROW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
HOUR1_SYNC = datetime(2026, 10, 16, 9, 12, tzinfo=UTC)
PAYLOAD_POINTS = 2160


def pressure_of(path: Path, now: datetime = NOW) -> dict[str, Any]:
    with TestClient(router_app(path, now)) as http:
        response = http.get(f"{PREFIX}/seller-pressure")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), "fresh"),
        (timedelta(hours=1, minutes=59), "fresh"),
        (timedelta(hours=2), "fresh"),
        (timedelta(hours=2, minutes=1), "delayed"),
        (timedelta(hours=6), "delayed"),
        (timedelta(hours=6, minutes=1), "stale"),
        (timedelta(days=3), "stale"),
        (None, "unavailable"),
    ],
)
def test_hour1_state_boundaries(age: timedelta | None, expected: str):
    now = datetime(2026, 10, 16, 15, 30, tzinfo=UTC)
    assert hour1_state(None if age is None else now - age, now) == expected


def test_pressure_view_after_sync(tmp_path: Path):
    path = synced(tmp_path, at=HOUR1_SYNC)
    view = pressure_of(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC))
    stored = Pressure.model_validate_json((OnchainStore(path).derived("pressure") or ("", NOW))[0])

    assert view["data_state"] == "fresh"
    assert datetime.fromisoformat(view["forming_at"]) == LAST_ROW
    assert datetime.fromisoformat(view["last_at"]) == LAST_ROW
    assert view["reasons"] == []
    assert view["refreshing"] is False
    assert view["brk_version"] == "0.12.2"
    assert isinstance(view["xgap"], int)
    for group in ("loss", "share", "supply", "price"):
        assert 0 < len(view[group]) <= PAYLOAD_POINTS
    # Only the tail is sent, while the thresholds still come from the whole stored computation.
    assert stored.kept > PAYLOAD_POINTS
    for group in ("loss", "price"):
        tail = getattr(stored, group)[-PAYLOAD_POINTS:]
        assert view[group] == [point.model_dump(mode="json") for point in tail]
    assert view["loss_levels"] == stored.loss_levels.model_dump()
    assert view["share_levels"] == stored.share_levels.model_dump()
    assert view["supply_levels"] == stored.supply_levels.model_dump()
    assert view["xgap"] == stored.xgap
    assert view["qc"] == stored.qc == []
    assert datetime.fromisoformat(view["loss"][-1]["at"]) == LAST_ROW
    assert set(view["loss"][0]) == {"at", "lth", "sth"}


def test_pressure_view_freshness_follows_the_clock(tmp_path: Path):
    path = synced(tmp_path, at=HOUR1_SYNC)

    def read(now: datetime) -> dict[str, Any]:
        return pressure_of(path, now)

    assert read(LAST_ROW + timedelta(hours=1, minutes=59))["data_state"] == "fresh"
    delayed = read(LAST_ROW + timedelta(hours=2, minutes=1))
    assert delayed["data_state"] == "delayed"
    stale = read(LAST_ROW + timedelta(hours=6, minutes=1))
    assert stale["data_state"] == "stale"
    # The row was in progress when it was computed, whatever the time is now, and stale data is
    # still served with its points.
    assert datetime.fromisoformat(stale["forming_at"]) == LAST_ROW
    assert len(stale["loss"]) == PAYLOAD_POINTS


@pytest.mark.parametrize(
    "at",
    [
        datetime(2026, 10, 16, 10, 0, tzinfo=UTC),
        datetime(2026, 10, 16, 10, 12, tzinfo=UTC),
        datetime(2026, 10, 16, 13, 40, tzinfo=UTC),
    ],
)
def test_forming_cleared_when_computed_after_hour_end(tmp_path: Path, at: datetime):
    view = pressure_of(synced(tmp_path, at=at), at)

    assert view["forming_at"] is None
    assert datetime.fromisoformat(view["last_at"]) == LAST_ROW
    assert len(view["loss"]) == PAYLOAD_POINTS


def test_forming_lasts_until_the_last_second_of_the_hour(tmp_path: Path):
    at = datetime(2026, 10, 16, 9, 59, 59, tzinfo=UTC)
    view = pressure_of(synced(tmp_path, at=at), at)

    assert datetime.fromisoformat(view["forming_at"]) == LAST_ROW


def test_pressure_unavailable_with_200_and_no_zero(tmp_path: Path):
    client, seen = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client)
    with TestClient(app) as http:
        response = http.get(f"{PREFIX}/seller-pressure")
    view = response.json()

    assert response.status_code == 200
    assert view["data_state"] == "unavailable"
    assert view["reasons"] == ["brk_unavailable"]
    assert (view["forming_at"], view["last_at"], view["xgap"], view["brk_version"]) == (
        None,
        None,
        None,
        None,
    )
    # Missing data is empty, not a zero-filled series, and a threshold is absent, not 0.
    for group in ("loss", "share", "supply", "price"):
        assert view[group] == []
    for levels in ("loss_levels", "share_levels", "supply_levels"):
        assert view[levels] is None
    assert view["qc"] == []
    assert seen == []


def test_pressure_view_passes_failed_qc_checks_through(tmp_path: Path):
    path = synced(tmp_path, at=HOUR1_SYNC)
    store = OnchainStore(path)
    stored = Pressure.model_validate_json((store.derived("pressure") or ("", NOW))[0])
    failed = stored.model_copy(update={"qc": ["intraday_legs"]})
    store.save_derived("pressure", failed.model_dump_json(), HOUR1_SYNC)

    view = pressure_of(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC))

    assert view["qc"] == ["intraday_legs"]
    assert view["data_state"] == "fresh"


def test_no_block_hour_does_not_delay_the_pressure_view(tmp_path: Path):
    path = synced(tmp_path, at=HOUR1_SYNC)
    store = OnchainStore(path)
    # BRK had no block in the hour before its newest one: every series is null there, so that hour
    # and the newest one are dropped while BRK itself is current.
    gap = LAST_ROW - timedelta(hours=1)
    rows = {
        name: [(at, None if at == gap else value) for at, value in store.read_series(name, "hour1")]
        for name in HOUR1_SERIES
    }
    pressure = seller_pressure(rows)
    assert pressure is not None
    assert pressure.latest_at == LAST_ROW
    assert pressure.last_at == LAST_ROW - timedelta(hours=2)
    store.save_derived("pressure", pressure.model_dump_json(), HOUR1_SYNC)
    now = LAST_ROW + timedelta(minutes=30)

    with TestClient(router_app(path, now)) as http:
        view = http.get(f"{PREFIX}/seller-pressure").json()
        hour1 = http.get(f"{PREFIX}/status").json()["datasets"][2]

    assert view["data_state"] == "fresh"
    assert datetime.fromisoformat(view["last_at"]) == LAST_ROW - timedelta(hours=2)
    assert hour1["data_state"] == "fresh"
    # The status still names the last row the charts show.
    assert datetime.fromisoformat(hour1["last_at"]) == LAST_ROW - timedelta(hours=2)


def test_hour1_outage_keeps_the_pressure_view_unavailable_with_a_reason(tmp_path: Path):
    path = synced(tmp_path, fail_index={"hour1"})
    with TestClient(router_app(path, NOW)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        pressure = http.get(f"{PREFIX}/seller-pressure").json()

    assert pressure["data_state"] == "unavailable"
    assert pressure["reasons"] == ["brk_unavailable"]
    assert pressure["loss"] == []
    assert pressure["loss_levels"] is None
    # day1 was fine, and the hour1 outage does not reach it.
    assert cycle["data_state"] == "fresh"
    assert cycle["reasons"] == []


def test_pressure_reasons_are_module_filtered(tmp_path: Path):
    day1_gap = "utxos_1d_to_1w_old_realized_price"
    hour1_gap = "sth_supply_in_loss"

    (tmp_path / "day1").mkdir()
    (tmp_path / "hour1").mkdir()
    day1_path = synced(tmp_path / "day1", at=HOUR1_SYNC, missing={day1_gap})
    hour1_path = synced(tmp_path / "hour1", at=HOUR1_SYNC, missing={hour1_gap})
    now = datetime(2026, 10, 16, 9, 30, tzinfo=UTC)

    with TestClient(router_app(day1_path, now)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        pressure = http.get(f"{PREFIX}/seller-pressure").json()
        day1, _, hour1 = http.get(f"{PREFIX}/status").json()["datasets"]
    # A day1 series gap is the cycle's business: the pressure view says nothing about it.
    assert cycle["reasons"] == [f"series_missing:{day1_gap}"]
    assert pressure["data_state"] == "fresh"
    assert pressure["reasons"] == []
    assert len(pressure["loss"]) == PAYLOAD_POINTS
    assert day1["reasons"] == [f"series_missing:{day1_gap}"]
    assert hour1["reasons"] == []

    with TestClient(router_app(hour1_path, now)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        levels = http.get(f"{PREFIX}/levels").json()
        pressure = http.get(f"{PREFIX}/seller-pressure").json()
        day1, _, hour1 = http.get(f"{PREFIX}/status").json()["datasets"]
    # An hour1 series gap clears the pressure and only the pressure.
    assert pressure["data_state"] == "unavailable"
    assert pressure["reasons"] == [f"series_missing:hour1:{hour1_gap}"]
    assert pressure["loss"] == pressure["share"] == pressure["supply"] == pressure["price"] == []
    assert pressure["share_levels"] is None
    assert cycle["data_state"] == "fresh"
    assert cycle["reasons"] == []
    assert levels["reasons"] == []
    assert (day1["data_state"], day1["reasons"]) == ("fresh", [])
    assert (hour1["data_state"], hour1["last_at"]) == ("unavailable", None)
    assert hour1["reasons"] == [f"series_missing:hour1:{hour1_gap}"]


def test_shared_price_gap_is_reported_per_index(tmp_path: Path):
    path = synced(tmp_path, at=HOUR1_SYNC, missing={"price_close"})
    with TestClient(router_app(path, NOW)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()
        pressure = http.get(f"{PREFIX}/seller-pressure").json()

    assert cycle["reasons"] == ["series_missing:price_close"]
    assert pressure["reasons"] == ["series_missing:hour1:price_close"]


def test_status_lists_hour1_dataset(tmp_path: Path):
    path = synced(tmp_path, at=HOUR1_SYNC)

    def read(now: datetime) -> list[dict[str, Any]]:
        with TestClient(router_app(path, now)) as http:
            datasets: list[dict[str, Any]] = http.get(f"{PREFIX}/status").json()["datasets"]
        return datasets

    datasets = read(datetime(2026, 10, 16, 9, 30, tzinfo=UTC))
    assert [item["name"] for item in datasets] == ["day1", "urpd", "hour1"]
    hour1 = datasets[2]
    assert (hour1["data_state"], hour1["reasons"]) == ("fresh", [])
    assert datetime.fromisoformat(hour1["last_at"]) == LAST_ROW

    # Hourly data can be delayed while the daily datasets are still current.
    datasets = read(datetime(2026, 10, 16, 13, 0, tzinfo=UTC))
    assert [item["data_state"] for item in datasets] == ["fresh", "fresh", "delayed"]
    assert [item["reasons"] for item in datasets] == [[], [], []]


D = date(2026, 10, 16)


def moment(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def cost_basis_of(path: Path, now: datetime = NOW) -> dict[str, Any]:
    with TestClient(router_app(path, now)) as http:
        response = http.get(f"{PREFIX}/cost-basis")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def store_cost_basis(
    path: Path,
    *,
    urpd_date: date,
    lines_as_of: date,
    snapshot_at: datetime,
    computed_at: datetime,
    reasons: tuple[str, ...] = (),
) -> None:
    """Store a derived cost basis directly, the way the sync worker would have left it."""
    stored = StoredCostBasis(
        urpd_date=urpd_date,
        lines_as_of=lines_as_of,
        snapshot_at=snapshot_at,
        buckets=[],
        reasons=list(reasons),
    )
    OnchainStore(path).save_derived("costbasis", stored.model_dump_json(), computed_at)


def test_cost_basis_view_from_golden_fixture(tmp_path: Path):
    path = synced(tmp_path, urpd_dir=GOLDEN)
    view = cost_basis_of(path)

    assert view["data_state"] == "fresh"
    assert view["reasons"] == []
    assert view["refreshing"] is False
    assert view["urpd_date"] == "2026-10-16"
    assert view["lines_as_of"] == "2026-10-16"
    assert datetime.fromisoformat(view["snapshot_at"]) == NOW
    assert datetime.fromisoformat(view["computed_at"]) == NOW
    assert view["brk_version"] == "0.12.2"
    buckets = {bucket["bucket"]: bucket for bucket in view["buckets"]}
    assert list(buckets) == [200, 500, 1000]

    # The day1 rows are the P1 fixture's, not the golden sample's, so only table 2 and the bands
    # are compared; the cluster tables are pinned against the oracle in the cost-basis tests.
    expected = json.loads((GOLDEN / "expected-500.json").read_text())
    assert buckets[500]["resistance"] == [86000, 88000, 96000, 104000]
    assert buckets[500]["support"] == [76000, 74000, 70000, 64000]
    assert buckets[500]["resistance"] == expected["resistance"]
    assert buckets[500]["support"] == expected["support"]
    for side in ("above", "below"):
        assert [(band["low"], band["high"]) for band in buckets[500][side]] == [
            (band["low"], band["high"]) for band in expected[side]
        ]


@pytest.mark.parametrize(
    ("urpd_date", "lines_as_of", "snapshot_at", "computed_at", "now", "forming", "state"),
    [
        pytest.param(
            D,
            D,
            moment(16, 10),
            moment(16, 10, 1),
            moment(16, 10, 40),
            moment(16),
            "fresh",
            id="same-day",
        ),
        # The next day, in the grace period: the 16th was never seen closed, so it still forms.
        pytest.param(
            D,
            D,
            moment(16, 10),
            moment(16, 10, 1),
            moment(17, 0, 30),
            moment(16),
            "fresh",
            id="next-day",
        ),
        # Reused after an outage: fetched at 23:12 on the 16th, so the day was open then.
        pytest.param(
            D,
            D,
            moment(16, 23, 12),
            moment(17, 0, 30),
            moment(17, 0, 40),
            moment(16),
            "fresh",
            id="reused",
        ),
        # Fetched at 02:30 on the 17th, the 16th was final: nothing forms, and the day is stale.
        pytest.param(
            D, D, moment(17, 2, 30), moment(17, 2, 31), moment(17, 2, 40), None, "stale", id="final"
        ),
        # Today's snapshot with yesterday's lines: the snapshot is the one still forming, and
        # freshness follows the older date, which the grace period still covers.
        pytest.param(
            date(2026, 10, 17),
            D,
            moment(17, 0, 10),
            moment(17, 0, 30),
            moment(17, 0, 40),
            moment(17),
            "fresh",
            id="mixed-snapshot",
        ),
        # A final snapshot of the 15th with lines of the 16th that still form.
        pytest.param(
            date(2026, 10, 15),
            D,
            moment(16, 2, 30),
            moment(16, 10),
            moment(16, 10, 40),
            moment(16),
            "stale",
            id="mixed-lines",
        ),
        # Both still form: the later date wins.
        pytest.param(
            date(2026, 10, 15),
            D,
            moment(15, 23),
            moment(16, 10),
            moment(16, 10, 40),
            moment(16),
            "stale",
            id="both",
        ),
    ],
)
def test_cost_basis_forming(
    tmp_path: Path,
    urpd_date: date,
    lines_as_of: date,
    snapshot_at: datetime,
    computed_at: datetime,
    now: datetime,
    forming: datetime | None,
    state: str,
):
    path = tmp_path / "onchain.sqlite"
    store_cost_basis(
        path,
        urpd_date=urpd_date,
        lines_as_of=lines_as_of,
        snapshot_at=snapshot_at,
        computed_at=computed_at,
    )
    view = cost_basis_of(path, now)

    if forming is None:
        assert view["forming_at"] is None
    else:
        assert datetime.fromisoformat(view["forming_at"]) == forming
    # Freshness follows the older of the two dates.
    assert view["data_state"] == state == day1_state(min(urpd_date, lines_as_of), now)


def test_cost_basis_unavailable_before_sync(tmp_path: Path):
    client, seen = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client)
    with TestClient(app) as http:
        response = http.get(f"{PREFIX}/cost-basis")

    assert response.status_code == 200
    view = response.json()
    assert view["data_state"] == "unavailable"
    assert view["reasons"] == ["brk_unavailable"]
    assert view["refreshing"] is False
    # Missing data is absent, never an empty-looking zero.
    assert view["forming_at"] is None
    assert view["urpd_date"] is None
    assert view["lines_as_of"] is None
    assert view["snapshot_at"] is None
    assert view["computed_at"] is None
    assert view["buckets"] == []
    assert view["brk_version"] is None
    assert seen == []


def test_cost_basis_without_result_keeps_its_shared_reasons(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    OnchainStore(path).set_state(reasons=json.dumps(["urpd_missing"]))
    view = cost_basis_of(path)

    assert view["data_state"] == "unavailable"
    # A known reason is shown as it is; the fallback is only for when there is none.
    assert view["reasons"] == ["urpd_missing"]
    assert view["buckets"] == []


def test_cost_basis_reasons_filtered(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    store_cost_basis(
        path,
        urpd_date=D,
        lines_as_of=D,
        snapshot_at=moment(16, 10),
        computed_at=moment(16, 10, 1),
        reasons=("urpd_missing:sth:lin200",),
    )
    # A synthetic state: no single run stores all of these codes at once. Only the filter is
    # under test here.
    OnchainStore(path).set_state(
        reasons=json.dumps(
            [
                "series_missing:true_market_mean",
                "series_missing:hour1:sth_supply_in_loss",
                "series_missing:utxos_1d_to_1w_old_realized_price",
                "urpd_missing",
                "brk_unavailable",
            ]
        )
    )
    view = cost_basis_of(path)

    # The pressure's and the cycle's codes are not the cost basis's business. The shared ones come
    # first, then the codes stored with the result.
    assert view["reasons"] == [
        "series_missing:true_market_mean",
        "urpd_missing",
        "brk_unavailable",
        "urpd_missing:sth:lin200",
    ]


def test_status_urpd_reasons_include_snapshot_codes(tmp_path: Path):
    path = synced(tmp_path, urpd_dir=GOLDEN, urpd_missing={("sth", "lin200")})
    with TestClient(router_app(path, NOW)) as http:
        day1, urpd, hour1 = http.get(f"{PREFIX}/status").json()["datasets"]
        view = http.get(f"{PREFIX}/cost-basis").json()

    assert urpd["reasons"] == ["urpd_missing:sth:lin200"]
    assert view["reasons"] == ["urpd_missing:sth:lin200"]
    assert [bucket["bucket"] for bucket in view["buckets"]] == [500, 1000]
    assert day1["reasons"] == []
    assert hour1["reasons"] == []


def test_cost_basis_read_does_not_touch_network(tmp_path: Path):
    synced(tmp_path, urpd_dir=GOLDEN)
    client, seen = blocked_client()
    app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client)
    with TestClient(app) as http:
        view = http.get(f"{PREFIX}/cost-basis").json()

    assert view["urpd_date"] == "2026-10-16"
    assert len(view["buckets"]) == 3
    assert seen == []
