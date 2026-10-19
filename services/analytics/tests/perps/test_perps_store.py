"""The perps SQLite store: migration, OI precedence, trade dedupe, coverage and pruning."""

import json
import sqlite3
import stat
from datetime import UTC, date, datetime
from pathlib import Path

from wheelhouse_service.market import digest
from wheelhouse_service.perps import store as store_module
from wheelhouse_service.perps.rows import CzPoint, Kline, OiPoint, RawLiquidation, Trade
from wheelhouse_service.perps.store import PerpsStore, liquidation_fields

DAY = 86_400
H4 = 14_400
M5 = 300
T0 = 1_792_022_400  # 2026-10-15 00:00 UTC
MIGRATIONS = Path(store_module.__file__).with_name("migrations")
WS = Path(__file__).parent / "fixtures" / "ws"


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
        assert [tuple(row) for row in db.execute("SELECT version FROM perps_schema")] == [
            (1,),
            (2,),
            (3,),
        ]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "cz_series",
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


def test_migration_002_maps_stored_liquidations_as_inserts_do(tmp_path: Path):
    """A database the first release left (migration 001 only) gains each event's side, size and
    price, mapped from its raw fields exactly as `insert_liquidations` maps a new event."""
    path = tmp_path / "perps.sqlite3"
    first = (MIGRATIONS / "001_perps.sql").read_text()
    order = json.loads((WS / "binance_force_order_btc.json").read_text())["o"]
    bybit = json.loads((WS / "bybit_all_liquidation.json").read_text())["data"]
    raw: list[tuple[str, dict[str, object]]] = [
        ("binance", order),  # FILLED SELL: longs, z counts
        ("binance", {**order, "S": "BUY", "z": "0.004"}),  # shorts
        ("binance", {**order, "X": "PARTIALLY_FILLED"}),  # not FILLED: no size
        ("binance", {**order, "S": "BUY", "X": "NEW"}),
        ("bybit", bybit[0]),  # Buy: longs
        ("bybit", bybit[1]),  # Sell: shorts
        ("bybit", {**bybit[0], "p": "n/a"}),  # a price that is no number
        ("bybit", {key: value for key, value in bybit[1].items() if key != "p"}),
    ]
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE perps_schema(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)")
    for statement in first.split(";"):
        if statement.strip():
            db.execute(statement)
    db.execute("INSERT INTO perps_schema VALUES(?,?)", (1, digest(first)))
    db.executemany(
        "INSERT INTO liquidations(venue, conn, event_ts, raw_json, key) VALUES(?,?,?,?,?)",
        [(venue, 0, T0 + n, json.dumps(item), str(n)) for n, (venue, item) in enumerate(raw)],
    )
    db.commit()
    db.close()

    store = PerpsStore(path)
    with store.connection() as db:
        assert [row[0] for row in db.execute("SELECT version FROM perps_schema")] == [1, 2, 3]
        migrated = [
            (row["venue"], row["raw_json"], (row["longs"], row["qty"], row["price"]))
            for row in db.execute("SELECT * FROM liquidations ORDER BY id")
        ]
    assert [fields for _, _, fields in migrated] == [
        (1, 0.25, None),
        (0, 0.004, None),
        (1, None, None),
        (0, None, None),
        (1, 0.513, 81602.3),
        (0, 0.02, 81610.0),
        (1, 0.513, None),
        (0, 0.02, None),
    ]
    for venue, raw_json, fields in migrated:
        assert fields == liquidation_fields(venue, json.loads(raw_json))

    # The same events stored now are mapped the same way.
    store.insert_liquidations(
        "binance",
        1,
        [
            RawLiquidation(event_ts=T0, key=str(n), raw=json.dumps(item))
            for n, (venue, item) in enumerate(raw)
            if venue == "binance"
        ],
    )
    store.insert_liquidations(
        "bybit",
        1,
        [
            RawLiquidation(event_ts=T0, key=str(n), raw=json.dumps(item))
            for n, (venue, item) in enumerate(raw)
            if venue == "bybit"
        ],
    )
    with store.connection() as db:
        inserted = [
            (row[0], row[1], row[2])
            for row in db.execute(
                "SELECT longs, qty, price FROM liquidations WHERE conn=1 ORDER BY id"
            )
        ]
    assert inserted == [fields for _, _, fields in migrated]


