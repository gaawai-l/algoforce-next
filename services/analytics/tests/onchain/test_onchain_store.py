import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from onchain_fixture import load_series, load_urpd

from wheelhouse_service.onchain.brk import SeriesData
from wheelhouse_service.onchain.store import OnchainStore

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
        assert [tuple(row) for row in db.execute("SELECT version FROM onchain_schema")] == [(1,)]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"series", "series_meta", "urpd", "derived", "sync_state"} <= tables


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
