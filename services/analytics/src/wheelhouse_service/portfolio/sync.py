"""Durable, paced, read-only account capture and complete order-fee collection."""

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from threading import Event, Thread
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import AwareDatetime

from ..market import Model, timestamp
from .models import PortfolioCapture, SyncRequest
from .store import PortfolioStore


class BrokerReader(Protocol):
    def sync(self, request: SyncRequest, *, include_fees: bool = True) -> PortfolioCapture: ...
    def fees(self, account: str, ids: list[str]) -> list[dict[str, Any]]: ...


class SyncJob(Model):
    job_id: str
    account_id: str
    state: Literal["queued", "running", "retry_wait", "succeeded", "partial", "failed"]
    phase: Literal["snapshot", "fees"]
    attempts: int
    total_orders: int
    completed_orders: int
    missing_orders: int
    updated_at: AwareDatetime
    next_due: AwareDatetime
    error: str | None


class BrokerSync:
    def __init__(self, store: PortfolioStore, reader: BrokerReader) -> None:
        self.store = store
        self.reader = reader
        self.stopping = Event()
        self.thread: Thread | None = None

    @staticmethod
    def _model(row: sqlite3.Row) -> SyncJob:
        missing = json.loads(row["missing_ids"])
        return SyncJob(
            job_id=row["id"],
            account_id=row["account"],
            state=row["state"],
            phase=row["phase"],
            attempts=row["attempts"],
            total_orders=len(json.loads(row["order_ids"])),
            completed_orders=row["cursor"] - len(missing),
            missing_orders=len(missing),
            updated_at=row["updated_at"],
            next_due=row["next_due"],
            error=row["error"],
        )

    def job(self, identifier: str) -> SyncJob:
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM broker_sync_jobs WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError("Broker sync not found")
        return self._model(row)

    def latest(self, account: str) -> SyncJob | None:
        with self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM broker_sync_jobs WHERE account=? ORDER BY "
                "created_at DESC,rowid DESC LIMIT 1",
                (account,),
            ).fetchone()
        return self._model(row) if row else None

    def submit(self, request: SyncRequest, key: str, *, now: datetime) -> SyncJob:
        payload = request.model_dump_json()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM broker_sync_jobs WHERE request_key=?", (key,)
            ).fetchone()
            if previous:
                if previous["request"] != payload:
                    raise ValueError("Idempotency key belongs to another request")
                return self._model(previous)
            active = db.execute(
                "SELECT * FROM broker_sync_jobs WHERE account=? AND state IN "
                "('queued','running','retry_wait')",
                (request.account_id,),
            ).fetchone()
            if active:
                raise ValueError(
                    "A sync is already active; retry with its original idempotency key"
                )
            identifier = uuid4().hex
            at = timestamp(now)
            db.execute(
                """INSERT INTO broker_sync_jobs(id,request_key,account,request,state,phase,
                created_at,updated_at,next_due) VALUES(?,?,?,?,'queued','snapshot',?,?,?)""",
                (identifier, key, request.account_id, payload, at, at, at),
            )
        return self.job(identifier)

    def run_once(self, *, now: datetime | None = None) -> bool:
        def clock() -> datetime:
            return now if now is not None else datetime.now(UTC)

        at = clock()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT * FROM broker_sync_jobs WHERE
                (state IN ('queued','retry_wait') AND next_due<=?) OR
                (state='running' AND lease_until<=?) ORDER BY created_at,rowid""",
                (timestamp(at), timestamp(at)),
            ).fetchall()
            row = None
            for candidate in rows:
                operation = candidate["phase"]
                limit = db.execute(
                    "SELECT not_before FROM broker_query_limits WHERE account=? AND operation=?",
                    (candidate["account"], operation),
                ).fetchone()
                if not limit or limit[0] <= timestamp(at):
                    row = candidate
                    break
            if row is None:
                return False
            if row["attempts"] >= 3:
                db.execute(
                    "UPDATE broker_sync_jobs SET "
                    "state='failed',error='attempts_exhausted',updated_at=?, "
                    "lease_token=NULL,lease_until=NULL "
                    "WHERE id=?",
                    (timestamp(at), row["id"]),
                )
                return True
            token = uuid4().hex
            db.execute(
                "UPDATE broker_sync_jobs SET "
                "state='running',attempts=attempts+1,lease_token=?,lease_until=?,updated_at=? "
                "WHERE id=?",
                (token, timestamp(at + timedelta(seconds=90)), timestamp(at), row["id"]),
            )
            cooldown = 31 if row["phase"] == "snapshot" else 3.1
            db.execute(
                """INSERT INTO broker_query_limits VALUES(?,?,?)
                ON CONFLICT(account,operation) DO UPDATE SET not_before=excluded.not_before""",
                (row["account"], row["phase"], timestamp(at + timedelta(seconds=cooldown))),
            )
        try:
            request = SyncRequest.model_validate_json(row["request"])
            missing: list[str] = json.loads(row["missing_ids"])
            if row["phase"] == "snapshot":
                capture = self.reader.sync(request, include_fees=False)
                capture = capture.model_copy(
                    update={
                        "snapshot_observed_at": capture.snapshot_observed_at or capture.captured_at
                    }
                )
                if capture.source != "moomoo" or capture.account_id != request.account_id:
                    raise ValueError("Reader returned a different account")
                ids = list(
                    dict.fromkeys(
                        str(deal["order_id"])
                        for deal in capture.raw.get("deals", [])
                        if deal.get("order_id")
                    )
                )
                cursor = 0
                missing = []
            else:
                capture = PortfolioCapture.model_validate_json(row["capture"])
                capture = capture.model_copy(
                    update={
                        "snapshot_observed_at": capture.snapshot_observed_at or capture.captured_at
                    }
                )
                ids = json.loads(row["order_ids"])
                cursor = int(row["cursor"])
                batch = ids[cursor : cursor + 20]
                fees = self.reader.fees(row["account"], batch)
                returned = [str(fee.get("order_id", "")) for fee in fees]
                if len(returned) != len(set(returned)) or not set(returned) <= set(batch):
                    raise ValueError("Invalid order-fee response identity")
                valid = []
                for fee in fees:
                    try:
                        amount = Decimal(str(fee.get("fee_amount")))
                        if amount.is_finite() and amount >= 0:
                            valid.append(str(fee["order_id"]))
                    except InvalidOperation:
                        pass
                missing.extend(identifier for identifier in batch if identifier not in valid)
                raw = {**capture.raw, "fees": [*capture.raw.get("fees", []), *fees]}
                capture = capture.model_copy(update={"raw": raw})
                cursor += len(batch)
            finished = cursor == len(ids)
            errors = dict(capture.errors)
            raw = dict(capture.raw)
            unidentified = sum(not deal.get("order_id") for deal in raw.get("deals", []))
            if unidentified:
                errors["fee_order_identity"] = "Executions without order IDs need reconciliation"
            if not finished:
                errors["fees"] = "Order-fee collection in progress"
            elif missing:
                errors["fees"] = f"Provider omitted fees for {len(missing)} orders"
            elif "deals" in errors or unidentified:
                errors["fees"] = "Execution set unavailable; fee coverage unknown"
            else:
                errors.pop("fees", None)
            raw["_coverage"] = {
                **raw.get("_coverage", {}),
                "fees": {
                    "total_orders": len(ids),
                    "completed_orders": cursor - len(missing),
                    "missing_order_ids": missing,
                    "pending_orders": len(ids) - cursor,
                    "unidentified_executions": unidentified,
                    "query_complete": finished
                    and not missing
                    and not unidentified
                    and "deals" not in errors,
                },
            }
            # Preserve each position's observation time while recording later fee acquisition.
            saved_at = max(clock(), capture.captured_at)
            capture = capture.model_copy(
                update={"captured_at": saved_at, "raw": raw, "errors": errors}
            )
            state = (
                "queued"
                if not finished
                else "partial"
                if missing
                or unidentified
                or any(k in errors for k in ("positions", "cash", "orders", "deals", "cash_flows"))
                else "succeeded"
            )
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute(
                    "SELECT lease_token,lease_until FROM broker_sync_jobs WHERE id=?", (row["id"],)
                ).fetchone()
                if current[0] != token or current[1] <= timestamp(clock()):
                    return True
                # Capture publication and cursor advancement are one atomic transaction.
                self.store.ingest(capture, transaction=db)
                db.execute(
                    """UPDATE broker_sync_jobs SET state=?,phase='fees',attempts=0,
                    capture=?,order_ids=?,cursor=?,missing_ids=?,updated_at=?,next_due=?,
                    lease_token=NULL,lease_until=NULL,error=? WHERE id=?""",
                    (
                        state,
                        capture.model_dump_json(),
                        json.dumps(ids),
                        cursor,
                        json.dumps(missing),
                        timestamp(clock()),
                        timestamp(
                            clock() + timedelta(seconds=3.1) if row["phase"] == "fees" else clock()
                        ),
                        "fees_incomplete" if missing or unidentified else None,
                        row["id"],
                    ),
                )
        except Exception:
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute(
                    "SELECT attempts,lease_token FROM broker_sync_jobs WHERE id=?", (row["id"],)
                ).fetchone()
                if current["lease_token"] == token:
                    state = "failed" if current["attempts"] >= 3 else "retry_wait"
                    limit = db.execute(
                        "SELECT not_before FROM broker_query_limits WHERE "
                        "account=? AND operation=?",
                        (row["account"], row["phase"]),
                    ).fetchone()
                    retry_at = max(clock() + timedelta(seconds=5), datetime.fromisoformat(limit[0]))
                    db.execute(
                        "UPDATE broker_sync_jobs SET "
                        "state=?,error='broker_query_failed',next_due=?,updated_at=?, "
                        "lease_token=NULL,lease_until=NULL "
                        "WHERE id=?",
                        (
                            state,
                            timestamp(retry_at),
                            timestamp(clock()),
                            row["id"],
                        ),
                    )
        return True

    def start(self) -> None:
        def loop() -> None:
            while not self.stopping.is_set():
                try:
                    worked = self.run_once()
                except Exception:
                    logging.getLogger("wheelhouse.broker").error("broker_worker_iteration_failed")
                    worked = False
                if not worked:
                    self.stopping.wait(0.5)

        self.thread = Thread(target=loop, name="wheelhouse-broker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=55)
