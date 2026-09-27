"""Pure FIFO cycle accounting. Lifecycle events expand into explicit share settlement."""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from .models import Cycle, CycleResult, Instrument, LedgerEvent, Lot


def text(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


@dataclass
class OpenLot:
    instrument: Instrument
    quantity: Decimal
    entry: Decimal
    fee: Decimal
    opening_id: str


def calculate_cycle(
    cycle: Cycle, events: list[LedgerEvent], *, marks: dict[str, str]
) -> CycleResult:
    with localcontext() as context:
        context.prec = 60
        return _calculate(cycle, events, marks)


def _calculate(cycle: Cycle, events: list[LedgerEvent], marks: dict[str, str]) -> CycleResult:
    lots: list[OpenLot] = []
    gross = Decimal(0)
    cash = Decimal(0)
    fees = Decimal(0)
    realized_fees = Decimal(0)
    received = Decimal(0)
    paid = Decimal(0)
    unknown_fee = False
    issues: list[str] = [issue for event in events for issue in event.evidence_issues]
    unresolved = bool(issues)
    # Python's stable sort preserves the explicitly supplied/persisted order on timestamp ties.
    ordered = sorted(events, key=lambda e: e.at)
    if len({e.event_id for e in ordered}) != len(ordered):
        raise ValueError("Duplicate event identity")

    def trade(
        event: LedgerEvent,
        instrument: Instrument,
        kind: str,
        qty: Decimal,
        price: Decimal,
        fee: Decimal,
    ) -> None:
        nonlocal gross, cash, realized_fees
        multiplier = Decimal(instrument.multiplier)
        buying = kind in {"buy_open", "buy_close"}
        cash += (-1 if buying else 1) * qty * price * multiplier
        same = [lot for lot in lots if lot.instrument.code == instrument.code and lot.quantity]
        if any(
            lot.instrument.model_dump(exclude={"source"})
            != instrument.model_dump(exclude={"source"})
            for lot in same
        ):
            raise ValueError("Instrument metadata changed inside an open lot")
        if kind.endswith("open"):
            sign = 1 if buying else -1
            if any(lot.quantity * sign < 0 for lot in same):
                raise ValueError("Opposite lot must be explicitly closed before opening")
            if instrument.kind == "stock" and sign < 0:
                raise ValueError("Wheel cycles do not support short stock")
            if instrument.kind == "call" and sign < 0:
                shares = sum(
                    (lot.quantity for lot in lots if lot.instrument.code == instrument.underlying),
                    Decimal(0),
                )
                calls = sum(
                    (
                        -lot.quantity * Decimal(lot.instrument.multiplier)
                        for lot in lots
                        if lot.instrument.kind == "call" and lot.quantity < 0
                    ),
                    Decimal(0),
                )
                if shares < calls + qty * multiplier:
                    raise ValueError("Covered call exceeds available cycle shares")
            lots.append(OpenLot(instrument, qty * sign, price, fee, event.event_id))
            return
        sign = -1 if buying else 1
        matching = [lot for lot in same if lot.quantity * sign > 0]
        if sum((abs(lot.quantity) for lot in matching), Decimal(0)) < qty:
            raise ValueError("Missing opening history or close exceeds available quantity")
        left = qty
        for lot in matching:
            if left == 0:
                break
            amount = min(abs(lot.quantity), left)
            proportion = amount / abs(lot.quantity)
            allocated_fee = lot.fee * proportion
            gross += (price - lot.entry) * amount * multiplier * sign
            realized_fees += allocated_fee
            lot.fee -= allocated_fee
            lot.quantity -= amount * sign
            left -= amount
        realized_fees += fee
        if instrument.kind == "stock":
            shares = sum(
                (lot.quantity for lot in lots if lot.instrument.code == instrument.code), Decimal(0)
            )
            covered = sum(
                (
                    -lot.quantity * Decimal(lot.instrument.multiplier)
                    for lot in lots
                    if lot.instrument.kind == "call" and lot.quantity < 0
                ),
                Decimal(0),
            )
            if shares < covered:
                raise ValueError("Stock disposal would leave outstanding calls uncovered")

    for event in ordered:
        if event.cycle_id != cycle.cycle_id or event.instrument.underlying != cycle.underlying:
            raise ValueError("Event must belong to the cycle and its underlying")
        if event.instrument.currency != cycle.currency:
            raise ValueError("One currency per accounting cycle")
        qty, price = Decimal(event.quantity), Decimal(event.price)
        fee = Decimal(event.fee or "0")
        fees += fee
        unknown_fee |= event.fee is None
        kind, instrument = event.kind, event.instrument
        if kind in {"expire", "assign", "exercise", "cash_settle"}:
            matches = [
                lot for lot in lots if lot.instrument.code == instrument.code and lot.quantity
            ]
            if not matches:
                raise ValueError("Lifecycle event has no opening lot")
            short = matches[0].quantity < 0
            if kind == "assign" and not short or kind == "exercise" and short:
                raise ValueError(
                    "Assignment requires short options; exercise requires long options"
                )
            if kind == "expire" and instrument.expiry and event.at.date() < instrument.expiry:
                raise ValueError("Expiration cannot precede contract expiry")
            trade(
                event,
                instrument,
                "buy_close" if short else "sell_close",
                qty,
                price if kind == "cash_settle" else Decimal(0),
                fee,
            )
            if kind in {"assign", "exercise"}:
                assert instrument.strike is not None
                stock = Instrument(
                    code=instrument.underlying,
                    underlying=instrument.underlying,
                    kind="stock",
                    currency=instrument.currency,
                    multiplier="1",
                    source="explicit settlement",
                )
                # Normalize metadata to an existing stock lot when present.
                stock = next(
                    (lot.instrument for lot in lots if lot.instrument.code == stock.code), stock
                )
                buy_stock = (instrument.kind == "put" and short) or (
                    instrument.kind == "call" and not short
                )
                trade(
                    event,
                    stock,
                    "buy_open" if buy_stock else "sell_close",
                    qty * Decimal(instrument.multiplier),
                    Decimal(instrument.strike),
                    Decimal(0),
                )
        else:
            if instrument.kind != "stock":
                premium = qty * price * Decimal(instrument.multiplier)
                if kind.startswith("sell"):
                    received += premium
                else:
                    paid += premium
            trade(event, instrument, kind, qty, price, fee)
    remaining = [lot for lot in lots if lot.quantity]
    unrealized = Decimal(0)
    for lot in remaining:
        mark = marks.get(lot.instrument.code)
        if mark is None:
            issues.append(f"Missing current mark: {lot.instrument.code}")
        else:
            unrealized += (
                (Decimal(mark) - lot.entry) * lot.quantity * Decimal(lot.instrument.multiplier)
            )
    if unknown_fee:
        issues.append("Fees incomplete; net accounting results unavailable")
    result_lots = [
        Lot(
            code=lot.instrument.code,
            quantity=text(lot.quantity),
            entry_price=text(lot.entry),
            opening_event_id=lot.opening_id,
        )
        for lot in remaining
    ]
    return CycleResult(
        cycle=cycle,
        state="incomplete"
        if unknown_fee or unresolved
        else "open"
        if remaining
        else "closed"
        if events
        else "empty",
        premium_received=None if unresolved else text(received),
        premium_paid=None if unresolved else text(paid),
        gross_cash_movement=None if unresolved else text(cash),
        known_fees=text(fees),
        net_cash_movement=None if unknown_fee or unresolved else text(cash - fees),
        realized_gross=None if unresolved else text(gross),
        realized_net=None if unknown_fee or unresolved else text(gross - realized_fees),
        unrealized=None
        if unresolved or any(i.startswith("Missing current mark") for i in issues)
        else text(unrealized),
        lots=result_lots,
        events=ordered,
        issues=issues,
    )