def test_migration_003_creates_cz_series_and_drops_the_old_direction_check(tmp_path: Path):
    """A database at version 2 holds a direction check in the shape P6 replaced: opening it
    applies migration 003, which removes that row and leaves the other state alone."""
    path = tmp_path / "perps.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE perps_schema(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)")
    for name in ("001_perps.sql", "002_liquidation_fields.sql"):
        sql = (MIGRATIONS / name).read_text()
        for statement in sql.split(";"):
            if statement.strip():
                db.execute(statement)
        db.execute("INSERT INTO perps_schema VALUES(?,?)", (int(name[:3]), digest(sql)))
    db.executemany(
        "INSERT INTO sync_state(key, value) VALUES(?,?)",
        [("direction_check", '{"binance": {}}'), ("last_error", None), ("hosts", "{}")],
    )
    db.commit()
    db.close()

    store = PerpsStore(path)

    with store.connection() as db:
        assert [row[0] for row in db.execute("SELECT version FROM perps_schema")] == [1, 2, 3]
        columns = {row[1]: row[2] for row in db.execute("PRAGMA table_info(cz_series)")}
        assert db.execute("SELECT COUNT(*) FROM cz_series").fetchone()[0] == 0
    assert columns == {
        "venue": "TEXT",
        "kind": "TEXT",
        "step": "INTEGER",
        "t": "INTEGER",
        "a": "REAL",
        "b": "REAL",
        "filled": "INTEGER",
    }
    assert store.state() == {"last_error": None, "hosts": "{}"}


def test_migration_003_has_no_semicolon_in_a_comment():
    # PerpsStore splits a migration on ";", so one inside a comment would cut a statement.
    for file in MIGRATIONS.glob("*.sql"):
        for line in file.read_text().splitlines():
            if line.lstrip().startswith("--"):
                assert ";" not in line, f"{file.name}: {line}"


def cz(t: int, a: float = 1.0, b: float = 2.0, *, filled: bool = False) -> CzPoint:
    return CzPoint(t=t, a=a, b=b, filled=filled)


