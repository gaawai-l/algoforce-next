import json
import logging
import re
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from onchain_fixture import brk_transport, load_urpd

from wheelhouse_service.onchain.brk import (
    DAY1_SERIES,
    HOUR1_BACKFILL,
    HOUR1_SERIES,
    START,
    BrkClient,
)
from wheelhouse_service.onchain.costbasis import PAST_DAYS, StoredCostBasis
from wheelhouse_service.onchain.cycle import Cycle
from wheelhouse_service.onchain.pressure import Pressure
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import URPD_SET, OnchainSync

NOW = datetime(2026, 10, 16, 10, 40, tzinfo=UTC)
LINES = {"true_mean", "short_term", "average", "long_term", "median"}
# The cost-basis golden sample: unlike the P1 fixtures, it has its own snapshot for each past day.
GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-16T1829Z"
D = date(2026, 10, 16)


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


def pressure_of(store: OnchainStore) -> Pressure:
    derived = store.derived("pressure")
    assert derived is not None
    return Pressure.model_validate_json(derived[0])


def costbasis_of(store: OnchainStore) -> StoredCostBasis:
    derived = store.derived("costbasis")
    assert derived is not None
    return StoredCostBasis.model_validate_json(derived[0])


def bucket_widths(store: OnchainStore) -> list[int]:
    return [bucket.bucket for bucket in costbasis_of(store).buckets]


def urpd_calls(calls: list[tuple[str, dict[str, str]]]) -> list[tuple[str, str, str]]:
    """The URPD requests, in order, as (cohort, date, agg)."""
    found = []
    for path, params in calls:
        if path.startswith("/api/urpd/"):
            _, _, _, cohort, day = path.split("/")
            found.append((cohort, day, params["agg"]))
    return found


def same_day(day: date) -> list[tuple[str, str, str]]:
    """The requests for the nine snapshots of `day`, in the order they are made."""
    return [(cohort, day.isoformat(), agg) for cohort, agg in URPD_SET]


def past_of(day: date) -> list[tuple[str, str, str]]:
    """The requests for the past snapshots of D = `day`, in the order they are made."""
    return [
        (cohort, (day - timedelta(days=n)).isoformat(), agg)
        for n in PAST_DAYS
        for cohort, agg in URPD_SET
    ]


def urpd_rows(store: OnchainStore) -> set[tuple[str, str, str]]:
    with store.connection() as db:
        return {tuple(row) for row in db.execute("SELECT cohort, day, agg FROM urpd")}


def strings(value: str | None) -> list[str]:
    assert value is not None
    parsed: list[str] = json.loads(value)
    return parsed


def bulk_calls(calls: list[tuple[str, dict[str, str]]]) -> list[dict[str, str]]:
    return [params for path, params in calls if path == "/api/series/bulk"]


def day1_calls(calls: list[tuple[str, dict[str, str]]]) -> list[dict[str, str]]:
    return [params for params in bulk_calls(calls) if params["index"] == "day1"]


def hour1_calls(calls: list[tuple[str, dict[str, str]]]) -> list[dict[str, str]]:
    """The hour1 series requests. None of them may start at a date: that would ask for years."""
    found = [params for params in bulk_calls(calls) if params["index"] == "hour1"]
    for params in found:
        assert re.fullmatch(r"-?\d+", params["start"]), params
    return found


def requested(calls: list[dict[str, str]]) -> set[str]:
    return {name for params in calls for name in params["series"].split(",")}


