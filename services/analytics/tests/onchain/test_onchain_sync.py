import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from onchain_fixture import brk_transport

from wheelhouse_service.onchain.brk import DAY1_SERIES, START, BrkClient
from wheelhouse_service.onchain.cycle import Cycle
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import OnchainSync

NOW = datetime(2026, 10, 16, 10, 40, tzinfo=UTC)
LINES = {"true_mean", "short_term", "average", "long_term", "median"}


def instant(value: str | None) -> datetime:
    assert value is not None
    return datetime.fromisoformat(value)


def sync_for(store: OnchainStore, transport: httpx.MockTransport, now: datetime) -> OnchainSync:
    return OnchainSync(store, BrkClient(httpx.Client(transport=transport), clock=lambda: now))


def run(store: OnchainStore, transport: httpx.MockTransport, now: datetime) -> bool:
    return sync_for(store, transport, now).run_once(now=now)


def rewritten(
    transport: httpx.MockTransport, edit: Callable[[str, dict[str, Any]], None]
) -> httpx.MockTransport:
    """Wrap `transport` so `edit(series name, response item)` can alter each bulk series."""

    def handler(request: httpx.Request) -> httpx.Response:
        response = transport.handler(request)
        if request.url.path != "/api/series/bulk":
            return response
        names = request.url.params["series"].split(",")
        body = json.loads(response.content)
        for name, item in zip(names, body, strict=True):
            edit(name, item)
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


def cycle_of(store: OnchainStore) -> Cycle:
    derived = store.derived("cycle")
    assert derived is not None
    return Cycle.model_validate_json(derived[0])


def levels_of(store: OnchainStore) -> dict[str, Any]:
    derived = store.derived("levels")
    assert derived is not None
    levels: dict[str, Any] = json.loads(derived[0])
    return levels


def strings(value: str | None) -> list[str]:
    assert value is not None
    parsed: list[str] = json.loads(value)
    return parsed


def bulk_calls(calls: list[tuple[str, dict[str, str]]]) -> list[dict[str, str]]:
    return [params for path, params in calls if path == "/api/series/bulk"]


