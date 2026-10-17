"""Rule switches: the rules stored with each on-chain payload, and re-deriving when they change."""

import json
import logging
import shutil
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onchain_fixture import brk_transport

from wheelhouse_service import derive, rules
from wheelhouse_service.http import create_app
from wheelhouse_service.market import timestamp
from wheelhouse_service.onchain.api import StoredLevels, create_router
from wheelhouse_service.onchain.brk import BrkClient
from wheelhouse_service.onchain.costbasis import StoredCostBasis
from wheelhouse_service.onchain.cycle import Cycle
from wheelhouse_service.onchain.pressure import Pressure
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import OnchainSync
from wheelhouse_service.rules import ALL_RULES, Rules

PREFIX = "/api/wheelhouse/v1/onchain"
NOW = datetime(2026, 10, 16, 10, 40, tzinfo=UTC)
# A restart some minutes after the sync: a re-derivation stamped with it would show.
RESTART = NOW + timedelta(minutes=7)
# The cost-basis golden sample: every bucket width is stored, so all four payloads exist.
GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-16T1829Z"
# Derived name -> the route of its view.
ROUTES = {
    "cycle": "cycle",
    "levels": "levels",
    "costbasis": "cost-basis",
    "pressure": "seller-pressure",
}
PAYLOADS: dict[str, type[Cycle | StoredLevels | StoredCostBasis | Pressure]] = {
    "cycle": Cycle,
    "levels": StoredLevels,
    "costbasis": StoredCostBasis,
    "pressure": Pressure,
}


