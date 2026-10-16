"""The perps SQLite store: migration, OI precedence, trade dedupe, coverage and pruning."""

import stat
from datetime import UTC, date, datetime
from pathlib import Path

from wheelhouse_service.perps.rows import Kline, OiPoint, RawLiquidation, Trade
from wheelhouse_service.perps.store import PerpsStore

DAY = 86_400
T0 = 1_792_022_400  # 2026-10-15 00:00 UTC


def kline(t: int) -> Kline:
    return Kline(t=t, close=100.0, volume=None, taker_buy=None, source="bybit_spot")


def trade(id_: str, ts: float, side: str, qty: float) -> Trade:
    return Trade.model_validate({"id": id_, "ts": ts, "side": side, "qty": qty})


def liquidation(ts: float) -> RawLiquidation:
    return RawLiquidation(event_ts=ts, key=f"{int(ts * 1000)}|Buy|1|1", raw="{}")


def count(store: PerpsStore, table: str) -> int:
    with store.connection() as db:
        return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_store_wal_and_migration(tmp_path: Path):
    path = tmp_path / "data" / "perps.sqlite3"
    PerpsStore(path)
    store = PerpsStore(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with store.connection() as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert [tuple(row) for row in db.execute("SELECT version FROM perps_schema")] == [(1,)]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "kline",
        "oi",
        "trades_10m",
        "trade_ids",
        "liquidations",
        "coverage",
        "derived",
        "sync_state",
        "archive_absent",
    } <= tables


