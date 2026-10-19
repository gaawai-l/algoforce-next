import json
import logging
import re
import threading
from collections.abc import Callable, Set
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from onchain_fixture import (
    EPOCH,
    GOLDEN_DAYS,
    brk_transport,
    golden_urpd,
    load_series,
    load_urpd,
    seed_golden,
)

from wheelhouse_service.onchain.agecohorts import AgeCohorts
from wheelhouse_service.onchain.brk import (
    AGE_ONLY_SERIES,
    AGE_URPD_COHORTS,
    DAY1_SERIES,
    HOUR1_BACKFILL,
    HOUR1_SERIES,
    SELL_SIDE_SERIES,
    START,
    BrkClient,
    SeriesData,
    Urpd,
)
from wheelhouse_service.onchain.costbasis import BUCKETS, MIN_PRICE, PAST_DAYS, StoredCostBasis
from wheelhouse_service.onchain.costflow import StoredCostFlow, cost_flow
from wheelhouse_service.onchain.cycle import Cycle
from wheelhouse_service.onchain.levels import median_cost
from wheelhouse_service.onchain.models import closed_day
from wheelhouse_service.onchain.pressure import Pressure, lookback
from wheelhouse_service.onchain.sellside import SellSide
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import DAY1_FETCH, URPD_SET, OnchainSync, closed_days
from wheelhouse_service.rules import Rules

NOW = datetime(2026, 10, 16, 10, 40, tzinfo=UTC)
LINES = {"true_mean", "short_term", "average", "long_term", "median"}
# The cost-basis golden sample: unlike the P1 fixtures, it has its own snapshot for each past day.
GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-16T1829Z"
D = date(2026, 10, 16)
# Every hour1 series the sync fetches: the seller pressure's, then those only the sell side needs,
# then, in a stage of their own, those only the age cohorts need.
HOUR1 = (*HOUR1_SERIES, *SELL_SIDE_SERIES, *AGE_ONLY_SERIES)


def instant(value: str | None) -> datetime:
    assert value is not None
    return datetime.fromisoformat(value)


def sync_for(
    store: OnchainStore,
    transport: httpx.MockTransport,
    now: datetime,
    rules: Rules = frozenset(),
) -> OnchainSync:
    client = BrkClient(httpx.Client(transport=transport), clock=lambda: now)
    return OnchainSync(store, client, rules=rules)


def run(
    store: OnchainStore,
    transport: httpx.MockTransport,
    now: datetime,
    rules: Rules = frozenset(),
) -> bool:
    return sync_for(store, transport, now, rules).run_once(now=now)


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


def urpd_calls(
    calls: list[tuple[str, dict[str, str]]], include_ages: bool = False
) -> list[tuple[str, str, str]]:
    """The URPD requests, in order, as (cohort, date, agg); those of the age cohorts only with
    `include_ages`."""
    found = []
    for path, params in calls:
        if path.startswith("/api/urpd/"):
            _, _, _, cohort, day = path.split("/")
            if include_ages or not cohort.startswith("utxos_"):
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
    assert requested(day1_calls(calls)) == set(DAY1_FETCH)
    assert requested(hour1_calls(calls)) == set(HOUR1)
    cycle = cycle_of(store)
    assert (cycle.state, cycle.as_of) == ("breakout", date(2026, 10, 16))
    levels = levels_of(store)
    assert set(levels) == {
        "as_of",
        "urpd_date",
        "onchain_close",
        "lines",
        "rules",
        "latest_day",
        "latest_urpd_day",
    }
    assert levels["rules"] == []
    assert (levels["latest_day"], levels["latest_urpd_day"]) == ("2026-10-16", "2026-10-16")
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
    starts = {name: store.last_position(name, "day1") - 3 for name in DAY1_FETCH}
    assert starts["sth_realized_price"] == 6484
    assert starts["true_market_mean"] == 6494

    later = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    incremental, calls = brk_transport()
    assert run(store, incremental, later) is True

    bulk = day1_calls(calls)
    assert requested(bulk) == set(DAY1_FETCH)
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
    assert requested(hour1) == set(HOUR1)
    # 3,000 points per series is over the weight cap past 6 series a request: the 29 series of the
    # first stage take 5 requests, the 126 of the age cohorts' stage 21.
    assert len(hour1) == 5 + 21
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
    assert requested(hour1_calls(calls)) == set(HOUR1)
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
    starts = {name: store.last_position(name, "hour1") - 3 for name in HOUR1}
    assert starts["sth_supply_in_loss"] == 155927
    assert starts["price_close"] == 155934
    assert starts["sth_supply_in_profit"] == 155934

    later = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    incremental, calls = brk_transport()
    assert run(store, incremental, later) is True

    hour1 = hour1_calls(calls)
    assert requested(hour1) == set(HOUR1)
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

    # The P1 fixtures' D does not share the close of its grid snapshots, so those are fetched again.
    assert urpd_calls(calls) == same_day(D) + refetch_of(D) + [("sth", "2026-10-15", "lin200")]
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


def test_same_day_snapshot_error_stops_the_stage_and_still_prunes(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    # A snapshot of a day no longer needed: a lasting outage must not keep it, or grow the table.
    store.save_urpd(load_urpd("all").model_copy(update={"date": date(2026, 10, 14)}), NOW)
    transport, calls = brk_transport(urpd_fail={("sth", "lin500")})

    assert run(store, transport, NOW) is True

    # The failed request ends the stage: nothing after it is asked for.
    assert urpd_calls(calls) == same_day(D)[:2]
    assert urpd_rows(store) == {("all", "2026-10-16", "lin500")}
    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["next_due"]) == NOW + timedelta(minutes=5)
    cost = costbasis_of(store)
    assert cost.urpd_date == D
    assert cost.buckets == []
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


def test_bucket_without_rows_from_the_floor_is_reported_empty(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    inner, _ = brk_transport()

    def below_floor(request: httpx.Request) -> httpx.Response:
        # Every lin200 snapshot keeps only the rows priced below MIN_PRICE.
        response = inner.handler(request)
        if request.url.path.startswith("/api/urpd/") and request.url.params["agg"] == "lin200":
            body = json.loads(response.content)
            body["buckets"] = [
                row for row in body["buckets"] if row["price_floor"] + 200 / 2 < MIN_PRICE
            ]
            return httpx.Response(200, json=body)
        return response

    assert run(store, httpx.MockTransport(below_floor), NOW) is True

    assert bucket_widths(store) == [500, 1000]
    assert costbasis_of(store).reasons == ["urpd_empty:lin200"]
    state = store.state()
    assert state["last_error"] is None
    assert strings(state["reasons"]) == []


def test_costbasis_failure_still_derives_the_pressure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert store.derived("costbasis") is not None

    def boom(*args: object) -> None:
        raise RuntimeError("secret value 123")

    monkeypatch.setattr("wheelhouse_service.onchain.sync.cost_basis", boom)
    second = NOW + timedelta(hours=1)
    again, _ = brk_transport()
    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert run(store, again, second) is True

    # Only the cost basis is gone; every other view is derived as usual.
    assert store.derived("costbasis") is None
    for kind in ("cycle", "levels", "pressure"):
        derived = store.derived(kind)
        assert derived is not None and derived[1] == second
    state = store.state()
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == second
    assert strings(state["reasons"]) == []
    assert "code=costbasis_failed" in caplog.text
    assert "secret" not in caplog.text


def test_sell_side_is_derived_with_the_pressure(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    assert run(store, transport, NOW) is True

    derived = store.derived("sellside")
    assert derived is not None and derived[1] == NOW
    sell_side = SellSide.model_validate_json(derived[0])
    assert sell_side.last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)
    assert sell_side.rules == []


def test_sell_side_failure_still_derives_everything_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert store.derived("sellside") is not None

    def boom(*args: object) -> None:
        raise RuntimeError("secret value 123")

    monkeypatch.setattr("wheelhouse_service.onchain.sync.sell_side", boom)
    second = NOW + timedelta(hours=1)
    again, _ = brk_transport()
    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert run(store, again, second) is True

    assert store.derived("sellside") is None
    for kind in ("cycle", "levels", "costbasis", "pressure"):
        derived = store.derived(kind)
        assert derived is not None and derived[1] == second
    state = store.state()
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == second
    assert strings(state["reasons"]) == []
    assert "code=sellside_failed" in caplog.text
    assert "secret" not in caplog.text


def test_a_missing_sell_side_series_keeps_the_pressure(tmp_path: Path):
    gap = "lth_transfer_volume_in_loss_cumulative_usd"
    store = OnchainStore(tmp_path / "onchain.sqlite")
    partial, _ = brk_transport(missing={gap})
    assert run(store, partial, NOW) is True

    state = store.state()
    assert strings(state["missing_series"]) == [f"hour1:{gap}"]
    assert strings(state["reasons"]) == [f"series_missing:hour1:{gap}"]
    assert store.derived("sellside") is None
    assert pressure_of(store).last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)


