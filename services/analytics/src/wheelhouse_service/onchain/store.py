"""Private SQLite store for public BRK series, URPD snapshots and derived results."""

import json
import os
import sqlite3
from collections.abc import Iterator, Sequence, Set
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..market import digest, timestamp
from .brk import EPOCH, URPD_SET, Index, SeriesData, Urpd
from .costbasis_history import HistoryDay, history_row
from .models import final_from

STEP: dict[Index, timedelta] = {"day1": timedelta(days=1), "hour1": timedelta(hours=1)}
STATE_KEYS = (
    "brk_version",
    "refreshing",
    "last_success_at",
    "last_error",
    "next_due",
    "missing_series",
    "reasons",
)


class OnchainStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS onchain_schema(version INTEGER PRIMARY KEY, "
                "checksum TEXT NOT NULL)"
            )
            applied = {
                row[0]: row[1] for row in db.execute("SELECT version, checksum FROM onchain_schema")
            }
            migrations = sorted(Path(__file__).with_name("migrations").glob("*.sql"))
            if set(applied) - {int(file.name.split("_")[0]) for file in migrations}:
                raise ValueError("On-chain database is newer than this application")
            for file in migrations:
                number = int(file.name.split("_")[0])
                sql = file.read_text()
                checksum = digest(sql)
                if number in applied:
                    if applied[number] != checksum:
                        raise ValueError("Applied on-chain migration changed")
                    continue
                for statement in sql.split(";"):
                    if statement.strip():
                        db.execute(statement)
                db.execute("INSERT INTO onchain_schema VALUES(?,?)", (number, checksum))
        path.chmod(0o600)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def merge_series(self, name: str, index: Index, data: SeriesData, fetched_at: datetime) -> None:
        stamp = timestamp(fetched_at)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._write_series(db, name, index, data, stamp)

    def replace_series(
        self, batch: dict[str, SeriesData], index: Index, fetched_at: datetime
    ) -> None:
        stamp = timestamp(fetched_at)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for name, data in batch.items():
                db.execute("DELETE FROM series WHERE series=? AND idx=?", (name, index))
                self._write_series(db, name, index, data, stamp)

    def _write_series(
        self, db: sqlite3.Connection, name: str, index: Index, data: SeriesData, fetched_at: str
    ) -> None:
        if data.index != index:
            raise ValueError(f"Series {name} has index {data.index}, not {index}")
        db.executemany(
            "INSERT INTO series(series, idx, position, value, fetched_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(series, idx, position) DO UPDATE SET "
            "value=excluded.value, fetched_at=excluded.fetched_at",
            [
                (name, index, data.start + offset, value, fetched_at)
                for offset, value in enumerate(data.data)
            ],
        )
        db.execute(
            "INSERT INTO series_meta(series, idx, version) VALUES(?,?,?) "
            "ON CONFLICT(series, idx) DO UPDATE SET version=excluded.version",
            (name, index, data.version),
        )

    def read_series(
        self, name: str, index: Index, tail: int | None = None
    ) -> list[tuple[datetime, float | None]]:
        """Every row in time order, or only the last `tail` rows."""
        if tail is not None and tail < 0:
            # SQLite treats a negative LIMIT as no limit, which would silently read everything.
            raise ValueError("tail must not be negative")
        with self.connection() as db:
            if tail is None:
                rows = db.execute(
                    "SELECT position, value FROM series WHERE series=? AND idx=? ORDER BY position",
                    (name, index),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT position, value FROM (SELECT position, value FROM series "
                    "WHERE series=? AND idx=? ORDER BY position DESC LIMIT ?) ORDER BY position",
                    (name, index, tail),
                ).fetchall()
        return [(EPOCH + STEP[index] * row["position"], row["value"]) for row in rows]

    def series_version(self, name: str, index: Index) -> int | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT version FROM series_meta WHERE series=? AND idx=?", (name, index)
            ).fetchone()
        return None if row is None else int(row["version"])

    def last_position(self, name: str, index: Index) -> int | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT MAX(position) FROM series WHERE series=? AND idx=?", (name, index)
            ).fetchone()
        return None if row[0] is None else int(row[0])

    def save_urpd(self, urpd: Urpd, fetched_at: datetime) -> None:
        buckets = json.dumps(
            [bucket.model_dump() for bucket in urpd.buckets],
            separators=(",", ":"),
            allow_nan=False,
        )
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO urpd(cohort, day, agg, close, total_supply, buckets_json, fetched_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(cohort, day, agg) DO UPDATE SET "
                "close=excluded.close, total_supply=excluded.total_supply, "
                "buckets_json=excluded.buckets_json, fetched_at=excluded.fetched_at",
                (
                    urpd.cohort,
                    urpd.date.isoformat(),
                    urpd.aggregation,
                    urpd.close,
                    urpd.total_supply,
                    buckets,
                    timestamp(fetched_at),
                ),
            )

    def latest_urpd(self, cohort: str, agg: str) -> Urpd | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM urpd WHERE cohort=? AND agg=? ORDER BY day DESC LIMIT 1",
                (cohort, agg),
            ).fetchone()
        return None if row is None else _urpd(row)

    def urpd(self, cohort: str, day: date, agg: str) -> Urpd | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM urpd WHERE cohort=? AND day=? AND agg=?",
                (cohort, day.isoformat(), agg),
            ).fetchone()
        return None if row is None else _urpd(row)

    def urpd_fetched_at(self, cohort: str, day: date, agg: str) -> datetime | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT fetched_at FROM urpd WHERE cohort=? AND day=? AND agg=?",
                (cohort, day.isoformat(), agg),
            ).fetchone()
        return None if row is None else datetime.fromisoformat(row["fetched_at"]).astimezone(UTC)

    def urpd_not_final(self, day: date) -> list[tuple[str, str]]:
        """The URPD_SET snapshots of `day` that are missing or were fetched before it was final."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT cohort, agg, fetched_at FROM urpd WHERE day=?", (day.isoformat(),)
            ).fetchall()
        fetched = {
            (row["cohort"], row["agg"]): datetime.fromisoformat(row["fetched_at"]).astimezone(UTC)
            for row in rows
        }
        final = final_from(day)
        return [kind for kind in URPD_SET if (stamp := fetched.get(kind)) is None or stamp < final]

    def final_urpd_day(self, candidates: Sequence[date]) -> date | None:
        """The first of `candidates` whose URPD_SET snapshots are all stored and final."""
        return next((day for day in candidates if not self.urpd_not_final(day)), None)

    def prune_urpd(self, keep: Set[date]) -> None:
        """Delete the snapshots of every day not in `keep`."""
        days = [day.isoformat() for day in keep]
        marks = ",".join("?" * len(days))
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(f"DELETE FROM urpd WHERE day NOT IN ({marks})", days)

    def save_urpd_history(self, urpd: Urpd, fetched_at: datetime) -> None:
        """Keep the all-coins lin500 `urpd` as its day's row of the cost-basis history."""
        row = history_row(urpd)
        if not row:
            raise ValueError("URPD snapshot has no bucket on the cost-basis history grid")
        supplies = json.dumps(row, separators=(",", ":"), allow_nan=False)
        self._write_history(urpd.date, urpd.close, supplies, fetched_at)

    def save_urpd_history_absent(self, day: date, fetched_at: datetime) -> None:
        """Record that BRK had no snapshot of `day` when asked at `fetched_at`."""
        self._write_history(day, None, None, fetched_at)

    def _write_history(
        self, day: date, close: float | None, supplies: str | None, fetched_at: datetime
    ) -> None:
        stamp = timestamp(fetched_at)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO urpd_history(day, close, supplies_json, fetched_at) VALUES(?,?,?,?) "
                "ON CONFLICT(day) DO UPDATE SET close=excluded.close, "
                "supplies_json=excluded.supplies_json, fetched_at=excluded.fetched_at",
                (day.isoformat(), close, supplies, stamp),
            )

    def urpd_history(self, first: date, last: date) -> dict[date, HistoryDay]:
        """The history rows from `first` through `last`, by day."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM urpd_history WHERE day BETWEEN ? AND ? ORDER BY day",
                (first.isoformat(), last.isoformat()),
            ).fetchall()
        return {
            date.fromisoformat(row["day"]): HistoryDay(
                day=date.fromisoformat(row["day"]),
                close=row["close"],
                supply=None if row["supplies_json"] is None else json.loads(row["supplies_json"]),
                fetched_at=datetime.fromisoformat(row["fetched_at"]).astimezone(UTC),
            )
            for row in rows
        }

    def prune_urpd_history(self, oldest: date) -> None:
        """Delete the history rows of every day before `oldest`."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM urpd_history WHERE day < ?", (oldest.isoformat(),))

    def urpd_days(self, cohort: str, agg: str) -> list[date]:
        """The days with a `cohort` `agg` snapshot in the urpd table, oldest first."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT day FROM urpd WHERE cohort=? AND agg=? ORDER BY day", (cohort, agg)
            ).fetchall()
        return [date.fromisoformat(row["day"]) for row in rows]

    def save_derived(self, kind: str, payload: str, computed_at: datetime) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO derived(kind, payload, computed_at) VALUES(?,?,?) "
                "ON CONFLICT(kind) DO UPDATE SET "
                "payload=excluded.payload, computed_at=excluded.computed_at",
                (kind, payload, timestamp(computed_at)),
            )

    def derived(self, kind: str) -> tuple[str, datetime] | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload, computed_at FROM derived WHERE kind=?", (kind,)
            ).fetchone()
        if row is None:
            return None
        return str(row["payload"]), datetime.fromisoformat(row["computed_at"]).astimezone(UTC)

    def clear_derived(self, kind: str) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM derived WHERE kind=?", (kind,))

    def set_state(self, **values: str | None) -> None:
        unknown = sorted(set(values) - set(STATE_KEYS))
        if unknown:
            raise ValueError(f"Unknown on-chain sync state: {unknown}")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "INSERT INTO sync_state(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                list(values.items()),
            )

    def state(self) -> dict[str, str | None]:
        with self.connection() as db:
            stored = {row["key"]: row["value"] for row in db.execute("SELECT * FROM sync_state")}
        return {key: stored.get(key) for key in STATE_KEYS}


def _urpd(row: sqlite3.Row) -> Urpd:
    return Urpd.model_validate(
        {
            "cohort": row["cohort"],
            "date": row["day"],
            "aggregation": row["agg"],
            "close": row["close"],
            "total_supply": row["total_supply"],
            "buckets": json.loads(row["buckets_json"]),
        }
    )
