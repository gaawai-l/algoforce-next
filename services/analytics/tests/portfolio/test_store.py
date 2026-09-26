from datetime import timedelta

from test_ledger import CYCLE, NOW, PUT, event

from wheelhouse_service.portfolio.demo import load_demo
from wheelhouse_service.portfolio.models import PortfolioCapture
from wheelhouse_service.portfolio.store import PortfolioStore


def test_demo_is_separate_idempotent_and_reopens(tmp_path):
    path = tmp_path / "portfolio.sqlite"
    store = PortfolioStore(path)
    load_demo(store)
    load_demo(store)
    assert len(store.accounts()) == 1
    assert store.accounts()[0]["source"] == "demo"
    assert len(store.events("demo-wheel-open")) == 3
    assert store.capture("moomoo", "wheelhouse-demo") is None
    assert len(PortfolioStore(path).events("demo-wheel-open")) == 3


def test_fill_import_revisions_and_classification_do_not_double_count(tmp_path):
    import pytest

    store = PortfolioStore(tmp_path / "portfolio.sqlite")
    raw = {
        "deals": [
            {
                "deal_id": "fill1",
                "order_id": "order1",
                "code": PUT.code,
                "qty": 1,
                "price": 2,
                "trd_side": "SELL_SHORT",
            }
        ]
    }
    capture = PortfolioCapture(
        source="demo",
        account_id="demo",
        captured_at=NOW,
        positions=[],
        instruments=[],
        quotes=[],
        fx=[],
        raw=raw,
        errors={},
    )
    store.ingest(capture)
    store.ingest(capture.model_copy(update={"captured_at": NOW + timedelta(seconds=1)}))
    records = store.records("demo", "demo")
    assert len(records) == 1
    store.create_cycle(CYCLE)
    mapped = event(0, "sell_open", PUT, "1", "2").model_copy(
        update={"source_record_id": records[0]["record_id"]}
    )
    store.append_event(mapped)
    store.append_event(mapped)
    assert len(store.events(CYCLE.cycle_id)) == 1
    with pytest.raises(ValueError, match="already classified"):
        store.append_event(mapped.model_copy(update={"event_id": "other"}))


def test_fee_corrections_are_audited_without_replacing_original_event(tmp_path):
    store = PortfolioStore(tmp_path / "fees.sqlite")
    store.create_cycle(CYCLE)
    original = event(0, "sell_open", PUT, "1", "2", None)
    store.append_event(original)
    assert store.events(CYCLE.cycle_id)[0].fee is None
    store.correct_fee(original.event_id, "1.25", "Local user", "Broker statement fee")
    assert store.events(CYCLE.cycle_id)[0].fee == "1.25"
    assert store.append_event(original).known_fees == "1.25"
    assert any(row["action"] == "fee_corrected" for row in store.audit("demo", "demo"))


def test_corrected_broker_fill_cannot_be_classified_twice(tmp_path):
    import pytest

    store = PortfolioStore(tmp_path / "revisions.sqlite")
    raw = {
        "deals": [
            {
                "deal_id": "same-fill",
                "code": PUT.code,
                "qty": 1,
                "price": 2,
                "trd_side": "SELL_SHORT",
            }
        ]
    }
    capture = PortfolioCapture(
        source="demo",
        account_id="demo",
        captured_at=NOW,
        positions=[],
        instruments=[],
        quotes=[],
        fx=[],
        raw=raw,
        errors={},
    )
    store.ingest(capture)
    store.create_cycle(CYCLE)
    record = store.records("demo", "demo")[0]
    store.append_event(
        event(0, "sell_open", PUT, "1", "2").model_copy(
            update={"source_record_id": record["record_id"]}
        )
    )
    corrected = {"deals": [{**raw["deals"][0], "price": 3}]}
    store.ingest(
        capture.model_copy(update={"captured_at": NOW + timedelta(seconds=1), "raw": corrected})
    )
    record = store.records("demo", "demo")[0]
    with pytest.raises(ValueError, match="already classified"):
        store.append_event(
            event(1, "sell_open", PUT, "1", "3").model_copy(
                update={"source_record_id": record["record_id"]}
            )
        )


