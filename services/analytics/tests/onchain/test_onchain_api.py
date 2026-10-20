import json
import math
import threading
from collections import Counter
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from costflow_sample import (
    WHEELHOUSE,
    _rows,
    crosscheck,
    render_sample_0512,
    render_sample_0604,
    sample_0512,
    sample_0604,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onchain_fixture import (
    GOLDEN_DAYS,
    HISTORY_SAMPLE_AT,
    brk_transport,
    seed_golden,
    seed_history_sample,
)
from sizes_fixture import golden_rows

from wheelhouse_service import rules as rules_module
from wheelhouse_service.http import create_app
from wheelhouse_service.onchain import (
    api,
    costbasis,
    costbasis_history,
    costflow,
    models,
    sizes,
)
from wheelhouse_service.onchain import sync as sync_module
from wheelhouse_service.onchain.api import create_router
from wheelhouse_service.onchain.brk import HOUR1_SERIES, BrkClient
from wheelhouse_service.onchain.costbasis import StoredCostBasis
from wheelhouse_service.onchain.costbasis_history import HISTORY_BUDGET
from wheelhouse_service.onchain.costflow import StoredCostFlow
from wheelhouse_service.onchain.models import closed_day, day1_state, hour1_state
from wheelhouse_service.onchain.pressure import Pressure, seller_pressure
from wheelhouse_service.onchain.sizes import size_cohorts
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import OnchainSync
from wheelhouse_service.rules import Rules

PREFIX = "/api/wheelhouse/v1/onchain"
NOW = datetime(2026, 10, 16, 10, 40, tzinfo=UTC)
LINES = {"true_mean", "short_term", "average", "long_term", "median"}
LEVEL_ROUTES = ("levels", "cost-basis")
# The cost-basis golden sample: its URPD set has every cohort and bucket width.
GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-16T1829Z"


def blocked_client() -> tuple[BrkClient, list[str]]:
    """A BRK client whose every request fails, and the paths it was asked for."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        raise httpx.ConnectError("network is blocked in this test", request=request)

    return BrkClient(httpx.Client(transport=httpx.MockTransport(handler))), seen


def synced(
    tmp_path: Path,
    *,
    at: datetime = NOW,
    rules: Rules = frozenset(),
    **transport_options: Any,
) -> Path:
    """Run one sync against the fixture BRK at `at` and return the store path."""
    path = tmp_path / "onchain.sqlite"
    transport, _ = brk_transport(**transport_options)
    client = BrkClient(httpx.Client(transport=transport), clock=lambda: at)
    OnchainSync(OnchainStore(path), client, rules=rules).run_once(now=at)
    return path


def router_app(
    path: Path,
    now: datetime = NOW,
    *,
    start_worker: bool = False,
    rules: Rules = frozenset(),
) -> FastAPI:
    """Only the on-chain router, with a fixed clock and a client that cannot reach the network."""
    client, _ = blocked_client()
    app = FastAPI()
    app.include_router(
        create_router(path, client, rules=rules, start_worker=start_worker, clock=lambda: now)
    )
    return app


def test_empty_store_is_unavailable_with_200(tmp_path: Path):
    client, seen = blocked_client()
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
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
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
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
    OnchainSync(OnchainStore(path), client, rules=frozenset()).run_once(now=later)

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


def test_o5_missing_1d_1w_series_concerns_the_levels_and_the_cost_basis(tmp_path: Path):
    missing = "utxos_1d_to_1w_old_realized_price"
    o5: Rules = frozenset({"O5"})
    path = synced(tmp_path, rules=o5, missing={missing}, urpd_dir=GOLDEN)
    with TestClient(router_app(path, NOW, rules=o5)) as http:
        levels = http.get(f"{PREFIX}/levels").json()
        cost = http.get(f"{PREFIX}/cost-basis").json()

    # Under O5 the series is that of the 1d–1w line, so without it there are no lines; under v1
    # only the cycle needs it (above).
    assert (levels["data_state"], levels["lines"]) == ("unavailable", [])
    assert levels["reasons"] == [f"series_missing:{missing}"]
    assert (cost["data_state"], cost["buckets"]) == ("unavailable", [])
    assert cost["reasons"] == [f"series_missing:{missing}"]


def test_levels_and_cost_basis_reasons_follow_the_rules_of_their_payload(tmp_path: Path):
    missing = "series_missing:utxos_1d_to_1w_old_realized_price"
    o5: Rules = frozenset({"O5"})

    def reasons(path: Path, configured: Rules) -> list[list[str]]:
        with TestClient(router_app(path, NOW, rules=configured)) as http:
            return [http.get(f"{PREFIX}/{route}").json()["reasons"] for route in LEVEL_ROUTES]

    for derived in (frozenset(), o5):
        directory = tmp_path / ("o5" if derived else "v1")
        directory.mkdir()
        path = synced(directory, rules=derived, urpd_dir=GOLDEN)
        # A synthetic state; only the filter is under test. The payloads need the series under O5
        # alone, whatever the configured rules, which the worker has not derived under yet.
        OnchainStore(path).set_state(reasons=json.dumps([missing]))
        for configured in (frozenset(), o5):
            assert reasons(path, configured) == ([[missing]] * 2 if derived else [[], []])

    # Without a payload, the configured rules decide.
    empty = tmp_path / "onchain.sqlite"
    OnchainStore(empty).set_state(reasons=json.dumps([missing]))
    assert reasons(empty, o5) == [[missing]] * 2
    assert reasons(empty, frozenset()) == [["brk_unavailable"]] * 2


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
        names = ("cycle", "levels", "seller-pressure", "cost-basis", "cost-flow", "status")
        views = [http.get(f"{PREFIX}/{name}").json() for name in names]

    assert [view["refreshing"] for view in views] == [True, True, True, True, True, True]


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


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (datetime(2026, 10, 16, 10, 40, tzinfo=UTC), date(2026, 10, 15)),
        (datetime(2026, 10, 17, 0, 12, tzinfo=UTC), date(2026, 10, 15)),
        (datetime(2026, 10, 17, 1, 30, tzinfo=UTC), date(2026, 10, 15)),
        (datetime(2026, 10, 17, 1, 59, 59, tzinfo=UTC), date(2026, 10, 15)),
        # From GRACE_END on, BRK no longer revises yesterday: it is closed.
        (datetime(2026, 10, 17, 2, 0, tzinfo=UTC), date(2026, 10, 16)),
        (datetime(2026, 10, 17, 2, 12, tzinfo=UTC), date(2026, 10, 16)),
        # The day is the UTC day, whatever the offset of `at`.
        (datetime(2026, 10, 17, 9, 30, tzinfo=timezone(timedelta(hours=8))), date(2026, 10, 15)),
    ],
)
def test_closed_day_is_yesterday_from_the_end_of_the_grace(at: datetime, expected: date):
    assert closed_day(at) == expected


def test_day_start_lives_in_models():
    assert models.day_start(date(2026, 10, 19)) == datetime(2026, 10, 19, tzinfo=UTC)
    # The routes read the one the worker uses.
    assert api.day_start is models.day_start


O1: Rules = frozenset({"O1"})


def test_o1_cycle_is_fresh_and_closed_at_10_40_and_01_30(tmp_path: Path):
    def read(path: Path, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
        with TestClient(router_app(path, now, rules=O1)) as http:
            return http.get(f"{PREFIX}/cycle").json(), http.get(f"{PREFIX}/status").json()

    # The fixture's last row is 10-16, still open at 10:40 and still being revised at 01:30.
    for at, now in (
        (NOW, NOW),
        (datetime(2026, 10, 17, 1, 12, tzinfo=UTC), datetime(2026, 10, 17, 1, 30, tzinfo=UTC)),
    ):
        directory = tmp_path / at.isoformat()
        directory.mkdir()
        cycle, status = read(synced(directory, at=at, rules=O1), now)

        assert cycle["data_state"] == "fresh", now
        assert cycle["as_of"] == "2026-10-15"
        assert cycle["forming_at"] is None
        assert (cycle["state"], cycle["since"], cycle["day"]) == ("breakout", "2026-09-23", 23)
        assert (cycle["rules"], cycle["rules_pending"]) == (["O1"], False)
        # How recent the data is stays inside the service.
        assert "latest_day" not in cycle
        day1 = status["datasets"][0]
        assert (day1["name"], day1["data_state"]) == ("day1", "fresh")
        assert datetime.fromisoformat(day1["last_at"]) == datetime(2026, 10, 16, tzinfo=UTC)


def test_status_day1_is_the_newer_latest_day_of_the_cycle_and_the_levels(tmp_path: Path):
    path = synced(tmp_path, rules=O1)
    store = OnchainStore(path)

    def status_with(cycle_day: str, levels_day: str) -> dict[str, Any]:
        for kind, day in (("cycle", cycle_day), ("levels", levels_day)):
            derived = store.derived(kind)
            assert derived is not None
            payload = json.loads(derived[0])
            payload["latest_day"] = day
            store.save_derived(kind, json.dumps(payload), derived[1])
        with TestClient(router_app(path, NOW, rules=O1)) as http:
            day1: dict[str, Any] = http.get(f"{PREFIX}/status").json()["datasets"][0]
        return day1

    # Whichever of the two is newer, and not merely the first or the last read.
    for cycle_day, levels_day in (("2026-10-16", "2026-10-14"), ("2026-10-14", "2026-10-16")):
        day1 = status_with(cycle_day, levels_day)
        assert (day1["name"], day1["data_state"]) == ("day1", "fresh")
        assert datetime.fromisoformat(day1["last_at"]) == datetime(2026, 10, 16, tzinfo=UTC)
    # Both older than the closed day each view reads: neither as_of stands in for them.
    day1 = status_with("2026-10-13", "2026-10-12")
    assert (day1["data_state"], day1["last_at"]) == ("stale", "2026-10-13T00:00:00Z")


def test_cycle_without_latest_day_is_judged_by_its_as_of(tmp_path: Path):
    path = synced(tmp_path, rules=O1)
    store = OnchainStore(path)
    derived = store.derived("cycle")
    assert derived is not None
    payload = json.loads(derived[0])
    assert payload["latest_day"] == "2026-10-16"
    # A payload stored before the field existed.
    del payload["latest_day"]
    store.save_derived("cycle", json.dumps(payload), derived[1])

    with TestClient(router_app(path, NOW, rules=O1)) as http:
        cycle = http.get(f"{PREFIX}/cycle").json()

    # Only the closed day is known, and by itself that is a day old at 10:40.
    assert (cycle["data_state"], cycle["as_of"]) == ("stale", "2026-10-15")


def test_worker_not_started_when_disabled(tmp_path: Path):
    client, seen = blocked_client()
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
    with TestClient(app):
        names = {thread.name for thread in threading.enumerate()}

    assert "wheelhouse-onchain" not in names
    assert seen == []


def test_worker_runs_only_while_the_app_runs(tmp_path: Path):
    with TestClient(router_app(tmp_path / "onchain.sqlite", start_worker=True)):
        assert "wheelhouse-onchain" in {thread.name for thread in threading.enumerate()}

    assert "wheelhouse-onchain" not in {thread.name for thread in threading.enumerate()}


def test_router_worker_backfills_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    recorded: dict[str, Any] = {}

    class Recorder:
        def __init__(self, *args: object, **options: Any) -> None:
            recorded.update(options)

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    monkeypatch.setattr(api, "OnchainSync", Recorder)
    with TestClient(router_app(tmp_path / "onchain.sqlite", start_worker=True)):
        pass

    assert recorded["history_budget"] == HISTORY_BUDGET == 120


def test_capability_and_get_only_schema(tmp_path: Path):
    client, _ = blocked_client()
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
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
        f"{PREFIX}/sell-side",
        f"{PREFIX}/age-cohorts",
        f"{PREFIX}/cost-basis",
        f"{PREFIX}/cost-flow",
        f"{PREFIX}/size-cohorts",
        f"{PREFIX}/cost-basis-history",
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
    assert set(view["loss"][0]) == {"at", "lth", "sth", "no_block", "gap", "p95", "p75", "level"}
    # Under v1 no point is without a block or behind a gap, and none has thresholds of its own.
    for group in ("loss", "share", "supply", "price"):
        assert not any(point["no_block"] or point["gap"] for point in view[group])
        assert all(
            point["p95"] is None and point["p75"] is None and point["level"] is None
            for point in view[group]
        )
    assert view["closed_at"] is None
    assert (view["loss_run"], view["share_run"], view["supply_run"]) == (None, None, None)


def test_pressure_view_passes_o1_o2_through(tmp_path: Path):
    rules: Rules = frozenset({"O1", "O2"})
    path = synced(tmp_path, at=HOUR1_SYNC, rules=rules)
    with TestClient(
        router_app(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC), rules=rules)
    ) as http:
        view = http.get(f"{PREFIX}/seller-pressure").json()
    stored = Pressure.model_validate_json((OnchainStore(path).derived("pressure") or ("", NOW))[0])

    assert (view["rules"], view["rules_pending"]) == (["O1", "O2"], False)
    # 09:00 is still forming at 09:12: it is drawn, and the current reading is 08:00.
    assert datetime.fromisoformat(view["forming_at"]) == LAST_ROW
    assert datetime.fromisoformat(view["closed_at"]) == LAST_ROW - timedelta(hours=1)
    assert view["loss"][-1]["level"] is None and view["loss"][-1]["p95"] is not None
    assert view["loss"][-2]["level"] in {"extreme", "warning", "none"}
    for group in ("loss", "share", "supply"):
        assert view[group] == [
            point.model_dump(mode="json") for point in getattr(stored, group)[-PAYLOAD_POINTS:]
        ]
        assert view[f"{group}_run"] == getattr(stored, f"{group}_run")
        assert view[f"{group}_levels"] == getattr(stored, f"{group}_levels").model_dump()
    assert isinstance(view["loss_run"], int)


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
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
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
    pressure = seller_pressure(rows, rules=frozenset(), computed_at=HOUR1_SYNC)
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
    assert pressure["closed_at"] is None
    assert (pressure["loss_run"], pressure["share_run"], pressure["supply_run"]) == (None,) * 3
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
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
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
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
    with TestClient(app) as http:
        view = http.get(f"{PREFIX}/cost-basis").json()

    assert view["urpd_date"] == "2026-10-16"
    assert len(view["buckets"]) == 3
    assert seen == []


def golden_o1(path: Path, at: datetime) -> None:
    """The golden sample stored as if fetched at `at`, and derived under O1 at `at`.

    The sample has no W series, so there is no cycle: the day1 status is the levels' alone.
    """
    store = OnchainStore(path)
    seed_golden(store, GOLDEN_DAYS, at)
    client, _ = blocked_client()
    sync = OnchainSync(store, client, rules=O1)
    assert sync._derive(sync._recent_urpd(at), at, set(), None, closed=closed_day(at)) is False


def o1_views(path: Path, now: datetime) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with TestClient(router_app(path, now, rules=O1)) as http:
        return (
            http.get(f"{PREFIX}/levels").json(),
            http.get(f"{PREFIX}/cost-basis").json(),
            http.get(f"{PREFIX}/status").json(),
        )


@pytest.mark.parametrize(
    ("at", "now"),
    [(NOW, NOW), (moment(17, 1, 12), moment(17, 1, 30))],
    ids=["10:40", "01:30"],
)
def test_o1_levels_cost_basis_and_status_are_fresh(tmp_path: Path, at: datetime, now: datetime):
    path = tmp_path / "onchain.sqlite"
    golden_o1(path, at)
    levels, cost, status = o1_views(path, now)

    # Both read the closed day 10-15, while the data reaches 10-16.
    assert levels["data_state"] == "fresh"
    assert datetime.fromisoformat(levels["as_of"]) == moment(15)
    assert (levels["urpd_date"], levels["onchain_close"]) == ("2026-10-15", 82203.57)
    assert levels["forming_at"] is None
    assert (levels["rules"], levels["rules_pending"]) == (["O1"], False)
    assert cost["data_state"] == "fresh"
    assert (cost["urpd_date"], cost["lines_as_of"]) == ("2026-10-15", "2026-10-15")
    assert cost["forming_at"] is None
    assert cost["reasons"] == []
    assert (cost["rules"], cost["rules_pending"]) == (["O1"], False)
    # How recent the data is stays inside the service.
    assert {"latest_day", "latest_urpd_day"}.isdisjoint(levels)
    assert "latest_day" not in cost
    day1, urpd, _ = status["datasets"]
    assert (day1["name"], day1["data_state"]) == ("day1", "fresh")
    assert datetime.fromisoformat(day1["last_at"]) == moment(16)
    assert (urpd["name"], urpd["data_state"]) == ("urpd", "fresh")
    assert datetime.fromisoformat(urpd["last_at"]) == moment(16)


def test_o1_payloads_without_the_newest_days_are_judged_by_their_dates(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    golden_o1(path, NOW)
    store = OnchainStore(path)
    # Payloads stored before the fields existed.
    for kind, fields in (
        ("levels", ("latest_day", "latest_urpd_day")),
        ("costbasis", ("latest_day",)),
    ):
        derived = store.derived(kind)
        assert derived is not None
        payload = json.loads(derived[0])
        for field in fields:
            assert payload.pop(field) == "2026-10-16"
        store.save_derived(kind, json.dumps(payload), derived[1])

    levels, cost, status = o1_views(path, NOW)

    # Only the closed day is known, and by itself that is a day old at 10:40.
    assert (levels["data_state"], cost["data_state"]) == ("stale", "stale")
    day1, urpd, _ = status["datasets"]
    assert (day1["data_state"], urpd["data_state"]) == ("stale", "stale")
    assert datetime.fromisoformat(day1["last_at"]) == moment(15)
    assert datetime.fromisoformat(urpd["last_at"]) == moment(15)


def test_o1_without_a_final_day_shows_urpd_not_final(tmp_path: Path):
    path = synced(tmp_path, rules=O1, urpd_dir=GOLDEN, urpd_missing={("sth", "lin200")})
    with TestClient(router_app(path, NOW, rules=O1)) as http:
        levels = http.get(f"{PREFIX}/levels").json()
        cost = http.get(f"{PREFIX}/cost-basis").json()
        day1, urpd, hour1 = http.get(f"{PREFIX}/status").json()["datasets"]
        cycle = http.get(f"{PREFIX}/cycle").json()

    assert levels["reasons"] == ["urpd_not_final"]
    assert {line["name"] for line in levels["lines"]} == LINES - {"median"}
    assert (levels["urpd_date"], levels["onchain_close"]) == (None, None)
    assert (cost["data_state"], cost["reasons"], cost["buckets"]) == (
        "unavailable",
        ["urpd_not_final"],
        [],
    )
    # D itself is current: the snapshots are there, just not final.
    assert (urpd["data_state"], urpd["reasons"]) == ("fresh", ["urpd_not_final"])
    assert day1["reasons"] == hour1["reasons"] == cycle["reasons"] == []


def test_sell_side_unavailable_with_200_and_no_zero(tmp_path: Path):
    with TestClient(router_app(tmp_path / "m.sqlite")) as http:
        response = http.get(f"{PREFIX}/sell-side")
    view = response.json()

    assert response.status_code == 200
    assert view["data_state"] == "unavailable"
    assert view["reasons"] == ["brk_unavailable"]
    assert (view["forming_at"], view["last_at"], view["xgap"]) == (None, None, None)
    # Missing data is empty columns, never zero-filled ones.
    assert view["at"] == view["price"] == []
    for measure in ("pnl", "volb", "volu"):
        assert all(values == [] for values in view[measure].values())
    assert (view["qc"], view["rules"], view["rules_pending"]) == ([], [], False)


def test_sell_side_view_after_sync(tmp_path: Path):
    path = synced(tmp_path, at=HOUR1_SYNC)
    with TestClient(router_app(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC))) as http:
        view = http.get(f"{PREFIX}/sell-side").json()

    assert view["data_state"] == "fresh"
    assert view["reasons"] == []
    assert datetime.fromisoformat(view["forming_at"]) == LAST_ROW
    assert datetime.fromisoformat(view["last_at"]) == LAST_ROW
    assert datetime.fromisoformat(view["at"][-1]) == LAST_ROW
    # Every column is lined up with `at`: the whole v1 lookback that was kept, not a tail.
    count = len(view["at"])
    assert 2500 < count < 2600
    assert len(view["price"]) == count
    for measure in ("pnl", "volb", "volu"):
        assert {len(values) for values in view[measure].values()} == {count}
    assert (view["xgap"], view["qc"], view["rules"]) == (0, [], [])
    assert view["brk_version"] == "0.12.2"


def test_a_sell_side_series_gap_leaves_the_seller_pressure_alone(tmp_path: Path):
    gap = "utxos_1h_to_1d_old_realized_loss_cumulative"
    path = synced(tmp_path, at=HOUR1_SYNC, missing={gap})
    with TestClient(router_app(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC))) as http:
        sell_side = http.get(f"{PREFIX}/sell-side").json()
        pressure = http.get(f"{PREFIX}/seller-pressure").json()
        _, _, hour1 = http.get(f"{PREFIX}/status").json()["datasets"]

    assert sell_side["data_state"] == "unavailable"
    assert sell_side["reasons"] == [f"series_missing:hour1:{gap}"]
    assert sell_side["at"] == []
    assert pressure["data_state"] == "fresh"
    assert pressure["reasons"] == []
    assert len(pressure["loss"]) == PAYLOAD_POINTS
    assert hour1["reasons"] == []


def test_a_seller_pressure_series_gap_leaves_the_sell_side_alone(tmp_path: Path):
    gap = "sth_supply_in_loss"
    path = synced(tmp_path, at=HOUR1_SYNC, missing={gap})
    with TestClient(router_app(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC))) as http:
        sell_side = http.get(f"{PREFIX}/sell-side").json()
        pressure = http.get(f"{PREFIX}/seller-pressure").json()

    assert pressure["data_state"] == "unavailable"
    assert sell_side["data_state"] == "fresh"
    assert sell_side["reasons"] == []
    assert datetime.fromisoformat(sell_side["last_at"]) == LAST_ROW


def test_age_cohorts_unavailable_with_200_and_no_zero(tmp_path: Path):
    with TestClient(router_app(tmp_path / "m.sqlite")) as http:
        response = http.get(f"{PREFIX}/age-cohorts")
    view = response.json()

    assert response.status_code == 200
    assert view["data_state"] == "unavailable"
    assert view["reasons"] == ["brk_unavailable"]
    assert (view["forming_at"], view["last_at"]) == (None, None)
    # Missing data is empty columns, never zero-filled ones.
    assert view["at"] == view["price"] == []
    for measure in ("pnl", "volb", "volu"):
        assert view[measure] == {"profit": [], "loss": []}
    assert (view["rules"], view["rules_pending"]) == ([], False)


def test_age_cohorts_view_after_sync(tmp_path: Path):
    path = synced(tmp_path, at=HOUR1_SYNC)
    with TestClient(router_app(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC))) as http:
        view = http.get(f"{PREFIX}/age-cohorts").json()

    assert view["data_state"] == "fresh"
    assert view["reasons"] == []
    assert datetime.fromisoformat(view["forming_at"]) == LAST_ROW
    assert datetime.fromisoformat(view["last_at"]) == LAST_ROW
    # The fixture has the age-only series for 25 hours; every column is lined up with `at`.
    count = len(view["at"])
    assert count == 24
    assert len(view["price"]) == count
    for measure in ("pnl", "volb", "volu"):
        for side in ("profit", "loss"):
            assert len(view[measure][side]) == 12
            assert {len(band) for band in view[measure][side]} == {count}
    assert view["rules"] == []
    assert view["brk_version"] == "0.12.2"


def test_an_age_series_gap_leaves_the_sell_side_alone(tmp_path: Path):
    gap = "utxos_7y_to_8y_old_realized_profit_cumulative"
    path = synced(tmp_path, at=HOUR1_SYNC, missing={gap})
    with TestClient(router_app(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC))) as http:
        ages = http.get(f"{PREFIX}/age-cohorts").json()
        sell_side = http.get(f"{PREFIX}/sell-side").json()
        pressure = http.get(f"{PREFIX}/seller-pressure").json()
        _, _, hour1 = http.get(f"{PREFIX}/status").json()["datasets"]

    assert ages["data_state"] == "unavailable"
    assert ages["reasons"] == [f"series_missing:hour1:{gap}"]
    assert ages["at"] == []
    assert (sell_side["data_state"], sell_side["reasons"]) == ("fresh", [])
    assert (pressure["data_state"], pressure["reasons"]) == ("fresh", [])
    assert hour1["reasons"] == []


def test_a_shared_series_gap_shows_on_the_age_cohorts_too(tmp_path: Path):
    gap = "utxos_1h_to_1d_old_transfer_volume_in_profit_cumulative_usd"
    path = synced(tmp_path, at=HOUR1_SYNC, missing={gap})
    with TestClient(router_app(path, datetime(2026, 10, 16, 9, 30, tzinfo=UTC))) as http:
        ages = http.get(f"{PREFIX}/age-cohorts").json()
        sell_side = http.get(f"{PREFIX}/sell-side").json()

    for view in (ages, sell_side):
        assert view["data_state"] == "unavailable"
        assert view["reasons"] == [f"series_missing:hour1:{gap}"]


# The cost-flow sample of Charts 3 and 4: D = 2026-10-19, its snapshots fetched by 05:12Z.
COSTFLOW = Path(__file__).parent / "fixtures" / "brk-2026-10-19T0512Z-costflow"
FLOW_D = date(2026, 10, 19)
FLOW_SYNC = datetime(2026, 10, 19, 5, 15, tzinfo=UTC)
FLOW_READ = datetime(2026, 10, 19, 5, 20, tzinfo=UTC)


def cost_flow_of(path: Path, now: datetime) -> dict[str, Any]:
    with TestClient(router_app(path, now)) as http:
        response = http.get(f"{PREFIX}/cost-flow")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def store_cost_flow(
    path: Path, *, snapshot_at: datetime, computed_at: datetime, reasons: tuple[str, ...] = ()
) -> None:
    """Store derived cost-flow inputs directly, the way the sync worker would have left them."""
    stored = StoredCostFlow(
        now_day=FLOW_D,
        snapshot_at=snapshot_at,
        spot=82347.76,
        grids=[],
        age=None,
        reasons=list(reasons),
        qc=[],
    )
    OnchainStore(path).save_derived("costflow", stored.model_dump_json(), computed_at)


def test_cost_flow_is_unavailable_without_a_payload(tmp_path: Path):
    view = cost_flow_of(tmp_path / "onchain.sqlite", NOW)

    assert view["data_state"] == "unavailable"
    assert view["reasons"] == ["brk_unavailable"]
    assert (view["grids"], view["age"]) == ([], None)
    # Missing data is absent, never a zero or an empty-looking value.
    for field in ("forming_at", "now_day", "snapshot_at", "computed_at", "spot", "brk_version"):
        assert view[field] is None, field
    assert (view["qc"], view["rules"], view["rules_pending"]) == ([], [], False)
    assert view["refreshing"] is False


def test_cost_flow_serves_the_derived_payload(tmp_path: Path):
    path = synced(tmp_path, at=FLOW_SYNC, urpd_dir=COSTFLOW)
    view = cost_flow_of(path, FLOW_READ)

    assert view["data_state"] == "fresh"
    # D was fetched at 05:15, while it was still open.
    assert view["forming_at"] == "2026-10-19T00:00:00Z"
    assert view["now_day"] == "2026-10-19"
    assert view["spot"] == 82347.76
    assert [grid["step"] for grid in view["grids"]] == [500, 200]
    assert "age_urpd_missing" in view["reasons"]
    assert view["rules"] == []
    assert datetime.fromisoformat(view["snapshot_at"]) == FLOW_SYNC
    assert datetime.fromisoformat(view["computed_at"]) == FLOW_SYNC
    assert view["brk_version"] == "0.12.2"
    # The stored inputs are served as they are.
    derived = OnchainStore(path).derived("costflow")
    assert derived is not None
    stored = json.loads(derived[0])
    for field in ("now_day", "snapshot_at", "spot", "grids", "age", "qc", "rules"):
        assert view[field] == stored[field], field


@pytest.mark.parametrize(
    ("snapshot_at", "now", "forming", "state"),
    [
        pytest.param(
            datetime(2026, 10, 19, 5, 12, 6, tzinfo=UTC),
            FLOW_READ,
            "2026-10-19T00:00:00Z",
            "fresh",
            id="same-day",
        ),
        # In the grace period of the next day D was never seen closed, so it still forms.
        pytest.param(
            datetime(2026, 10, 19, 5, 12, 6, tzinfo=UTC),
            datetime(2026, 10, 20, 1, 30, tzinfo=UTC),
            "2026-10-19T00:00:00Z",
            "fresh",
            id="grace",
        ),
        pytest.param(
            datetime(2026, 10, 19, 23, 59, 59, tzinfo=UTC),
            datetime(2026, 10, 20, 2, 30, tzinfo=UTC),
            "2026-10-19T00:00:00Z",
            "stale",
            id="stale",
        ),
        # Fetched once D had ended: nothing in it forms, and how fresh it is follows D itself.
        pytest.param(
            datetime(2026, 10, 20, tzinfo=UTC),
            datetime(2026, 10, 20, 2, 30, tzinfo=UTC),
            None,
            "stale",
            id="closed",
        ),
    ],
)
def test_cost_flow_forming_and_freshness(
    tmp_path: Path, snapshot_at: datetime, now: datetime, forming: str | None, state: str
):
    path = tmp_path / "onchain.sqlite"
    store_cost_flow(path, snapshot_at=snapshot_at, computed_at=snapshot_at + timedelta(minutes=1))
    view = cost_flow_of(path, now)

    assert view["forming_at"] == forming
    assert view["data_state"] == state == day1_state(FLOW_D, now)


def test_cost_flow_reasons_filtered(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    # A synthetic state: no single run stores all of these codes at once. Only the filter is
    # under test here.
    OnchainStore(path).set_state(
        reasons=json.dumps(
            [
                "series_missing:true_market_mean",
                "series_missing:price_low",
                "series_missing:hour1:sth_supply_in_loss",
                "urpd_missing",
                "urpd_not_final",
                "series_missing:price_high",
                "brk_unavailable",
            ]
        )
    )
    shared = [
        "series_missing:price_low",
        "urpd_missing",
        "series_missing:price_high",
        "brk_unavailable",
    ]
    # Without a payload, the shared reasons that concern Charts 3 and 4 say why.
    assert cost_flow_of(path, FLOW_READ)["reasons"] == shared

    store_cost_flow(
        path,
        snapshot_at=FLOW_SYNC,
        computed_at=FLOW_SYNC,
        reasons=("urpd_missing:sth:lin200", "age_urpd_missing"),
    )
    # The shared ones first, in their stored order, then the codes stored with the payload.
    assert cost_flow_of(path, FLOW_READ)["reasons"] == [
        *shared,
        "urpd_missing:sth:lin200",
        "age_urpd_missing",
    ]


def test_cost_flow_rules_pending_until_the_worker_derives_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "onchain.sqlite"
    store_cost_flow(path, snapshot_at=FLOW_SYNC, computed_at=FLOW_SYNC)
    # Were O1 to apply to the cost flow, the payload derived under no rule would be pending while
    # a worker runs; the worker's thread itself is not started.
    monkeypatch.setitem(rules_module.IMPLEMENTED, "costflow", frozenset({"O1"}))
    monkeypatch.setattr(OnchainSync, "start", lambda self: None)
    with TestClient(router_app(path, FLOW_READ, start_worker=True, rules=O1)) as http:
        response = http.get(f"{PREFIX}/cost-flow")

    assert response.status_code == 200
    view = response.json()
    assert (view["rules"], view["rules_pending"]) == ([], True)


def test_cost_flow_reads_no_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    synced(tmp_path, at=FLOW_SYNC, urpd_dir=COSTFLOW)

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the read route computed something")

    # Nor does it compute: neither the worker's derivation nor an engine runs. Each name must still
    # be there, or the patch would silently patch nothing; and no series is read, which any
    # recomputation, under whatever name, would need.
    patched = (
        (costflow, ("cost_flow", "qc_codes", "age_band", "age_groups")),
        (costbasis, ("weighted_kde", "find_peaks")),
    )
    for module, names in patched:
        for name in names:
            assert hasattr(module, name), f"{module.__name__}.{name}"
            monkeypatch.setattr(module, name, boom)
    monkeypatch.setattr(OnchainStore, "read_series", boom)
    client, seen = blocked_client()
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
    with TestClient(app) as http:
        response = http.get(f"{PREFIX}/cost-flow")

    assert response.status_code == 200
    view = response.json()
    assert view["now_day"] == "2026-10-19"
    assert [grid["step"] for grid in view["grids"]] == [500, 200]
    assert seen == []


def mismatches(committed: Any, fresh: Any, at: str = "$") -> list[str]:
    """Where `fresh` departs from `committed`: in its structure, or in a number by more than a
    relative 1e-12."""
    if isinstance(committed, dict) and isinstance(fresh, dict):
        if committed.keys() != fresh.keys():
            return [f"{at}: keys"]
        return [
            m for key in committed for m in mismatches(committed[key], fresh[key], f"{at}.{key}")
        ]
    if isinstance(committed, list) and isinstance(fresh, list):
        if len(committed) != len(fresh):
            return [f"{at}: length {len(committed)} != {len(fresh)}"]
        return [
            m
            for i, (left, right) in enumerate(zip(committed, fresh, strict=True))
            for m in mismatches(left, right, f"{at}[{i}]")
        ]
    if type(committed) is type(fresh):
        if type(committed) is float:
            if math.isclose(committed, fresh, rel_tol=1e-12, abs_tol=0.0):
                return []
        elif committed == fresh:
            return []
    return [f"{at}: {committed!r} != {fresh!r}"]


def test_mismatches_reports_a_number_beyond_a_relative_1e_12():
    committed = {"sides": [{"h": 2000.0, "k": 1}]}

    def moved(by: float) -> dict[str, Any]:
        return {"sides": [{"h": 2000.0 * (1 + by), "k": 1}]}

    assert mismatches(committed, moved(5e-13)) == []
    for by in (2e-12, 1e-11):
        assert mismatches(committed, moved(by)) == [
            f"$.sides[0].h: 2000.0 != {2000.0 * (1 + by)!r}"
        ]


def test_sample_rows_trim_as_stage_a_does():
    grids = {grid.step: grid for grid in sample_0512().stored.grids}
    stage_a = json.loads((COSTFLOW / "expected_chart3.json").read_text())["views"]
    # `_rows` draws All and STH, the holders of the crosscheck: STH on the $200 grid, All on the
    # $500 one, both at Zoom All.
    views = [v for v in stage_a if v["zoom"] == 0 and v["cohort"] in ("all", "sth")]
    assert len(views) == 12
    counts = {}
    for view in views:
        step = 200 if view["cohort"] == "sth" else 500
        assert view["bin"] == step
        rows = _rows(grids[step], view["win"], view["cohort"], view["aging"] == "on")
        counts[(view["win"], view["cohort"], view["aging"])] = len(rows)
    assert counts == {(v["win"], v["cohort"], v["aging"]): v["rows"] for v in views}
    # 1d All draws no bar in its two highest buckets, which Zoom All trims.
    assert counts[("1d", "all", "off")] == 250


def test_samples_regenerate_identically(tmp_path: Path):
    s1, s2 = sample_0512(), sample_0604()
    windows = ["1d", "7d", "30d", "90d"]

    # S1, stage A: the sample's 30 snapshots without age snapshots.
    assert (s1.stored.snapshot_at, s1.computed_at, s1.read_at) == (
        datetime(2026, 10, 19, 5, 12, 6, tzinfo=UTC),
        datetime(2026, 10, 19, 5, 12, 30, tzinfo=UTC),
        FLOW_READ,
    )
    assert s1.stored.spot == 82347.76
    assert [(grid.step, [w.window for w in grid.windows]) for grid in s1.stored.grids] == [
        (500, windows),
        (200, windows),
    ]
    assert (s1.stored.age, s1.stored.reasons, s1.stored.qc) == (None, ["age_urpd_missing"], [])
    # S2: the snapshot of 06:04:42, rebuilt on the $500 grid only.
    assert (s2.stored.snapshot_at, s2.computed_at, s2.read_at) == (
        datetime(2026, 10, 19, 6, 4, 42, tzinfo=UTC),
        datetime(2026, 10, 19, 6, 5, tzinfo=UTC),
        datetime(2026, 10, 19, 6, 10, tzinfo=UTC),
    )
    assert s2.stored.spot == 82361.33
    assert [(grid.step, [w.window for w in grid.windows]) for grid in s2.stored.grids] == [
        (500, windows)
    ]
    assert s2.stored.reasons == [
        "urpd_missing:all:lin200",
        "urpd_missing:sth:lin200",
        "urpd_missing:lth:lin200",
    ]
    assert s2.stored.qc == []
    assert s2.stored.age is not None
    assert [len(group) for group in s2.stored.age.groups] == [252] * 4
    assert len(s2.stored.age.band) == 252
    # Its then columns are the same finalized snapshots as S1's.
    assert s2.stored.grids[0].windows == s1.stored.grids[0].windows
    # Net buy and net sell of the whole supply are the page's Chart 4 legends of that snapshot.
    grid = s2.stored.grids[0]
    nets = []
    for found in grid.windows[:3]:
        buy = sell = 0.0
        for now, then in zip(grid.now.all, found.then.all, strict=True):
            if now - then > 0:
                buy += now - then
            else:
                sell += now - then
        nets.append((round(buy), round(sell)))
    assert nets == [(54_914, -54_811), (329_997, -327_019), (1_134_837, -1_121_241)]

    for name, sample, render in (
        ("cost-flow-sample-0512.json", s1, render_sample_0512),
        ("cost-flow-sample.json", s2, render_sample_0604),
    ):
        # No libm result is in these two, so they are the same bytes on every platform.
        committed = (WHEELHOUSE / name).read_text()
        assert committed == render(), name
        # The route serves the same body from the same stored payload.
        directory = tmp_path / name
        directory.mkdir()
        path = directory / "onchain.sqlite"
        payload = sample.stored.model_dump_json()
        OnchainStore(path).save_derived("costflow", payload, sample.computed_at)
        view = cost_flow_of(path, sample.read_at)
        assert view == json.loads(committed), name
        assert (view["data_state"], view["forming_at"]) == ("fresh", "2026-10-19T00:00:00Z")

    # The crosscheck holds math.exp results, whose last bit depends on the platform's libm.
    committed = json.loads((WHEELHOUSE / "cost-flow-crosscheck.json").read_text())
    assert mismatches(committed, crosscheck().model_dump(mode="json")) == []
    sides = [
        (side["holders"], side["aging"], side["side"], len(side["centers"]))
        for side in committed["sides"]
    ]
    assert sides == [
        ("all", False, "pos", 252),
        ("all", False, "neg", 252),
        ("sth", True, "pos", 629),
        ("sth", True, "neg", 629),
    ]
    # Its rows and weights are stage A's: the same engine finds the same peaks on them.
    stage_a = json.loads((COSTFLOW / "expected_chart3.json").read_text())["views"]
    for side in committed["sides"]:
        aging = "on" if side["aging"] else "off"
        (view,) = [
            v
            for v in stage_a
            if (v["win"], v["cohort"], v["zoom"], v["aging"]) == ("30d", side["holders"], 0, aging)
        ]
        assert view["rows"] == len(side["centers"])
        assert mismatches(view["sides"][side["side"]]["peaks"], side["peaks"]) == []


# The size cohorts of Charts 5 and 6: the page's readings at 2026-10-19 06:00Z (see the README of
# `fixtures/sr5-6-page-2026-10-19T0600Z`), derived at 06:21 while that hour was still open.
SIZE_LAST = "2026-10-19T06:00:00Z"
SIZE_COMPUTED = datetime(2026, 10, 19, 6, 21, tzinfo=UTC)
SIZE_READ = datetime(2026, 10, 19, 6, 30, tzinfo=UTC)
SIZE_SAMPLE = (
    Path(__file__).resolve().parents[4]
    / "integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse"
    / "size-cohorts-sample.json"
)
SizeRows = dict[str, list[tuple[datetime, float | None]]]


def size_cohorts_of(path: Path, now: datetime, **options: Any) -> dict[str, Any]:
    with TestClient(router_app(path, now, **options)) as http:
        response = http.get(f"{PREFIX}/size-cohorts")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def store_sizes(
    path: Path,
    computed_at: datetime = SIZE_COMPUTED,
    *,
    rows: SizeRows | None = None,
    rules: tuple[str, ...] = (),
) -> None:
    """Store derived size cohorts directly, the way the sync worker would have left them."""
    result = size_cohorts(golden_rows() if rows is None else rows)
    assert result is not None
    payload = result.model_copy(update={"rules": list(rules)}).model_dump_json()
    OnchainStore(path).save_derived("sizes", payload, computed_at)


def test_size_cohorts_unavailable_with_200_and_no_zero(tmp_path: Path):
    with TestClient(router_app(tmp_path / "m.sqlite")) as http:
        response = http.get(f"{PREFIX}/size-cohorts")

    assert response.status_code == 200
    view = response.json()
    assert view["data_state"] == "unavailable"
    assert view["reasons"] == ["brk_unavailable"]
    # Missing data is empty, never bands of zeros.
    assert (view["bands"], view["no_block"]) == ([], [])
    assert (view["last_at"], view["forming_at"], view["brk_version"]) == (None, None, None)
    assert (view["rules"], view["rules_pending"]) == ([], False)


def test_size_cohorts_view_matches_the_frontend_sample(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    store_sizes(path, SIZE_COMPUTED)
    view = size_cohorts_of(path, SIZE_READ)

    committed = SIZE_SAMPLE.read_text()
    regenerate = (
        f"{SIZE_SAMPLE.name} is out of date. If the change is meant, regenerate it from the same "
        "inputs (store_sizes(path, SIZE_COMPUTED), then size_cohorts_of(path, SIZE_READ)) by "
        'writing json.dumps(view, indent=1, ensure_ascii=False) + "\\n" to it.'
    )
    assert view == json.loads(committed), regenerate
    # The sample is this response written as it came, so any drift of the route or of the rows
    # shows here, down to a whole number that turned into a float.
    assert committed == json.dumps(view, indent=1, ensure_ascii=False) + "\n", regenerate
    assert view["data_state"] == "fresh"
    assert view["last_at"] == view["forming_at"] == "2026-10-19T06:00:00Z"
    assert len(view["bands"]) == 12
    assert (view["reasons"], view["no_block"], view["rules"]) == ([], [], [])


@pytest.mark.parametrize(
    ("computed_at", "now", "forming", "state"),
    [
        pytest.param(moment(19, 6, 21), moment(19, 6, 30), SIZE_LAST, "fresh", id="forming"),
        pytest.param(moment(19, 7, 5), moment(19, 7, 10), None, "fresh", id="closed"),
        # Computed while 06:00 was open, it stays forming however long ago that was.
        pytest.param(moment(19, 6, 21), moment(19, 8, 30), SIZE_LAST, "delayed", id="delayed"),
        # How fresh it is follows the hour it is of, not when it was computed.
        pytest.param(moment(19, 7, 5), moment(19, 12, 30), None, "stale", id="stale"),
        # The hour is open until its last second.
        pytest.param(
            moment(19, 7) - timedelta(seconds=1), moment(19, 7, 10), SIZE_LAST, "fresh", id="59:59"
        ),
        pytest.param(moment(19, 7), moment(19, 7, 10), None, "fresh", id="hour-end"),
    ],
)
def test_size_cohorts_freshness_and_forming(
    tmp_path: Path, computed_at: datetime, now: datetime, forming: str | None, state: str
):
    path = tmp_path / "onchain.sqlite"
    store_sizes(path, computed_at)
    view = size_cohorts_of(path, now)

    assert view["last_at"] == SIZE_LAST
    assert view["forming_at"] == forming
    assert view["data_state"] == state


def test_size_cohorts_reasons_are_module_filtered(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    # A synthetic state: only the filter is under test here.
    OnchainStore(path).set_state(
        reasons=json.dumps(
            [
                "series_missing:hour1:sth_supply_in_loss",
                "series_missing:hour1:addrs_over_100k_btc_realized_cap",
                "urpd_missing",
            ]
        )
    )
    own = ["series_missing:hour1:addrs_over_100k_btc_realized_cap"]
    # Without a payload the reasons that concern Charts 5 and 6 say why; with one they still show.
    assert size_cohorts_of(path, SIZE_READ)["reasons"] == own
    store_sizes(path)
    assert size_cohorts_of(path, SIZE_READ)["reasons"] == own

    # An outage the sync recorded concerns them too, after their own codes as stored.
    OnchainStore(path).set_state(
        reasons=json.dumps(
            ["series_missing:hour1:addrs_under_1k_sats_supply", "urpd_missing", "brk_unavailable"]
        )
    )
    assert size_cohorts_of(path, SIZE_READ)["reasons"] == [
        "series_missing:hour1:addrs_under_1k_sats_supply",
        "brk_unavailable",
    ]


def test_size_cohorts_expose_the_sync_state(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    OnchainStore(path).set_state(refreshing="true", brk_version="0.12.2")
    without = size_cohorts_of(path, SIZE_READ)
    store_sizes(path)
    served = size_cohorts_of(path, SIZE_READ)

    # Without a payload and with one: the sync's state shows either way.
    for view in (without, served):
        assert (view["refreshing"], view["brk_version"]) == (True, "0.12.2")


def test_size_cohorts_pass_no_block_through(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    # The 7d anchor as an hour without a block: every series has its row there, all of them null.
    newest = datetime(2026, 10, 19, 6, tzinfo=UTC)
    anchor = newest - timedelta(hours=168)
    rows = {
        name: [(at, None if at == anchor else value) for at, value in series]
        for name, series in golden_rows().items()
    }
    # And one band's supply null at the newest hour: a gap in one series, not a blockless hour.
    gap = "addrs_1btc_to_10btc"
    rows[f"{gap}_supply"] = [
        (at, None if at == newest else value) for at, value in rows[f"{gap}_supply"]
    ]
    store_sizes(path, rows=rows)
    view = size_cohorts_of(path, SIZE_READ)

    assert view["no_block"] == ["7d"]
    # That band's supply and all four of its supply changes are null, never zero.
    (band,) = [band for band in view["bands"] if band["band"] == gap]
    assert band["supply"] is None
    assert [window["supply_change"] for window in band["windows"]] == [None] * 4
    assert band["realized_cap"] is not None
    assert [[w["window"] for w in band["windows"]] for band in view["bands"]] == [
        ["1d", "7d", "30d", "90d"]
    ] * 12
    # Its cells are null, never zero.
    assert {
        (window["supply_change"], window["profit"], window["loss"])
        for band in view["bands"]
        for window in band["windows"]
        if window["window"] == "7d"
    } == {(None, None, None)}


def test_size_cohorts_rules_pending_until_the_worker_derives_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "onchain.sqlite"
    store_sizes(path)
    # Were O1 to apply to the size cohorts, the payload derived under no rule would be pending
    # while a worker runs; the worker's thread itself is not started.
    monkeypatch.setitem(rules_module.IMPLEMENTED, "sizes", frozenset({"O1"}))
    monkeypatch.setattr(OnchainSync, "start", lambda self: None)
    view = size_cohorts_of(path, SIZE_READ, start_worker=True, rules=O1)
    assert (view["rules"], view["rules_pending"]) == ([], True)

    # Once derived under O1 it is no longer pending, and it names the rules it was derived under.
    store_sizes(path, rules=("O1",))
    view = size_cohorts_of(path, SIZE_READ, start_worker=True, rules=O1)
    assert (view["rules"], view["rules_pending"]) == (["O1"], False)


def test_size_cohorts_after_sync_never_touch_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    synced(tmp_path)

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the read route computed something")

    # Nor does it compute: the worker's derivation does not run, wherever the route would have
    # imported it from. Each name must still be there, or the patch would silently patch nothing;
    # and no series is read, which any recomputation, under whatever name, would need.
    for module in (sizes, sync_module):
        assert hasattr(module, "size_cohorts"), module.__name__
        monkeypatch.setattr(module, "size_cohorts", boom)
    monkeypatch.setattr(OnchainStore, "read_series", boom)
    client, seen = blocked_client()
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
    with TestClient(app) as http:
        response = http.get(f"{PREFIX}/size-cohorts")

    assert response.status_code == 200
    view = response.json()
    # This app runs on the real clock, so how fresh the fixture's rows are is not asserted here.
    assert view["last_at"] == "2026-10-16T09:00:00Z"
    assert len(view["bands"]) == 12
    assert view["brk_version"] == "0.12.2"
    assert seen == []


# The cost-basis history of Chart 8: the golden sample's all-coins lin500 snapshots (see
# `seed_history_sample`), derived at HISTORY_SAMPLE_AT and read ten minutes later.
SAMPLE_NOW = datetime(2026, 10, 16, 18, 40, tzinfo=UTC)
SAMPLE = (
    Path(__file__).parents[4]
    / "integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse"
)


def seed_history(path: Path, *, history_error: str | None = None) -> None:
    """Store the history sample at `path` and derive Chart 8 from it at HISTORY_SAMPLE_AT, with
    `history_error` as the last backfill's error."""
    store = OnchainStore(path)
    seed_history_sample(store)
    store.set_state(history_error=history_error)
    OnchainSync(store, blocked_client()[0], rules=frozenset())._derive_history(HISTORY_SAMPLE_AT)


def history_app(tmp_path: Path, now: datetime, **options: Any) -> FastAPI:
    path = tmp_path / "onchain.sqlite"
    seed_history(path)
    return router_app(path, now, **options)


def test_cost_basis_history_slices_the_span(tmp_path: Path):
    with TestClient(history_app(tmp_path, SAMPLE_NOW)) as http:
        body = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
        assert body["span"] == "30" and body["data_state"] == "fresh"
        assert body["latest_day"] == "2026-10-16"
        assert len(body["days"]) == 30
        assert body["days"][0] == "2026-09-17" and body["days"][-1] == "2026-10-16"
        assert len(body["floors"]) == 250
        assert body["floors"][0] == 1000 and body["floors"][-1] == 125500
        assert Counter(body["status"]) == {"pending": 24, "absent": 1, "closed": 4, "forming": 1}
        # Missing is null, never 0.
        assert body["supply"][0] is None and body["close"][0] is None
        assert body["supply"][-1][(82000 - 1000) // 500] == 252722.29
        assert body["close"][-2] == 82203.57
        assert body["backfill_error"] is None
        assert body["rules"] == [] and body["rules_pending"] is False
        assert body["computed_at"].startswith("2026-10-16T18:29:37")
        assert len(http.get(f"{PREFIX}/cost-basis-history").json()["days"]) == 365
        everything = http.get(f"{PREFIX}/cost-basis-history?span=all").json()
        assert len(everything["days"]) == 1461 and everything["days"][0] == "2022-10-17"
        ninety = http.get(f"{PREFIX}/cost-basis-history?span=90").json()

    # Every column of a span is the tail of the same columns, lined up with its days.
    assert len(ninety["days"]) == 90 and ninety["days"][0] == "2026-07-19"
    for span in (body, ninety, everything):
        assert {len(span[column]) for column in ("close", "supply", "status")} == {
            len(span["days"])
        }
    for span in (body, ninety):
        for column in ("days", "close", "supply", "status"):
            assert span[column] == everything[column][-len(span["days"]) :], column
        assert span["floors"] == everything["floors"]


def test_cost_basis_history_matches_the_frontend_sample(tmp_path: Path):
    # The committed sample is exactly what the service answers (PLAN-SR5-6:396 does the same).
    with TestClient(history_app(tmp_path, SAMPLE_NOW)) as http:
        body = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    committed = (SAMPLE / "cost-basis-history-sample.json").read_text()
    regenerate = (
        "cost-basis-history-sample.json is out of date. If the change is meant, regenerate it "
        "from the same inputs (history_app(tmp_path, SAMPLE_NOW), then GET ?span=30) by writing "
        'json.dumps(body, separators=(",", ":"), ensure_ascii=False) + "\\n" to it, and '
        "cost-basis-history-expected.json from it with cbh_reference.reference."
    )
    assert body == json.loads(committed), regenerate
    # No libm result is in it, so it is the same bytes on every platform: any drift of the route
    # or of the rows shows here, down to a whole number that turned into a float.
    assert committed == json.dumps(body, separators=(",", ":"), ensure_ascii=False) + "\n"


def test_cost_basis_history_rejects_an_unknown_span(tmp_path: Path):
    with TestClient(history_app(tmp_path, SAMPLE_NOW)) as http:
        for span in ("7", "ALL", "365d", ""):
            assert http.get(f"{PREFIX}/cost-basis-history?span={span}").status_code == 422, span


def test_cost_basis_history_is_unavailable_without_a_payload(tmp_path: Path):
    with TestClient(router_app(tmp_path / "onchain.sqlite", SAMPLE_NOW)) as http:
        response = http.get(f"{PREFIX}/cost-basis-history")

    assert response.status_code == 200
    body = response.json()
    assert body["data_state"] == "unavailable" and body["reasons"] == ["urpd_missing"]
    assert body["span"] == "365"
    for column in ("floors", "days", "close", "supply", "status"):
        assert body[column] == [], column
    assert (body["latest_day"], body["computed_at"]) == (None, None)
    assert (body["backfill_error"], body["last_error"]) == (None, None)
    assert (body["rules"], body["rules_pending"], body["refreshing"]) == ([], False, False)
    assert body["brk_version"] is None


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 17, 1, 59, tzinfo=UTC), "fresh"),
        (datetime(2026, 10, 17, 2, 0, tzinfo=UTC), "stale"),
    ],
)
def test_cost_basis_history_goes_stale_after_the_grace(
    tmp_path: Path, now: datetime, expected: str
):
    with TestClient(history_app(tmp_path, now)) as http:
        body = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert body["data_state"] == expected == day1_state(date(2026, 10, 16), now)
    # How fresh it is never changes what it holds.
    assert body["latest_day"] == "2026-10-16" and body["days"][-1] == "2026-10-16"


