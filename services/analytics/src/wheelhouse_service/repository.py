"""Append-only market versions, immutable snapshots and durable task state in SQLite."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .market import (
    DURATIONS,
    Analysis,
    Bar,
    Batch,
    Dataset,
    Job,
    JobEvent,
    JobRequest,
    Schedule,
    ScheduleRequest,
    SnapshotSummary,
    StorageStats,
    StoredBar,
    Stream,
    digest,
    timestamp,
)

MIGRATIONS = Path(__file__).with_name("migrations")


class LeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class Claim:
    job: Job
    token: str


class Repository:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        files = sorted(MIGRATIONS.glob("*.sql"))
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
        with self.connection(write=True) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER "
                "PRIMARY KEY, checksum TEXT NOT NULL)"
            )
            applied = {
                row[0]: row[1]
                for row in db.execute("SELECT version, checksum FROM schema_migrations")
            }
            if set(applied) - {int(p.name.split("_")[0]) for p in files}:
                raise ValueError("Database schema is newer than this application")
            for path in files:
                number = int(path.name.split("_")[0])
                sql = path.read_text()
                checksum = digest(sql)
                if number in applied:
                    if applied[number] != checksum:
                        raise ValueError("Applied migration checksum changed")
                    continue
                for statement in sql.split(";"):
                    if statement.strip():
                        db.execute(statement)
                db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (number, checksum))

    def ingest(self, batch: Batch) -> str:
        batch_id = digest(batch.model_dump_json())
        with self.connection(write=True) as db:
            if db.execute("SELECT 1 FROM batches WHERE batch_id=?", (batch_id,)).fetchone():
                return batch_id
            db.execute(
                "INSERT INTO batches VALUES (?, ?, ?, ?)",
                (batch_id, batch.stream.key, timestamp(batch.fetched_at), batch.model_dump_json()),
            )
            unique = {bar.open_time: bar for bar in batch.bars}
            for opened in sorted(unique):
                value = unique[opened]
                payload = value.model_dump_json()
                content_hash = digest(payload)
                old = db.execute(
                    "SELECT * FROM bar_revisions WHERE stream_key=? AND open_time=? "
                    "ORDER BY revision DESC LIMIT 1",
                    (batch.stream.key, timestamp(value.open_time)),
                ).fetchone()
                last_observation = db.execute(
                    "SELECT MAX(batches.fetched_at) FROM observations "
                    "JOIN batches USING(batch_id) JOIN bar_revisions USING(revision_id) "
                    "WHERE bar_revisions.stream_key=? AND bar_revisions.open_time=?",
                    (batch.stream.key, timestamp(value.open_time)),
                ).fetchone()[0]
                if last_observation and timestamp(batch.fetched_at) < last_observation:
                    raise ValueError("Out-of-order acquisition precedes the latest observation")
                if old and old["content_hash"] == content_hash:
                    revision_id = old["revision_id"]
                else:
                    if (
                        old
                        and Bar.model_validate_json(old["payload"]).is_closed
                        and not value.is_closed
                    ):
                        raise ValueError("A closed bar cannot revert to forming")
                    if old and timestamp(batch.fetched_at) == last_observation:
                        raise ValueError("Conflicting revision at the same acquisition time")
                    revision_id = uuid4().hex
                    revision = old["revision"] + 1 if old else 1
                    db.execute(
                        "INSERT INTO bar_revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            revision_id,
                            batch.stream.key,
                            timestamp(value.open_time),
                            revision,
                            timestamp(batch.fetched_at),
                            content_hash,
                            payload,
                        ),
                    )
                db.execute(
                    "INSERT OR IGNORE INTO observations VALUES (?, ?)", (batch_id, revision_id)
                )
        return batch_id

    def batch(self, batch_id: str) -> Batch:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if row is None:
            raise KeyError("Batch not found")
        return Batch.model_validate_json(row[0])

    def read(
        self,
        stream: Stream,
        *,
        market_at: datetime,
        knowledge_at: datetime,
        limit: int | None = 1000,
    ) -> Dataset:
        if limit is not None and not 1 <= limit <= 10000:
            raise ValueError("Dataset limit must be 1..10000")
        with self.connection() as db:
            rows = db.execute(
                """
                WITH ranked AS (
                  SELECT *, ROW_NUMBER() OVER(PARTITION BY open_time ORDER BY revision DESC) AS rank
                  FROM bar_revisions WHERE stream_key=? AND fetched_at<=? AND open_time<?
                ) SELECT * FROM ranked WHERE rank=1 ORDER BY open_time DESC LIMIT ?
                """,
                (
                    stream.key,
                    timestamp(knowledge_at),
                    timestamp(market_at),
                    -1 if limit is None else limit,
                ),
            ).fetchall()
            fetched = db.execute(
                "SELECT MAX(fetched_at) FROM batches WHERE stream_key=? AND fetched_at<=?",
                (stream.key, timestamp(knowledge_at)),
            ).fetchone()[0]
        stored = [
            StoredBar(
                revision_id=row["revision_id"],
                revision=row["revision"],
                fetched_at=row["fetched_at"],
                bar=Bar.model_validate_json(row["payload"]),
            )
            for row in reversed(rows)
        ]
        return Dataset(
            stream=stream,
            market_at=market_at,
            knowledge_at=knowledge_at,
            fetched_at=datetime.fromisoformat(fetched) if fetched else None,
            bars=[b for b in stored if b.bar.is_closed and b.bar.close_time <= market_at],
            forming=[b for b in stored if not b.bar.is_closed or b.bar.close_time > market_at],
        )

    def stats(self) -> StorageStats:
        with self.connection() as db:
            return StorageStats(
                schema_version=db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                    0
                ],
                batches=db.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
                revisions=db.execute("SELECT COUNT(*) FROM bar_revisions").fetchone()[0],
                snapshots=db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
            )

    def save_snapshot(self, result: "Analysis", *, created_at: datetime) -> str:
        with self.connection(write=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?, ?, ?)",
                (
                    result.snapshot_id,
                    result.stream.key,
                    timestamp(created_at),
                    result.input_hash,
                    result.model_dump_json(),
                ),
            )
        return result.snapshot_id

    def snapshot(self, snapshot_id: str) -> "Analysis":
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Snapshot not found")
        return Analysis.model_validate_json(row[0])

    def snapshots(self, stream: Stream, limit: int = 30) -> list["SnapshotSummary"]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT snapshot_id, created_at, payload FROM snapshots WHERE "
                "stream_key=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (stream.key, limit),
            ).fetchall()
        result = []
        for row in rows:
            snapshot = Analysis.model_validate_json(row["payload"])
            result.append(
                SnapshotSummary(
                    snapshot_id=snapshot.snapshot_id,
                    created_at=row["created_at"],
                    market_at=snapshot.market_at,
                    knowledge_at=snapshot.knowledge_at,
                    rules=snapshot.rules,
                    data_state=snapshot.data_state,
                    mode=snapshot.mode,
                    bar_count=len(snapshot.bars),
                )
            )
        return result

    def _enqueue(
        self, db: sqlite3.Connection, request: "JobRequest", key: str, now: datetime
    ) -> str:
        existing = db.execute(
            "SELECT job_id, request FROM jobs WHERE request_key=?", (key,)
        ).fetchone()
        payload = request.model_dump_json()
        if existing:
            if JobRequest.model_validate_json(existing["request"]).model_dump_json() != payload:
                raise ValueError("Idempotency key is already used for another request")
            return str(existing["job_id"])
        job_id = uuid4().hex
        at = timestamp(now)
        db.execute(
            """INSERT INTO jobs(job_id, request_key, request, stream_key, state,
                   created_at, updated_at, next_attempt_at)
                   VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (job_id, key, payload, request.stream.key, at, at, at),
        )
        db.execute(
            "INSERT INTO job_events(job_id, at, state, reason) VALUES (?, ?, "
            "'queued', 'requested')",
            (job_id, at),
        )
        return job_id

    def enqueue(self, request: "JobRequest", key: str, *, now: datetime) -> "Job":
        with self.connection(write=True) as db:
            job_id = self._enqueue(db, request, key, now)
        return self.job(job_id)

    @staticmethod
    def _job(row: sqlite3.Row) -> "Job":
        return Job(
            job_id=row["job_id"],
            request=JobRequest.model_validate_json(row["request"]),
            state=row["state"],
            attempts=row["attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            next_attempt_at=row["next_attempt_at"],
            lease_until=row["lease_until"],
            checkpoint_batch_id=row["checkpoint_batch_id"],
            snapshot_id=row["snapshot_id"],
            error_code=row["error_code"],
        )

    def job(self, job_id: str) -> "Job":
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("Job not found")
        return self._job(row)

    def latest_job(self, stream: Stream, *, refresh_only: bool = False) -> "Job | None":
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE stream_key=? "
                "AND (?=0 OR json_extract(request, '$.kind')='refresh') "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (stream.key, int(refresh_only)),
            ).fetchone()
        return self._job(row) if row else None

    def live_snapshot(self, stream: Stream) -> "Analysis | None":
        with self.connection() as db:
            row = db.execute(
                """SELECT snapshots.payload FROM jobs JOIN snapshots USING(snapshot_id)
                JOIN batches ON jobs.checkpoint_batch_id=batches.batch_id
                WHERE jobs.stream_key=? AND jobs.state='succeeded'
                AND json_extract(jobs.request, '$.kind')='refresh'
                ORDER BY batches.fetched_at DESC, jobs.updated_at DESC, jobs.rowid DESC LIMIT 1""",
                (stream.key,),
            ).fetchone()
        return Analysis.model_validate_json(row[0]) if row else None

    def job_events(self, job_id: str) -> list["JobEvent"]:
        self.job(job_id)
        with self.connection() as db:
            rows = db.execute(
                "SELECT at, state, reason FROM job_events WHERE job_id=? ORDER BY event_id",
                (job_id,),
            ).fetchall()
        return [JobEvent(**dict(row)) for row in rows]

    def claim(self, *, now: datetime, lease_seconds: int = 30) -> "Claim | None":
        at = timestamp(now)
        with self.connection(write=True) as db:
            row = db.execute(
                """SELECT * FROM jobs WHERE
                (state IN ('queued', 'retry_wait') AND next_attempt_at<=?) OR
                (state='running' AND lease_until<=?) ORDER BY created_at, rowid LIMIT 1""",
                (at, at),
            ).fetchone()
            if row is None:
                return None
            if row["attempts"] >= 3:
                db.execute(
                    "UPDATE jobs SET state='failed', error_code='lease_exhausted', "
                    "updated_at=?, lease_until=NULL, lease_token=NULL WHERE "
                    "job_id=?",
                    (at, row["job_id"]),
                )
                db.execute(
                    "INSERT INTO job_events(job_id, at, state, reason) VALUES (?, "
                    "?, 'failed', 'lease_exhausted')",
                    (row["job_id"], at),
                )
                return None
            token = uuid4().hex
            until = timestamp(now + timedelta(seconds=lease_seconds))
            db.execute(
                "UPDATE jobs SET state='running', attempts=attempts+1, "
                "updated_at=?, lease_until=?, lease_token=?, error_code=NULL WHERE "
                "job_id=?",
                (at, until, token, row["job_id"]),
            )
            reason = "lease_recovered" if row["state"] == "running" else "claimed"
            db.execute(
                "INSERT INTO job_events(job_id, at, state, reason) VALUES (?, ?, 'running', ?)",
                (row["job_id"], at, reason),
            )
            updated = db.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
        return Claim(self._job(updated), token)

    @staticmethod
    def _owns(db: sqlite3.Connection, claim: "Claim", now: datetime) -> None:
        row = db.execute(
            "SELECT 1 FROM jobs WHERE job_id=? AND lease_token=? AND "
            "state='running' AND lease_until>?",
            (claim.job.job_id, claim.token, timestamp(now)),
        ).fetchone()
        if row is None:
            raise LeaseLost("Task lease expired or changed owner")

    def checkpoint(self, claim: "Claim", batch_id: str, *, now: datetime) -> None:
        if self.batch(batch_id).stream != claim.job.request.stream:
            raise ValueError("Checkpoint stream must match the job")
        with self.connection(write=True) as db:
            self._owns(db, claim, now)
            db.execute(
                "UPDATE jobs SET checkpoint_batch_id=?, updated_at=? WHERE job_id=?",
                (batch_id, timestamp(now), claim.job.job_id),
            )
            db.execute(
                "INSERT INTO job_events(job_id, at, state, reason) VALUES (?, ?, "
                "'running', 'ingested')",
                (claim.job.job_id, timestamp(now)),
            )

    def complete(self, claim: "Claim", result: "Analysis", *, now: datetime) -> None:
        if result.stream != claim.job.request.stream or result.rules != claim.job.request.rules:
            raise ValueError("Result must match the claimed stream and rules")
        with self.connection(write=True) as db:
            self._owns(db, claim, now)
            if claim.job.request.kind == "refresh":
                captured = db.execute(
                    "SELECT batches.fetched_at FROM jobs JOIN batches "
                    "ON jobs.checkpoint_batch_id=batches.batch_id WHERE jobs.job_id=?",
                    (claim.job.job_id,),
                ).fetchone()
                if captured is None or captured[0] != timestamp(result.knowledge_at):
                    raise ValueError("Refresh result must use its persisted acquisition checkpoint")
            db.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (?, ?, ?, ?, ?)",
                (
                    result.snapshot_id,
                    result.stream.key,
                    timestamp(now),
                    result.input_hash,
                    result.model_dump_json(),
                ),
            )
            db.execute(
                "UPDATE jobs SET state='succeeded', snapshot_id=?, updated_at=?, "
                "lease_until=NULL, lease_token=NULL, error_code=NULL WHERE job_id=?",
                (result.snapshot_id, timestamp(now), claim.job.job_id),
            )
            db.execute(
                "INSERT INTO job_events(job_id, at, state, reason) VALUES (?, ?, "
                "'succeeded', 'snapshot_saved')",
                (claim.job.job_id, timestamp(now)),
            )

    def fail(self, claim: "Claim", *, now: datetime, code: str, retryable: bool) -> None:
        with self.connection(write=True) as db:
            self._owns(db, claim, now)
            retry = retryable and claim.job.attempts < 3
            state = "retry_wait" if retry else "failed"
            due = now + timedelta(seconds=2**claim.job.attempts)
            db.execute(
                "UPDATE jobs SET state=?, error_code=?, updated_at=?, "
                "next_attempt_at=?, lease_until=NULL, lease_token=NULL WHERE "
                "job_id=?",
                (state, code, timestamp(now), timestamp(due), claim.job.job_id),
            )
            db.execute(
                "INSERT INTO job_events(job_id, at, state, reason) VALUES (?, ?, ?, ?)",
                (claim.job.job_id, timestamp(now), state, code),
            )

    @staticmethod
    def next_close(stream: Stream, at: datetime) -> datetime:
        interval = DURATIONS[stream.timeframe]
        return datetime.fromtimestamp((int(at.timestamp()) // interval + 1) * interval + 2, UTC)

    def set_schedule(self, request: "ScheduleRequest", *, now: datetime) -> "Schedule":
        schedule_id = digest(request.stream.key)
        due = self.next_close(request.stream, now)
        with self.connection(write=True) as db:
            db.execute(
                """INSERT INTO schedules VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(stream_key) DO UPDATE SET request=excluded.request,
                enabled=excluded.enabled, next_due=excluded.next_due""",
                (
                    schedule_id,
                    request.stream.key,
                    request.model_dump_json(),
                    int(request.enabled),
                    timestamp(due),
                ),
            )
        return Schedule(schedule_id=schedule_id, request=request, next_due=due)

    def schedule(self, stream: Stream) -> "Schedule | None":
        with self.connection() as db:
            row = db.execute("SELECT * FROM schedules WHERE stream_key=?", (stream.key,)).fetchone()
        return (
            Schedule(
                schedule_id=row["schedule_id"],
                request=ScheduleRequest.model_validate_json(row["request"]),
                next_due=row["next_due"],
            )
            if row
            else None
        )

    def dispatch_due(self, *, now: datetime) -> int:
        count = 0
        with self.connection(write=True) as db:
            for row in db.execute(
                "SELECT * FROM schedules WHERE enabled=1 AND next_due<=?", (timestamp(now),)
            ).fetchall():
                request = ScheduleRequest.model_validate_json(row["request"])
                active = db.execute(
                    "SELECT 1 FROM jobs WHERE stream_key=? AND state IN ('queued', "
                    "'running', 'retry_wait') LIMIT 1",
                    (request.stream.key,),
                ).fetchone()
                if not active:
                    self._enqueue(
                        db,
                        JobRequest(stream=request.stream, rules=request.rules),
                        f"schedule:{row['schedule_id']}:{row['next_due']}",
                        now,
                    )
                    count += 1
                db.execute(
                    "UPDATE schedules SET next_due=? WHERE schedule_id=?",
                    (timestamp(self.next_close(request.stream, now)), row["schedule_id"]),
                )
        return count
