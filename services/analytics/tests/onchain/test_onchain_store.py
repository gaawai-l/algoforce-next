import stat
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from onchain_fixture import history_urpd, load_series, load_urpd

from wheelhouse_service.onchain.brk import SeriesData
from wheelhouse_service.onchain.costbasis_history import HistoryDay, history_row
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import URPD_SET

FETCHED = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
STAMP = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def series(
    values: list[float | None], *, start: int = 0, version: int = 1, index: str = "day1"
) -> SeriesData:
    return SeriesData.model_validate(
        {
            "version": version,
            "index": index,
            "start": start,
            "end": start + len(values),
            "stamp": STAMP,
            "data": values,
        }
    )


def test_migration_is_idempotent_and_private(tmp_path: Path):
    path = tmp_path / "data" / "onchain.sqlite3"
    OnchainStore(path)
    store = OnchainStore(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with store.connection() as db:
        assert [tuple(row) for row in db.execute("SELECT version FROM onchain_schema")] == [
            (1,),
            (2,),
        ]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"series", "series_meta", "urpd", "derived", "sync_state", "urpd_history"} <= tables


def test_replace_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    store.merge_series("a", "day1", series([1.0, 2.0], version=1), FETCHED)
    store.merge_series("b", "day1", series([3.0, None], version=1), FETCHED)
    before = {name: store.read_series(name, "day1") for name in ("a", "b")}

    original = OnchainStore._write_series
    calls = 0

    def fail_on_second(self: OnchainStore, *args: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("disk error")
        original(self, *args)

    monkeypatch.setattr(OnchainStore, "_write_series", fail_on_second)
    replacement = {"a": series([9.0, 9.0, 9.0], version=2), "b": series([8.0], version=2)}
    with pytest.raises(RuntimeError, match="disk error"):
        store.replace_series(replacement, "day1", FETCHED)

    assert calls == 2
    assert {name: store.read_series(name, "day1") for name in ("a", "b")} == before
    assert store.series_version("a", "day1") == 1
    assert store.series_version("b", "day1") == 1


def test_replace_drops_old_positions_and_updates_version(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    store.merge_series("a", "day1", series([1.0, 2.0, 3.0], version=1), FETCHED)

    store.replace_series({"a": series([7.0], start=5, version=2)}, "day1", FETCHED)

    assert [value for _, value in store.read_series("a", "day1")] == [7.0]
    assert store.last_position("a", "day1") == 5
    assert store.series_version("a", "day1") == 2


def test_merge_upserts_by_position_and_keeps_missing_values(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    assert store.series_version("a", "day1") is None
    assert store.last_position("a", "day1") is None
    assert store.read_series("a", "day1") == []

    store.merge_series("a", "day1", series([1.0, 2.0, 3.0], version=1), FETCHED)
    store.merge_series("a", "day1", series([20.0, None, 40.0], start=1, version=2), FETCHED)

    assert [value for _, value in store.read_series("a", "day1")] == [1.0, 20.0, None, 40.0]
    assert store.last_position("a", "day1") == 3
    assert store.series_version("a", "day1") == 2
    # The same name under another index is a separate series.
    assert store.read_series("a", "hour1") == []
    assert store.last_position("a", "hour1") is None


def test_merge_rejects_index_mismatch(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    with pytest.raises(ValueError, match="index"):
        store.merge_series("a", "hour1", series([1.0], index="day1"), FETCHED)
    assert store.read_series("a", "hour1") == []


def test_positions_map_to_utc_from_2009(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    fixture = load_series("price_close", "day1")
    store.merge_series("price_close", "day1", fixture, FETCHED)
    store.merge_series("hourly", "hour1", series([5.0, None, 7.0], index="hour1"), FETCHED)

    rows = store.read_series("price_close", "day1")
    assert len(rows) == len(fixture.data)
    assert rows[-1] == (datetime(2026, 10, 16, tzinfo=UTC), fixture.data[-1])
    assert rows[0][0] == datetime(2009, 1, 1, tzinfo=UTC) + timedelta(days=fixture.start)
    assert [moment for moment, _ in rows] == sorted(moment for moment, _ in rows)
    assert all(moment.utcoffset() == timedelta(0) for moment, _ in rows)

    assert store.read_series("hourly", "hour1") == [
        (datetime(2009, 1, 1, 0, tzinfo=UTC), 5.0),
        (datetime(2009, 1, 1, 1, tzinfo=UTC), None),
        (datetime(2009, 1, 1, 2, tzinfo=UTC), 7.0),
    ]


def test_read_series_tail_returns_last_rows(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    fixture = load_series("price_close", "hour1")
    store.merge_series("price_close", "hour1", fixture, FETCHED)
    everything = store.read_series("price_close", "hour1")

    tail = store.read_series("price_close", "hour1", tail=5)
    assert tail == everything[-5:]
    assert tail[-1] == (datetime(2026, 10, 16, 9, tzinfo=UTC), fixture.data[-1])
    assert [moment for moment, _ in tail] == sorted(moment for moment, _ in tail)
    # Without `tail`, or with a tail longer than the table, every row comes back.
    assert store.read_series("price_close", "hour1", tail=None) == everything
    assert store.read_series("price_close", "hour1", tail=len(everything) + 10) == everything
    assert store.read_series("price_close", "hour1", tail=0) == []
    assert store.read_series("missing", "hour1", tail=3) == []

    # Gaps are kept as None, and a tail only reads its own series and index.
    store.merge_series("gappy", "hour1", series([1.0, None, 3.0], index="hour1"), FETCHED)
    store.merge_series("gappy", "day1", series([9.0, 9.0, 9.0]), FETCHED)
    assert store.read_series("gappy", "hour1", tail=2) == [
        (datetime(2009, 1, 1, 1, tzinfo=UTC), None),
        (datetime(2009, 1, 1, 2, tzinfo=UTC), 3.0),
    ]

    # SQLite treats a negative LIMIT as "no limit", so it must not reach the query.
    with pytest.raises(ValueError, match="tail"):
        store.read_series("price_close", "hour1", tail=-1)


def test_naive_fetch_time_is_rejected(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    with pytest.raises(ValueError, match="Timezone"):
        store.merge_series("a", "day1", series([1.0]), datetime(2026, 10, 16, 10, 0))
    assert store.read_series("a", "day1") == []


def test_state_roundtrip_and_latest_urpd(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    assert store.state() == {
        "brk_version": None,
        "refreshing": None,
        "last_success_at": None,
        "last_error": None,
        "next_due": None,
        "missing_series": None,
        "reasons": None,
        "history_error": None,
    }
    store.set_state(brk_version="0.12.2", refreshing="1", missing_series='["x"]')
    store.set_state(refreshing=None, last_error="brk_unavailable")
    state = store.state()
    assert state["brk_version"] == "0.12.2"
    assert state["refreshing"] is None
    assert state["last_error"] == "brk_unavailable"
    assert state["missing_series"] == '["x"]'
    with pytest.raises(ValueError, match="bogus"):
        store.set_state(bogus="1")

    assert store.latest_urpd("all", "lin500") is None
    older = load_urpd("all").model_copy(update={"date": load_urpd("all").date - timedelta(days=1)})
    newer = load_urpd("all")
    store.save_urpd(older, FETCHED)
    store.save_urpd(newer, FETCHED)
    store.save_urpd(newer, FETCHED + timedelta(hours=1))

    assert store.latest_urpd("all", "lin500") == newer
    assert store.latest_urpd("all", "lin100") is None
    assert store.latest_urpd("sth", "lin500") is None
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM urpd").fetchone()[0] == 2


def test_store_urpd_by_day_and_fetched_at(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    snapshot = load_urpd("sth")
    day = snapshot.date
    assert store.urpd("sth", day, "lin500") is None
    assert store.urpd_fetched_at("sth", day, "lin500") is None

    older = snapshot.model_copy(update={"date": day - timedelta(days=1)})
    store.save_urpd(older, FETCHED)
    store.save_urpd(snapshot, FETCHED)
    store.save_urpd(snapshot, FETCHED + timedelta(hours=1))

    assert store.urpd("sth", day, "lin500") == snapshot
    assert store.urpd("sth", day - timedelta(days=1), "lin500") == older
    # The time of the last save, in UTC.
    fetched = store.urpd_fetched_at("sth", day, "lin500")
    assert fetched == FETCHED + timedelta(hours=1)
    assert fetched is not None and fetched.utcoffset() == timedelta(0)
    assert store.urpd_fetched_at("sth", day - timedelta(days=1), "lin500") == FETCHED
    # Another cohort, aggregation or day is another snapshot.
    assert store.urpd("all", day, "lin500") is None
    assert store.urpd("sth", day, "lin200") is None
    assert store.urpd("sth", day + timedelta(days=1), "lin500") is None
    assert store.urpd_fetched_at("all", day, "lin500") is None
    assert store.urpd_fetched_at("sth", day, "lin200") is None


def test_prune_urpd_keeps_listed_days(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    days = [date(2026, 10, 16) - timedelta(days=n) for n in range(4)]
    for day in days:
        for cohort in ("all", "sth"):
            for agg in ("lin200", "lin500"):
                snapshot = load_urpd(cohort).model_copy(update={"date": day, "aggregation": agg})
                store.save_urpd(snapshot, FETCHED)

    # A listed day without snapshots is no problem.
    store.prune_urpd({days[0], days[2], date(2026, 10, 17)})

    with store.connection() as db:
        kept = {tuple(row) for row in db.execute("SELECT cohort, day, agg FROM urpd")}
    assert kept == {
        (cohort, day.isoformat(), agg)
        for day in (days[0], days[2])
        for cohort in ("all", "sth")
        for agg in ("lin200", "lin500")
    }

    store.prune_urpd(set())
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM urpd").fetchone()[0] == 0


def test_final_urpd_day_needs_every_snapshot_stored_and_final(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    closed = date(2026, 10, 15)
    before = closed - timedelta(days=1)
    candidates = (closed, before)
    # A snapshot is final once fetched at 02:00 on the next day or later.
    final = {
        day: datetime.combine(day + timedelta(days=1), time(2), tzinfo=UTC) for day in candidates
    }

    def save(day: date, fetched_at: datetime, kinds: tuple[tuple[str, str], ...] = URPD_SET):
        for cohort, agg in kinds:
            snapshot = load_urpd(cohort).model_copy(update={"date": day, "aggregation": agg})
            store.save_urpd(snapshot, fetched_at)

    assert store.final_urpd_day(candidates) is None
    save(before, final[before])
    # C lacks one of its nine snapshots, so the day before it is the first that qualifies.
    save(closed, final[closed], URPD_SET[:-1])
    assert store.final_urpd_day(candidates) == before
    # Then all nine are stored, but one was fetched a second before its day was final.
    save(closed, final[closed] - timedelta(seconds=1), URPD_SET[-1:])
    assert store.final_urpd_day(candidates) == before
    # With all nine final, C comes first; the order of the candidates decides.
    save(closed, final[closed], URPD_SET[-1:])
    assert store.final_urpd_day(candidates) == closed
    assert store.final_urpd_day((before, closed)) == before
    # Neither day qualifies.
    save(before, final[before] - timedelta(seconds=1), URPD_SET[:1])
    save(closed, final[closed] - timedelta(seconds=1), URPD_SET[4:5])
    assert store.final_urpd_day(candidates) is None


def test_urpd_not_final_lists_the_missing_and_early_snapshots_in_urpd_set_order(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    day = date(2026, 10, 15)
    final = datetime(2026, 10, 16, 2, tzinfo=UTC)
    assert store.urpd_not_final(day) == list(URPD_SET)

    # One a second before its day is final, the rest at that moment or later; the first is missing.
    stamps = [final - timedelta(seconds=1), final] + [final + timedelta(hours=1)] * 6
    for (cohort, agg), fetched_at in zip(URPD_SET[1:], stamps, strict=True):
        snapshot = load_urpd(cohort).model_copy(update={"date": day, "aggregation": agg})
        store.save_urpd(snapshot, fetched_at)

    assert store.urpd_not_final(day) == [URPD_SET[0], URPD_SET[1]]
    # Another day's snapshots do not count.
    assert store.urpd_not_final(day + timedelta(days=1)) == list(URPD_SET)


def test_derived_roundtrip_and_clear(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    assert store.derived("regime") is None

    store.save_derived("regime", '{"a":1}', FETCHED)
    store.save_derived("regime", '{"a":2}', FETCHED + timedelta(hours=1))
    store.save_derived("other", "x", FETCHED)
    assert store.derived("regime") == ('{"a":2}', FETCHED + timedelta(hours=1))

    store.clear_derived("regime")
    assert store.derived("regime") is None
    assert store.derived("other") == ("x", FETCHED)


def test_urpd_history_round_trip(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    snapshot = history_urpd(date(2025, 10, 20))
    store.save_urpd_history(snapshot, FETCHED)
    store.save_urpd_history_absent(date(2025, 10, 21), FETCHED)
    got = store.urpd_history(date(2025, 10, 20), date(2025, 10, 21))
    assert got[date(2025, 10, 20)] == HistoryDay(
        day=date(2025, 10, 20), close=110893.6, supply=history_row(snapshot), fetched_at=FETCHED
    )
    assert got[date(2025, 10, 21)] == HistoryDay(
        day=date(2025, 10, 21), close=None, supply=None, fetched_at=FETCHED
    )
    with store.connection() as db:  # compact JSON: the storage estimate in the plan rests on it
        text = db.execute(
            "SELECT supplies_json FROM urpd_history WHERE day='2025-10-20'"
        ).fetchone()[0]
    assert len(text) == 2249


def test_urpd_history_overwrites_the_whole_row(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    snapshot = history_urpd(date(2025, 10, 20))
    day = snapshot.date
    later = FETCHED + timedelta(days=1)

    store.save_urpd_history_absent(day, FETCHED)
    store.save_urpd_history(snapshot, later)
    assert store.urpd_history(day, day) == {
        day: HistoryDay(day=day, close=110893.6, supply=history_row(snapshot), fetched_at=later)
    }

    store.save_urpd_history_absent(day, FETCHED)
    assert store.urpd_history(day, day) == {
        day: HistoryDay(day=day, close=None, supply=None, fetched_at=FETCHED)
    }


def test_prune_urpd_history_keeps_from_the_oldest_day(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    snapshot = load_urpd("all")
    for day in (date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)):
        store.save_urpd_history(snapshot.model_copy(update={"date": day}), FETCHED)

    store.prune_urpd_history(date(2026, 10, 15))

    kept = store.urpd_history(date(2026, 10, 1), date(2026, 10, 31))
    assert set(kept) == {date(2026, 10, 15), date(2026, 10, 16)}


def test_prune_urpd_leaves_the_history_alone(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    snapshot = load_urpd("all")
    day = snapshot.date
    store.save_urpd(snapshot, FETCHED)
    store.save_urpd_history(snapshot, FETCHED)

    store.prune_urpd(set())

    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM urpd").fetchone()[0] == 0
    assert set(store.urpd_history(day, day)) == {day}


def test_urpd_days_lists_one_kind(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    assert store.urpd_days("all", "lin500") == []
    for day in (date(2026, 10, 16), date(2026, 10, 15)):
        store.save_urpd(load_urpd("all").model_copy(update={"date": day}), FETCHED)
    store.save_urpd(load_urpd("sth").model_copy(update={"date": date(2026, 10, 14)}), FETCHED)
    other_agg = {"date": date(2026, 10, 13), "aggregation": "lin200"}
    store.save_urpd(load_urpd("all").model_copy(update=other_agg), FETCHED)

    assert store.urpd_days("all", "lin500") == [date(2026, 10, 15), date(2026, 10, 16)]


def test_save_urpd_history_refuses_an_empty_row(tmp_path: Path):
    store = OnchainStore(tmp_path / "onchain.sqlite3")
    snapshot = load_urpd("all")
    low = snapshot.model_copy(
        update={"buckets": [b for b in snapshot.buckets if b.price_floor < 1000]}
    )
    assert low.buckets

    with pytest.raises(ValueError):
        store.save_urpd_history(low, FETCHED)

    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM urpd_history").fetchone()[0] == 0


def test_migration_upgrades_a_store_that_has_only_001(tmp_path: Path):
    path = tmp_path / "onchain.sqlite3"
    store = OnchainStore(path)
    with store.connection() as db:  # make it look like a store from before SR-8
        db.execute("DROP TABLE urpd_history")
        db.execute("DELETE FROM onchain_schema WHERE version=2")
    store.save_urpd(load_urpd("all"), FETCHED)
    store.save_derived("costbasis", '{"a":1}', FETCHED)
    reopened = OnchainStore(path)
    with reopened.connection() as db:
        versions = [
            tuple(r) for r in db.execute("SELECT version FROM onchain_schema ORDER BY version")
        ]
    assert versions == [(1,), (2,)]
    assert reopened.urpd_history(date(2026, 10, 16), date(2026, 10, 16)) == {}
    assert reopened.latest_urpd("all", "lin500").date == date(2026, 10, 16)
    assert reopened.derived("costbasis") == ('{"a":1}', FETCHED)


def test_an_older_image_refuses_a_newer_store(tmp_path: Path):
    path = tmp_path / "onchain.sqlite3"
    store = OnchainStore(path)
    with store.connection() as db:  # a migration this code does not have
        db.execute("INSERT INTO onchain_schema VALUES(999, 'x')")

    with pytest.raises(ValueError, match="newer than this application"):
        OnchainStore(path)