def test_cz_upsert_replaces_and_reads_back_filled(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    store.upsert_cz("liq", H4, "binance", [cz(T0, 1.5, 2.5), cz(T0 + H4, filled=False)])
    store.upsert_cz("liq", H4, "binance", [cz(T0 + 2 * H4, 0.0, 0.0, filled=True)])
    store.upsert_cz("liq", H4, "bybit", [cz(T0, 9.0, 8.0)])
    store.upsert_cz("liq", M5, "binance", [cz(T0, 7.0, 7.0)])
    store.upsert_cz("oi", H4, "okx", [cz(T0, 70.0, 71.0)])

    assert store.cz_series("liq", H4, "binance", T0) == {
        T0: cz(T0, 1.5, 2.5),
        T0 + H4: cz(T0 + H4),
        T0 + 2 * H4: cz(T0 + 2 * H4, 0.0, 0.0, filled=True),
    }
    # A row is told apart by venue, kind and step, and `since` is inclusive.
    assert store.cz_series("liq", H4, "binance", T0 + H4) == {
        T0 + H4: cz(T0 + H4),
        T0 + 2 * H4: cz(T0 + 2 * H4, 0.0, 0.0, filled=True),
    }
    assert store.cz_series("liq", H4, "bybit", 0) == {T0: cz(T0, 9.0, 8.0)}
    assert store.cz_series("liq", M5, "binance", 0) == {T0: cz(T0, 7.0, 7.0)}
    assert store.cz_series("oi", H4, "okx", 0) == {T0: cz(T0, 70.0, 71.0)}
    assert store.cz_series("oi", H4, "hyperliquid", 0) == {}
    assert store.cz_series("ohlcv", H4, "bybit", 0) == {}

    # Fetching an interval again replaces it, whichever way `filled` changes.
    store.upsert_cz(
        "liq", H4, "binance", [cz(T0, 0.0, 0.0, filled=True), cz(T0 + 2 * H4, 4.0, 5.0)]
    )
    assert store.cz_series("liq", H4, "binance", 0) == {
        T0: cz(T0, 0.0, 0.0, filled=True),
        T0 + H4: cz(T0 + H4),
        T0 + 2 * H4: cz(T0 + 2 * H4, 4.0, 5.0),
    }
    store.upsert_cz("liq", H4, "binance", [])  # nothing to write is fine


def test_cz_latest_lists_only_the_venues_with_rows(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    assert store.cz_latest("liq", H4) == {}
    store.upsert_cz("liq", H4, "binance", [cz(T0), cz(T0 + H4), cz(T0 + 2 * H4)])
    store.upsert_cz("liq", H4, "okx", [cz(T0)])
    store.upsert_cz("liq", M5, "bybit", [cz(T0 + 9 * M5)])
    store.upsert_cz("ohlcv", H4, "bybit", [cz(T0 + 5 * H4)])

    assert store.cz_latest("liq", H4) == {"binance": T0 + 2 * H4, "okx": T0}
    assert store.cz_latest("liq", M5) == {"bybit": T0 + 9 * M5}
    assert store.cz_latest("ohlcv", H4) == {"bybit": T0 + 5 * H4}
    assert store.cz_latest("oi", H4) == {}


def test_prune_keeps_125_days_of_4hour_and_one_day_of_5min(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    now = T0 + 130 * DAY
    four_before, five_before = now - 125 * DAY, now - DAY
    for venue in ("binance", "okx"):
        store.upsert_cz(
            "liq", H4, venue, [cz(four_before - H4), cz(four_before), cz(five_before - H4)]
        )
        store.upsert_cz("liq", M5, venue, [cz(five_before - M5), cz(five_before), cz(now - M5)])
    store.upsert_cz("oi", H4, "okx", [cz(four_before - H4), cz(four_before)])

    store.prune(four_before, trade_ids_before=four_before, cz_5min_before=five_before)

    # 4hour goes by the 125-day cut, 5min by its own one-day cut, whatever the kind or venue.
    for venue in ("binance", "okx"):
        assert list(store.cz_series("liq", H4, venue, 0)) == [four_before, five_before - H4]
        assert list(store.cz_series("liq", M5, venue, 0)) == [five_before, now - M5]
    assert list(store.cz_series("oi", H4, "okx", 0)) == [four_before]


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


def test_stamps_reach_back_to_the_last_row_at_or_before_since(tmp_path: Path):
    store = PerpsStore(tmp_path / "perps.sqlite3")
    store.upsert_klines("bybit", [kline(t) for t in (T0 - 900, T0 - 600, T0 + 300, T0 + 600)])
    store.upsert_oi(
        "binance",
        [OiPoint(t=T0, oi=None, source="archive"), OiPoint(t=T0 + 300, oi=1.0, source="hist")],
    )

    assert store.stamps("kline", "bybit", T0) == [T0 - 600, T0 + 300, T0 + 600]
    assert store.stamps("kline", "bybit", T0 + 300) == [T0 + 300, T0 + 600]
    assert store.stamps("kline", "bybit", T0 - 3600) == [T0 - 900, T0 - 600, T0 + 300, T0 + 600]
    assert store.stamps("kline", "binance", T0) == []
    # A NULL row is a stamp too.
    assert store.stamps("oi", "binance", T0) == [T0, T0 + 300]
    assert store.oi_source("binance", T0) == "archive"
    assert store.oi_source("binance", T0 + 600) is None


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

    store.prune(new, trade_ids_before=new, cz_5min_before=new)

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