def blocked_client() -> tuple[BrkClient, list[str]]:
    """A BRK client whose every request fails, and the paths it was asked for."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        raise httpx.ConnectError("network is blocked in this test", request=request)

    return BrkClient(httpx.Client(transport=httpx.MockTransport(handler))), seen


def synced(directory: Path, configured: Rules) -> Path:
    """One sync of the golden fixtures at NOW under `configured`; returns the store path."""
    path = directory / "onchain.sqlite"
    transport, _ = brk_transport(urpd_dir=GOLDEN)
    client = BrkClient(httpx.Client(transport=transport), clock=lambda: NOW)
    assert OnchainSync(OnchainStore(path), client, rules=configured).run_once(now=NOW)
    return path


def stored(store: OnchainStore) -> dict[str, tuple[dict[str, Any], datetime]]:
    """Every derived payload, parsed, with the time it was computed."""
    found: dict[str, tuple[dict[str, Any], datetime]] = {}
    for name in ROUTES:
        derived = store.derived(name)
        assert derived is not None, name
        found[name] = (json.loads(derived[0]), derived[1])
    return found


def labels(views: dict[str, dict[str, Any]]) -> dict[str, tuple[list[str], bool]]:
    return {name: (view["rules"], view["rules_pending"]) for name, view in views.items()}


def read_views(path: Path, configured: Rules) -> dict[str, dict[str, Any]]:
    """The four views of a router configured with `configured`; it cannot reach BRK."""
    client, seen = blocked_client()
    app = FastAPI()
    app.include_router(
        create_router(path, client, rules=configured, start_worker=False, clock=lambda: NOW)
    )
    with TestClient(app) as http:
        views = {name: http.get(f"{PREFIX}/{route}").json() for name, route in ROUTES.items()}
    assert seen == []
    return views


def test_payloads_are_stored_with_the_rules_they_were_derived_under(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setitem(rules.IMPLEMENTED, "cycle", frozenset({"O1", "O4"}))
    monkeypatch.setitem(rules.IMPLEMENTED, "pressure", frozenset({"O3", "O2"}))
    path = synced(tmp_path, frozenset({"O4", "O3", "O2", "O6"}))

    payloads = stored(OnchainStore(path))
    assert {name: payload["rules"] for name, (payload, _) in payloads.items()} == {
        "cycle": ["O4"],
        "levels": [],
        "costbasis": [],
        "pressure": ["O2", "O3"],
    }
    assert labels(read_views(path, frozenset({"O4", "O3", "O2", "O6"}))) == {
        "cycle": (["O4"], False),
        "levels": ([], False),
        "costbasis": ([], False),
        "pressure": (["O2", "O3"], False),
    }


def test_payloads_stored_before_rules_existed_read_as_no_rules(tmp_path: Path):
    path = synced(tmp_path, frozenset())
    store = OnchainStore(path)
    for name, (payload, computed_at) in stored(store).items():
        assert payload.pop("rules") == []
        # Nor was the newest day stored then.
        payload.pop("latest_day", None)
        old = json.dumps(payload)
        store.save_derived(name, old, computed_at)
        assert PAYLOADS[name].model_validate_json(old).rules == []
    cycle = store.derived("cycle")
    assert cycle is not None
    assert Cycle.model_validate_json(cycle[0]).latest_day is None

    # Only the cycle has rules implemented, so under every rule only it waits to be derived again.
    views = read_views(path, ALL_RULES)
    assert labels(views) == {
        "cycle": ([], True),
        "levels": ([], False),
        "costbasis": ([], False),
        "pressure": ([], False),
    }
    # Without the newest day, freshness follows `as_of`, the fixture's last day.
    assert (views["cycle"]["data_state"], views["cycle"]["as_of"]) == ("fresh", "2026-10-16")
    assert views["cycle"]["state"] == "breakout"
    assert views["levels"]["lines"]
    assert views["costbasis"]["buckets"]
    assert views["pressure"]["loss"]


def test_empty_store_has_no_rules_and_nothing_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setitem(rules.IMPLEMENTED, "cycle", frozenset({"O1"}))
    views = read_views(tmp_path / "onchain.sqlite", ALL_RULES)

    assert {name: view["data_state"] for name, view in views.items()} == {
        name: "unavailable" for name in ROUTES
    }
    assert labels(views) == {name: ([], False) for name in ROUTES}


def test_restart_with_other_rules_rederives_from_the_store_only(tmp_path: Path):
    path = synced(tmp_path, frozenset())
    store = OnchainStore(path)
    before = stored(store)
    due = store.state()["next_due"]
    # O4 changes no number on this data (no day is missing), so only the label may change.
    configured: Rules = frozenset({"O4"})

    # Restarted under O4, before the worker re-derived: the label is still the payload's.
    assert labels(read_views(path, configured)) == {
        "cycle": ([], True),
        "levels": ([], False),
        "costbasis": ([], False),
        "pressure": ([], False),
    }
    assert store.state()["next_due"] == due

    client, seen = blocked_client()
    assert OnchainSync(store, client, rules=configured).rederive_if_rules_changed(RESTART)

    assert labels(read_views(path, configured)) == {
        "cycle": (["O4"], False),
        "levels": ([], False),
        "costbasis": ([], False),
        "pressure": ([], False),
    }
    after = stored(store)
    # Each payload keeps the time it was computed; only the cycle's label changed.
    assert {name: at for name, (_, at) in after.items()} == {name: NOW for name in ROUTES}
    assert after["cycle"][0] == {**before["cycle"][0], "rules": ["O4"]}
    for name in ("levels", "costbasis", "pressure"):
        assert after[name][0] == before[name][0]
    # The fetches the new rules need happen at once.
    assert store.state()["next_due"] == timestamp(RESTART)
    assert seen == []

    # Once they agree, there is nothing to do.
    assert not OnchainSync(store, client, rules=configured).rederive_if_rules_changed(
        RESTART + timedelta(minutes=1)
    )
    assert store.state()["next_due"] == timestamp(RESTART)
    assert seen == []


def test_a_rule_unrelated_to_a_view_does_not_make_it_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setitem(rules.IMPLEMENTED, "cycle", frozenset({"O4"}))
    monkeypatch.setitem(rules.IMPLEMENTED, "pressure", frozenset({"O2"}))
    path = synced(tmp_path, frozenset({"O2", "O4"}))
    store = OnchainStore(path)
    due = store.state()["next_due"]
    client, seen = blocked_client()

    # O1 and O5 are not implemented for any view, so turning them on changes nothing.
    wider: Rules = frozenset({"O1", "O2", "O4", "O5"})
    assert labels(read_views(path, wider)) == {
        "cycle": (["O4"], False),
        "levels": ([], False),
        "costbasis": ([], False),
        "pressure": (["O2"], False),
    }
    assert not OnchainSync(store, client, rules=wider).rederive_if_rules_changed(RESTART)
    assert store.state()["next_due"] == due

    # Turning O2 off concerns the pressure only.
    assert labels(read_views(path, frozenset({"O4"}))) == {
        "cycle": (["O4"], False),
        "levels": ([], False),
        "costbasis": ([], False),
        "pressure": (["O2"], True),
    }
    assert seen == []


def test_rederive_skips_views_that_were_never_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setitem(rules.IMPLEMENTED, "pressure", frozenset({"O2"}))
    path = synced(tmp_path, frozenset())
    store = OnchainStore(path)
    for name in ("cycle", "levels", "costbasis"):
        store.clear_derived(name)
    client, seen = blocked_client()

    assert OnchainSync(store, client, rules=frozenset({"O2"})).rederive_if_rules_changed(RESTART)

    # Without a day1 payload there is no time to derive the day1 views at, so none appears.
    assert [store.derived(name) for name in ("cycle", "levels", "costbasis")] == [None] * 3
    pressure = store.derived("pressure")
    assert pressure is not None
    assert (json.loads(pressure[0])["rules"], pressure[1]) == (["O2"], NOW)
    assert seen == []


def test_empty_store_is_not_rederived(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(rules.IMPLEMENTED, "cycle", frozenset({"O1"}))
    store = OnchainStore(tmp_path / "onchain.sqlite")
    client, seen = blocked_client()

    assert not OnchainSync(store, client, rules=ALL_RULES).rederive_if_rules_changed(RESTART)
    assert store.state()["next_due"] is None
    assert seen == []


def test_rederive_takes_the_closed_day_from_the_stored_time(tmp_path: Path):
    path = synced(tmp_path, frozenset())
    store = OnchainStore(path)
    client, seen = blocked_client()
    # Restarted the next day after 02:00, when 10-16 is closed; at NOW, when the payloads were
    # derived, it was not.
    restart = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)

    assert OnchainSync(store, client, rules=frozenset({"O1"})).rederive_if_rules_changed(restart)

    derived = store.derived("cycle")
    assert derived is not None and derived[1] == NOW
    cycle = Cycle.model_validate_json(derived[0])
    assert (cycle.rules, cycle.as_of, cycle.day, cycle.latest_day) == (
        ["O1"],
        date(2026, 10, 15),
        23,
        date(2026, 10, 16),
    )
    assert seen == []


def test_failed_rederive_still_makes_the_next_refresh_due_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    path = synced(tmp_path, frozenset())
    store = OnchainStore(path)
    before = stored(store)
    client, seen = blocked_client()
    sync = OnchainSync(store, client, rules=frozenset({"O4"}))

    def fail() -> None:
        raise RuntimeError("secret value 123")

    monkeypatch.setattr(sync, "derive_from_store", fail)

    with pytest.raises(RuntimeError):
        sync.rederive_if_rules_changed(RESTART)

    # The payloads stay as they were, and the refresh that derives them anyway is due at once.
    assert stored(store) == before
    assert store.state()["next_due"] == timestamp(RESTART)

    # The worker logs only a fixed code and goes on to that refresh.
    ran = threading.Event()

    def run_once(*, now: datetime | None = None) -> bool:
        ran.set()
        return False

    monkeypatch.setattr(sync, "run_once", run_once)
    with caplog.at_level(logging.ERROR, logger="wheelhouse.onchain"):
        sync.start()
        try:
            assert ran.wait(5)
        finally:
            sync.stop()
    assert [record.getMessage() for record in caplog.records] == ["onchain_rederive_failed"]
    assert "secret" not in caplog.text
    assert seen == []


def test_worker_rederives_before_its_first_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    client, _ = blocked_client()
    sync = OnchainSync(OnchainStore(tmp_path / "onchain.sqlite"), client, rules=frozenset())
    order: list[str] = []
    ran = threading.Event()

    def rederive(now: datetime) -> bool:
        order.append("rederive")
        return False

    def run_once(*, now: datetime | None = None) -> bool:
        order.append("run")
        ran.set()
        return False

    monkeypatch.setattr(sync, "rederive_if_rules_changed", rederive)
    monkeypatch.setattr(sync, "run_once", run_once)
    sync.start()
    try:
        assert ran.wait(5)
    finally:
        sync.stop()
    assert order[:2] == ["rederive", "run"]
    assert order.count("rederive") == 1


def test_derive_command_rederives_a_copy_without_brk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setitem(rules.IMPLEMENTED, "cycle", frozenset({"O1"}))
    monkeypatch.setitem(rules.IMPLEMENTED, "pressure", frozenset({"O1", "O3"}))
    live = tmp_path / "live"
    synced(live, frozenset())
    copy = tmp_path / "copy"
    copy.mkdir()
    shutil.copy(live / "onchain.sqlite", copy / "onchain.sqlite")
    requests: list[str] = []

    def refuse(self: BrkClient, path: str, params: dict[str, str] | None) -> httpx.Response:
        requests.append(path)
        raise httpx.ConnectError("network is blocked in this test")

    monkeypatch.setattr(BrkClient, "_send", refuse)
    monkeypatch.delenv("WHEELHOUSE_RULES", raising=False)

    derive.main(["--data-dir", str(copy), "--rules", " o3,O1 "])

    copied = stored(OnchainStore(copy / "onchain.sqlite"))
    assert {name: payload["rules"] for name, (payload, _) in copied.items()} == {
        "cycle": ["O1"],
        "levels": [],
        "costbasis": [],
        "pressure": ["O1", "O3"],
    }
    assert {name: at for name, (_, at) in copied.items()} == {name: NOW for name in ROUTES}
    # The original store is left as it was.
    original = stored(OnchainStore(live / "onchain.sqlite"))
    assert {name: payload["rules"] for name, (payload, _) in original.items()} == {
        name: [] for name in ROUTES
    }
    # Each view with the rules its payload recorded, not the rules asked for.
    assert capsys.readouterr().out == "derived cycle=O1 levels=v1 costbasis=v1 pressure=O1,O3\n"

    # Without --rules, WHEELHOUSE_RULES decides.
    monkeypatch.setenv("WHEELHOUSE_RULES", "v1")
    derive.main(["--data-dir", str(copy)])
    copied = stored(OnchainStore(copy / "onchain.sqlite"))
    assert {name: payload["rules"] for name, (payload, _) in copied.items()} == {
        name: [] for name in ROUTES
    }
    assert capsys.readouterr().out == "derived cycle=v1 levels=v1 costbasis=v1 pressure=v1\n"
    assert requests == []


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--rules", "O1"],
        ["--data-dir", "{copy}", "--rules", "v1,O1"],
        ["--data-dir", "{copy}", "--rules", "O9"],
        ["--data-dir", "{missing}"],
    ],
)
def test_derive_command_rejects_bad_arguments(tmp_path: Path, argv: list[str]):
    synced(tmp_path, frozenset())
    paths = {"copy": str(tmp_path), "missing": str(tmp_path / "missing")}
    with pytest.raises(SystemExit) as exited:
        derive.main([arg.format(**paths) for arg in argv])
    assert exited.value.code == 2
    assert not (tmp_path / "missing").exists()


def test_derive_command_help_says_it_is_for_a_copy(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit):
        derive.main(["--help"])
    assert "copy" in capsys.readouterr().out


def test_create_app_rules_default_to_the_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(rules.IMPLEMENTED, "cycle", frozenset({"O1"}))
    synced(tmp_path, frozenset())
    client, seen = blocked_client()

    def cycle_label(**options: Any) -> tuple[list[str], bool]:
        app = create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client, **options)
        with TestClient(app) as http:
            view = http.get(f"{PREFIX}/cycle").json()
        return view["rules"], view["rules_pending"]

    monkeypatch.delenv("WHEELHOUSE_RULES", raising=False)
    assert cycle_label() == ([], True)
    assert cycle_label(rules=frozenset()) == ([], False)
    monkeypatch.setenv("WHEELHOUSE_RULES", "v1")
    assert cycle_label() == ([], False)
    assert cycle_label(rules=frozenset({"O1"})) == ([], True)
    monkeypatch.setenv("WHEELHOUSE_RULES", "O7")
    with pytest.raises(ValueError, match="WHEELHOUSE_RULES"):
        create_app(tmp_path / "m.sqlite", start_worker=False, brk_client=client)
    assert seen == []
