"""Financial records remain separate from broker snapshots and analytical overlays."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BeforeValidator, Field, model_validator

from ..market import Model


def money_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Financial values must be decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not number.is_finite() or number.copy_abs() > Decimal("1e18"):
        raise ValueError("Value outside supported range")
    if number.as_tuple().exponent < -18:  # type: ignore[operator]
        raise ValueError("At most 18 decimal places")
    if number.is_zero():
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


Amount = Annotated[str, BeforeValidator(money_text)]
Source = Literal["demo", "moomoo"]


class Instrument(Model):
    code: str = Field(min_length=1, max_length=80)
    underlying: str = Field(min_length=1, max_length=80)
    kind: Literal["stock", "call", "put"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    multiplier: Amount
    strike: Amount | None = None
    expiry: date | None = None
    source: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_instrument(self) -> Self:
        if Decimal(self.multiplier) <= 0:
            raise ValueError("Multiplier must be positive")
        if self.kind == "stock":
            if self.multiplier != "1" or self.code != self.underlying:
                raise ValueError("Stock must have multiplier 1 and identify itself as underlying")
        elif self.strike is None or Decimal(self.strike) <= 0 or self.expiry is None:
            raise ValueError("Option requires strike and expiry")
        return self


class Position(Model):
    code: str
    quantity: Amount
    mark: Amount | None = None
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def valid_mark(self) -> Self:
        if self.mark is not None and Decimal(self.mark) < 0:
            raise ValueError("Mark must be nonnegative")
        return self


class Quote(Model):
    code: str
    spot: Amount
    delta: Amount | None = None
    gamma: Amount | None = None
    theta: Amount | None = None
    vega: Amount | None = None
    units: Literal["per_share", "per_contract"]
    theta_basis: Literal["day", "year"]
    vega_basis: Literal["percentage_point", "unit_volatility"]
    observed_at: AwareDatetime
    source: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def positive_spot(self) -> Self:
        if Decimal(self.spot) <= 0:
            raise ValueError("Underlying spot must be positive")
        return self


class FxRate(Model):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    to_base: Amount
    observed_at: AwareDatetime
    source: str

    @model_validator(mode="after")
    def positive_rate(self) -> Self:
        if Decimal(self.to_base) <= 0:
            raise ValueError("FX must be positive")
        return self


class PortfolioCapture(Model):
    source: Source
    account_id: str = Field(min_length=1, max_length=80)
    captured_at: AwareDatetime
    snapshot_observed_at: AwareDatetime | None = None
    base_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    positions: list[Position]
    instruments: list[Instrument]
    quotes: list[Quote]
    fx: list[FxRate]
    raw: dict[str, Any]
    errors: dict[str, str]
    history_start: date | None = None
    history_end: date | None = None

    @model_validator(mode="after")
    def unique_identifiers(self) -> Self:
        if self.snapshot_observed_at and self.snapshot_observed_at > self.captured_at:
            raise ValueError("Snapshot observation cannot follow capture acquisition")
        for values, field in (
            (self.positions, "code"),
            (self.instruments, "code"),
            (self.quotes, "code"),
            (self.fx, "currency"),
        ):
            keys = [getattr(value, field) for value in values]
            if len(keys) != len(set(keys)):
                raise ValueError("Duplicate identity in portfolio snapshot")
        return self


class Cycle(Model):
    cycle_id: str
    source: Source
    account_id: str
    underlying: str = Field(min_length=1, max_length=80)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=120)
    created_at: AwareDatetime


EventKind = Literal[
    "buy_open",
    "sell_open",
    "buy_close",
    "sell_close",
    "expire",
    "assign",
    "exercise",
    "cash_settle",
]


class LedgerEvent(Model):
    event_id: str = Field(min_length=1, max_length=100)
    cycle_id: str
    at: AwareDatetime
    kind: EventKind
    instrument: Instrument
    quantity: Amount
    price: Amount
    fee: Amount | None = None
    source_record_id: str | None = None
    settlement_record_id: str | None = None
    roll_group: str | None = None
    evidence_issues: list[str] = Field(default_factory=list)
    author: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_event(self) -> Self:
        if Decimal(self.quantity) <= 0 or Decimal(self.price) < 0:
            raise ValueError("Quantity must be positive and price non-negative")
        if self.fee is not None and Decimal(self.fee) < 0:
            raise ValueError("Fee cannot be negative")
        if self.instrument.kind != "stock" and Decimal(self.quantity) % 1:
            raise ValueError("Option quantity must be whole contracts")
        if self.kind == "cash_settle" and self.instrument.kind == "stock":
            raise ValueError("Cash settlement requires an option")
        if self.kind in {"expire", "assign", "exercise"}:
            if self.instrument.kind == "stock" or Decimal(self.price) != 0:
                raise ValueError("Lifecycle events require an option and zero close premium")
        return self


class Lot(Model):
    code: str
    quantity: str
    entry_price: str
    opening_event_id: str


class CycleResult(Model):
    cycle: Cycle
    method: str = "FIFO; option premiums realized separately; assignment shares at strike"
    state: Literal["empty", "open", "closed", "incomplete"]
    premium_received: str | None
    premium_paid: str | None
    gross_cash_movement: str | None
    known_fees: str
    net_cash_movement: str | None
    realized_gross: str | None
    realized_net: str | None
    unrealized: str | None
    lots: list[Lot]
    events: list[LedgerEvent]
    issues: list[str]


class Exposure(Model):
    underlying: str
    currency: str
    share_delta: str | None
    share_gamma: str | None
    theta_daily: str | None
    vega_point: str | None
    dollar_delta_base: str | None
    issues: list[str]


class RiskResult(Model):
    base_currency: str
    evaluated_at: AwareDatetime
    state: Literal["complete", "partial", "unavailable"]
    exposures: list[Exposure]
    dollar_delta: str | None
    theta_daily: str | None
    vega_point: str | None
    issues: list[str]


class SyncRequest(Model):
    account_id: str = Field(pattern=r"^[0-9]+$")
    start: date
    end: date

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.end < self.start or (self.end - self.start).days > 90 or self.end > date.today():
            raise ValueError("Select a past range of at most 90 days per sync")
        return self
