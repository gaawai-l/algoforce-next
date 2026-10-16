"""Versioned, transport-independent Sequential result vocabulary."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["buy", "sell"]


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )


class DemarkConfig(Model):
    variant: Literal["sequential"] = "sequential"
    ruleset_version: Literal["wheelhouse-sequential-1", "wheelhouse-sequential-2"] = (
        "wheelhouse-sequential-1"
    )
    price_flip_required: bool = True
    perfection_policy: Literal["strict", "strict_at_nine"] = "strict"
    same_side_policy: Literal["parallel", "retain_active"] = "parallel"
    qualifier_8_vs_5: Literal[False] = False
    risk_formula: Literal["countdown_span_true_extreme_earliest"] = (
        "countdown_span_true_extreme_earliest"
    )
    tdst_breach: Literal["true_extreme", "close"] = "true_extreme"
    risk_breach: Literal["close", "true_extreme"] = "close"
    recycling: Literal["range_and_22", "none"] = "range_and_22"
    validity_bars: int | None = Field(default=None, ge=1, le=10000)


class BarRef(Model):
    revision_id: str
    open_time: datetime
    close_time: datetime
    close: str


class DemarkEvent(Model):
    sequence_id: str
    side: Side
    kind: Literal[
        "setup_count",
        "setup_completed",
        "setup_interrupted",
        "perfected",
        "countdown_count",
        "deferred13",
        "qualified13",
        "cancelled",
        "recycled",
        "invalidated",
        "expired",
        "continuity_lost",
    ]
    bar: BarRef
    count: int | None = None
    reason: str


class NextCondition(Model):
    field: Literal["close", "low", "high"]
    operator: Literal["<", ">", "<=", ">="]
    threshold: str
    reference: BarRef
    purpose: Literal["setup", "countdown", "qualification13"]


class DemarkSequence(Model):
    sequence_id: str
    side: Side
    setup_count: int
    setup_status: Literal["forming", "completed", "interrupted"]
    setup_bars: list[BarRef]
    setup_perfected: bool | None = None
    perfected_at: datetime | None = None
    countdown_count: int = 0
    countdown_status: Literal[
        "inactive", "active", "count13_unqualified", "qualified13", "cancelled", "recycled"
    ] = "inactive"
    countdown_bars: list[BarRef] = Field(default_factory=list)
    countdown_bar8: BarRef | None = None
    qualification_threshold: str | None = None
    qualified_at: datetime | None = None
    confirmation_close: str | None = None
    tdst: str | None = None
    tdst_source: BarRef | None = None
    tdst_breached_at: datetime | None = None
    risk_level: str | None = None
    risk_source: BarRef | None = None
    risk_status: Literal["not_available", "valid", "invalidated", "expired", "unknown"] = (
        "not_available"
    )
    risk_ended_at: datetime | None = None
    continuity: Literal["observed", "lost"] = "observed"
    bars_since_setup9: int | None = None
    bars_since_qualified13: int | None = None
    elapsed_since_setup9_seconds: int | None = None
    elapsed_since_qualified13_seconds: int | None = None
    next_conditions: list[NextCondition] = Field(default_factory=list)


class DemarkResult(Model):
    config: DemarkConfig
    input_hash: str
    history_start: datetime | None
    history_end: datetime | None
    history_status: Literal["window_only", "gapped", "empty"]
    status: Literal["ready", "warming_up", "unavailable"]
    warmup_required: int = 6
    sequences: list[DemarkSequence]
    events: list[DemarkEvent]
    qualified13_count: int
    issues: list[str]
