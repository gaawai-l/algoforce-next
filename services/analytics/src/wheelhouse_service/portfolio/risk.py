"""Normalize position sensitivities before aggregation; missing data stays missing."""

from datetime import datetime
from decimal import Decimal, localcontext

from .ledger import text
from .models import Exposure, PortfolioCapture, RiskResult


def calculate_risk(
    capture: PortfolioCapture, *, at: datetime, max_age_seconds: int = 900
) -> RiskResult:
    with localcontext() as context:
        context.prec = 60
        return _calculate(capture, at, max_age_seconds)


def _calculate(capture: PortfolioCapture, at: datetime, max_age: int) -> RiskResult:
    instruments = {item.code: item for item in capture.instruments}
    quotes = {item.code: item for item in capture.quotes}
    rates = {item.currency: item for item in capture.fx}
    buckets: dict[tuple[str, str], list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]] = {}
    problems: dict[tuple[str, str], list[str]] = {}
    global_issues: list[str] = [
        message
        for key, message in capture.errors.items()
        if key in {"positions", "position_mapping", "position_direction"}
    ]

    def fresh(time: datetime) -> bool:
        return 0 <= (at - time).total_seconds() <= max_age

    for position in capture.positions:
        qty = Decimal(position.quantity)
        if qty == 0:
            continue
        item = instruments.get(position.code)
        if item is None:
            global_issues.append(f"Contract metadata unavailable: {position.code}")
            continue
        key = item.underlying, item.currency
        buckets.setdefault(key, [])
        issues = problems.setdefault(key, [])
        quote = quotes.get(position.code)
        if not fresh(position.observed_at) or not fresh(capture.captured_at):
            issues.append(f"Stale position: {position.code}")
            continue
        if quote is None or not fresh(quote.observed_at):
            issues.append(f"Missing/stale quote: {position.code}")
            continue
        if item.kind == "stock":
            delta, gamma, theta, vega = qty, Decimal(0), Decimal(0), Decimal(0)
        else:
            if any(value is None for value in (quote.delta, quote.gamma, quote.theta, quote.vega)):
                issues.append(f"Incomplete Greeks: {position.code}")
                continue
            scale = qty * (Decimal(item.multiplier) if quote.units == "per_share" else 1)
            delta = Decimal(quote.delta or "0") * scale
            gamma = Decimal(quote.gamma or "0") * scale
            theta = (
                Decimal(quote.theta or "0") * scale / (365 if quote.theta_basis == "year" else 1)
            )
            vega = (
                Decimal(quote.vega or "0")
                * scale
                / (100 if quote.vega_basis == "unit_volatility" else 1)
            )
        buckets[key].append((delta, gamma, theta, vega, delta * Decimal(quote.spot)))
    exposures: list[Exposure] = []
    total_delta, total_theta, total_vega = Decimal(0), Decimal(0), Decimal(0)
    all_complete = not global_issues
    complete_count = 0
    for (underlying, currency), values in buckets.items():
        issues = problems[(underlying, currency)]
        amounts = [sum((row[i] for row in values), Decimal(0)) for i in range(5)]
        rate = Decimal(1) if currency == capture.base_currency else None
        fx = rates.get(currency)
        if rate is None and fx and fresh(fx.observed_at):
            rate = Decimal(fx.to_base)
        greek_complete = not issues and bool(values)
        if rate is None:
            issues.append(f"Missing/stale FX {currency}/{capture.base_currency}")
        complete = greek_complete and rate is not None
        if complete:
            assert rate is not None
            total_delta += amounts[4] * rate
            total_theta += amounts[2] * rate
            total_vega += amounts[3] * rate
            complete_count += 1
        else:
            all_complete = False
        exposures.append(
            Exposure(
                underlying=underlying,
                currency=currency,
                share_delta=text(amounts[0]) if greek_complete else None,
                share_gamma=text(amounts[1]) if greek_complete else None,
                theta_daily=text(amounts[2]) if greek_complete else None,
                vega_point=text(amounts[3]) if greek_complete else None,
                dollar_delta_base=text(amounts[4] * rate)
                if complete and rate is not None
                else None,
                issues=issues,
            )
        )
    if not capture.positions:
        all_complete = False
        global_issues.append("No position snapshot available")
    return RiskResult(
        base_currency=capture.base_currency,
        evaluated_at=at,
        state="complete" if all_complete else "partial" if complete_count else "unavailable",
        exposures=exposures,
        dollar_delta=text(total_delta) if all_complete else None,
        theta_daily=text(total_theta) if all_complete else None,
        vega_point=text(total_vega) if all_complete else None,
        issues=global_issues,
    )