def test_first_run_backfills_and_derives(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, calls = brk_transport()

    assert run(store, transport, NOW) is True

    assert calls[0][0] == "/version"
    assert all(params["start"] == START.isoformat() for params in day1_calls(calls))
    assert requested(day1_calls(calls)) == set(DAY1_SERIES)
    assert requested(hour1_calls(calls)) == set(HOUR1_SERIES)
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

    bulk = day1_calls(calls)
    assert requested(bulk) == set(DAY1_SERIES)
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
        # `price_close` is also an hour1 series; only the day1 one changes version here.
        if name == "price_close" and item["index"] == "day1":
            item["version"] = stored + 1

    later = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    inner, calls = brk_transport()
    assert run(store, rewritten(inner, bump), later) is True

    refetch = [params for params in day1_calls(calls) if params["start"] == START.isoformat()]
    assert [params["series"] for params in refetch] == ["price_close"]
    assert all(params["start"] != str(-HOUR1_BACKFILL) for params in hour1_calls(calls))
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
    # A URPD failure is not a series failure: the shared reasons stay clean.
    assert strings(state["reasons"]) == []
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

    assert all(params["start"] != START.isoformat() for params in day1_calls(calls))
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
    # The error is on `last_error`; the shared reasons are not touched by a URPD-stage failure.
    assert strings(state["reasons"]) == []
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


@pytest.mark.parametrize(
    ("snapshot_day", "accepted"),
    [
        (date(2026, 10, 16), True),
        (date(2026, 10, 15), True),
        (date(2026, 10, 14), False),
        (date(2026, 10, 13), False),
    ],
)
def test_urpd_outage_accepts_only_a_snapshot_from_the_last_two_days(
    tmp_path: Path, snapshot_day: date, accepted: bool
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    store.save_urpd(load_urpd("all").model_copy(update={"date": snapshot_day}), NOW)
    outage, _ = brk_transport(fail_paths={"/api/urpd"})

    assert run(store, outage, NOW) is True

    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == NOW + timedelta(minutes=5)
    levels = levels_of(store)
    if accepted:
        assert levels["urpd_date"] == snapshot_day.isoformat()
        assert levels["onchain_close"] == 82154.25
        assert {line["name"] for line in levels["lines"]} == LINES
        assert strings(state["reasons"]) == []
    else:
        # An older snapshot is treated as no snapshot: no median, and no date that looks current.
        assert levels["urpd_date"] is None
        assert levels["onchain_close"] is None
        assert {line["name"] for line in levels["lines"]} == LINES - {"median"}
        assert strings(state["reasons"]) == ["urpd_missing"]


def test_urpd_outage_without_snapshot_gives_four_lines(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    outage, _ = brk_transport(fail_paths={"/api/urpd"})

    assert run(store, outage, NOW) is True

    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == NOW + timedelta(minutes=5)
    assert state["last_success_at"] is None
    assert state["refreshing"] == "false"
    assert strings(state["reasons"]) == ["urpd_missing"]
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
    assert strings(state["missing_series"]) == ["day1:realized_price"]
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
    assert strings(state["missing_series"]) == ["day1:lth_realized_price"]
    assert strings(state["reasons"]) == ["series_missing:lth_realized_price"]
    assert store.derived("levels") is None
    assert store.read_series("lth_realized_price", "day1") == []
    assert cycle_of(store).state == "breakout"
    assert state["last_error"] is None


def test_first_run_backfills_hour1_from_minus_3000(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, calls = brk_transport()

    assert run(store, transport, NOW) is True

    hour1 = hour1_calls(calls)
    assert all(params["start"] == str(-HOUR1_BACKFILL) for params in hour1)
    assert requested(hour1) == set(HOUR1_SERIES)
    # 11 series of 3,000 points are over the weight cap in one request, so they are split in two.
    assert len(hour1) == 2
    assert [store.last_position(name, "hour1") for name in HOUR1_SERIES] == [155937] * 11
    pressure = pressure_of(store)
    assert pressure.last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)
    derived = store.derived("pressure")
    assert derived is not None and derived[1] == NOW
    state = store.state()
    assert strings(state["missing_series"]) == []
    assert strings(state["reasons"]) == []
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == NOW


def test_hour1_added_to_existing_day1_store_does_not_refetch_day1(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    # What a store written before hour1 existed looks like.
    with store.connection() as db:
        db.execute("DELETE FROM series WHERE idx='hour1'")
        db.execute("DELETE FROM series_meta WHERE idx='hour1'")
        db.execute("DELETE FROM derived WHERE kind='pressure'")
    day1 = {name: store.read_series(name, "day1") for name in DAY1_SERIES}

    later = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    upgraded, calls = brk_transport()
    assert run(store, upgraded, later) is True

    assert all(params["start"] != START.isoformat() for params in day1_calls(calls))
    assert all(params["start"] == str(-HOUR1_BACKFILL) for params in hour1_calls(calls))
    assert requested(hour1_calls(calls)) == set(HOUR1_SERIES)
    assert {name: store.read_series(name, "day1") for name in DAY1_SERIES} == day1
    assert pressure_of(store).last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)
    assert instant(store.state()["last_success_at"]) == later


def test_incremental_hour1_starts_three_back(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    # One series is behind, and another ends with NULLs; both must be covered by the overlap.
    with store.connection() as db:
        db.execute(
            "DELETE FROM series WHERE series='sth_supply_in_loss' AND idx='hour1' "
            "AND position>155930"
        )
        db.execute(
            "UPDATE series SET value=NULL WHERE series='price_close' AND idx='hour1' "
            "AND position>155934"
        )
    starts = {name: store.last_position(name, "hour1") - 3 for name in HOUR1_SERIES}
    assert starts["sth_supply_in_loss"] == 155927
    assert starts["price_close"] == 155934
    assert starts["sth_supply_in_profit"] == 155934

    later = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    incremental, calls = brk_transport()
    assert run(store, incremental, later) is True

    hour1 = hour1_calls(calls)
    assert requested(hour1) == set(HOUR1_SERIES)
    for params in hour1:
        for name in params["series"].split(","):
            assert params["start"] == str(starts[name])
    assert [store.last_position(name, "hour1") for name in HOUR1_SERIES] == [155937] * 11
    assert store.read_series("price_close", "hour1")[-1][1] is not None
    assert store.read_series("sth_supply_in_loss", "hour1")[-1][1] is not None
    derived = store.derived("pressure")
    assert derived is not None and derived[1] == later


def test_pressure_is_stamped_when_the_hour1_stage_finished(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    inner, _ = brk_transport()
    hour1_done = datetime(2026, 10, 16, 9, 59, tzinfo=UTC)
    done = hour1_done + timedelta(minutes=2)
    ticks = [datetime(2026, 10, 16, 9, 12, tzinfo=UTC)]

    def handler(request: httpx.Request) -> httpx.Response:
        # The hour1 requests end just before the hour boundary, and a slow URPD fetch crosses it.
        if request.url.path == "/api/series/bulk" and request.url.params["index"] == "hour1":
            ticks.append(hour1_done)
        elif request.url.path.startswith("/api/urpd"):
            ticks.append(done)
        return inner.handler(request)

    sync = sync_for(store, httpx.MockTransport(handler), ticks[0])
    assert sync._refresh(ticks[0], lambda: ticks[-1]) is None

    pressure = store.derived("pressure")
    assert pressure is not None and pressure[1] == hour1_done
    cycle, levels = store.derived("cycle"), store.derived("levels")
    assert cycle is not None and cycle[1] == done
    assert levels is not None and levels[1] == done
    assert instant(store.state()["last_success_at"]) == done


def test_hour1_series_version_change_refetches_from_minus_3000(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    with store.connection() as db:
        db.execute("INSERT INTO series VALUES('sth_supply_in_loss','hour1',1000,1.0,'x')")
        db.execute("INSERT INTO series VALUES('sth_supply_in_profit','hour1',1000,1.0,'x')")
    stored = store.series_version("sth_supply_in_loss", "hour1")
    assert stored is not None

    def bump(name: str, item: dict[str, Any]) -> None:
        if name == "sth_supply_in_loss":
            item["version"] = stored + 1

    later = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    inner, calls = brk_transport()
    assert run(store, rewritten(inner, bump), later) is True

    refetch = [p for p in hour1_calls(calls) if p["start"] == str(-HOUR1_BACKFILL)]
    assert [params["series"] for params in refetch] == ["sth_supply_in_loss"]
    assert all(params["start"] != START.isoformat() for params in day1_calls(calls))
    assert store.series_version("sth_supply_in_loss", "hour1") == stored + 1
    # Replaced as a whole, so the planted row is gone; the other series were only merged.
    assert len(store.read_series("sth_supply_in_loss", "hour1")) == 2600
    assert len(store.read_series("sth_supply_in_profit", "hour1")) == 2601
    assert pressure_of(store).last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)


def test_hour1_stage_failure_keeps_cycle_and_levels(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    pressure = store.derived("pressure")
    assert pressure is not None

    second = NOW + timedelta(hours=1)
    failing, calls = brk_transport(fail_index={"hour1"})
    assert run(store, failing, second) is True

    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == second + timedelta(minutes=5)
    # Not a full success, so the last success is unchanged.
    assert instant(state["last_success_at"]) == NOW
    # An hour1 failure is not a series failure: the shared reasons stay clean.
    assert strings(state["reasons"]) == []
    assert state["refreshing"] == "false"
    # The day1 stage and URPD still ran and were derived from.
    cycle = store.derived("cycle")
    assert cycle is not None and cycle[1] == second
    levels = store.derived("levels")
    assert levels is not None and levels[1] == second
    assert levels_of(store)["urpd_date"] == "2026-10-16"
    assert any(path.startswith("/api/urpd") for path, _ in calls)
    # The old pressure stays as it was, with the time it was computed.
    assert store.derived("pressure") == pressure

    third = second + timedelta(minutes=5)
    healthy, _ = brk_transport()
    assert run(store, healthy, third) is True

    assert store.state()["last_error"] is None
    assert instant(store.state()["last_success_at"]) == third
    derived = store.derived("pressure")
    assert derived is not None and derived[1] == third


def test_hour1_stage_failure_on_first_run_leaves_no_pressure(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    failing, _ = brk_transport(fail_index={"hour1"})

    assert run(store, failing, NOW) is True

    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == NOW + timedelta(minutes=5)
    assert state["last_success_at"] is None
    assert strings(state["reasons"]) == []
    assert cycle_of(store).state == "breakout"
    assert {line["name"] for line in levels_of(store)["lines"]} == LINES
    assert store.derived("pressure") is None


def test_hour1_failure_keeps_the_hour1_missing_reason(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    partial, _ = brk_transport(missing={"sth_supply_in_loss"})
    run(store, partial, NOW)
    assert strings(store.state()["reasons"]) == ["series_missing:hour1:sth_supply_in_loss"]

    second = NOW + timedelta(hours=1)
    failing, _ = brk_transport(fail_index={"hour1"})
    assert run(store, failing, second) is True

    # Whether `sth_supply_in_loss` exists is not known from a failed request, so the last answer
    # stands, together with the pressure it led to.
    state = store.state()
    assert strings(state["missing_series"]) == ["hour1:sth_supply_in_loss"]
    assert strings(state["reasons"]) == ["series_missing:hour1:sth_supply_in_loss"]
    assert store.derived("pressure") is None


def test_a_retryable_stage_failure_decides_the_retry_delay(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    inner, _ = brk_transport(fail_paths={"/api/urpd"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/series/bulk" and request.url.params["index"] == "hour1":
            return httpx.Response(400)
        return inner.handler(request)

    assert run(store, httpx.MockTransport(handler), NOW) is True

    # hour1 is rejected for good, but the URPD outage is worth retrying soon.
    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == NOW + timedelta(minutes=5)
    assert cycle_of(store).state == "breakout"


def test_missing_hour1_series_clears_pressure_only(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert store.derived("pressure") is not None

    second = NOW + timedelta(hours=1)
    partial, _ = brk_transport(missing={"sth_supply_in_loss"})
    assert run(store, partial, second) is True

    state = store.state()
    assert strings(state["missing_series"]) == ["hour1:sth_supply_in_loss"]
    assert strings(state["reasons"]) == ["series_missing:hour1:sth_supply_in_loss"]
    assert state["last_error"] is None
    assert store.derived("pressure") is None
    # The data already stored is kept, and the other modules carry on.
    assert len(store.read_series("sth_supply_in_loss", "hour1")) == 2600
    cycle = store.derived("cycle")
    assert cycle is not None and cycle[1] == second
    levels = store.derived("levels")
    assert levels is not None and levels[1] == second
    assert {line["name"] for line in levels_of(store)["lines"]} == LINES

    third = second + timedelta(hours=1)
    healthy, _ = brk_transport()
    assert run(store, healthy, third) is True

    assert strings(store.state()["missing_series"]) == []
    assert strings(store.state()["reasons"]) == []
    assert pressure_of(store).last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)


def test_missing_hour1_series_on_first_run_leaves_no_pressure(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    partial, _ = brk_transport(missing={"price_close"})

    assert run(store, partial, NOW) is True

    # `price_close` is both a day1 and an hour1 series, and the reasons tell the two apart.
    state = store.state()
    assert strings(state["missing_series"]) == ["day1:price_close", "hour1:price_close"]
    assert strings(state["reasons"]) == [
        "series_missing:price_close",
        "series_missing:hour1:price_close",
    ]
    assert store.derived("pressure") is None


def test_urpd_set_is_every_cohort_at_every_bucket_width():
    assert URPD_SET[0] == ("all", "lin500")
    assert len(URPD_SET) == 9
    assert set(URPD_SET) == {
        (cohort, f"lin{bucket}") for cohort in ("all", "sth", "lth") for bucket in (200, 500, 1000)
    }


def test_sync_fetches_nine_snapshots_for_one_day(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, calls = brk_transport(urpd_dir=GOLDEN)

    assert run(store, transport, NOW) is True

    # Today's `all lin500` exists, so D is today and no other day is probed.
    assert urpd_calls(calls) == same_day(D) + past_of(D)
    assert len(past_of(D)) == 36
    cost = costbasis_of(store)
    assert cost.urpd_date == D
    assert cost.lines_as_of == D
    assert cost.snapshot_at == NOW
    assert cost.reasons == []
    assert bucket_widths(store) == [200, 500, 1000]
    # The golden snapshots were used: their close, not the P1 fixture's 82154.25.
    assert {bucket.spot for bucket in cost.buckets} == {81217.6}
    assert urpd_rows(store) == {(c, d, a) for c, d, a in same_day(D) + past_of(D)}
    state = store.state()
    assert state["last_error"] is None
    assert strings(state["reasons"]) == []

    second = NOW + timedelta(hours=1)
    again, calls = brk_transport(urpd_dir=GOLDEN)
    assert run(store, again, second) is True

    # Every past snapshot was fetched after its day was final, so only the nine are asked again.
    assert urpd_calls(calls) == same_day(D)
    derived = store.derived("costbasis")
    assert derived is not None and derived[1] == second
    assert costbasis_of(store).snapshot_at == second


def test_past_snapshot_stored_intraday_is_refetched(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    yesterday = D - timedelta(days=1)
    final = datetime(2026, 10, 16, 2, tzinfo=UTC)
    # One past snapshot was stored a second before its day counted as final, one right at it.
    for cohort, fetched_at in (("sth", final - timedelta(seconds=1)), ("lth", final)):
        snapshot = store.urpd(cohort, yesterday, "lin200")
        assert snapshot is not None
        store.save_urpd(snapshot, fetched_at)

    later = NOW + timedelta(hours=1)
    again, calls = brk_transport()
    assert run(store, again, later) is True

    assert urpd_calls(calls) == same_day(D) + [("sth", "2026-10-15", "lin200")]
    assert store.urpd_fetched_at("sth", yesterday, "lin200") == later
    assert store.urpd_fetched_at("lth", yesterday, "lin200") == final


def test_past_snapshot_error_does_not_fail_the_stage(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    inner, _ = brk_transport()

    def handler(request: httpx.Request) -> httpx.Response:
        # Every past lin200 snapshot fails; D's are served.
        path = request.url.path
        if (
            path.startswith("/api/urpd/")
            and not path.endswith(f"/{D.isoformat()}")
            and request.url.params["agg"] == "lin200"
        ):
            return httpx.Response(500)
        return inner.handler(request)

    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert run(store, httpx.MockTransport(handler), NOW) is True

    state = store.state()
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == NOW
    assert strings(state["reasons"]) == []
    assert bucket_widths(store) == [200, 500, 1000]
    assert costbasis_of(store).reasons == ["urpd_grid_partial:lin200"]
    # One line per failed request, with the error code only.
    assert caplog.text.count("onchain_urpd_past_failed code=brk_unavailable") == 12


def test_all_buckets_missing_still_stores_reasons(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport(urpd_missing=set(URPD_SET[1:]))

    assert run(store, transport, NOW) is True

    cost = costbasis_of(store)
    assert cost.buckets == []
    assert cost.urpd_date == D
    assert cost.lines_as_of == D
    # No bucket width was usable, so this is when `all lin500` was fetched.
    assert cost.snapshot_at == NOW
    assert cost.reasons == [
        "urpd_missing:all:lin200",
        "urpd_missing:sth:lin200",
        "urpd_missing:lth:lin200",
        "urpd_missing:sth:lin500",
        "urpd_missing:lth:lin500",
        "urpd_missing:all:lin1000",
        "urpd_missing:sth:lin1000",
        "urpd_missing:lth:lin1000",
    ]


def test_costbasis_reasons_stay_out_of_shared_reasons(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport(urpd_missing=set(URPD_SET[1:]))

    assert run(store, transport, NOW) is True

    assert costbasis_of(store).reasons
    state = store.state()
    assert strings(state["reasons"]) == []
    assert strings(state["missing_series"]) == []
    assert state["last_error"] is None


def test_missing_snapshot_drops_only_that_bucket(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport(urpd_missing={("sth", "lin200")})

    assert run(store, transport, NOW) is True

    assert bucket_widths(store) == [500, 1000]
    # The past lin200 snapshots of sth are missing too, but an unusable width has no grid.
    assert costbasis_of(store).reasons == ["urpd_missing:sth:lin200"]
    state = store.state()
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == NOW
    assert strings(state["reasons"]) == []


def test_failed_snapshot_keeps_stored_same_day(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)

    second = NOW + timedelta(hours=1)
    failing, _ = brk_transport(urpd_fail={("lth", "lin1000")})
    assert run(store, failing, second) is True

    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == second + timedelta(minutes=5)
    assert instant(state["last_success_at"]) == NOW
    assert "brk_unavailable" not in strings(state["reasons"])
    for kind in ("cycle", "levels", "costbasis"):
        derived = store.derived(kind)
        assert derived is not None and derived[1] == second
    # D's lth lin1000 from the first run is still stored, so every width is usable.
    cost = costbasis_of(store)
    assert bucket_widths(store) == [200, 500, 1000]
    assert cost.reasons == []
    assert cost.urpd_date == D
    # The oldest snapshot in use is that one.
    assert cost.snapshot_at == NOW


def test_hour1_failure_still_derives_costbasis(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    failing, _ = brk_transport(fail_index={"hour1"})

    assert run(store, failing, NOW) is True

    assert store.state()["last_error"] == "brk_unavailable"
    assert store.derived("pressure") is None
    derived = store.derived("costbasis")
    assert derived is not None and derived[1] == NOW
    assert bucket_widths(store) == [200, 500, 1000]
    assert costbasis_of(store).reasons == []


def test_day_rollover_uses_yesterday_for_all(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    # A snapshot of a day no longer needed, which the stage prunes.
    store.save_urpd(load_urpd("all").model_copy(update={"date": date(2026, 10, 14)}), NOW)
    after_midnight = datetime(2026, 10, 17, 0, 30, tzinfo=UTC)
    published = {D, *(D - timedelta(days=n) for n in PAST_DAYS)}
    transport, calls = brk_transport(urpd_dates=published)

    assert run(store, transport, after_midnight) is True

    # Only `all lin500` is asked for today; all nine snapshots are then yesterday's, D.
    assert urpd_calls(calls) == [("all", "2026-10-17", "lin500"), *same_day(D), *past_of(D)]
    cost = costbasis_of(store)
    assert cost.urpd_date == D
    assert bucket_widths(store) == [200, 500, 1000]
    assert cost.reasons == []
    assert levels_of(store)["urpd_date"] == "2026-10-16"
    assert urpd_rows(store) == {(c, d, a) for c, d, a in same_day(D) + past_of(D)}


def test_no_urpd_sends_no_other_requests_and_clears_costbasis(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert store.derived("costbasis") is not None
    stored = urpd_rows(store)
    assert len(stored) == 45

    later = datetime(2026, 10, 18, 10, 40, tzinfo=UTC)
    none, calls = brk_transport(urpd_dates=set())
    assert run(store, none, later) is True

    assert urpd_calls(calls) == [("all", "2026-10-18", "lin500"), ("all", "2026-10-17", "lin500")]
    assert store.derived("costbasis") is None
    # Without D nothing is pruned, although none of these days would be kept.
    assert urpd_rows(store) == stored


def test_missing_lines_clears_costbasis(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert store.derived("costbasis") is not None

    # A snapshot without supply has no median.
    inner, _ = brk_transport()

    def no_supply(request: httpx.Request) -> httpx.Response:
        response = inner.handler(request)
        if request.url.path == f"/api/urpd/all/{D.isoformat()}":
            body = json.loads(response.content)
            body["buckets"] = [{**bucket, "supply": 0.0} for bucket in body["buckets"]]
            return httpx.Response(200, json=body)
        return response

    second = NOW + timedelta(hours=1)
    assert run(store, httpx.MockTransport(no_supply), second) is True

    assert {line["name"] for line in levels_of(store)["lines"]} == LINES - {"median"}
    assert store.derived("costbasis") is None

    third = second + timedelta(hours=1)
    healthy, _ = brk_transport()
    assert run(store, healthy, third) is True
    assert store.derived("costbasis") is not None

    # Without one of the series lines there are no levels at all.
    with store.connection() as db:
        db.execute("DELETE FROM series WHERE series='lth_realized_price'")
    fourth = third + timedelta(hours=1)
    partial, _ = brk_transport(missing={"lth_realized_price"})
    assert run(store, partial, fourth) is True

    assert store.derived("levels") is None
    assert store.derived("costbasis") is None
    assert store.state()["last_error"] is None


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