def test_first_run_backfills_and_derives(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, calls = brk_transport()

    assert run(store, transport, NOW) is True

    assert calls[0][0] == "/version"
    assert all(params["start"] == START.isoformat() for params in bulk_calls(calls))
    assert {name for params in bulk_calls(calls) for name in params["series"].split(",")} == set(
        DAY1_SERIES
    )
    cycle = cycle_of(store)
    assert (cycle.state, cycle.as_of) == ("breakout", date(2026, 10, 16))
    levels = levels_of(store)
    assert set(levels) == {"as_of", "urpd_date", "onchain_close", "lines"}
    assert {line["name"] for line in levels["lines"]} == LINES
    assert instant(levels["as_of"]) == datetime(2026, 10, 16, tzinfo=UTC)
    assert levels["urpd_date"] == "2026-10-16"
    assert levels["onchain_close"] == 82154.25
    state = store.state()
    assert state["brk_version"] == "0.12.2"
    assert state["refreshing"] == "false"
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == NOW
    assert instant(state["next_due"]) == datetime(2026, 10, 16, 11, 12, tzinfo=UTC)
    assert strings(state["missing_series"]) == []
    assert strings(state["reasons"]) == []


def test_not_due_does_nothing_until_next_slot(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, calls = brk_transport()
    assert run(store, transport, NOW) is True
    seen = len(calls)

    assert run(store, transport, datetime(2026, 10, 16, 11, 11, 59, tzinfo=UTC)) is False
    assert len(calls) == seen

    slot = datetime(2026, 10, 16, 11, 12, tzinfo=UTC)
    assert run(store, transport, slot) is True
    assert len(calls) > seen
    # A run exactly on the slot is not scheduled for the same slot again.
    assert instant(store.state()["next_due"]) == slot + timedelta(hours=1)


def test_incremental_run_starts_three_positions_back(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert [store.last_position(name, "day1") for name in DAY1_SERIES] == [6497] * 6
    # One series is behind, and another ends with NULLs; both must be covered by the overlap.
    with store.connection() as db:
        db.execute("DELETE FROM series WHERE series='sth_realized_price' AND position>6487")
        db.execute("UPDATE series SET value=NULL WHERE series='true_market_mean' AND position>6495")
    starts = {name: store.last_position(name, "day1") - 3 for name in DAY1_SERIES}
    assert starts["sth_realized_price"] == 6484
    assert starts["true_market_mean"] == 6494

    later = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    incremental, calls = brk_transport()
    assert run(store, incremental, later) is True

    bulk = bulk_calls(calls)
    assert {name for params in bulk for name in params["series"].split(",")} == set(DAY1_SERIES)
    for params in bulk:
        for name in params["series"].split(","):
            assert params["start"] == str(starts[name])
    assert [store.last_position(name, "day1") for name in DAY1_SERIES] == [6497] * 6
    assert [value for _, value in store.read_series("true_market_mean", "day1")][-1] is not None
    assert [value for _, value in store.read_series("sth_realized_price", "day1")][-1] is not None
    assert instant(store.state()["last_success_at"]) == later
    assert instant(store.state()["next_due"]) == datetime(2026, 10, 16, 12, 12, tzinfo=UTC)


def test_series_version_change_refetches_only_that_series(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    with store.connection() as db:
        db.execute("INSERT INTO series VALUES('price_close','day1',1000,1.0,'x')")
        db.execute("INSERT INTO series VALUES('realized_price','day1',1000,1.0,'x')")
    stored = store.series_version("price_close", "day1")
    assert stored is not None

    def bump(name: str, item: dict[str, Any]) -> None:
        if name == "price_close":
            item["version"] = stored + 1

    later = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    inner, calls = brk_transport()
    assert run(store, rewritten(inner, bump), later) is True

    refetch = [params for params in bulk_calls(calls) if params["start"] == START.isoformat()]
    assert [params["series"] for params in refetch] == ["price_close"]
    assert store.series_version("price_close", "day1") == stored + 1
    # Replaced as a whole, so the planted row is gone; the other series were only merged.
    assert len(store.read_series("price_close", "day1")) == 5037
    assert len(store.read_series("realized_price", "day1")) == 5038


def test_version_change_failure_keeps_old_data(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    with store.connection() as db:
        db.execute("INSERT INTO series VALUES('price_close','day1',1000,1.0,'x')")
    before = {name: store.read_series(name, "day1") for name in DAY1_SERIES}
    cycle, levels = store.derived("cycle"), store.derived("levels")

    second = NOW + timedelta(hours=1)
    failing, _ = brk_transport(version="0.13.0", fail_paths={"/api/series"})
    assert run(store, failing, second) is True

    state = store.state()
    assert state["refreshing"] == "true"
    assert state["last_error"] == "brk_unavailable"
    assert state["brk_version"] == "0.12.2"
    assert instant(state["next_due"]) == second + timedelta(minutes=5)
    assert instant(state["last_success_at"]) == NOW
    assert "brk_unavailable" in strings(state["reasons"])
    assert {name: store.read_series(name, "day1") for name in DAY1_SERIES} == before
    assert (store.derived("cycle"), store.derived("levels")) == (cycle, levels)

    third = second + timedelta(minutes=5)
    healthy, _ = brk_transport(version="0.13.0")
    assert run(store, healthy, third) is True

    state = store.state()
    assert state["brk_version"] == "0.13.0"
    assert state["refreshing"] == "false"
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == third
    assert "brk_unavailable" not in strings(state["reasons"])
    # Replaced as a whole: the planted row is gone.
    assert len(store.read_series("price_close", "day1")) == 5037


def test_urpd_failure_after_replacement_still_derives_and_does_not_repeat_it(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")

    def drop_today(name: str, item: dict[str, Any]) -> None:
        item["data"] = item["data"][:-1]
        item["end"] -= 1

    transport, _ = brk_transport()
    run(store, rewritten(transport, drop_today), NOW)
    assert cycle_of(store).as_of == date(2026, 10, 15)

    second = NOW + timedelta(hours=1)
    no_urpd, _ = brk_transport(version="0.13.0", fail_paths={"/api/urpd"})
    assert run(store, no_urpd, second) is True

    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == second + timedelta(minutes=5)
    # The series were replaced, so the new version is recorded and nothing is refreshing.
    assert state["brk_version"] == "0.13.0"
    assert state["refreshing"] == "false"
    # Not a full success, so the last success is unchanged.
    assert instant(state["last_success_at"]) == NOW
    # The fresh series were still derived, with the snapshot stored by the first run.
    assert cycle_of(store).as_of == date(2026, 10, 16)
    cycle = store.derived("cycle")
    assert cycle is not None and cycle[1] == second
    assert instant(levels_of(store)["as_of"]) == datetime(2026, 10, 16, tzinfo=UTC)

    third = second + timedelta(minutes=5)
    healthy, calls = brk_transport(version="0.13.0")
    assert run(store, healthy, third) is True

    assert all(params["start"] != START.isoformat() for params in bulk_calls(calls))
    assert store.state()["last_error"] is None
    assert instant(store.state()["last_success_at"]) == third


def test_urpd_outage_uses_latest_stored_snapshot(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    snapshot, _ = brk_transport(urpd_dates={date(2026, 10, 15)})
    run(store, snapshot, NOW)

    second = NOW + timedelta(hours=1)
    outage, _ = brk_transport(fail_paths={"/api/urpd"})
    assert run(store, outage, second) is True

    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == second + timedelta(minutes=5)
    assert instant(state["last_success_at"]) == NOW
    assert strings(state["reasons"]) == ["brk_unavailable"]
    levels = levels_of(store)
    assert levels["urpd_date"] == "2026-10-15"
    assert levels["onchain_close"] == 82154.25
    assert {line["name"] for line in levels["lines"]} == LINES
    derived = store.derived("levels")
    assert derived is not None and derived[1] == second

    third = second + timedelta(minutes=5)
    healthy, _ = brk_transport()
    assert run(store, healthy, third) is True

    assert levels_of(store)["urpd_date"] == "2026-10-16"
    assert strings(store.state()["reasons"]) == []
    assert store.state()["last_error"] is None


def test_urpd_outage_without_snapshot_gives_four_lines(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    outage, _ = brk_transport(fail_paths={"/api/urpd"})

    assert run(store, outage, NOW) is True

    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == NOW + timedelta(minutes=5)
    assert state["last_success_at"] is None
    assert state["refreshing"] == "false"
    assert strings(state["reasons"]) == ["urpd_missing", "brk_unavailable"]
    assert cycle_of(store).state == "breakout"
    levels = levels_of(store)
    assert levels["urpd_date"] is None
    assert {line["name"] for line in levels["lines"]} == LINES - {"median"}


def test_refreshing_clears_when_brk_returns_to_the_old_version(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)

    second = NOW + timedelta(hours=1)
    failing, _ = brk_transport(version="0.13.0", fail_paths={"/api/series"})
    run(store, failing, second)
    assert store.state()["refreshing"] == "true"

    third = second + timedelta(minutes=5)
    reverted, _ = brk_transport(version="0.12.2")
    assert run(store, reverted, third) is True

    state = store.state()
    assert state["refreshing"] == "false"
    assert state["brk_version"] == "0.12.2"
    assert state["last_error"] is None


def test_empty_full_refetch_keeps_old_series(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    before = store.read_series("realized_price", "day1")
    version = store.series_version("realized_price", "day1")

    def empty(name: str, item: dict[str, Any]) -> None:
        if name == "realized_price":
            item["version"] += 1
            item["data"] = []

    later = NOW + timedelta(hours=1)
    inner, _ = brk_transport(version="0.13.0")
    assert run(store, rewritten(inner, empty), later) is True

    assert store.read_series("realized_price", "day1") == before
    assert store.series_version("realized_price", "day1") == version
    state = store.state()
    assert strings(state["missing_series"]) == ["realized_price"]
    assert "series_missing:realized_price" in strings(state["reasons"])
    assert state["brk_version"] == "0.13.0"
    assert state["refreshing"] == "false"
    # The other series were replaced, and levels are still served from the kept data.
    assert {line["name"] for line in levels_of(store)["lines"]} == LINES


def test_urpd_falls_back_to_yesterday_then_reports_missing(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    yesterday, _ = brk_transport(urpd_dates={date(2026, 10, 15)})
    assert run(store, yesterday, NOW) is True

    levels = levels_of(store)
    assert levels["urpd_date"] == "2026-10-15"
    assert {line["name"] for line in levels["lines"]} == LINES
    assert "urpd_missing" not in strings(store.state()["reasons"])

    none, _ = brk_transport(urpd_dates=set())
    later = NOW + timedelta(hours=1)
    assert run(store, none, later) is True

    levels = levels_of(store)
    assert levels["urpd_date"] is None
    assert levels["onchain_close"] is None
    assert {line["name"] for line in levels["lines"]} == LINES - {"median"}
    assert "urpd_missing" in strings(store.state()["reasons"])


def test_missing_series_clears_levels_but_keeps_cycle(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport(missing={"lth_realized_price"})

    assert run(store, transport, NOW) is True

    state = store.state()
    assert strings(state["missing_series"]) == ["lth_realized_price"]
    assert strings(state["reasons"]) == ["series_missing:lth_realized_price"]
    assert store.derived("levels") is None
    assert store.read_series("lth_realized_price", "day1") == []
    assert cycle_of(store).state == "breakout"
    assert state["last_error"] is None


def test_non_retryable_error_waits_for_next_slot(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    rejecting = httpx.MockTransport(lambda request: httpx.Response(400))

    assert run(store, rejecting, NOW) is True

    state = store.state()
    assert state["last_error"] == "brk_bad_request"
    assert instant(state["next_due"]) == datetime(2026, 10, 16, 11, 12, tzinfo=UTC)
    assert state["last_success_at"] is None
    assert store.derived("cycle") is None


def test_unexpected_error_is_recorded_and_not_retried_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()

    def boom(*args: object) -> None:
        raise RuntimeError("secret value 123")

    monkeypatch.setattr(OnchainSync, "_derive", boom)

    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert run(store, transport, NOW) is True

    state = store.state()
    assert state["last_error"] == "sync_failed"
    assert instant(state["next_due"]) == datetime(2026, 10, 16, 11, 12, tzinfo=UTC)
    assert state["last_success_at"] is None
    assert "onchain_sync_failed code=sync_failed" in caplog.text
    assert "secret" not in caplog.text


def test_worker_thread_runs_and_stops_promptly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    sync = sync_for(store, transport, NOW)
    ran = threading.Event()

    def run_once(*, now: datetime | None = None) -> bool:
        ran.set()
        return False

    monkeypatch.setattr(sync, "run_once", run_once)
    sync.start()
    try:
        assert ran.wait(5)
        assert sync.thread is not None
        assert sync.thread.name == "wheelhouse-onchain"
        assert sync.thread.daemon
    finally:
        sync.stop()

    assert sync.thread is not None
    assert not sync.thread.is_alive()
