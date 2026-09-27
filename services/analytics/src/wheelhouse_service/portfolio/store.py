"""Private broker mirror and audited local classification overlays."""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..market import digest, timestamp
from .ledger import calculate_cycle
from .models import (
    Cycle,
    CycleResult,
    FxRate,
    Instrument,
    LedgerEvent,
    PortfolioCapture,
    Quote,
    Source,
)


class PortfolioStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS portfolio_schema(version INTEGER PRIMARY KEY, "
                "checksum TEXT NOT NULL)"
            )
            applied = {
                row[0]: row[1]
                for row in db.execute("SELECT version, checksum FROM portfolio_schema")
            }
            migrations = sorted(Path(__file__).with_name("migrations").glob("*.sql"))
            if set(applied) - {int(file.name.split("_")[0]) for file in migrations}:
                raise ValueError("Portfolio database is newer than this application")
            for file in migrations:
                number = int(file.name.split("_")[0])
                sql = file.read_text()
                checksum = digest(sql)
                if number in applied:
                    if applied[number] != checksum:
                        raise ValueError("Applied portfolio migration changed")
                    continue
                for statement in sql.split(";"):
                    if statement.strip():
                        db.execute(statement)
                db.execute("INSERT INTO portfolio_schema VALUES(?,?)", (number, checksum))
        path.chmod(0o600)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def ingest(
        self, capture: PortfolioCapture, *, transaction: sqlite3.Connection | None = None
    ) -> str:
        identifier = digest(capture.model_dump_json())
        with self.connection() if transaction is None else nullcontext(transaction) as db:
            if transaction is None:
                db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM captures WHERE id=?", (identifier,)).fetchone():
                return identifier
            same_time = db.execute(
                "SELECT id,payload FROM captures WHERE source=? AND account=? AND at=?",
                (capture.source, capture.account_id, timestamp(capture.captured_at)),
            ).fetchall()
            for previous in same_time:
                if PortfolioCapture.model_validate_json(previous["payload"]) == capture:
                    return str(previous["id"])
            latest = db.execute(
                "SELECT MAX(at) FROM captures WHERE source=? AND account=?",
                (capture.source, capture.account_id),
            ).fetchone()[0]
            if latest and timestamp(capture.captured_at) <= latest:
                raise ValueError("New capture acquisition must follow the latest observation")
            db.execute(
                "INSERT INTO captures VALUES(?,?,?,?,?)",
                (
                    identifier,
                    capture.source,
                    capture.account_id,
                    timestamp(capture.captured_at),
                    capture.model_dump_json(),
                ),
            )
            for kind in ("orders", "deals", "fees", "cash_flows"):
                for row in capture.raw.get(kind, []):
                    broker_id = str(
                        row.get(
                            {
                                "orders": "order_id",
                                "deals": "deal_id",
                                "fees": "order_id",
                                "cash_flows": "cashflow_id",
                            }[kind],
                            "",
                        )
                    )
                    payload = json.dumps(
                        row, sort_keys=True, separators=(",", ":"), allow_nan=False
                    )
                    if not broker_id:
                        broker_id = "unidentified:" + digest(payload)
                    previous = db.execute(
                        "SELECT id,payload,at FROM records WHERE source=? AND "
                        "account=? AND kind=? AND broker_id=? ORDER BY at "
                        "DESC,rowid DESC LIMIT 1",
                        (capture.source, capture.account_id, kind, broker_id),
                    ).fetchone()
                    if previous and previous["payload"] == payload:
                        continue
                    if previous and previous["at"] >= timestamp(capture.captured_at):
                        raise ValueError("Broker correction must follow previous acquisition")
                    prior = previous["id"] if previous else ""
                    record_id = digest(
                        f"{capture.source}:{capture.account_id}:{kind}:{broker_id}:{prior}:{payload}"
                    )
                    db.execute(
                        "INSERT INTO records VALUES(?,?,?,?,?,?,?)",
                        (
                            record_id,
                            capture.source,
                            capture.account_id,
                            kind,
                            broker_id,
                            timestamp(capture.captured_at),
                            payload,
                        ),
                    )
            self._audit(
                db,
                capture.source,
                capture.account_id,
                "import",
                identifier,
                "collector",
                "Read-only broker snapshot",
            )
        return identifier

    @staticmethod
    def _audit(
        db: sqlite3.Connection,
        source: str,
        account: str,
        action: str,
        entity: str,
        author: str,
        reason: str,
    ) -> None:
        db.execute(
            "INSERT INTO audit(source,account,at,action,entity_id,author,reason) "
            "VALUES(?,?,?,?,?,?,?)",
            (source, account, timestamp(datetime.now(UTC)), action, entity, author, reason),
        )

    def accounts(self) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT source,account,MAX(at) AS captured_at FROM captures GROUP BY source,account"
            ).fetchall()
        return [dict(row) for row in rows]

    def capture(self, source: Source, account: str) -> PortfolioCapture | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM captures WHERE source=? AND account=? ORDER BY "
                "at DESC,rowid DESC LIMIT 1",
                (source, account),
            ).fetchone()
            annotations = db.execute(
                "SELECT kind,code,payload FROM annotations WHERE source=? AND "
                "account=? ORDER BY id",
                (source, account),
            ).fetchall()
        if row is None:
            return None
        result = PortfolioCapture.model_validate_json(row[0])
        instruments = {v.code: v for v in result.instruments}
        quotes = {v.code: v for v in result.quotes}
        fx = {v.currency: v for v in result.fx}
        for annotation in annotations:
            if annotation["kind"] == "instrument":
                instruments[annotation["code"]] = Instrument.model_validate_json(
                    annotation["payload"]
                )
            elif annotation["kind"] == "quote":
                quotes[annotation["code"]] = Quote.model_validate_json(annotation["payload"])
            elif annotation["kind"] == "fx":
                fx[annotation["code"]] = FxRate.model_validate_json(annotation["payload"])
        return result.model_copy(
            update={
                "instruments": list(instruments.values()),
                "quotes": list(quotes.values()),
                "fx": list(fx.values()),
            }
        )

    def records(self, source: Source, account: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                """WITH latest AS (
                  SELECT *, ROW_NUMBER() OVER(
                    PARTITION BY kind,broker_id ORDER BY at DESC,rowid DESC) AS rank
                  FROM records WHERE source=? AND account=?
                ) SELECT * FROM latest WHERE rank=1 ORDER BY kind,broker_id""",
                (source, account),
            ).fetchall()
        return [
            {
                "record_id": r["id"],
                "kind": r["kind"],
                "broker_id": r["broker_id"],
                "captured_at": r["at"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    def create_cycle(self, cycle: Cycle) -> Cycle:
        with self.connection() as db:
            existing = db.execute(
                "SELECT payload FROM cycles WHERE id=?", (cycle.cycle_id,)
            ).fetchone()
            if existing:
                if Cycle.model_validate_json(existing[0]) != cycle:
                    raise ValueError("Cycle identity conflicts")
                return cycle
            db.execute(
                "INSERT INTO cycles VALUES(?,?,?,?)",
                (cycle.cycle_id, cycle.source, cycle.account_id, cycle.model_dump_json()),
            )
            self._audit(
                db,
                cycle.source,
                cycle.account_id,
                "cycle_created",
                cycle.cycle_id,
                "user",
                "Explicit cycle grouping",
            )
        return cycle

    def cycles(self, source: Source, account: str) -> list[Cycle]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM cycles WHERE source=? AND account=? ORDER BY rowid",
                (source, account),
            ).fetchall()
        return [Cycle.model_validate_json(row[0]) for row in rows]

    def cycle(self, identifier: str) -> Cycle:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM cycles WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Cycle not found")
        return Cycle.model_validate_json(row[0])

    def events(self, identifier: str) -> list[LedgerEvent]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM events WHERE cycle_id=? ORDER BY rowid", (identifier,)
            ).fetchall()
        events = [LedgerEvent.model_validate_json(row[0]) for row in rows]
        with self.connection() as db:
            return self._effective_events(db, events)

    @staticmethod
    def _effective_events(db: sqlite3.Connection, events: list[LedgerEvent]) -> list[LedgerEvent]:
        result = []
        for original in events:
            correction = db.execute(
                "SELECT at,payload FROM event_reconciliations WHERE event_id=? "
                "ORDER BY id DESC LIMIT 1",
                (original.event_id,),
            ).fetchone()
            event = (
                LedgerEvent.model_validate_json(correction["payload"]) if correction else original
            )
            fee = db.execute(
                "SELECT fee,at FROM fee_overlays WHERE event_id=? ORDER BY id DESC LIMIT 1",
                (event.event_id,),
            ).fetchone()
            if fee and (not correction or fee["at"] > correction["at"]):
                event = event.model_copy(update={"fee": fee["fee"]})
            issues = []
            for identifier in (event.source_record_id, event.settlement_record_id):
                if not identifier:
                    continue
                record = db.execute("SELECT * FROM records WHERE id=?", (identifier,)).fetchone()
                if not record:
                    issues.append("Linked broker evidence is unavailable")
                    continue
                latest = db.execute(
                    "SELECT id FROM records WHERE source=? AND account=? AND kind=? "
                    "AND broker_id=? ORDER BY at DESC,rowid DESC LIMIT 1",
                    (record["source"], record["account"], record["kind"], record["broker_id"]),
                ).fetchone()
                if latest[0] != identifier:
                    issues.append(
                        f"Broker fill revised after classification: {event.event_id}; "
                        "reconcile before using P&L"
                    )
            result.append(event.model_copy(update={"evidence_issues": issues}))
        return result

    def reconcile_fill(
        self, event_id: str, record_id: str, at: datetime, fee: str | None, author: str, reason: str
    ) -> None:
        from decimal import Decimal

        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()
            record = db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            if row is None or record is None:
                raise KeyError("Event or source record not found")
            old = self._effective_events(db, [LedgerEvent.model_validate_json(row[0])])[0]
            cycle_row = db.execute(
                "SELECT payload FROM cycles WHERE id=?", (old.cycle_id,)
            ).fetchone()
            cycle = Cycle.model_validate_json(cycle_row[0])
            previous_id = old.source_record_id or old.settlement_record_id
            previous = db.execute("SELECT * FROM records WHERE id=?", (previous_id,)).fetchone()
            if (
                not previous
                or any(
                    previous[key] != record[key]
                    for key in ("source", "account", "kind", "broker_id")
                )
                or record["kind"] != "deals"
            ):
                raise ValueError("Reconciliation must link the same original broker fill")
            newest = db.execute(
                "SELECT id FROM records WHERE source=? AND account=? AND kind=? "
                "AND broker_id=? ORDER BY at DESC,rowid DESC LIMIT 1",
                (record["source"], record["account"], record["kind"], record["broker_id"]),
            ).fetchone()
            if newest[0] != record_id:
                raise ValueError("Choose the latest broker revision for reconciliation")
            raw = json.loads(record["payload"])
            if old.source_record_id:
                if raw.get("code") != old.instrument.code:
                    raise ValueError("Changed instrument identity needs a separate review")
                buying = old.kind.startswith("buy")
                if raw.get("trd_side") not in (
                    {"BUY", "BUY_BACK"} if buying else {"SELL", "SELL_SHORT"}
                ):
                    raise ValueError("Changed execution side needs a separate review")
                changes = {
                    "source_record_id": record_id,
                    "quantity": str(raw["qty"]),
                    "price": str(raw["price"]),
                }
            else:
                if raw.get("code") != old.instrument.underlying or Decimal(
                    str(raw.get("price"))
                ) != Decimal(old.instrument.strike or "0"):
                    raise ValueError(
                        "Changed delivery instrument or strike needs a separate review"
                    )
                buying = (old.kind == "assign" and old.instrument.kind == "put") or (
                    old.kind == "exercise" and old.instrument.kind == "call"
                )
                if raw.get("trd_side") not in (
                    {"BUY", "BUY_BACK"} if buying else {"SELL", "SELL_SHORT"}
                ):
                    raise ValueError("Delivery side differs from the lifecycle event")
                changes = {
                    "settlement_record_id": record_id,
                    "quantity": str(Decimal(str(raw["qty"])) / Decimal(old.instrument.multiplier)),
                }
            updated = LedgerEvent.model_validate(
                {
                    **old.model_dump(),
                    **changes,
                    "at": at,
                    "fee": fee,
                    "author": author,
                    "reason": reason,
                    "evidence_issues": [],
                }
            )
            db.execute(
                "INSERT INTO "
                "event_reconciliations(event_id,at,author,reason,payload) "
                "VALUES(?,?,?,?,?)",
                (event_id, timestamp(datetime.now(UTC)), author, reason, updated.model_dump_json()),
            )
            rows = db.execute(
                "SELECT payload FROM events WHERE cycle_id=? ORDER BY rowid", (old.cycle_id,)
            ).fetchall()
            calculate_cycle(
                cycle,
                self._effective_events(db, [LedgerEvent.model_validate_json(r[0]) for r in rows]),
                marks={},
            )
            self._audit(
                db, cycle.source, cycle.account_id, "fill_reconciled", event_id, author, reason
            )

    def correct_fee(self, event_id: str, fee: str, author: str, reason: str) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError("Event not found")
            event = LedgerEvent.model_validate_json(row[0])
            cycle_row = db.execute(
                "SELECT payload FROM cycles WHERE id=?", (event.cycle_id,)
            ).fetchone()
            cycle = Cycle.model_validate_json(cycle_row[0])
            db.execute(
                "INSERT INTO fee_overlays(event_id,fee,at,author,reason) VALUES(?,?,?,?,?)",
                (event_id, fee, timestamp(datetime.now(UTC)), author, reason),
            )
            self._audit(
                db, cycle.source, cycle.account_id, "fee_corrected", event_id, author, reason
            )

    def append_event(self, event: LedgerEvent) -> CycleResult:
        cycle = self.cycle(event.cycle_id)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload FROM events WHERE id=?", (event.event_id,)
            ).fetchone()
            if existing and LedgerEvent.model_validate_json(existing[0]) != event:
                raise ValueError("Event identity conflicts; history is immutable")
            if event.settlement_record_id and event.kind not in {"assign", "exercise"}:
                raise ValueError("Delivery links are only valid for assignment or exercise")
            if event.source_record_id:
                record = db.execute(
                    "SELECT * FROM records WHERE id=?", (event.source_record_id,)
                ).fetchone()
                if (
                    not record
                    or record["source"] != cycle.source
                    or record["account"] != cycle.account_id
                    or record["kind"] != "deals"
                ):
                    raise ValueError("Event must link to this account's execution record")
                if record["broker_id"].startswith("unidentified:"):
                    raise ValueError("Execution identity is missing; use explicit manual evidence")
                raw = json.loads(record["payload"])
                from decimal import Decimal

                if (
                    str(raw.get("code")) != event.instrument.code
                    or Decimal(str(raw.get("qty"))) != Decimal(event.quantity)
                    or Decimal(str(raw.get("price"))) != Decimal(event.price)
                ):
                    raise ValueError(
                        "Event must match the complete linked fill code, quantity and price"
                    )
                side = str(raw.get("trd_side", ""))
                if (
                    side in {"BUY", "BUY_BACK"}
                    and not event.kind.startswith("buy")
                    or side in {"SELL", "SELL_SHORT"}
                    and not event.kind.startswith("sell")
                ):
                    raise ValueError("Event direction conflicts with linked execution")
                used = db.execute(
                    "SELECT events.id FROM events JOIN records ON "
                    "(records.id=json_extract(events.payload,'$.source_record_id') "
                    "OR "
                    "records.id=json_extract(events.payload,'$.settlement_record_id')) "
                    "WHERE records.source=? AND records.account=? AND "
                    "records.kind='deals' AND records.broker_id=?",
                    (cycle.source, cycle.account_id, record["broker_id"]),
                ).fetchone()
                if used and used[0] != event.event_id:
                    raise ValueError("Fill is already classified")
            if event.settlement_record_id:
                record = db.execute(
                    "SELECT * FROM records WHERE id=?", (event.settlement_record_id,)
                ).fetchone()
                if (
                    not record
                    or record["source"] != cycle.source
                    or record["account"] != cycle.account_id
                    or record["kind"] != "deals"
                ):
                    raise ValueError("Delivery must link to this account's execution")
                if record["broker_id"].startswith("unidentified:"):
                    raise ValueError("Execution identity is missing; use explicit manual evidence")
                raw = json.loads(record["payload"])
                from decimal import Decimal

                if (
                    raw.get("code") != event.instrument.underlying
                    or Decimal(str(raw.get("qty")))
                    != Decimal(event.quantity) * Decimal(event.instrument.multiplier)
                    or Decimal(str(raw.get("price"))) != Decimal(event.instrument.strike or "0")
                ):
                    raise ValueError("Delivery must match underlying, actual multiplier and strike")
                buying = (event.kind == "assign" and event.instrument.kind == "put") or (
                    event.kind == "exercise" and event.instrument.kind == "call"
                )
                if str(raw.get("trd_side")) not in (
                    {"BUY", "BUY_BACK"} if buying else {"SELL", "SELL_SHORT"}
                ):
                    raise ValueError("Delivery direction conflicts with lifecycle event")
                used = db.execute(
                    "SELECT events.id FROM events JOIN records ON "
                    "(records.id=json_extract(events.payload,'$.source_record_id') "
                    "OR "
                    "records.id=json_extract(events.payload,'$.settlement_record_id')) "
                    "WHERE records.source=? AND records.account=? AND "
                    "records.kind='deals' AND records.broker_id=?",
                    (cycle.source, cycle.account_id, record["broker_id"]),
                ).fetchone()
                if used and used[0] != event.event_id:
                    raise ValueError("Delivery fill is already classified")
            rows = db.execute(
                "SELECT payload FROM events WHERE cycle_id=? ORDER BY rowid", (event.cycle_id,)
            ).fetchall()
            events = [LedgerEvent.model_validate_json(row[0]) for row in rows]
            if not existing:
                events.append(event)
            result = calculate_cycle(cycle, self._effective_events(db, events), marks={})
            if not existing:
                db.execute(
                    "INSERT INTO events VALUES(?,?,?)",
                    (event.event_id, event.cycle_id, event.model_dump_json()),
                )
                self._audit(
                    db,
                    cycle.source,
                    cycle.account_id,
                    "event_added",
                    event.event_id,
                    event.author,
                    event.reason,
                )
        return result

    def annotate(
        self,
        source: Source,
        account: str,
        kind: str,
        value: Instrument | Quote | FxRate,
        author: str,
        reason: str,
    ) -> None:
        code = value.currency if isinstance(value, FxRate) else value.code
        with self.connection() as db:
            db.execute(
                "INSERT INTO "
                "annotations(source,account,kind,code,at,author,reason,payload) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    source,
                    account,
                    kind,
                    code,
                    timestamp(datetime.now(UTC)),
                    author,
                    reason,
                    value.model_dump_json(),
                ),
            )
            self._audit(db, source, account, "annotation", code, author, reason)

    def audit(self, source: Source, account: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT at,action,entity_id,author,reason FROM audit WHERE source=? "
                "AND account=? ORDER BY id DESC LIMIT 100",
                (source, account),
            ).fetchall()
        return [dict(row) for row in rows]