def bulk_names(request: httpx.Request) -> set[str]:
    """The series a bulk request asks for; none for any other request."""
    if request.url.path != "/api/series/bulk":
        return set()
    return set(request.url.params["series"].split(","))


def failing_for(names: Set[str], **options: Any) -> httpx.MockTransport:
    """The fixture BRK, except that an hour1 bulk request for any of `names` gets a 503."""
    inner, _ = brk_transport(**options)

    def handler(request: httpx.Request) -> httpx.Response:
        if bulk_names(request) & names and request.url.params["index"] == "hour1":
            return httpx.Response(503)
        return inner.handler(request)

    return httpx.MockTransport(handler)


def test_age_cohorts_are_stamped_as_of_the_first_hour1_stage(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    inner, _ = brk_transport()
    start = datetime(2026, 10, 16, 9, 12, tzinfo=UTC)
    hour1_done = start + timedelta(minutes=1)
    age_done = start + timedelta(minutes=2)
    ticks = [start]

    def handler(request: httpx.Request) -> httpx.Response:
        names = bulk_names(request)
        if names and request.url.params["index"] == "hour1":
            ticks.append(age_done if names <= set(AGE_ONLY_SERIES) else hour1_done)
        return inner.handler(request)

    sync = sync_for(store, httpx.MockTransport(handler), start)
    assert sync._refresh(start, lambda: ticks[-1]) is None

    # They read that stage's series too, so a row it fetched still forming stays marked so.
    pressure, ages = store.derived("pressure"), store.derived("agecohorts")
    assert pressure is not None and pressure[1] == hour1_done
    assert ages is not None and ages[1] == hour1_done
    result = AgeCohorts.model_validate_json(ages[0])
    # The fixture holds the age-only series for 25 hours, and 24 of them have an hour before them.
    assert len(result.at) == 24
    assert result.at[-1] == datetime(2026, 10, 16, 9, tzinfo=UTC)
    assert result.rules == []


def test_a_failed_age_stage_keeps_the_other_hour1_views_current(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    before = store.derived("agecohorts")
    assert before is not None

    second = NOW + timedelta(hours=1)
    assert run(store, failing_for(set(AGE_ONLY_SERIES)), second) is True

    # The age cohorts stay as they were, with the time they were computed.
    assert store.derived("agecohorts") == before
    for kind in ("pressure", "sellside", "cycle", "levels", "costbasis"):
        derived = store.derived(kind)
        assert derived is not None and derived[1] == second
    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert instant(state["last_success_at"]) == NOW
    assert instant(state["next_due"]) == second + timedelta(minutes=5)
    assert strings(state["reasons"]) == []


def test_a_failed_first_hour1_stage_keeps_the_age_cohorts_as_they_were(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    before = {kind: store.derived(kind) for kind in ("pressure", "sellside", "agecohorts")}

    second = NOW + timedelta(hours=1)
    assert run(store, failing_for({*HOUR1_SERIES, *SELL_SIDE_SERIES}), second) is True

    # The age stage fetched, but the bands also read the first stage's series, which did not.
    assert {kind: store.derived(kind) for kind in before} == before
    assert store.state()["last_error"] == "brk_unavailable"


def test_each_hour1_stage_keeps_its_own_missing_series(tmp_path: Path):
    age_gap = "utxos_3y_to_4y_old_realized_profit_cumulative"
    side_gap = "lth_transfer_volume_in_loss_cumulative_usd"
    later = NOW + timedelta(hours=1)

    # The first stage fails: what it last found missing stands, the age stage's is found again.
    store = OnchainStore(tmp_path / "first.sqlite")
    partial, _ = brk_transport(missing={age_gap, side_gap})
    run(store, partial, NOW)
    assert strings(store.state()["missing_series"]) == [f"hour1:{side_gap}", f"hour1:{age_gap}"]
    run(store, failing_for({*HOUR1_SERIES, *SELL_SIDE_SERIES}), later)
    assert strings(store.state()["missing_series"]) == [f"hour1:{side_gap}"]

    # The age stage fails: what it last found missing stands, the first stage's is found again.
    store = OnchainStore(tmp_path / "age.sqlite")
    run(store, partial, NOW)
    run(store, failing_for(set(AGE_ONLY_SERIES)), later)
    assert strings(store.state()["missing_series"]) == [f"hour1:{age_gap}"]
    assert strings(store.state()["reasons"]) == [f"series_missing:hour1:{age_gap}"]


def test_a_missing_shared_series_clears_the_age_cohorts_even_when_their_stage_failed(
    tmp_path: Path,
):
    gap = "utxos_1h_to_1d_old_realized_loss_cumulative"
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert store.derived("agecohorts") is not None

    second = NOW + timedelta(hours=1)
    assert run(store, failing_for(set(AGE_ONLY_SERIES), missing={gap}), second) is True

    # An absent series is not a zero: the stored bands go rather than stand in for it.
    assert store.derived("agecohorts") is None
    assert store.derived("sellside") is None
    assert store.derived("pressure") is not None


def test_derive_from_store_keeps_the_age_cohorts_stamp(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    sync = sync_for(store, transport, NOW)
    sync.run_once(now=NOW)
    before = store.derived("agecohorts")
    assert before is not None

    sync.derive_from_store()
    assert store.derived("agecohorts") == before

    # With nothing stored there is no time to stamp them with, so none are derived.
    store.clear_derived("agecohorts")
    sync.derive_from_store()
    assert store.derived("agecohorts") is None


def test_a_missing_age_series_keeps_the_other_hour1_views(tmp_path: Path):
    gap = "utxos_3y_to_4y_old_transfer_volume_in_loss_cumulative_usd"
    store = OnchainStore(tmp_path / "onchain.sqlite")
    partial, _ = brk_transport(missing={gap})
    assert run(store, partial, NOW) is True

    state = store.state()
    assert strings(state["missing_series"]) == [f"hour1:{gap}"]
    assert strings(state["reasons"]) == [f"series_missing:hour1:{gap}"]
    assert state["last_error"] is None
    assert store.derived("agecohorts") is None
    assert store.derived("sellside") is not None
    assert pressure_of(store).last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)


def test_age_cohorts_failure_still_derives_everything_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert store.derived("agecohorts") is not None

    def boom(*args: object) -> None:
        raise RuntimeError("secret value 123")

    monkeypatch.setattr("wheelhouse_service.onchain.sync.age_cohorts", boom)
    second = NOW + timedelta(hours=1)
    again, _ = brk_transport()
    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert run(store, again, second) is True

    assert store.derived("agecohorts") is None
    for kind in ("cycle", "levels", "costbasis", "pressure", "sellside"):
        derived = store.derived(kind)
        assert derived is not None and derived[1] == second
    state = store.state()
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == second
    assert "code=agecohorts_failed" in caplog.text
    assert "secret" not in caplog.text


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

    # Only `all lin500` is asked for today; all nine snapshots are then yesterday's, D. The P1
    # fixtures' D does not share the close of its grid snapshots, so those are fetched again.
    assert urpd_calls(calls) == [
        ("all", "2026-10-17", "lin500"),
        *same_day(D),
        *refetch_of(D),
        *past_of(D),
    ]
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
    assert store.derived("costflow") is not None
    stored = urpd_rows(store)
    assert len(stored) == 45

    later = datetime(2026, 10, 18, 10, 40, tzinfo=UTC)
    none, calls = brk_transport(urpd_dates=set())
    assert run(store, none, later) is True

    assert urpd_calls(calls) == [("all", "2026-10-18", "lin500"), ("all", "2026-10-17", "lin500")]
    assert store.derived("costbasis") is None
    assert store.derived("costflow") is None
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


# 2026-10-01 is inside the fixture's last run, which started on 09-23.
GAP = date(2026, 10, 1)


def without_gap_day(transport: httpx.MockTransport) -> httpx.MockTransport:
    """The fixture BRK, except that TMM has no value for GAP."""

    def edit(name: str, item: dict[str, Any]) -> None:
        offset = (GAP - EPOCH).days - item["start"]
        if name == "true_market_mean" and 0 <= offset < len(item["data"]):
            item["data"][offset] = None

    return rewritten(transport, edit)


def test_o4_reaches_the_derived_cycle(tmp_path: Path):
    def derived(rules: Rules) -> Cycle:
        store = OnchainStore(tmp_path / f"{'-'.join(sorted(rules)) or 'v1'}.sqlite")
        transport, _ = brk_transport()
        assert run(store, without_gap_day(transport), NOW, rules)
        return cycle_of(store)

    v1, o4 = derived(frozenset()), derived(frozenset({"O4"}))

    # v1 skips the day with no TMM; O4 keeps the state over it and counts it.
    assert (v1.rules, v1.since, v1.day, v1.episodes[-1].days) == ([], date(2026, 9, 23), 23, 23)
    assert (o4.rules, o4.since, o4.day, o4.episodes[-1].days) == (
        ["O4"],
        date(2026, 9, 23),
        24,
        24,
    )
    assert (v1.as_of, v1.state, v1.changes) == (o4.as_of, o4.state, o4.changes)


def test_o3_reaches_the_derived_pressure(tmp_path: Path):
    def derived(rules: Rules) -> Pressure:
        store = OnchainStore(tmp_path / f"{'-'.join(sorted(rules)) or 'v1'}.sqlite")
        transport, _ = brk_transport()
        assert run(store, transport, NOW, rules)
        return pressure_of(store)

    v1, o3 = derived(frozenset()), derived(frozenset({"O3"}))

    # v1 drops the 11 hours without a block and the 11 after them; O3 keeps them all.
    assert (v1.rules, v1.kept, v1.loss_levels.n) == ([], 2577, 716)
    assert (o3.rules, o3.kept, o3.loss_levels.n, o3.share_levels.n) == (["O3"], 2599, 720, 718)
    assert not any(point.no_block for point in v1.loss)
    assert [point.at for point in o3.loss if point.no_block][-2:] == [
        datetime(2026, 10, 3, 14, tzinfo=UTC),
        datetime(2026, 10, 3, 18, tzinfo=UTC),
    ]
    assert (v1.last_at, v1.qc) == (o3.last_at, o3.qc)


def test_o1_reaches_the_derived_cycle(tmp_path: Path):
    def derived(rules: Rules) -> Cycle:
        store = OnchainStore(tmp_path / f"{'-'.join(sorted(rules)) or 'v1'}.sqlite")
        transport, _ = brk_transport()
        assert run(store, transport, NOW, rules)
        return cycle_of(store)

    v1, o1 = derived(frozenset()), derived(frozenset({"O1"}))

    assert (v1.rules, v1.as_of, v1.day, v1.latest_day) == ([], D, 24, D)
    # At 10:40 the closed day is 10-15; 10-16 is still open but is the newest day there is.
    assert (o1.rules, o1.as_of, o1.day, o1.latest_day) == (["O1"], date(2026, 10, 15), 23, D)
    assert (o1.state, o1.since, o1.changes) == (v1.state, v1.since, v1.changes)


def test_o1_closed_day_is_the_one_at_the_start_of_the_round(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    # The round starts before 02:00, while 10-16 may still be revised, and ends after it.
    start = datetime(2026, 10, 17, 1, 59, tzinfo=UTC)
    done = datetime(2026, 10, 17, 2, 1, tzinfo=UTC)
    sync = sync_for(store, transport, start, frozenset({"O1"}))

    assert sync._refresh(start, lambda: done) is None

    derived = store.derived("cycle")
    assert derived is not None and derived[1] == done
    assert cycle_of(store).as_of == date(2026, 10, 15)


# O1 on the levels and the cost basis. In the golden sample C, the closed day at NOW, is D - 1.
O1: Rules = frozenset({"O1"})
C = D - timedelta(days=1)


def derive(store: OnchainStore, rules: Rules, at: datetime = NOW) -> bool:
    """`_derive` at `at` from the store alone; D is the stored snapshot a refresh would reuse."""
    sync = sync_for(store, httpx.MockTransport(lambda request: httpx.Response(503)), at, rules)
    return sync._derive(sync._recent_urpd(at), at, set(), None, closed=closed_day(at))


def line_prices(levels: dict[str, Any]) -> dict[str, float]:
    return {line["name"]: line["price"] for line in levels["lines"]}


def test_v1_levels_and_cost_basis_stay_as_in_p3(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    seed_golden(store, GOLDEN_DAYS, NOW)

    assert derive(store, frozenset()) is False

    levels = levels_of(store)
    assert {key: value for key, value in levels.items() if key != "lines"} == {
        "as_of": "2026-10-16T00:00:00+00:00",
        "urpd_date": "2026-10-16",
        "onchain_close": 81217.6,
        "rules": [],
        # Written whatever the rules; under v1 they are the days the readings are of.
        "latest_day": "2026-10-16",
        "latest_urpd_day": "2026-10-16",
    }
    assert line_prices(levels) == {
        "true_mean": 77481.81,
        "short_term": 74475.07,
        "average": 53845.04,
        "long_term": 49245.48,
        "median": median_cost(golden_urpd("all", "lin500", D)),
    }
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.lines_as_of, cost.latest_day, cost.rules) == (D, D, D, [])
    assert cost.reasons == []
    # Table 2 and the bands of the original page, as the cost-basis tests pin them.
    for bucket in cost.buckets:
        expected = json.loads((GOLDEN / f"expected-{bucket.bucket}.json").read_text())
        assert (bucket.resistance, bucket.support) == (expected["resistance"], expected["support"])
        for side in ("above", "below"):
            assert [(band.low, band.high) for band in getattr(bucket, side)] == [
                (band["low"], band["high"]) for band in expected[side]
            ]
    assert [bucket.bucket for bucket in cost.buckets] == list(BUCKETS)


def test_o1_derives_from_the_closed_day_and_its_final_snapshots(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    seed_golden(store, GOLDEN_DAYS, NOW)
    final = golden_urpd("all", "lin500", C)

    assert derive(store, O1) is False

    levels = levels_of(store)
    # The lines are the closed day's; the median, the date and the close are F's, here C.
    assert {key: value for key, value in levels.items() if key != "lines"} == {
        "as_of": "2026-10-15T00:00:00+00:00",
        "urpd_date": "2026-10-15",
        "onchain_close": 82203.57,
        "rules": ["O1"],
        # The newest complete day and D, whatever the closed day.
        "latest_day": "2026-10-16",
        "latest_urpd_day": "2026-10-16",
    }
    assert final.close == 82203.57
    assert line_prices(levels) == {
        "true_mean": 77467.0,
        "short_term": 74445.29,
        "average": 53836.03,
        "long_term": 49237.52,
        "median": median_cost(final),
    }
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.lines_as_of, cost.latest_day, cost.rules) == (C, C, D, ["O1"])
    # F's own grid days, F-1 to F-90, are all stored.
    assert cost.reasons == []
    assert [bucket.bucket for bucket in cost.buckets] == list(BUCKETS)
    assert {bucket.spot for bucket in cost.buckets} == {82203.57}
    assert cost.snapshot_at == NOW


# Table 2 of the golden sample: Resistance by bucket width, and Support, the same for every width.
RESISTANCE = {
    200: [86000, 88000, 96000, 104000],
    500: [86000, 88000, 96000, 104000],
    1000: [86000, 90000, 96000, 104000],
}
V1_SUPPORT = [76000, 74000, 70000, 64000]
O1_SUPPORT = [80000, 76000, 74000, 70000]


def test_o1_changes_table_2_of_the_golden_sample(tmp_path: Path):
    def table_2(rules: Rules) -> tuple[set[float], dict[int, tuple[list[float], list[float]]]]:
        store = OnchainStore(tmp_path / f"{'-'.join(sorted(rules)) or 'v1'}.sqlite")
        seed_golden(store, GOLDEN_DAYS, NOW)
        assert derive(store, rules) is False
        buckets = costbasis_of(store).buckets
        spots = {bucket.spot for bucket in buckets}
        return spots, {bucket.bucket: (bucket.resistance, bucket.support) for bucket in buckets}

    (v1_spots, v1), (o1_spots, o1) = table_2(frozenset()), table_2(O1)

    assert v1 == {bucket: (RESISTANCE[bucket], V1_SUPPORT) for bucket in BUCKETS}
    # F's clusters barely differ from D's. Its close, though, is in the band from 82000, so the
    # band below it is now the nearest support and 64000 is no longer among the four.
    assert (v1_spots, o1_spots) == ({81217.6}, {82203.57})
    assert all(82000 <= spot < 84000 for spot in o1_spots)
    assert o1 == {bucket: (RESISTANCE[bucket], O1_SUPPORT) for bucket in BUCKETS}


def test_o1_falls_back_to_the_day_before_and_then_to_no_snapshot(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    seed_golden(store, GOLDEN_DAYS, NOW)
    before = C - timedelta(days=1)
    with store.connection() as db:
        db.execute(
            "DELETE FROM urpd WHERE cohort='sth' AND agg='lin200' AND day=?", (C.isoformat(),)
        )

    # C lacks one of its nine snapshots, so F is the day before.
    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert derive(store, O1) is False
    assert "onchain_urpd_not_final" not in caplog.text

    levels = levels_of(store)
    assert (levels["urpd_date"], levels["onchain_close"], levels["latest_urpd_day"]) == (
        "2026-10-14",
        golden_urpd("all", "lin500", before).close,
        "2026-10-16",
    )
    assert line_prices(levels)["median"] == median_cost(golden_urpd("all", "lin500", before))
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.lines_as_of, cost.latest_day) == (before, C, D)
    # The golden sample has none of F's own past days.
    assert cost.reasons == [f"urpd_grid_partial:lin{bucket}" for bucket in BUCKETS]

    # One snapshot of the day before was fetched before that day was final: neither day is.
    store.save_urpd(golden_urpd("all", "lin500", before), datetime(2026, 10, 15, 1, 59, tzinfo=UTC))
    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert derive(store, O1) is True

    # Each candidate is logged once, with the snapshot kinds that keep it from being F: the kinds
    # only, never a value.
    lines = [line for line in caplog.messages if line.startswith("onchain_urpd_not_final")]
    assert lines == [
        "onchain_urpd_not_final day=2026-10-15 kinds=sth:lin200",
        "onchain_urpd_not_final day=2026-10-14 kinds=all:lin500",
    ]

    levels = levels_of(store)
    assert set(line_prices(levels)) == LINES - {"median"}
    assert (levels["urpd_date"], levels["onchain_close"], levels["latest_urpd_day"]) == (
        None,
        None,
        "2026-10-16",
    )
    assert store.derived("costbasis") is None

    # v1 reads D and does not ask for F.
    assert derive(store, frozenset()) is False
    assert levels_of(store)["urpd_date"] == "2026-10-16"
    assert costbasis_of(store).urpd_date == D


def test_o1_reaches_the_derived_levels_and_cost_basis(tmp_path: Path):
    def derived(rules: Rules) -> tuple[dict[str, Any], StoredCostBasis]:
        store = OnchainStore(tmp_path / f"{'-'.join(sorted(rules)) or 'v1'}.sqlite")
        transport, _ = brk_transport(urpd_dir=GOLDEN)
        assert run(store, transport, NOW, rules)
        assert strings(store.state()["reasons"]) == []
        return levels_of(store), costbasis_of(store)

    (v1, v1_cost), (o1, o1_cost) = derived(frozenset()), derived(O1)

    # The run fetched D and its past days; D - 1 among them is C, final once fetched at NOW.
    assert (v1["rules"], v1["as_of"], v1["urpd_date"], v1["onchain_close"]) == (
        [],
        "2026-10-16T00:00:00+00:00",
        "2026-10-16",
        81217.6,
    )
    assert (o1["rules"], o1["as_of"], o1["urpd_date"], o1["onchain_close"]) == (
        ["O1"],
        "2026-10-15T00:00:00+00:00",
        "2026-10-15",
        82203.57,
    )
    assert line_prices(o1)["median"] == median_cost(golden_urpd("all", "lin500", C))
    assert line_prices(o1)["median"] != line_prices(v1)["median"]
    for levels in (v1, o1):
        assert (levels["latest_day"], levels["latest_urpd_day"]) == ("2026-10-16", "2026-10-16")
    assert (v1_cost.urpd_date, v1_cost.rules, v1_cost.reasons) == (D, [], [])
    assert (o1_cost.urpd_date, o1_cost.lines_as_of, o1_cost.latest_day, o1_cost.rules) == (
        C,
        C,
        D,
        ["O1"],
    )
    # The closed days' snapshots were fetched too, so F's own grid is complete.
    assert o1_cost.reasons == []


def test_o1_without_a_final_day_reports_urpd_not_final(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    # C, fetched as D's past day, lacks sth lin200, and the day before C was never fetched.
    transport, _ = brk_transport(urpd_dir=GOLDEN, urpd_missing={("sth", "lin200")})

    assert run(store, transport, NOW, O1)

    state = store.state()
    assert strings(state["reasons"]) == ["urpd_not_final"]
    assert state["last_error"] is None
    levels = levels_of(store)
    assert set(line_prices(levels)) == LINES - {"median"}
    assert (levels["urpd_date"], levels["latest_urpd_day"]) == (None, "2026-10-16")
    assert store.derived("costbasis") is None

    # v1 on the same data has D, so no such reason.
    v1 = OnchainStore(tmp_path / "v1.sqlite")
    again, _ = brk_transport(urpd_dir=GOLDEN, urpd_missing={("sth", "lin200")})
    assert run(v1, again, NOW)
    assert strings(v1.state()["reasons"]) == []
    assert bucket_widths(v1) == [500, 1000]

    # Deriving that store again under O1 leaves the shared reasons to the next refresh.
    sync_for(v1, again, NOW, O1).derive_from_store()
    assert v1.derived("costbasis") is None
    assert strings(v1.state()["reasons"]) == []


# O1's URPD fetch and prune over one night. T is the day the rounds run on: until 02:00 the closed
# day C is T - 2, and from then on T - 1. BRK publishes T's snapshots at 01:00.
T = date(2026, 10, 17)


def at_t(hour: int) -> datetime:
    """HH:12 on T, when a refresh is due."""
    return datetime.combine(T, time(hour, 12), tzinfo=UTC)


def night_brk(
    *,
    unpublished: Set[date] = frozenset(),
    failing: Set[tuple[str, date, str]] = frozenset(),
) -> tuple[httpx.MockTransport, list[tuple[str, dict[str, str]]]]:
    """The golden sample's BRK, without the snapshots of the `unpublished` days and with a 500 for
    each (cohort, day, agg) in `failing`. Every request is recorded, in order."""
    inner, calls = brk_transport(urpd_dir=GOLDEN)

    def handler(request: httpx.Request) -> httpx.Response:
        response = inner.handler(request)
        path = request.url.path
        if path.startswith("/api/urpd/"):
            _, _, _, cohort, day = path.split("/")
            when = date.fromisoformat(day)
            if (cohort, when, request.url.params["agg"]) in failing:
                return httpx.Response(500)
            if when in unpublished:
                return httpx.Response(404, json={"error": {"type": "not_found", "code": "x"}})
        return response

    return httpx.MockTransport(handler), calls


def night_round(
    store: OnchainStore,
    hour: int,
    rules: Rules,
    *,
    unpublished: Set[date] | None = None,
    failing: Set[tuple[str, date, str]] = frozenset(),
) -> list[tuple[str, str, str]]:
    """One refresh at HH:12 on T; the URPD requests it made."""
    if unpublished is None:
        unpublished = {T} if hour < 1 else set()
    transport, calls = night_brk(unpublished=unpublished, failing=failing)
    assert run(store, transport, at_t(hour), rules) is True
    return urpd_calls(calls)


def days_of(day: date, *more: date) -> list[tuple[str, str, str]]:
    """The requests for the nine snapshots of each day, in the order they are made."""
    return [request for each in (day, *more) for request in same_day(each)]


def v1_keep(at: datetime, d: date) -> set[date]:
    """What v1's prune keeps at `at` with D = `d`."""
    today = at.date()
    return {today, today - timedelta(days=1), d, *(d - timedelta(days=n) for n in PAST_DAYS)}


def stored_days(store: OnchainStore) -> set[date]:
    return {date.fromisoformat(day) for _, day, _ in urpd_rows(store)}


def ago(n: int) -> date:
    return T - timedelta(days=n)


def test_closed_days_are_the_two_anchors_then_their_grid_days_newest_first():
    at = datetime(2026, 10, 17, 10, 40, tzinfo=UTC)
    c = date(2026, 10, 16)

    assert closed_days(at) == [c - timedelta(days=n) for n in (0, 1, 2, 7, 8, 30, 31, 90, 91)]
    # The closed day changes at 02:00, and so does the whole list.
    assert closed_days(datetime(2026, 10, 17, 1, 59, tzinfo=UTC))[0] == date(2026, 10, 15)
    assert closed_days(datetime(2026, 10, 17, 2, tzinfo=UTC))[0] == c


def test_o1_keeps_f_on_a_closed_day_through_the_night(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")

    # 00:12: T is not published yet, so D is T - 1, and C is T - 2.
    requests = night_round(store, 0, O1)

    at = at_t(0)
    assert closed_days(at)[:2] == [ago(2), ago(3)]
    # v1's requests, then the closed days except C: one of D's past days, fetched final just now.
    assert requests == [
        ("all", T.isoformat(), "lin500"),
        *same_day(ago(1)),
        *past_of(ago(1)),
        *days_of(*closed_days(at)[1:]),
    ]
    levels = levels_of(store)
    assert (levels["urpd_date"], levels["onchain_close"]) == ("2026-10-15", 82203.57)
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.lines_as_of, cost.reasons) == (ago(2), ago(2), [])
    assert [bucket.bucket for bucket in cost.buckets] == list(BUCKETS)
    assert strings(store.state()["reasons"]) == []
    # T is kept but has nothing to keep yet.
    assert stored_days(store) == (v1_keep(at, ago(1)) | set(closed_days(at))) - {T}

    # 01:12: D is T now. v1 would keep T, T - 1, T - 7, T - 30 and T - 90 only, which drops C.
    at = at_t(1)
    assert ago(2) not in v1_keep(at, T)
    assert ago(2) in stored_days(store)
    requests = night_round(store, 1, O1)

    # Every closed day's snapshots are final already, so none is fetched again.
    assert requests == same_day(T) + past_of(T)
    assert stored_days(store) == v1_keep(at, T) | set(closed_days(at))
    assert levels_of(store)["urpd_date"] == "2026-10-15"
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.reasons) == (ago(2), [])
    assert strings(store.state()["reasons"]) == []

    # 02:12: C is T - 1, whose nine snapshots this round fetched final as one of D's past days.
    at = at_t(2)
    requests = night_round(store, 2, O1)

    assert closed_days(at)[0] == ago(1)
    # Only the grid days new to the closed days are fetched: C - 7, C - 30 and C - 90.
    assert requests == same_day(T) + same_day(ago(1)) + days_of(ago(8), ago(31), ago(91))
    levels = levels_of(store)
    assert (levels["urpd_date"], levels["onchain_close"]) == ("2026-10-16", 81217.6)
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.lines_as_of, cost.reasons) == (ago(1), ago(1), [])
    assert [bucket.bucket for bucket in cost.buckets] == list(BUCKETS)
    assert strings(store.state()["reasons"]) == []
    assert stored_days(store) == v1_keep(at, T) | set(closed_days(at))


def test_o1_failed_closed_snapshot_keeps_f_on_the_day_before(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    night_round(store, 0, O1)
    night_round(store, 1, O1)

    # 02:12: one of C = T - 1's snapshots fails, both as D's past day and as C.
    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        requests = night_round(store, 2, O1, failing={("lth", ago(1), "lin1000")})

    at = at_t(2)
    # The closed step stops at the error: C - 7, C - 30 and C - 90 are not asked for this round.
    assert requests == same_day(T) + same_day(ago(1)) + [("lth", ago(1).isoformat(), "lin1000")]
    assert caplog.text.count("onchain_urpd_past_failed code=brk_unavailable") == 1
    assert caplog.text.count("onchain_urpd_closed_failed code=brk_unavailable") == 1
    # The stage did not fail, and F is the day before C, still kept with its grid days.
    state = store.state()
    assert (state["last_error"], strings(state["reasons"])) == (None, [])
    levels = levels_of(store)
    assert (levels["urpd_date"], levels["onchain_close"]) == ("2026-10-15", 82203.57)
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.lines_as_of, cost.reasons) == (ago(2), ago(1), [])
    assert [bucket.bucket for bucket in cost.buckets] == list(BUCKETS)
    assert {ago(2), ago(3), ago(9), ago(32), ago(92)} <= stored_days(store)
    unfetched = {ago(8), ago(31), ago(91)}
    assert stored_days(store) == (v1_keep(at, T) | set(closed_days(at))) - unfetched


def test_o1_fetches_the_closed_days_when_d_fails(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    night_round(store, 0, O1)
    night_round(store, 1, O1)

    # 02:12: D's second snapshot fails the URPD stage, which prunes before it raises.
    requests = night_round(store, 2, O1, failing={("sth", T, "lin500")})

    at = at_t(2)
    # The closed step still runs. That prune kept the closed days stored at 01:12, so only C, not
    # final yet, and the grid days new to the closed days are fetched.
    assert requests == same_day(T)[:2] + days_of(ago(1), ago(8), ago(31), ago(91))
    state = store.state()
    assert state["last_error"] == "brk_unavailable"
    assert strings(state["reasons"]) == []
    levels = levels_of(store)
    assert (levels["urpd_date"], levels["onchain_close"]) == ("2026-10-16", 81217.6)
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.reasons) == (ago(1), [])
    assert stored_days(store) == v1_keep(at, T) | set(closed_days(at))


def test_o1_fetches_the_closed_days_without_d_and_skips_what_does_not_exist(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")

    # Neither T nor T - 1 is published, so there is no D; C = T - 1 has no snapshots either.
    requests = night_round(store, 2, O1, unpublished={T, ago(1)})

    at = at_t(2)
    # Each missing snapshot of C is skipped, and the days after it are still fetched.
    assert requests == [
        ("all", T.isoformat(), "lin500"),
        ("all", ago(1).isoformat(), "lin500"),
        *days_of(*closed_days(at)),
    ]
    state = store.state()
    assert (state["last_error"], strings(state["reasons"])) == (None, ["urpd_missing"])
    levels = levels_of(store)
    assert (levels["urpd_date"], levels["latest_urpd_day"]) == ("2026-10-15", None)
    cost = costbasis_of(store)
    assert (cost.urpd_date, cost.reasons) == (ago(2), [])
    # Without D nothing is pruned.
    assert stored_days(store) == set(closed_days(at)) - {ago(1)}


def test_v1_night_makes_no_closed_day_requests(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    v1: Rules = frozenset()

    requests = night_round(store, 0, v1)
    assert requests == [
        ("all", T.isoformat(), "lin500"),
        *same_day(ago(1)),
        *past_of(ago(1)),
    ]
    assert len(requests) == 46
    assert stored_days(store) == v1_keep(at_t(0), ago(1)) - {T}

    requests = night_round(store, 1, v1)
    assert requests == same_day(T) + past_of(T)
    assert len(requests) == 45
    # v1 drops T - 2, which it no longer needs.
    assert stored_days(store) == v1_keep(at_t(1), T)

    requests = night_round(store, 2, v1)
    assert requests == same_day(T) + same_day(ago(1))
    assert len(requests) == 18
    assert stored_days(store) == v1_keep(at_t(2), T)
    assert levels_of(store)["urpd_date"] == T.isoformat()


def add_older_hours(store: OnchainStore, hours: int, at: datetime) -> None:
    """Put `hours` hours before each stored hour1 series, each a copy of its oldest row."""
    for name in HOUR1_SERIES:
        stored = store.read_series(name, "hour1")
        first = (stored[0][0] - datetime.combine(EPOCH, time(), tzinfo=UTC)) // timedelta(hours=1)
        version = store.series_version(name, "hour1")
        assert version is not None
        older = SeriesData(
            version=version,
            index="hour1",
            start=first - hours,
            end=first,
            stamp=at,
            data=[stored[0][1]] * hours,
        )
        store.merge_series(name, "hour1", older, at)


def test_o2_reaches_the_derived_pressure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def derived(rules: Rules) -> tuple[Pressure, list[int]]:
        store = OnchainStore(tmp_path / f"{'-'.join(sorted(rules)) or 'v1'}.sqlite")
        transport, _ = brk_transport()
        sync = sync_for(store, transport, NOW, rules)
        assert sync.run_once(now=NOW)
        # The fixture holds 2600 hours; with more stored, a read is as long as it is allowed to be.
        add_older_hours(store, 400, NOW)
        lengths: list[int] = []
        read = store.read_series

        def spy(name: str, index: Any, tail: int | None = None) -> list[tuple[datetime, Any]]:
            rows = read(name, index, tail)
            if index == "hour1":
                lengths.append(len(rows))
            return rows

        monkeypatch.setattr(store, "read_series", spy)
        sync.derive_from_store()
        return pressure_of(store), lengths

    o2_rules: Rules = frozenset({"O2"})
    (v1, v1_lengths), (o2, o2_lengths) = derived(frozenset()), derived(o2_rules)

    # The pressure reads first; the sell side then reads its 25 series and the age cohorts their
    # 139, both over the v1 lookback.
    pressure_v1, pressure_o2 = v1_lengths[: len(HOUR1_SERIES)], o2_lengths[: len(HOUR1_SERIES)]
    assert pressure_v1 == [lookback(frozenset()) + 1] * len(HOUR1_SERIES) == [2601] * 11
    assert pressure_o2 == [lookback(o2_rules) + 1] * len(HOUR1_SERIES) == [2882] * 11
    assert len(v1_lengths) == len(o2_lengths) == 11 + 25 + 139
    assert (v1.rules, o2.rules) == ([], ["O2"])
    assert v1.last_at == o2.last_at == datetime(2026, 10, 16, 9, tzinfo=UTC)
    # Each point carries its own thresholds and level under O2 only.
    assert all(p.p95 is None and p.level is None for p in v1.loss)
    last = o2.loss[-1]
    assert last.p95 is not None and last.p75 is not None and last.level is not None
    assert (o2.loss_levels.p95, o2.loss_levels.p75) == (last.p95, last.p75)
    assert v1.loss_run is None and isinstance(o2.loss_run, int)


def test_o1_closes_the_pressure_as_of_the_hour1_stage(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    inner, _ = brk_transport()
    hour1_done = datetime(2026, 10, 16, 9, 59, tzinfo=UTC)
    done = hour1_done + timedelta(minutes=2)
    ticks = [datetime(2026, 10, 16, 9, 12, tzinfo=UTC)]

    def handler(request: httpx.Request) -> httpx.Response:
        # The hour1 requests end just before 10:00, and a slow URPD fetch crosses it.
        if request.url.path == "/api/series/bulk" and request.url.params["index"] == "hour1":
            ticks.append(hour1_done)
        elif request.url.path.startswith("/api/urpd"):
            ticks.append(done)
        return inner.handler(request)

    sync = sync_for(store, httpx.MockTransport(handler), ticks[0], frozenset({"O1", "O2"}))
    assert sync._refresh(ticks[0], lambda: ticks[-1]) is None

    pressure = pressure_of(store)
    # 09:00 was still forming when hour1 was read, though no longer when the round ended.
    assert (pressure.rules, pressure.last_at) == (
        ["O1", "O2"],
        datetime(2026, 10, 16, 9, tzinfo=UTC),
    )
    assert pressure.closed_at == datetime(2026, 10, 16, 8, tzinfo=UTC)
    assert pressure.loss[-1].level is None and pressure.loss[-2].level is not None
    # Deriving again from the store keeps the time it was computed, and so the same closed row.
    sync.derive_from_store()
    assert pressure_of(store) == pressure
    derived = store.derived("pressure")
    assert derived is not None and derived[1] == hour1_done


# O5 on the levels and the cost basis. W, the 1d–1w line, is the P1 fixture's value of D: captured
# at 10:02Z while the day was forming, so not of the same moment as the golden URPD (18:29Z).
O5: Rules = frozenset({"O5"})
W_SERIES = "utxos_1d_to_1w_old_realized_price"
W = 82651.72
# Close 81217.6 ± 50%, by bucket width: (low, high) of the domain.
O5_DOMAINS = [(200, 40_600.0, 121_800.0), (500, 40_500.0, 122_000.0), (1000, 41_000.0, 122_000.0)]


def test_o5_reaches_the_derived_levels_and_cost_basis(tmp_path: Path):
    def derived(rules: Rules) -> tuple[dict[str, Any], StoredCostBasis]:
        store = OnchainStore(tmp_path / f"{'-'.join(sorted(rules)) or 'v1'}.sqlite")
        transport, _ = brk_transport(urpd_dir=GOLDEN)
        assert run(store, transport, NOW, rules)
        assert strings(store.state()["reasons"]) == []
        return levels_of(store), costbasis_of(store)

    (v1, v1_cost), (o5, o5_cost) = derived(frozenset()), derived(O5)

    # The levels gain the 1d–1w line, last; the others stay as they are.
    assert (v1["rules"], o5["rules"]) == ([], ["O5"])
    assert [line["name"] for line in o5["lines"]] == [
        *(line["name"] for line in v1["lines"]),
        "one_day_to_week",
    ]
    assert line_prices(o5) == {**line_prices(v1), "one_day_to_week": W}
    assert o5["as_of"] == v1["as_of"] == "2026-10-16T00:00:00+00:00"

    # The cost basis is fitted in the fixed domain and counts the line, so its numbers change.
    assert (v1_cost.rules, o5_cost.rules, o5_cost.reasons) == ([], ["O5"], [])
    assert [(b.bucket, b.domain_low, b.domain_high) for b in v1_cost.buckets] == [
        (200, 1000.0, 125_800.0),
        (500, 1000.0, 126_000.0),
        (1000, 1000.0, 126_000.0),
    ]
    assert [(b.bucket, b.domain_low, b.domain_high) for b in o5_cost.buckets] == O5_DOMAINS
    for bucket in o5_cost.buckets:
        nearest = bucket.above[0]
        assert (nearest.low, nearest.high) == (82_000.0, 84_000.0)
        assert [c.line for c in nearest.candidates] == ["one_day_to_week"]
        assert bucket.resistance[0] == 84_000.0
    for before, after in zip(v1_cost.buckets, o5_cost.buckets, strict=True):
        assert (before.resistance, before.support) != (after.resistance, after.support)


def test_o5_without_the_median_clears_the_cost_basis(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    seed_golden(store, GOLDEN_DAYS, NOW)
    store.replace_series({W_SERIES: load_series(W_SERIES, "day1")}, "day1", NOW)
    # D's all lin500 snapshot holds no supply, so there is no median line.
    empty = golden_urpd("all", "lin500", D)
    empty = empty.model_copy(
        update={"buckets": [b.model_copy(update={"supply": 0.0}) for b in empty.buckets]}
    )
    store.save_urpd(empty, NOW)

    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        for rules, names in (
            (frozenset(), LINES - {"median"}),
            (O5, LINES - {"median"} | {"one_day_to_week"}),
        ):
            assert derive(store, rules) is False
            levels = levels_of(store)
            assert set(line_prices(levels)) == names
            # Five lines under O5 are not all six it counts, so there is no cost basis.
            assert store.derived("costbasis") is None
    # It was never computed, so it never failed.
    assert "onchain_derive_failed" not in caplog.text


def test_o1_with_o5_fixes_the_domain_around_f_close(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    seed_golden(store, GOLDEN_DAYS, NOW)
    store.replace_series({W_SERIES: load_series(W_SERIES, "day1")}, "day1", NOW)

    assert derive(store, frozenset({"O1", "O5"})) is False

    levels = levels_of(store)
    cost = costbasis_of(store)
    assert (levels["rules"], cost.rules) == (["O1", "O5"], ["O1", "O5"])
    # F is C, 10-15: its close is spot, and the domain is that close ± 50%, not D's.
    assert (levels["urpd_date"], levels["onchain_close"]) == ("2026-10-15", 82203.57)
    assert cost.urpd_date == C
    assert {bucket.spot for bucket in cost.buckets} == {levels["onchain_close"]}
    assert [(b.bucket, b.domain_low, b.domain_high) for b in cost.buckets] == [
        (200, 41_200.0, 123_400.0),
        (500, 41_000.0, 123_500.0),
        (1000, 41_000.0, 123_000.0),
    ]
    # The 1d–1w line is C's too: the P1 fixture's 10-15 value of W.
    assert line_prices(levels)["one_day_to_week"] == 82739.99


# Charts 3 and 4, the cost-basis flow: D's age snapshots, the daily range and the stored inputs.
# The cost-flow sample: D = 2026-10-19, each snapshot dated, every one of D at close 82347.76.
COSTFLOW = Path(__file__).parent / "fixtures" / "brk-2026-10-19T0512Z-costflow"
FLOW_D = date(2026, 10, 19)
FLOW_THEN = [FLOW_D - timedelta(days=n) for n in PAST_DAYS]
# The close every snapshot of D shares in the golden sample.
GOLDEN_CLOSE = 81217.6


def write_ages(directory: Path, close: float) -> Path:
    """Six lin500 snapshots of the age cohorts at `close`, which the fake BRK serves for any day."""
    directory.mkdir()
    for n, cohort in enumerate(AGE_URPD_COHORTS, start=1):
        bucket = {
            "price_floor": 80_000.0,
            "supply": float(n),
            "realized_cap": 80_000.0 * n,
            "unrealized_pnl": 0.0,
        }
        snapshot = {
            "cohort": cohort,
            "date": D.isoformat(),
            "aggregation": "lin500",
            "close": close,
            "total_supply": float(n),
            "buckets": [bucket],
        }
        (directory / f"urpd_{cohort}_lin500.json").write_text(json.dumps(snapshot))
    return directory


def ages_of(day: date) -> list[tuple[str, str, str]]:
    """The requests for the six age snapshots of `day`, in the order they are made."""
    return [(cohort, day.isoformat(), "lin500") for cohort in AGE_URPD_COHORTS]


def refetch_of(day: date) -> list[tuple[str, str, str]]:
    """The requests made again when the closes of D's set differ: `all lin500`, then the grids'."""
    kinds = [("all", "lin500"), ("sth", "lin500"), ("lth", "lin500")]
    kinds += [("all", "lin200"), ("sth", "lin200"), ("lth", "lin200")]
    return [(cohort, day.isoformat(), agg) for cohort, agg in kinds]


def costflow_of(store: OnchainStore) -> StoredCostFlow:
    derived = store.derived("costflow")
    assert derived is not None
    return StoredCostFlow.model_validate_json(derived[0])


def windows_of(flow: StoredCostFlow) -> list[tuple[int, list[date]]]:
    """Each grid's step and the then days of its windows."""
    return [(grid.step, [window.then_day for window in grid.windows]) for grid in flow.grids]


def reclosed(transport: httpx.MockTransport, close: float) -> httpx.MockTransport:
    """Wrap `transport` so every URPD snapshot it serves closes at `close`, as after a new block."""

    def handler(request: httpx.Request) -> httpx.Response:
        response = transport.handler(request)
        if request.url.path.startswith("/api/urpd/") and response.status_code == 200:
            return httpx.Response(200, json={**json.loads(response.content), "close": close})
        return response

    return httpx.MockTransport(handler)


def test_age_snapshots_follow_the_urpd_set_of_d(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    ages = write_ages(tmp_path / "ages", GOLDEN_CLOSE)
    transport, calls = brk_transport(urpd_dir=GOLDEN, age_dir=ages)

    assert run(store, transport, NOW) is True

    # Every snapshot of D shares its close, so none is fetched again.
    assert urpd_calls(calls, include_ages=True) == [*same_day(D), *ages_of(D), *past_of(D)]
    assert {row for row in urpd_rows(store) if row[0].startswith("utxos_")} == set(ages_of(D))
    flow = costflow_of(store)
    # The six snapshots and the daily range, which ends on D, give Chart 4 its rows.
    assert flow.age is not None
    assert (len(flow.age.groups), len(flow.age.band)) == (4, len(flow.grids[0].floors))
    assert flow.reasons == []
    assert store.state()["last_error"] is None


def test_d_set_close_mismatch_refetches_once(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    # The age snapshots are of another block than D.
    ages = write_ages(tmp_path / "ages", 1.0)
    transport, calls = brk_transport(urpd_dir=GOLDEN, age_dir=ages)

    assert run(store, transport, NOW) is True

    # After the ages: D, its five grid snapshots and the six ages once more, and only once.
    assert urpd_calls(calls, include_ages=True) == [
        *same_day(D),
        *ages_of(D),
        *refetch_of(D),
        *ages_of(D),
        *past_of(D),
    ]
    flow = costflow_of(store)
    # Still another block: Chart 4 has no rows, while the grids, which agree with D, stay.
    assert (flow.age, flow.reasons) == (None, ["age_urpd_mismatch"])
    assert [grid.step for grid in flow.grids] == [500, 200]
    assert flow.spot == GOLDEN_CLOSE
    state = store.state()
    assert (state["last_error"], strings(state["reasons"])) == (None, [])


def test_refetched_d_that_is_gone_keeps_the_first(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    # The P1 fixtures' D closes at 82154.25 and its grid snapshots at 81217.6, so D is refetched.
    inner, calls = brk_transport()
    heads: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = inner.handler(request)
        if (
            request.url.path == f"/api/urpd/all/{D.isoformat()}"
            and request.url.params["agg"] == "lin500"
        ):
            heads.append(request)
            if len(heads) == 2:
                return httpx.Response(404, json={"error": {"type": "not_found", "code": "x"}})
        return response

    assert run(store, httpx.MockTransport(handler), NOW) is True

    assert urpd_calls(calls) == [*same_day(D), *refetch_of(D), *past_of(D)]
    assert len(heads) == 2
    first = store.urpd("all", D, "lin500")
    assert first is not None and first.close == 82154.25
    state = store.state()
    assert (state["last_error"], strings(state["reasons"])) == (None, [])
    levels = levels_of(store)
    assert (levels["urpd_date"], levels["onchain_close"]) == ("2026-10-16", 82154.25)
    flow = costflow_of(store)
    assert (flow.now_day, flow.spot) == (D, 82154.25)


def test_age_snapshot_error_does_not_fail_the_stage(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    ages = write_ages(tmp_path / "ages", GOLDEN_CLOSE)
    transport, calls = brk_transport(
        urpd_dir=GOLDEN, age_dir=ages, urpd_fail={("utxos_1w_to_1m_old", "lin500")}
    )

    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert run(store, transport, NOW) is True

    # The failed request ends the age snapshots; the past days are fetched as usual.
    assert urpd_calls(calls, include_ages=True) == [*same_day(D), *ages_of(D)[:4], *past_of(D)]
    assert caplog.text.count("onchain_urpd_age_failed code=brk_unavailable") == 1
    state = store.state()
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == NOW
    assert strings(state["reasons"]) == []
    assert bucket_widths(store) == [200, 500, 1000]
    flow = costflow_of(store)
    assert [grid.step for grid in flow.grids] == [500, 200]
    assert (flow.age, flow.reasons) == (None, ["age_urpd_missing"])


def test_stale_age_snapshot_is_never_paired_with_a_new_d(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    ages = write_ages(tmp_path / "ages", GOLDEN_CLOSE)
    first, _ = brk_transport(urpd_dir=GOLDEN, age_dir=ages)
    assert run(store, first, NOW) is True
    assert costflow_of(store).age is not None

    # An hour on, BRK serves D one block later and has no snapshot of one age cohort.
    later = NOW + timedelta(hours=1)
    inner, _ = brk_transport(
        urpd_dir=GOLDEN, age_dir=ages, urpd_missing={("utxos_under_1h_old", "lin500")}
    )
    assert run(store, reclosed(inner, 81300.0), later) is True

    flow = costflow_of(store)
    assert flow.spot == 81300.0
    assert [grid.step for grid in flow.grids] == [500, 200]
    # The stored snapshot of that cohort is of the earlier block, so Chart 4 has no rows.
    stale = store.urpd("utxos_under_1h_old", D, "lin500")
    assert stale is not None and stale.close == GOLDEN_CLOSE
    assert (flow.age, flow.reasons) == (None, ["age_urpd_mismatch"])


def test_then_snapshot_counts_once_its_day_closed(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    fetched = datetime(2026, 10, 19, 5, 12, 6, tzinfo=UTC)
    for path in sorted(COSTFLOW.glob("urpd_*.json")):
        store.save_urpd(Urpd.model_validate_json(path.read_text()), fetched)
    transport, _ = brk_transport()
    sync = sync_for(store, transport, fetched)
    yesterday = FLOW_D - timedelta(days=1)

    def refetched(at: datetime) -> StoredCostFlow:
        """The cost flow with yesterday's three lin500 snapshots stored as fetched at `at`."""
        for cohort in ("all", "sth", "lth"):
            snapshot = store.urpd(cohort, yesterday, "lin500")
            assert snapshot is not None
            store.save_urpd(snapshot, at)
        flow = sync._cost_flow(FLOW_D)
        assert flow is not None
        return flow

    # 00:30: the day has closed, though it is not final before 02:00, so the 1d window counts.
    flow = refetched(datetime(2026, 10, 19, 0, 30, tzinfo=UTC))
    assert windows_of(flow) == [(500, FLOW_THEN), (200, FLOW_THEN)]
    assert flow.reasons == ["age_urpd_missing"]
    assert flow.snapshot_at == fetched
    # From midnight on.
    flow = refetched(datetime(2026, 10, 19, tzinfo=UTC))
    assert windows_of(flow) == [(500, FLOW_THEN), (200, FLOW_THEN)]
    # 23:12 the day before: still forming, so there is no 1d window on that grid.
    flow = refetched(datetime(2026, 10, 18, 23, 12, tzinfo=UTC))
    assert windows_of(flow) == [(500, FLOW_THEN[1:]), (200, FLOW_THEN)]
    assert flow.reasons == [
        "urpd_grid_partial:lin500",
        "window_missing:1d:lin500",
        "age_urpd_missing",
    ]


def test_day1_stage_fetches_the_daily_range(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, calls = brk_transport()

    assert run(store, transport, NOW) is True

    assert DAY1_FETCH == (*DAY1_SERIES, "price_high", "price_low")
    assert requested(day1_calls(calls)) == set(DAY1_FETCH)
    for name in ("price_high", "price_low"):
        assert len(store.read_series(name, "day1")) == 5037


def test_missing_daily_range_only_takes_chart_4_down(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    # The golden sample, whose snapshots of D share one close: the P1 fixtures' do not, and
    # without a $500 grid nothing would be said about the age groups.
    ages = write_ages(tmp_path / "ages", GOLDEN_CLOSE)
    transport, _ = brk_transport(missing={"price_high"}, urpd_dir=GOLDEN, age_dir=ages)

    assert run(store, transport, NOW) is True

    state = store.state()
    assert strings(state["missing_series"]) == ["day1:price_high"]
    assert strings(state["reasons"]) == ["series_missing:price_high"]
    assert state["last_error"] is None
    assert cycle_of(store).state == "breakout"
    assert {line["name"] for line in levels_of(store)["lines"]} == LINES
    assert bucket_widths(store) == [200, 500, 1000]
    flow = costflow_of(store)
    assert [grid.step for grid in flow.grids] == [500, 200]
    assert (flow.age, flow.reasons) == (None, ["age_floor_missing"])


def test_costflow_derives_the_golden_snapshots(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    at = datetime(2026, 10, 19, 5, 15, tzinfo=UTC)
    transport, _ = brk_transport(urpd_dir=COSTFLOW)

    assert run(store, transport, at) is True

    flow = costflow_of(store)
    assert (flow.now_day, flow.spot, flow.snapshot_at) == (FLOW_D, 82347.76, at)
    assert windows_of(flow) == [(500, FLOW_THEN), (200, FLOW_THEN)]
    assert (flow.qc, flow.reasons, flow.rules) == ([], ["age_urpd_missing"], [])
    # Exactly what the sample's 30 snapshots give.
    sample = [Urpd.model_validate_json(path.read_text()) for path in COSTFLOW.glob("urpd_*.json")]
    snapshots = {(urpd.cohort, urpd.aggregation, urpd.date): urpd for urpd in sample}
    assert flow == cost_flow(FLOW_D, snapshots, {}, [], [], snapshot_at=at)
    derived = store.derived("costflow")
    assert derived is not None and derived[1] == at


def test_costflow_after_midnight_uses_yesterday_and_its_own_past_days(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    after_midnight = datetime(2026, 10, 20, 0, 30, tzinfo=UTC)
    transport, _ = brk_transport(urpd_dir=COSTFLOW, urpd_dates={FLOW_D, *FLOW_THEN})

    assert run(store, transport, after_midnight) is True

    flow = costflow_of(store)
    assert (flow.now_day, flow.spot) == (FLOW_D, 82347.76)
    # D's own past days, not today's, each fetched after it had closed.
    assert FLOW_THEN == [
        date(2026, 10, 18),
        date(2026, 10, 12),
        date(2026, 9, 19),
        date(2026, 7, 21),
    ]
    assert windows_of(flow) == [(500, FLOW_THEN), (200, FLOW_THEN)]
    assert flow.reasons == ["age_urpd_missing"]


def test_costflow_failure_still_derives_everything_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    transport, _ = brk_transport()
    run(store, transport, NOW)
    assert store.derived("costflow") is not None

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret value 123")

    monkeypatch.setattr("wheelhouse_service.onchain.sync.cost_flow", boom)
    second = NOW + timedelta(hours=1)
    again, _ = brk_transport()
    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert run(store, again, second) is True

    # Only the cost flow is gone; every other view is derived as usual.
    assert store.derived("costflow") is None
    for kind in ("cycle", "levels", "costbasis", "pressure", "sellside", "agecohorts"):
        derived = store.derived(kind)
        assert derived is not None and derived[1] == second
    state = store.state()
    assert state["last_error"] is None
    assert instant(state["last_success_at"]) == second
    assert strings(state["reasons"]) == []
    assert "code=costflow_failed" in caplog.text
    assert "secret" not in caplog.text


def test_d_fetched_again_on_a_new_block_is_the_one_used(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    # The P1 fixtures' D closes at 82154.25 and its grid snapshots at 81217.6, as when BRK moves on
    # to a new block after D was fetched; fetched again, D is of that block too.
    inner, calls = brk_transport()
    heads: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = inner.handler(request)
        if (
            request.url.path == f"/api/urpd/all/{D.isoformat()}"
            and request.url.params["agg"] == "lin500"
        ):
            heads.append(request)
            if len(heads) == 2:
                body = {**json.loads(response.content), "close": GOLDEN_CLOSE}
                return httpx.Response(200, json=body)
        return response

    assert run(store, httpx.MockTransport(handler), NOW) is True

    assert urpd_calls(calls) == [*same_day(D), *refetch_of(D), *past_of(D)]
    stored = store.urpd("all", D, "lin500")
    assert stored is not None and stored.close == GOLDEN_CLOSE
    # The levels read the D fetched again, like the cost flow.
    assert levels_of(store)["onchain_close"] == GOLDEN_CLOSE
    flow = costflow_of(store)
    assert flow.spot == GOLDEN_CLOSE
    assert [grid.step for grid in flow.grids] == [500, 200]
    assert flow.reasons == ["age_urpd_missing"]


def test_a_grid_snapshot_brk_lacks_is_checked_as_stored(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    ages = write_ages(tmp_path / "ages", GOLDEN_CLOSE)
    first, _ = brk_transport(urpd_dir=GOLDEN, age_dir=ages)
    assert run(store, first, NOW) is True

    # An hour on, D is one block later and BRK has no `sth lin200` of it: the stored one, of the
    # earlier block, is what the cost flow would read, so the set is fetched again.
    later = NOW + timedelta(hours=1)
    inner, calls = brk_transport(urpd_dir=GOLDEN, age_dir=ages, urpd_missing={("sth", "lin200")})
    assert run(store, reclosed(inner, 81300.0), later) is True

    # The past days were final already, so they are not asked for.
    assert urpd_calls(calls, include_ages=True) == [
        *same_day(D),
        *ages_of(D),
        *refetch_of(D),
        *ages_of(D),
    ]
    flow = costflow_of(store)
    assert [grid.step for grid in flow.grids] == [500]
    assert flow.reasons == ["urpd_mismatch:sth:lin200"]
    assert flow.age is not None


def test_a_failed_refetch_does_not_fail_the_stage(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    store = OnchainStore(tmp_path / "onchain.sqlite")
    # The P1 fixtures' D does not share the close of its grid snapshots, so the set is fetched
    # again, and the second request for `lth lin500` fails.
    inner, calls = brk_transport()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = inner.handler(request)
        if (
            request.url.path == f"/api/urpd/lth/{D.isoformat()}"
            and request.url.params["agg"] == "lin500"
        ):
            seen.append(request)
            if len(seen) == 2:
                return httpx.Response(500)
        return response

    with caplog.at_level(logging.INFO, logger="wheelhouse.onchain"):
        assert run(store, httpx.MockTransport(handler), NOW) is True

    # The failure ends what is fetched again; the past days are fetched as usual.
    assert urpd_calls(calls, include_ages=True) == [
        *same_day(D),
        *ages_of(D),
        *refetch_of(D)[:3],
        *past_of(D),
    ]
    assert caplog.text.count("onchain_urpd_age_failed code=brk_unavailable") == 1
    state = store.state()
    assert (state["last_error"], strings(state["reasons"])) == (None, [])
    assert store.derived("costflow") is not None