def test_stale_fill_classification_blocks_results_until_audited_reconciliation(tmp_path):
    from wheelhouse_service.portfolio.ledger import calculate_cycle

    store = PortfolioStore(tmp_path / "stale-fill.sqlite")
    raw = {
        "deals": [
            {"deal_id": "fill", "code": PUT.code, "qty": 1, "price": 2, "trd_side": "SELL_SHORT"}
        ]
    }
    capture = PortfolioCapture(
        source="demo",
        account_id="demo",
        captured_at=NOW,
        positions=[],
        instruments=[],
        quotes=[],
        fx=[],
        raw=raw,
        errors={},
    )
    store.ingest(capture)
    store.create_cycle(CYCLE)
    first = store.records("demo", "demo")[0]
    store.append_event(
        event(0, "sell_open", PUT, "1", "2", "0").model_copy(
            update={"source_record_id": first["record_id"]}
        )
    )
    store.append_event(event(1, "buy_close", PUT, "1", "1", "0"))
    raw["deals"][0]["price"] = 3
    store.ingest(capture.model_copy(update={"captured_at": NOW + timedelta(seconds=1), "raw": raw}))
    result = calculate_cycle(CYCLE, store.events(CYCLE.cycle_id), marks={})
    assert result.state == "incomplete"
    assert result.realized_net is None
    latest = store.records("demo", "demo")[0]
    store.reconcile_fill("0", latest["record_id"], NOW, "0", "Local user", "Broker revised fill")
    result = calculate_cycle(CYCLE, store.events(CYCLE.cycle_id), marks={})
    assert result.realized_net == "200"
    assert any(a["action"] == "fill_reconciled" for a in store.audit("demo", "demo"))


def test_out_of_order_account_capture_cannot_replace_latest_repeated_observation(tmp_path):
    import pytest

    store = PortfolioStore(tmp_path / "out-of-order.sqlite")
    raw = {"deals": [{"deal_id": "fill", "code": PUT.code, "qty": 1, "price": 2}]}
    capture = PortfolioCapture(
        source="demo",
        account_id="demo",
        captured_at=NOW,
        positions=[],
        instruments=[],
        quotes=[],
        fx=[],
        raw=raw,
        errors={},
    )
    store.ingest(capture)
    store.ingest(capture.model_copy(update={"captured_at": NOW + timedelta(seconds=4)}))
    with pytest.raises(ValueError, match="acquisition"):
        store.ingest(
            capture.model_copy(
                update={
                    "captured_at": NOW + timedelta(seconds=3),
                    "raw": {"deals": [{**raw["deals"][0], "price": 3}]},
                }
            )
        )
    assert store.records("demo", "demo")[0]["payload"]["price"] == 2


def test_assignment_delivery_fill_cannot_be_imported_again_as_stock_trade(tmp_path):
    import pytest
    from test_ledger import STOCK

    store = PortfolioStore(tmp_path / "delivery.sqlite")
    capture = PortfolioCapture(
        source="demo",
        account_id="demo",
        captured_at=NOW,
        positions=[],
        instruments=[],
        quotes=[],
        fx=[],
        raw={
            "deals": [
                {
                    "deal_id": "delivery",
                    "code": STOCK.code,
                    "qty": 100,
                    "price": 100,
                    "trd_side": "BUY",
                }
            ]
        },
        errors={},
    )
    store.ingest(capture)
    store.create_cycle(CYCLE)
    record = store.records("demo", "demo")[0]
    store.append_event(event(0, "sell_open", PUT, "1", "2", "0"))
    store.append_event(
        event(1, "assign", PUT, "1", "0", "0").model_copy(
            update={"settlement_record_id": record["record_id"]}
        )
    )
    with pytest.raises(ValueError, match="already classified"):
        store.append_event(
            event(2, "buy_open", STOCK, "100", "100", "0").model_copy(
                update={"source_record_id": record["record_id"]}
            )
        )


def test_legacy_capture_and_event_defaults_remain_idempotent_after_schema_extension(tmp_path):
    import json

    from wheelhouse_service.market import digest, timestamp

    store = PortfolioStore(tmp_path / "legacy.sqlite")
    capture = PortfolioCapture(
        source="demo",
        account_id="demo",
        captured_at=NOW,
        positions=[],
        instruments=[],
        quotes=[],
        fx=[],
        raw={},
        errors={},
    )
    legacy = capture.model_dump(mode="json")
    legacy.pop("snapshot_observed_at")
    payload = json.dumps(legacy, separators=(",", ":"))
    legacy_id = digest(payload)
    store.create_cycle(CYCLE)
    original = event(0, "sell_open", PUT, "1", "2")
    old_event = original.model_dump(mode="json")
    old_event.pop("evidence_issues")
    with store.connection() as db:
        db.execute(
            "INSERT INTO captures VALUES(?,?,?,?,?)",
            (legacy_id, "demo", "demo", timestamp(NOW), payload),
        )
        db.execute(
            "INSERT INTO events VALUES(?,?,?)",
            (original.event_id, CYCLE.cycle_id, json.dumps(old_event, separators=(",", ":"))),
        )
    assert store.ingest(capture) == legacy_id
    assert store.append_event(original).premium_received == "200"
    assert len(store.events(CYCLE.cycle_id)) == 1
