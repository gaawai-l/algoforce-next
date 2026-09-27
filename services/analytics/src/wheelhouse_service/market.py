"""Normalized market contracts, independent of transport and persistence."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .indicators.demark.models import DemarkConfig, DemarkResult

Timeframe = Literal["5m", "15m", "1h", "4h", "1d"]
Source = Literal["fixture", "binance"]
DURATIONS: dict[str, int] = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Timezone is required")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_serialization_defaults_required=True,
    )


class Stream(Model):
    source: Source
    symbol: Literal["BTCUSDT", "ETHUSDT"]
    timeframe: Timeframe
    venue: Literal["binance-spot"] = "binance-spot"
    market_session: Literal["24/7"] = "24/7"
    timezone: Literal["UTC"] = "UTC"
    quote_currency: Literal["USDT"] = "USDT"
    base_currency: Literal["BTC", "ETH"] = "BTC"
    price_encoding: Literal["decimal_string_18_places"] = "decimal_string_18_places"

    @model_validator(mode="before")
    @classmethod
    def base_from_symbol(cls, values: Any) -> Any:
        if isinstance(values, dict) and "base_currency" not in values:
            return {
                **values,
                "base_currency": "ETH" if values.get("symbol") == "ETHUSDT" else "BTC",
            }
        return values

    @model_validator(mode="after")
    def matching_currency(self) -> Self:
        if self.base_currency != self.symbol.removesuffix("USDT"):
            raise ValueError("Base currency must match instrument identity")
        return self

    @property
    def key(self) -> str:
        return f"{self.source}:{self.venue}:{self.symbol}:{self.timeframe}"


class Bar(Model):
    open_time: AwareDatetime
    close_time: AwareDatetime
    open: str
    high: str
    low: str
    close: str
    volume: str | None = None
    is_closed: bool

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def decimal_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal") from exc
        if not number.is_finite() or number < 0 or number > Decimal("1e18"):
            raise ValueError("Number must be finite and between zero and 1e18")
        if number.as_tuple().exponent < -18:  # type: ignore[operator]
            raise ValueError("At most 18 decimal places are supported")
        if number.is_zero():
            return "0"
        text = format(number, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    @field_validator("open_time", "close_time")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_candle(self) -> Self:
        o, h, low, c = (Decimal(x) for x in (self.open, self.high, self.low, self.close))
        if min(o, h, low, c) <= 0 or low > min(o, c) or h < max(o, c):
            raise ValueError("Inconsistent OHLC values")
        if self.close_time <= self.open_time:
            raise ValueError("Close must follow open")
        return self


class Batch(Model):
    stream: Stream
    fetched_at: AwareDatetime
    bars: list[Bar] = Field(min_length=1, max_length=10000)
    raw_payload: dict[str, Any]

    @model_validator(mode="after")
    def valid_batch(self) -> Self:
        seconds = DURATIONS[self.stream.timeframe]
        seen: dict[datetime, Bar] = {}
        for bar in self.bars:
            if (bar.close_time - bar.open_time).total_seconds() != seconds:
                raise ValueError("Bar duration does not match its timeframe")
            if bar.open_time.timestamp() % seconds:
                raise ValueError("Bar does not align to UTC timeframe boundaries")
            if bar.open_time > self.fetched_at:
                raise ValueError("Cannot fetch a bar before it opens")
            if bar.is_closed and bar.close_time > self.fetched_at:
                raise ValueError("Cannot fetch a closed bar before it closes")
            if bar.open_time in seen and seen[bar.open_time] != bar:
                raise ValueError("Conflicting duplicates within one batch")
            seen[bar.open_time] = bar
        return self


class StoredBar(Model):
    revision_id: str
    revision: int
    fetched_at: AwareDatetime
    bar: Bar


class Dataset(Model):
    stream: Stream
    market_at: AwareDatetime
    knowledge_at: AwareDatetime
    fetched_at: AwareDatetime | None
    bars: list[StoredBar]
    forming: list[StoredBar]


class StorageStats(Model):
    schema_version: int
    batches: int
    revisions: int
    snapshots: int


class Rules(Model):
    engine_version: Literal["baseline-v1"] = "baseline-v1"
    window: int = Field(default=20, ge=2, le=200)
    demark: DemarkConfig | None = None


class Point(Model):
    at: AwareDatetime
    revision_id: str
    sma: str | None
    prior_high: str | None
    prior_low: str | None


class Analysis(Model):
    snapshot_id: str
    input_hash: str
    stream: Stream
    rules: Rules
    market_at: AwareDatetime
    knowledge_at: AwareDatetime
    fetched_at: AwareDatetime | None
    closed_bar_time: AwareDatetime | None
    forming_bar_time: AwareDatetime | None
    expected_next_close: AwareDatetime | None
    data_state: Literal["fresh", "delayed", "stale", "unavailable", "simulated"]
    mode: Literal["as_known", "retrospective"]
    warmup_required: int
    warmup_complete: bool
    issues: list[str]
    bars: list[StoredBar]
    points: list[Point]
    signal_status: Literal["not_implemented"] = "not_implemented"
    demark: DemarkResult | None = None


class JobRequest(Model):
    kind: Literal["refresh", "analyze"] = "refresh"
    stream: Stream
    rules: Rules = Field(default_factory=Rules)
    market_at: AwareDatetime | None = None
    knowledge_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_cutoffs(self) -> Self:
        if self.kind == "refresh" and (self.market_at is not None or self.knowledge_at is not None):
            raise ValueError("Refresh uses acquisition time; use analyze for replay")
        if self.kind == "analyze" and (self.market_at is None or self.knowledge_at is None):
            raise ValueError("Replay requires both market and knowledge cutoffs")
        return self


class Job(Model):
    job_id: str
    request: JobRequest
    state: Literal["queued", "running", "retry_wait", "succeeded", "failed"]
    attempts: int
    created_at: AwareDatetime
    updated_at: AwareDatetime
    next_attempt_at: AwareDatetime
    lease_until: AwareDatetime | None
    checkpoint_batch_id: str | None
    snapshot_id: str | None
    error_code: str | None


class JobEvent(Model):
    at: AwareDatetime
    state: str
    reason: str


class ScheduleRequest(Model):
    stream: Stream
    rules: Rules = Field(default_factory=Rules)
    enabled: bool


class Schedule(Model):
    schedule_id: str
    request: ScheduleRequest
    next_due: AwareDatetime


class Workspace(Model):
    stream: Stream
    checked_at: AwareDatetime
    current_state: Literal["fresh", "delayed", "stale", "unavailable", "simulated"]
    snapshot: Analysis | None
    latest_job: Job | None
    refresh_job: Job | None
    schedule: Schedule | None


class SnapshotSummary(Model):
    snapshot_id: str
    created_at: AwareDatetime
    market_at: AwareDatetime
    knowledge_at: AwareDatetime
    rules: Rules
    data_state: str
    mode: str
    bar_count: int