def test_cost_basis_history_reasons_are_module_filtered(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    seed_history(path)
    shared = ["urpd_missing", "brk_unavailable"]
    OnchainStore(path).set_state(
        reasons=json.dumps(
            ["series_missing:price_close", "urpd_not_final", shared[0], shared[1]]
            + ["series_missing:hour1:price_close"]
        )
    )
    with TestClient(router_app(path, SAMPLE_NOW)) as http:
        body = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    # Only the shared reasons that concern D, in their stored order; the payload stays as it was.
    assert body["reasons"] == shared
    assert body["latest_day"] == "2026-10-16" and len(body["days"]) == 30

    # Without a payload the same filter applies, and `urpd_missing` is not repeated.
    empty = tmp_path / "empty.sqlite"
    OnchainStore(empty).set_state(reasons=json.dumps(["urpd_not_final", "brk_unavailable"]))
    with TestClient(router_app(empty, SAMPLE_NOW)) as http:
        assert http.get(f"{PREFIX}/cost-basis-history").json()["reasons"] == ["brk_unavailable"]


def test_cost_basis_history_passes_the_backfill_error_through(tmp_path: Path):
    path = tmp_path / "onchain.sqlite"
    seed_history(path, history_error="brk_bad_snapshot")
    with TestClient(router_app(path, SAMPLE_NOW)) as http:
        body = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert (body["backfill_error"], body["last_error"]) == ("brk_bad_snapshot", None)


def test_cost_basis_history_passes_the_sync_state_through(tmp_path: Path):
    # With the sample and without any payload alike, the round's state is read as it is stored.
    sample = tmp_path / "onchain.sqlite"
    seed_history(sample)
    empty = tmp_path / "empty.sqlite"
    for path in (sample, empty):
        OnchainStore(path).set_state(
            refreshing="true", brk_version="0.12.2", last_error="brk_unavailable"
        )
    for path, state in ((sample, "fresh"), (empty, "unavailable")):
        with TestClient(router_app(path, SAMPLE_NOW)) as http:
            body = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
        assert body["data_state"] == state, path.name
        assert (body["refreshing"], body["brk_version"], body["last_error"]) == (
            True,
            "0.12.2",
            "brk_unavailable",
        ), path.name


def test_cost_basis_history_shows_a_failed_round_holding_the_backfill(tmp_path: Path):
    # Every hour1 stage fails. The round records its error, but the shared reasons stay clean and
    # no history is asked for, so no backfill error is recorded either: without `last_error` the
    # view would claim the missing days are still being fetched.
    path = synced(tmp_path, at=NOW, urpd_dir=GOLDEN, fail_index={"hour1"})
    with TestClient(router_app(path, NOW)) as http:
        failed = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert failed["data_state"] == "fresh" and failed["latest_day"] == "2026-10-16"
    assert "pending" in failed["status"]
    assert failed["reasons"] == [] and failed["backfill_error"] is None
    assert failed["last_error"] == "brk_unavailable"

    # A clean round clears it.
    later = NOW + timedelta(hours=1)
    synced(tmp_path, at=later, urpd_dir=GOLDEN)
    with TestClient(router_app(path, later)) as http:
        clean = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert (clean["last_error"], clean["backfill_error"], clean["reasons"]) == (None, None, [])


def test_cost_basis_history_rules_pending_until_the_worker_derives_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "onchain.sqlite"
    seed_history(path)
    monkeypatch.setattr(OnchainSync, "start", lambda self: None)
    # Chart 8 implements no rule, so under any of them, O1 among them, which the cost basis does
    # implement, nothing is pending.
    with TestClient(router_app(path, SAMPLE_NOW, start_worker=True, rules=O1)) as http:
        view = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert (view["rules"], view["rules_pending"]) == ([], False)

    # Were O1 to apply to Chart 8, the payload derived under no rule would be pending while a
    # worker runs; the worker's thread itself is not started.
    monkeypatch.setitem(rules_module.IMPLEMENTED, "costbasis_history", frozenset({"O1"}))
    with TestClient(router_app(path, SAMPLE_NOW, start_worker=True, rules=O1)) as http:
        view = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert (view["rules"], view["rules_pending"]) == ([], True)
    # Without a worker nothing derives it again, so nothing is pending.
    with TestClient(router_app(path, SAMPLE_NOW, rules=O1)) as http:
        view = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert (view["rules"], view["rules_pending"]) == ([], False)

    # Once derived under O1 it is no longer pending, and it names the rules it was derived under.
    OnchainSync(OnchainStore(path), blocked_client()[0], rules=O1)._derive_history(
        HISTORY_SAMPLE_AT
    )
    with TestClient(router_app(path, SAMPLE_NOW, start_worker=True, rules=O1)) as http:
        view = http.get(f"{PREFIX}/cost-basis-history?span=30").json()
    assert (view["rules"], view["rules_pending"]) == (["O1"], False)


def test_cost_basis_history_reads_no_network_and_computes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    seed_history(tmp_path / "onchain.sqlite")

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the read route computed something")

    # Each name must still be there, or the patch would silently patch nothing; and no stored input
    # is read, which any recomputation, under whatever name, would need.
    for module in (costbasis_history, sync_module):
        for name in ("cost_basis_history", "history_row"):
            assert hasattr(module, name), f"{module.__name__}.{name}"
            monkeypatch.setattr(module, name, boom)
    stored_inputs = (
        "read_series",
        "urpd_history",
        "urpd",
        "latest_urpd",
        "urpd_days",
        "urpd_fetched_at",
    )
    for name in stored_inputs:
        assert hasattr(OnchainStore, name), f"OnchainStore.{name}"
        monkeypatch.setattr(OnchainStore, name, boom)
    client, seen = blocked_client()
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
    with TestClient(app) as http:
        response = http.get(f"{PREFIX}/cost-basis-history?span=all")

    assert response.status_code == 200 and len(response.json()["days"]) == 1461
    assert seen == []


def test_cost_basis_history_is_gzipped(tmp_path: Path):
    # The whole app, so the middleware is in the path.
    seed_history(tmp_path / "onchain.sqlite")
    client, _ = blocked_client()
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
    with TestClient(app) as http:
        response = http.get(
            f"{PREFIX}/cost-basis-history?span=all", headers={"Accept-Encoding": "gzip"}
        )
        # A client that does not ask for it gets the plain body.
        plain = http.get(
            f"{PREFIX}/cost-basis-history?span=all", headers={"Accept-Encoding": "identity"}
        )

    assert response.status_code == 200 and response.headers["content-encoding"] == "gzip"
    assert len(response.json()["days"]) == 1461
    assert "content-encoding" not in plain.headers and plain.json() == response.json()
    # The request headers the app sets on every response survive the compression.
    assert response.headers["cache-control"] == "no-store" and response.headers["x-request-id"]


def test_a_small_response_is_not_gzipped(tmp_path: Path):
    client, _ = blocked_client()
    app = create_app(
        tmp_path / "m.sqlite", start_worker=False, brk_client=client, rules=frozenset()
    )
    with TestClient(app) as http:
        response = http.get(f"{PREFIX}/cost-basis-history", headers={"Accept-Encoding": "gzip"})

    # The unavailable view is far under the 1,024-byte minimum.
    assert response.status_code == 200 and len(response.content) < 1024
    assert "content-encoding" not in response.headers
