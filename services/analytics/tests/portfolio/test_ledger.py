from datetime import UTC, date, datetime, timedelta

from wheelhouse_service.portfolio.ledger import calculate_cycle
from wheelhouse_service.portfolio.models import Cycle, Instrument, LedgerEvent

NOW = datetime(2026, 9, 20, tzinfo=UTC)
STOCK = Instrument(
    code="US.TEST",
    underlying="US.TEST",
    kind="stock",
    currency="USD",
    multiplier="1",
    source="fixture",
)
PUT = Instrument(
    code="TEST-P100",
    underlying="US.TEST",
    kind="put",
    currency="USD",
    multiplier="100",
    strike="100",
    expiry=date(2026, 9, 25),
    source="fixture",
)
CALL = PUT.model_copy(update={"code": "TEST-C110", "kind": "call", "strike": "110"})
CYCLE = Cycle(
    cycle_id="cycle",
    source="demo",
    account_id="demo",
    underlying="US.TEST",
    currency="USD",
    name="Test wheel",
    created_at=NOW,
)


def event(i, kind, instrument, quantity, price, fee="1"):
    return LedgerEvent(
        event_id=str(i),
        cycle_id="cycle",
        at=NOW + timedelta(hours=i),
        kind=kind,
        instrument=instrument,
        quantity=quantity,
        price=price,
        fee=fee,
        author="test",
        reason="Independent worked example",
    )


def test_short_put_assignment_covered_call_and_callaway_do_not_double_count_premium():
    events = [
        event(0, "sell_open", PUT, "1", "2"),
        event(1, "assign", PUT, "1", "0"),
        event(2, "sell_open", CALL, "1", "3"),
        event(3, "assign", CALL, "1", "0"),
    ]
    result = calculate_cycle(CYCLE, events, marks={})
    assert result.state == "closed"
    assert result.premium_received == "500"
    assert result.realized_gross == "1500"
    assert result.realized_net == "1496"
    assert result.net_cash_movement == "1496"
    assert result.lots == []


def test_partial_close_fifo_and_roll_keep_fees_and_cash_distinct():
    events = [event(0, "sell_open", PUT, "2", "3", "2"), event(1, "buy_close", PUT, "1", "1", "1")]
    result = calculate_cycle(CYCLE, events, marks={PUT.code: "2"})
    assert result.realized_gross == "200"
    assert result.realized_net == "198"
    assert result.net_cash_movement == "497"
    assert result.unrealized == "100"
    assert result.lots[0].quantity == "-1"
    assert result.premium_received == "600"
    assert result.premium_paid == "100"


def test_nonstandard_multiplier_and_unknown_fees():
    option = PUT.model_copy(update={"multiplier": "10"})
    events = [
        event(0, "sell_open", option, "1", "3", None),
        event(1, "buy_close", option, "1", "1", "1"),
    ]
    result = calculate_cycle(CYCLE, events, marks={})
    assert result.realized_gross == "20"
    assert result.realized_net is None
    assert result.net_cash_movement is None
    assert result.state == "incomplete"


def test_expiry_realizes_premium_once_and_uncovered_or_missing_history_is_rejected():
    import pytest

    expiry = event(10, "expire", PUT, "1", "0").model_copy(update={"at": NOW + timedelta(days=6)})
    result = calculate_cycle(CYCLE, [event(0, "sell_open", PUT, "1", "2"), expiry], marks={})
    assert result.premium_received == "200"
    assert result.realized_net == "198"
    with pytest.raises(ValueError, match="opening history"):
        calculate_cycle(CYCLE, [event(0, "buy_close", PUT, "1", "1")], marks={})
    with pytest.raises(ValueError, match="Covered call"):
        calculate_cycle(CYCLE, [event(0, "sell_open", CALL, "1", "2")], marks={})


def test_stock_sale_cannot_leave_covered_calls_uncovered():
    import pytest

    with pytest.raises(ValueError, match="uncovered"):
        calculate_cycle(
            CYCLE,
            [
                event(0, "buy_open", STOCK, "100", "100"),
                event(1, "sell_open", CALL, "1", "2"),
                event(2, "sell_close", STOCK, "100", "105"),
            ],
            marks={},
        )


def test_same_timestamp_uses_explicit_input_order_not_random_event_identity():
    opened = event(0, "sell_open", PUT, "1", "2", "0").model_copy(update={"event_id": "z-open"})
    closed = event(0, "buy_close", PUT, "1", "1", "0").model_copy(update={"event_id": "a-close"})
    result = calculate_cycle(CYCLE, [opened, closed], marks={})
    assert result.realized_net == "100"


def test_cash_settlement_closes_option_without_stock_delivery():
    opened = event(0, "sell_open", PUT, "1", "3", "0")
    settlement = event(1, "cash_settle", PUT, "1", "1", "0")
    result = calculate_cycle(CYCLE, [opened, settlement], marks={})
    assert result.lots == []
    assert result.realized_net == "200"
    assert result.net_cash_movement == "200"
    assert result.premium_received == "300"
