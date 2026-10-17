"""Private SQLite store for perp REST series, collected events, coverage and derived results."""

import json
import math
import os
import sqlite3
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from ..market import digest, timestamp
from .rows import Kline, OiPoint, RawLiquidation, Stream, Trade
from .states import STEP

Venue = Literal["binance", "bybit"]

# Whether the raw side field means longs were liquidated (spec §3.1).
LONGS: dict[Venue, dict[str, bool]] = {
    "binance": {"SELL": True, "BUY": False},
    "bybit": {"Buy": True, "Sell": False},
}


class LiquidationSizes(NamedTuple):
    """Bybit's distinct liquidations with a size and a price, for the size-unit check."""

    events: int
    min_qty: float | None
    min_notional: float | None
    max_notional: float | None


def liquidation_fields(
    venue: Venue, raw: Mapping[str, Any]
) -> tuple[bool | None, float | None, float | None]:
    """How a stored event counts (spec §3.1): (longs liquidated, quantity in BTC, price).

    Binance: `S=SELL` means longs, the quantity is `z` and counts only when `X=FILLED`. Bybit:
    `S=Buy` means longs, the quantity is `v`, and `p` backs the size-unit check. A field that
    cannot be read is None; an event without a side or quantity does not count. Migration 002
    maps the rows stored before it the same way.
    """
    side = raw.get("S")
    longs = LONGS[venue].get(side) if isinstance(side, str) else None
    if venue == "binance":
        return longs, _finite(raw.get("z")) if raw.get("X") == "FILLED" else None, None
    return longs, _finite(raw.get("v")), _finite(raw.get("p"))


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class PerpsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        # journal_mode cannot change inside a transaction, so WAL is set before the migration.
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
        with self.connection(write=True) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS perps_schema(version INTEGER PRIMARY KEY, "
                "checksum TEXT NOT NULL)"
            )
            applied = {
                row[0]: row[1] for row in db.execute("SELECT version, checksum FROM perps_schema")
            }
            migrations = sorted(Path(__file__).with_name("migrations").glob("*.sql"))
            if set(applied) - {int(file.name.split("_")[0]) for file in migrations}:
                raise ValueError("Perps database is newer than this application")
            for file in migrations:
                number = int(file.name.split("_")[0])
                sql = file.read_text()
                checksum = digest(sql)
                if number in applied:
                    if applied[number] != checksum:
                        raise ValueError("Applied perps migration changed")
                    continue
                for statement in sql.split(";"):
                    if statement.strip():
                        db.execute(statement)
                db.execute("INSERT INTO perps_schema VALUES(?,?)", (number, checksum))
        path.chmod(0o600)

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def upsert_klines(self, venue: Venue, rows: Sequence[Kline]) -> None:
        with self.connection(write=True) as db:
            db.executemany(
                "INSERT INTO kline(venue, t, close, volume, taker_buy, source) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(venue, t) DO UPDATE SET close=excluded.close, "
                "volume=excluded.volume, taker_buy=excluded.taker_buy, source=excluded.source",
                [(venue, r.t, r.close, r.volume, r.taker_buy, r.source) for r in rows],
            )

    def upsert_oi(self, venue: Venue, rows: Sequence[OiPoint]) -> None:
        """Store OI rows, NULL ones too; at one `t`, hist replaces archive but never the reverse."""
        with self.connection(write=True) as db:
            db.executemany(
                "INSERT INTO oi(venue, t, oi, source) VALUES(?,?,?,?) "
                "ON CONFLICT(venue, t) DO UPDATE SET oi=excluded.oi, source=excluded.source "
                "WHERE NOT (oi.source='hist' AND excluded.source='archive')",
                [(venue, r.t, r.oi, r.source) for r in rows],
            )

    def record_trades(self, venue: Venue, trades: Sequence[Trade]) -> None:
        """Add the trades whose id is new to their 10m buckets; ids already seen are skipped."""
        sums: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])  # bucket: [buy, sell]
        with self.connection(write=True) as db:
            for trade in trades:
                inserted = db.execute(
                    "INSERT OR IGNORE INTO trade_ids(venue, id, ts) VALUES(?,?,?)",
                    (venue, trade.id, trade.ts),
                ).rowcount
                if inserted:
                    side = 0 if trade.side == "Buy" else 1
                    sums[int(trade.ts // STEP) * STEP][side] += trade.qty
            db.executemany(
                "INSERT INTO trades_10m(venue, t, buy, sell) VALUES(?,?,?,?) "
                "ON CONFLICT(venue, t) DO UPDATE SET "
                "buy=trades_10m.buy+excluded.buy, sell=trades_10m.sell+excluded.sell",
                [(venue, t, buy, sell) for t, (buy, sell) in sums.items()],
            )

    def insert_liquidations(self, venue: Venue, conn: int, rows: Sequence[RawLiquidation]) -> None:
        """Store every event as this connection received it, with how it counts; duplicates are
        merged when deriving."""
        values = [
            (venue, conn, r.event_ts, r.raw, r.key, *liquidation_fields(venue, json.loads(r.raw)))
            for r in rows
        ]
        with self.connection(write=True) as db:
            db.executemany(
                "INSERT INTO liquidations(venue, conn, event_ts, raw_json, key, longs, qty, price) "
                "VALUES(?,?,?,?,?,?,?,?)",
                values,
            )

    def klines(
        self, venue: Venue, since: int
    ) -> dict[int, tuple[float, float | None, float | None]]:
        """(close, volume, taker_buy) by open time, from `since` on."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT t, close, volume, taker_buy FROM kline WHERE venue=? AND t>=?",
                (venue, since),
            ).fetchall()
        return {row["t"]: (row["close"], row["volume"], row["taker_buy"]) for row in rows}

    def oi(self, venue: Venue, since: int) -> dict[int, tuple[float | None, str]]:
        """(oi, source) by `t`, from `since` on."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT t, oi, source FROM oi WHERE venue=? AND t>=?", (venue, since)
            ).fetchall()
        return {row["t"]: (row["oi"], row["source"]) for row in rows}

    def trades(self, venue: Venue, since: int) -> dict[int, tuple[float, float]]:
        """(buy, sell) by 10m bucket, from `since` on."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT t, buy, sell FROM trades_10m WHERE venue=? AND t>=?", (venue, since)
            ).fetchall()
        return {row["t"]: (row["buy"], row["sell"]) for row in rows}

    def liquidations(self, venue: Venue, since: float) -> list[tuple[int, float, str, str]]:
        """(conn, event_ts, raw_json, key) of every stored event from `since` on."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT conn, event_ts, raw_json, key FROM liquidations "
                "WHERE venue=? AND event_ts>=?",
                (venue, since),
            ).fetchall()
        return [(row["conn"], row["event_ts"], row["raw_json"], row["key"]) for row in rows]

    def liquidation_sums(self, venue: Venue, start: int) -> dict[int, tuple[float, float]]:
        """(longs, shorts) in BTC by 10m bucket number from `start`, over the events that count.

        An event key seen on both connections counts as often as the connection that saw it most
        (spec §3.1). The rows of a key share its time, which the key starts with; were they to
        differ, the earliest would place it.
        """
        with self.connection() as db:
            rows = db.execute(
                "SELECT CAST((ts - :start) / :step AS INTEGER) AS bucket, "
                "TOTAL(CASE WHEN longs = 1 THEN n * qty END), "
                "TOTAL(CASE WHEN longs = 0 THEN n * qty END) "
                "FROM (SELECT MIN(ts) AS ts, MAX(longs) AS longs, MAX(qty) AS qty, MAX(n) AS n "
                "FROM (SELECT key, MIN(event_ts) AS ts, MAX(longs) AS longs, MAX(qty) AS qty, "
                "COUNT(*) AS n FROM liquidations WHERE venue=:venue AND event_ts>=:start "
                "AND longs IS NOT NULL AND qty IS NOT NULL GROUP BY key, conn) GROUP BY key) "
                "GROUP BY bucket",
                {"venue": venue, "start": start, "step": STEP},
            ).fetchall()
        return {row[0]: (row[1], row[2]) for row in rows}

    def liquidation_sizes(self, since: float) -> LiquidationSizes:
        """Bybit's distinct event keys from `since` whose size and price are numbers, with the
        smallest size and the smallest and largest notional."""
        with self.connection() as db:
            row = db.execute(
                "SELECT COUNT(DISTINCT key), MIN(qty), MIN(qty * price), MAX(qty * price) "
                "FROM liquidations WHERE venue='bybit' AND event_ts>=? "
                "AND qty IS NOT NULL AND price IS NOT NULL",
                (since,),
            ).fetchone()
        return LiquidationSizes(*row)

    def open_coverage(self, stream: Stream, conn: int, start: float) -> int:
        with self.connection(write=True) as db:
            row_id = db.execute(
                "INSERT INTO coverage(stream, conn, start, end, open) VALUES(?,?,?,?,1)",
                (stream, conn, start, start),
            ).lastrowid
        if row_id is None:
            raise RuntimeError("SQLite did not return the coverage row id")
        return row_id

    def extend_coverage(self, row_id: int, end: float) -> None:
        with self.connection(write=True) as db:
            db.execute("UPDATE coverage SET end=MAX(end, ?) WHERE id=?", (end, row_id))

    def close_coverage(self, row_id: int, end: float) -> None:
        """A connection ended: its interval stops at `end` (an end never moves back)."""
        with self.connection(write=True) as db:
            db.execute("UPDATE coverage SET end=MAX(end, ?), open=0 WHERE id=?", (end, row_id))

    def close_open_coverage(self) -> None:
        """At startup: the intervals a stopped process left open end at their last saved end."""
        with self.connection(write=True) as db:
            db.execute("UPDATE coverage SET open=0 WHERE open=1")

    def coverage(self, stream: Stream, since: float) -> list[tuple[float, float]]:
        """The union of all connections' intervals that reach `since`, as sorted disjoint spans."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT start, end FROM coverage WHERE stream=? AND end>=? ORDER BY start",
                (stream, since),
            ).fetchall()
        merged: list[tuple[float, float]] = []
        for row in rows:
            start, end = row["start"], row["end"]
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def save_derived(self, key: str, payload: str, computed_at: datetime) -> None:
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO derived(key, payload, computed_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "payload=excluded.payload, computed_at=excluded.computed_at",
                (key, payload, timestamp(computed_at)),
            )

    def derived(self, key: str) -> tuple[str, datetime] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload, computed_at FROM derived WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        return str(row["payload"]), datetime.fromisoformat(row["computed_at"]).astimezone(UTC)

    def set_state(self, **values: str | None) -> None:
        with self.connection(write=True) as db:
            db.executemany(
                "INSERT INTO sync_state(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                list(values.items()),
            )

    def state(self) -> dict[str, str | None]:
        with self.connection() as db:
            return {row["key"]: row["value"] for row in db.execute("SELECT * FROM sync_state")}

    def prune(self, before: int, trade_ids_before: float) -> None:
        """Drop everything older than `before`, coverage included, and trade ids older than
        `trade_ids_before`."""
        with self.connection(write=True) as db:
            for table in ("kline", "oi", "trades_10m"):
                db.execute(f"DELETE FROM {table} WHERE t<?", (before,))
            db.execute("DELETE FROM liquidations WHERE event_ts<?", (before,))
            db.execute("DELETE FROM coverage WHERE end<?", (before,))
            db.execute("DELETE FROM trade_ids WHERE ts<?", (trade_ids_before,))
            db.execute(
                "DELETE FROM archive_absent WHERE day<?",
                (datetime.fromtimestamp(before, UTC).date().isoformat(),),
            )

    def archive_absent(self, day: date) -> bool:
        with self.connection() as db:
            row = db.execute(
                "SELECT 1 FROM archive_absent WHERE day=?", (day.isoformat(),)
            ).fetchone()
        return row is not None

    def mark_archive_absent(self, day: date) -> None:
        with self.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO archive_absent(day) VALUES(?)", (day.isoformat(),))