def test_hist_overrides_archive_not_reverse(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    store.upsert_oi(
        "binance",
        [
            OiPoint(t=T0, oi=1.0, source="archive"),
            OiPoint(t=T0 + 300, oi=None, source="archive"),  # quarantined: kept as a NULL row
        ],
    )
    store.upsert_oi("bybit", [OiPoint(t=T0, oi=7.0, source="bybit")])

    store.upsert_oi("binance", [OiPoint(t=T0, oi=2.0, source="hist")])
    store.upsert_oi(
        "binance",
        [OiPoint(t=T0, oi=3.0, source="archive"), OiPoint(t=T0 + 300, oi=None, source="archive")],
    )
    assert store.oi("binance", T0) == {T0: (2.0, "hist"), T0 + 300: (None, "archive")}

    store.upsert_oi(
        "binance",
        [OiPoint(t=T0, oi=5.0, source="hist"), OiPoint(t=T0 + 300, oi=6.0, source="hist")],
    )
    assert store.oi("binance", T0) == {T0: (5.0, "hist"), T0 + 300: (6.0, "hist")}
    assert store.oi("bybit", T0) == {T0: (7.0, "bybit")}


def test_record_trades_dedupes_in_one_batch_and_across_batches(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    store.record_trades(
        "bybit",
        [
            trade("a", T0 + 1.5, "Buy", 1.0),
            trade("a", T0 + 1.5, "Buy", 1.0),  # the same trade twice in one batch
            trade("b", T0 + 2, "Sell", 0.5),
            trade("c", T0 + 600.25, "Buy", 2.0),
        ],
    )
    assert store.trades("bybit", T0) == {T0: (1.0, 0.5), T0 + 600: (2.0, 0.0)}

    store.record_trades(
        "bybit", [trade("b", T0 + 2, "Sell", 0.5), trade("d", T0 + 3, "Sell", 0.25)]
    )
    assert store.trades("bybit", T0) == {T0: (1.0, 0.75), T0 + 600: (2.0, 0.0)}
    assert count(store, "trade_ids") == 4


def test_coverage_union_and_close_open_on_restart(tmp_path: Path):
    path = tmp_path / "perps.sqlite3"
    store = PerpsStore(path)
    first = store.open_coverage("bybit_liq", 0, T0)
    second = store.open_coverage("bybit_liq", 1, T0 + 60)
    store.extend_coverage(first, T0 + 1000)
    store.extend_coverage(second, T0 + 2000)
    store.extend_coverage(first, T0 + 900)  # an end never moves back
    later = store.open_coverage("bybit_liq", 0, T0 + 3000)
    store.extend_coverage(later, T0 + 3600)
    store.extend_coverage(store.open_coverage("bybit_trades", 0, T0), T0 + 9000)

    union = [(T0, T0 + 2000), (T0 + 3000, T0 + 3600)]
    assert store.coverage("bybit_liq", T0) == union
    assert store.coverage("bybit_liq", T0 + 2500) == union[1:]
    assert store.coverage("binance_liq", T0) == []

    # A restart: the intervals left open end at their last saved end.
    restarted = PerpsStore(path)
    restarted.close_open_coverage()
    with restarted.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM coverage WHERE open=1").fetchone()[0] == 0
    assert restarted.coverage("bybit_liq", T0) == union


def test_close_coverage_ends_one_interval(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    first = store.open_coverage("binance_liq", 0, T0)
    second = store.open_coverage("binance_liq", 1, T0 + 60)
    store.extend_coverage(first, T0 + 500)
    store.close_coverage(first, T0 + 400)  # an end never moves back
    store.extend_coverage(second, T0 + 700)

    with store.connection() as db:
        rows = [tuple(row) for row in db.execute("SELECT id, end, open FROM coverage ORDER BY id")]
    assert rows == [(first, T0 + 500, 0), (second, T0 + 700, 1)]
    store.close_coverage(second, T0 + 800)
    assert store.coverage("binance_liq", T0) == [(T0, T0 + 800)]
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM coverage WHERE open=1").fetchone()[0] == 0


def test_prune_drops_old_rows_and_trade_ids(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    old, new = T0 - DAY, T0
    store.upsert_klines("bybit", [kline(old), kline(new)])
    store.upsert_oi(
        "binance", [OiPoint(t=old, oi=1.0, source="hist"), OiPoint(t=new, oi=2.0, source="hist")]
    )
    store.record_trades(
        "bybit", [trade("old", old + 1, "Buy", 1.0), trade("new", new + 1, "Buy", 1.0)]
    )
    store.insert_liquidations("bybit", 0, [liquidation(old + 1), liquidation(new + 1)])
    store.extend_coverage(store.open_coverage("bybit_liq", 0, old), old + 600)
    store.extend_coverage(store.open_coverage("bybit_liq", 0, old + 900), new + 600)
    store.mark_archive_absent(date(2026, 10, 14))
    store.mark_archive_absent(date(2026, 10, 15))

    store.prune(new, trade_ids_before=new)

    assert list(store.klines("bybit", 0)) == [new]
    assert list(store.oi("binance", 0)) == [new]
    assert list(store.trades("bybit", 0)) == [new]
    assert [ts for _, ts, _, _ in store.liquidations("bybit", 0)] == [new + 1]
    # Coverage that reaches past the cut is kept whole.
    assert store.coverage("bybit_liq", 0) == [(old + 900, new + 600)]
    assert not store.archive_absent(date(2026, 10, 14))
    assert store.archive_absent(date(2026, 10, 15))
    # The old id is gone, so the same id counts again.
    store.record_trades(
        "bybit", [trade("old", new + 2, "Buy", 1.0), trade("new", new + 3, "Buy", 1.0)]
    )
    assert store.trades("bybit", 0) == {new: (2.0, 0.0)}


def test_derived_and_state_round_trip(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    computed = datetime(2026, 10, 17, 1, 5, tzinfo=UTC)
    assert store.derived("binance:4h") is None
    store.save_derived("binance:4h", '{"a":1}', computed)
    store.save_derived("binance:4h", '{"a":2}', computed)
    assert store.derived("binance:4h") == ('{"a":2}', computed)

    store.set_state(direction="pending", last_error=None)
    store.set_state(direction="ok")
    assert store.state() == {"direction": "ok", "last_error": None}
