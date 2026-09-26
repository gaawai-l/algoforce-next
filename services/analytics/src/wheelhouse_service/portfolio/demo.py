"""Fictional fixtures isolated from real brokerage namespaces."""

from datetime import UTC, date, datetime, timedelta

from .models import Cycle, Instrument, LedgerEvent, PortfolioCapture, Position, Quote
from .store import PortfolioStore

AT = datetime(2026, 9, 25, 20, tzinfo=UTC)
ACCOUNT = "wheelhouse-demo"


def load_demo(store: PortfolioStore) -> None:
    stock = Instrument(
        code="DEMO.ACME",
        underlying="DEMO.ACME",
        kind="stock",
        currency="USD",
        multiplier="1",
        source="synthetic fixture",
    )
    put = Instrument(
        code="DEMO.ACME-P100",
        underlying=stock.code,
        kind="put",
        currency="USD",
        multiplier="100",
        strike="100",
        expiry=date(2026, 9, 25),
        source="synthetic fixture",
    )
    call = Instrument(
        code="DEMO.ACME-C110",
        underlying=stock.code,
        kind="call",
        currency="USD",
        multiplier="100",
        strike="110",
        expiry=date(2026, 10, 16),
        source="synthetic fixture",
    )
    capture = PortfolioCapture(
        source="demo",
        account_id=ACCOUNT,
        captured_at=AT,
        positions=[
            Position(code=stock.code, quantity="100", mark="105", observed_at=AT),
            Position(code=call.code, quantity="-1", mark="1.5", observed_at=AT),
        ],
        instruments=[stock, put, call],
        quotes=[
            Quote(
                code=stock.code,
                spot="105",
                units="per_share",
                theta_basis="day",
                vega_basis="percentage_point",
                observed_at=AT,
                source="synthetic fixture",
            ),
            Quote(
                code=call.code,
                spot="105",
                delta="0.3",
                gamma="0.02",
                theta="-0.05",
                vega="0.1",
                units="per_share",
                theta_basis="day",
                vega_basis="percentage_point",
                observed_at=AT,
                source="synthetic fixture",
            ),
        ],
        fx=[],
        raw={
            "cash": [{"currency": "USD", "cash": 15000}],
            "deals": [],
            "orders": [],
            "fees": [],
            "cash_flows": [],
        },
        errors={"simulated": "Fictional data at a fixed historical time"},
        history_start=date(2026, 9, 1),
        history_end=date(2026, 9, 25),
    )
    store.ingest(capture)
    cycle = Cycle(
        cycle_id="demo-wheel-open",
        source="demo",
        account_id=ACCOUNT,
        underlying=stock.code,
        currency="USD",
        name="ACME · assigned put → covered call",
        created_at=AT - timedelta(days=10),
    )
    store.create_cycle(cycle)
    actions = [
        ("sell_open", put, "2", AT - timedelta(days=10)),
        ("assign", put, "0", AT - timedelta(days=1)),
        ("sell_open", call, "3", AT),
    ]
    for i, (kind, instrument, price, at) in enumerate(actions):
        store.append_event(
            LedgerEvent(
                event_id=f"demo-event-{i}",
                cycle_id=cycle.cycle_id,
                at=at,
                kind=kind,  # type: ignore[arg-type]
                instrument=instrument,
                quantity="1",
                price=price,
                fee="1",
                author="fixture",
                reason="Synthetic worked example",
            )
        )
