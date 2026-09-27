"""Pure, ordered Sequential transitions; no I/O or implicit clock."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...market import Dataset, StoredBar, Stream


from .models import (
    BarRef,
    DemarkConfig,
    DemarkEvent,
    DemarkResult,
    DemarkSequence,
    NextCondition,
    Side,
)


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


SetupStatus = Literal["forming", "completed", "interrupted"]
CountStatus = Literal[
    "inactive", "active", "count13_unqualified", "qualified13", "cancelled", "recycled"
]
EventKind = Literal[
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
RiskStatus = Literal["not_available", "valid", "invalidated", "expired", "unknown"]
ACTIVE = ("active", "count13_unqualified")


def ref(stored: StoredBar) -> BarRef:
    b = stored.bar
    return BarRef(
        revision_id=stored.revision_id,
        open_time=b.open_time,
        close_time=b.close_time,
        close=b.close,
    )


def text(value: Decimal) -> str:
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


@dataclass
class Sequence:
    side: Side
    identity: str
    setup: list[int] = field(default_factory=list)
    setup_status: SetupStatus = "forming"
    perfected_at: datetime | None = None
    countdown: list[int] = field(default_factory=list)
    countdown_status: CountStatus = "inactive"
    tdst: Decimal | None = None
    tdst_index: int | None = None
    breached_at: datetime | None = None
    risk: Decimal | None = None
    risk_index: int | None = None
    risk_status: RiskStatus = "not_available"
    risk_ended_at: datetime | None = None
    continuity: Literal["observed", "lost"] = "observed"


class SequentialSession:
    """Append-only public interface. Revisions/config changes require a new replay."""

    def __init__(
        self,
        stream: Stream,
        *,
        market_at: datetime,
        knowledge_at: datetime,
        config: DemarkConfig | None = None,
    ) -> None:
        if market_at.tzinfo is None or knowledge_at.tzinfo is None:
            raise ValueError("Cutoffs must be timezone aware")
        self.config = config or DemarkConfig()
        self.stream = stream
        self.market_at = market_at
        self.knowledge_at = knowledge_at
        self.bars: list[StoredBar] = []
        self._sequences: list[Sequence] = []
        self._streak: Sequence | None = None
        self._streak_length = 0
        self._segment_start = 0
        self._events: list[DemarkEvent] = []
        self._gapped = False
        self._revision_ids: set[str] = set()

    def _event(
        self, seq: Sequence, kind: EventKind, i: int, reason: str, count: int | None = None
    ) -> None:
        self._events.append(
            DemarkEvent(
                sequence_id=seq.identity,
                side=seq.side,
                kind=kind,
                bar=ref(self.bars[i]),
                reason=reason,
                count=count,
            )
        )

    def _true_high(self, i: int) -> Decimal:
        b = self.bars[i].bar
        return (
            max(Decimal(b.high), Decimal(self.bars[i - 1].bar.close))
            if i > self._segment_start
            else Decimal(b.high)
        )

    def _true_low(self, i: int) -> Decimal:
        b = self.bars[i].bar
        return (
            min(Decimal(b.low), Decimal(self.bars[i - 1].bar.close))
            if i > self._segment_start
            else Decimal(b.low)
        )

    def _new_sequence(self, side: Side, i: int, suffix: str = "") -> Sequence:
        identity = digest(
            f"{self.stream.key}:{side}:{self.bars[i].bar.open_time.isoformat()}:{suffix}"
        )
        seq = Sequence(side, identity)
        self._sequences.append(seq)
        return seq

    def advance(self, stored: StoredBar) -> None:
        """Consume one closed selected revision; reject ambiguous or future inputs."""
        # Validate again even if a caller used Pydantic model_copy/model_construct.
        from ...market import DURATIONS, StoredBar

        stored = StoredBar.model_validate(stored.model_dump())
        b = stored.bar
        interval = DURATIONS[self.stream.timeframe]
        if (
            not b.is_closed
            or b.close_time > self.market_at
            or stored.fetched_at > self.knowledge_at
            or stored.fetched_at < b.close_time
        ):
            raise ValueError("Input must be closed and known at both cutoffs")
        if (
            b.close_time - b.open_time
        ).total_seconds() != interval or b.open_time.timestamp() % interval:
            raise ValueError("Bar does not match the stream interval")
        if stored.revision_id in self._revision_ids:
            raise ValueError("Duplicate revision")
        if self.bars and b.open_time <= self.bars[-1].bar.open_time:
            raise ValueError("Bars must have unique, strictly increasing open times")
        gap = bool(self.bars and b.open_time != self.bars[-1].bar.close_time)
        self.bars.append(stored)
        self._revision_ids.add(stored.revision_id)
        i = len(self.bars) - 1
        if gap:
            self._gapped = True
            for seq in self._sequences:
                if seq.continuity == "observed" and (
                    seq.countdown_status in ACTIVE
                    or seq.setup_status == "forming"
                    or seq.risk_status == "valid"
                    or (seq.countdown_status == "qualified13" and seq.perfected_at is None)
                ):
                    seq.continuity = "lost"
                    if seq.risk_status == "valid":
                        seq.risk_status = "unknown"
                    self._event(seq, "continuity_lost", i, "missing_closed_bar")
            self._streak = None
            self._streak_length = 0
            self._segment_start = i
        # Explicit context prevents caller Decimal settings from changing results.
        with localcontext() as context:
            context.prec = 80
            self._advance(i)

    def _complete_setup(self, seq: Sequence, i: int, reason: str) -> None:
        seq.setup_status = "completed"
        seq.countdown_status = "active"
        extrema = [
            (self._true_high(j) if seq.side == "buy" else self._true_low(j), j) for j in seq.setup
        ]
        extreme = max(v for v, _ in extrema) if seq.side == "buy" else min(v for v, _ in extrema)
        seq.tdst = extreme
        seq.tdst_index = next(j for v, j in extrema if v == extreme)
        self._event(seq, "setup_completed", i, reason, 9)
        new_range = max(self._true_high(j) for j in seq.setup) - min(
            self._true_low(j) for j in seq.setup
        )
        for older in self._sequences:
            if older is seq or older.continuity == "lost" or older.countdown_status not in ACTIVE:
                continue
            if older.side != seq.side:
                older.countdown_status = "cancelled"
                self._event(older, "cancelled", i, "opposite_setup_completed")
            elif self.config.recycling == "range_and_22":
                old_range = max(self._true_high(j) for j in older.setup) - min(
                    self._true_low(j) for j in older.setup
                )
                if old_range > 0 and old_range <= new_range <= old_range * 2:
                    older.countdown_status = "recycled"
                    self._event(older, "recycled", i, "same_side_setup_range_100_to_200_percent")

    def _advance(self, i: int) -> None:
        if i - self._segment_start < 4:
            return
        b = self.bars[i].bar
        close = Decimal(b.close)
        other = Decimal(self.bars[i - 4].bar.close)
        side: Side | None = "buy" if close < other else "sell" if close > other else None
        if self._streak and side != self._streak.side:
            if self._streak.setup_status == "forming":
                self._streak.setup_status = "interrupted"
                self._event(self._streak, "setup_interrupted", i, "consecutive_condition_failed")
            self._streak = None
            self._streak_length = 0
        flip = False
        if i - self._segment_start >= 5 and side:
            previous = Decimal(self.bars[i - 1].bar.close)
            prior = Decimal(self.bars[i - 5].bar.close)
            flip = previous >= prior if side == "buy" else previous <= prior
        if side and self._streak is None and (flip or not self.config.price_flip_required):
            self._streak = self._new_sequence(side, i)
        if self._streak:
            seq = self._streak
            self._streak_length += 1
            if seq.setup_status == "forming":
                seq.setup.append(i)
                self._event(seq, "setup_count", i, "close_vs_four_bars_earlier", len(seq.setup))
                if len(seq.setup) == 9:
                    self._complete_setup(seq, i, "nine_consecutive_closes")
            if self._streak_length == 22 and self.config.recycling == "range_and_22":
                # Only a subsequent overlapping Setup can recycle an older Countdown.
                for older in self._sequences:
                    if (
                        older is not seq
                        and older.side == seq.side
                        and older.continuity == "observed"
                        and older.countdown_status in ACTIVE
                        and older.setup[-1] < seq.setup[0]
                    ):
                        older.countdown_status = "recycled"
                        self._event(older, "recycled", i, "subsequent_setup_extended_to_22")
        for seq in self._sequences:
            if seq.continuity == "lost" or seq.setup_status != "completed":
                continue
            if seq.risk_status == "valid" and i > seq.countdown[-1]:
                assert seq.risk is not None
                risk_price = (
                    close
                    if self.config.risk_breach == "close"
                    else (self._true_high(i) if seq.side == "buy" else self._true_low(i))
                )
                if risk_price < seq.risk if seq.side == "buy" else risk_price > seq.risk:
                    seq.risk_status = "invalidated"
                    seq.risk_ended_at = b.close_time
                    self._event(seq, "invalidated", i, "risk_level_breach")
                elif (
                    self.config.validity_bars is not None
                    and i - seq.countdown[-1] >= self.config.validity_bars
                ):
                    seq.risk_status = "expired"
                    seq.risk_ended_at = b.close_time
                    self._event(seq, "expired", i, "configured_validity_bars")
            if seq.countdown_status in ACTIVE:
                assert seq.tdst is not None
                boundary = (
                    (self._true_low(i) if seq.side == "buy" else self._true_high(i))
                    if self.config.tdst_breach == "true_extreme"
                    else close
                )
                breach = boundary > seq.tdst if seq.side == "buy" else boundary < seq.tdst
                if breach:
                    seq.countdown_status = "cancelled"
                    seq.breached_at = b.close_time
                    self._event(seq, "cancelled", i, "tdst_breach")
            if seq.countdown_status in (*ACTIVE, "qualified13"):
                self._perfect(seq, i)
            if seq.countdown_status in ACTIVE:
                qualifies = (
                    close <= Decimal(self.bars[i - 2].bar.low)
                    if seq.side == "buy"
                    else close >= Decimal(self.bars[i - 2].bar.high)
                )
                if qualifies:
                    if len(seq.countdown) == 12:
                        threshold = Decimal(self.bars[seq.countdown[7]].bar.close)
                        qualified = (
                            Decimal(b.low) <= threshold
                            if seq.side == "buy"
                            else Decimal(b.high) >= threshold
                        )
                        if not qualified:
                            seq.countdown_status = "count13_unqualified"
                            self._event(
                                seq, "deferred13", i, "extreme_did_not_reach_countdown_eight", 13
                            )
                            continue
                        seq.countdown_status = "qualified13"
                    seq.countdown.append(i)
                    self._event(
                        seq, "countdown_count", i, "close_vs_two_bars_earlier", len(seq.countdown)
                    )
                    if seq.countdown_status == "qualified13":
                        self._event(seq, "qualified13", i, "extreme_reached_countdown_eight", 13)
                        span = range(seq.countdown[0], i + 1)
                        extreme = (
                            min(self._true_low(j) for j in span)
                            if seq.side == "buy"
                            else max(self._true_high(j) for j in span)
                        )
                        seq.risk_index = next(
                            j
                            for j in span
                            if (self._true_low(j) if seq.side == "buy" else self._true_high(j))
                            == extreme
                        )
                        tr = self._true_high(seq.risk_index) - self._true_low(seq.risk_index)
                        seq.risk = extreme - tr if seq.side == "buy" else extreme + tr
                        seq.risk_status = "valid"

    def _perfect(self, seq: Sequence, i: int) -> None:
        if seq.perfected_at is not None:
            return
        six, seven = (self.bars[seq.setup[k]].bar for k in (5, 6))
        candidates = [self.bars[j].bar for j in (*seq.setup[7:9], i)]
        perfected = (
            min(Decimal(b.low) for b in candidates) < min(Decimal(six.low), Decimal(seven.low))
            if seq.side == "buy"
            else max(Decimal(b.high) for b in candidates)
            > max(Decimal(six.high), Decimal(seven.high))
        )
        if perfected:
            seq.perfected_at = self.bars[i].bar.close_time
            self._event(seq, "perfected", i, "extreme_vs_setup_six_and_seven")

    def result(self) -> DemarkResult:
        """Return a detached snapshot of all observed sequences and immutable events."""
        sequences = [self._result_sequence(s) for s in self._sequences]
        payload = {
            "stream": self.stream.model_dump(),
            "config": self.config.model_dump(),
            "bars": [b.model_dump(mode="json") for b in self.bars],
        }
        warmup = 6 if self.config.price_flip_required else 5
        return DemarkResult(
            config=self.config,
            input_hash=digest(json.dumps(payload, sort_keys=True)),
            history_start=self.bars[0].bar.open_time if self.bars else None,
            history_end=self.bars[-1].bar.close_time if self.bars else None,
            history_status="gapped" if self._gapped else "window_only" if self.bars else "empty",
            status="unavailable"
            if self._gapped or not self.bars
            else "ready"
            if len(self.bars) - self._segment_start >= warmup
            else "warming_up",
            warmup_required=warmup,
            sequences=sequences,
            events=list(self._events),
            qualified13_count=sum(s.countdown_status == "qualified13" for s in self._sequences),
            issues=["History before the first input bar is unknown; counts cover this window only."]
            + (
                ["Missing closed bars: cross-gap sequence validity is unknown."]
                if self._gapped
                else []
            ),
        )

    def _result_sequence(self, s: Sequence) -> DemarkSequence:
        last = len(self.bars) - 1
        end = self.bars[-1].bar.close_time
        completed = s.setup_status == "completed"
        qualified = s.countdown_status == "qualified13"
        conditions: list[NextCondition] = []
        if (
            s.continuity == "observed"
            and s.setup_status == "forming"
            and len(self.bars) - self._segment_start >= 4
        ):
            conditions.append(
                NextCondition(
                    field="close",
                    operator="<" if s.side == "buy" else ">",
                    threshold=self.bars[-4].bar.close,
                    reference=ref(self.bars[-4]),
                    purpose="setup",
                )
            )
        if s.continuity == "observed" and s.countdown_status in ACTIVE:
            base = self.bars[-2]
            conditions.append(
                NextCondition(
                    field="close",
                    operator="<=" if s.side == "buy" else ">=",
                    threshold=base.bar.low if s.side == "buy" else base.bar.high,
                    reference=ref(base),
                    purpose="countdown",
                )
            )
            if len(s.countdown) == 12:
                eighth = self.bars[s.countdown[7]]
                conditions.append(
                    NextCondition(
                        field="low" if s.side == "buy" else "high",
                        operator="<=" if s.side == "buy" else ">=",
                        threshold=eighth.bar.close,
                        reference=ref(eighth),
                        purpose="qualification13",
                    )
                )
        return DemarkSequence(
            sequence_id=s.identity,
            side=s.side,
            setup_count=len(s.setup),
            setup_status=s.setup_status,
            setup_bars=[ref(self.bars[i]) for i in s.setup],
            setup_perfected=(True if s.perfected_at else None if s.continuity == "lost" else False)
            if completed
            else None,
            perfected_at=s.perfected_at,
            countdown_count=len(s.countdown),
            countdown_status=s.countdown_status,
            countdown_bars=[ref(self.bars[i]) for i in s.countdown],
            countdown_bar8=ref(self.bars[s.countdown[7]]) if len(s.countdown) >= 8 else None,
            qualification_threshold=self.bars[s.countdown[7]].bar.close
            if len(s.countdown) >= 8
            else None,
            qualified_at=self.bars[s.countdown[-1]].bar.close_time if qualified else None,
            confirmation_close=self.bars[s.countdown[-1]].bar.close if qualified else None,
            tdst=text(s.tdst) if s.tdst is not None else None,
            tdst_source=ref(self.bars[s.tdst_index]) if s.tdst_index is not None else None,
            tdst_breached_at=s.breached_at,
            risk_level=text(s.risk) if s.risk is not None else None,
            risk_source=ref(self.bars[s.risk_index]) if s.risk_index is not None else None,
            risk_status=s.risk_status,
            risk_ended_at=s.risk_ended_at,
            continuity=s.continuity,
            bars_since_setup9=last - s.setup[-1] if completed else None,
            bars_since_qualified13=last - s.countdown[-1] if qualified else None,
            elapsed_since_setup9_seconds=int(
                (end - self.bars[s.setup[-1]].bar.close_time).total_seconds()
            )
            if completed
            else None,
            elapsed_since_qualified13_seconds=int(
                (end - self.bars[s.countdown[-1]].bar.close_time).total_seconds()
            )
            if qualified
            else None,
            next_conditions=conditions,
        )


def evaluate_demark(dataset: Dataset, config: DemarkConfig | None = None) -> DemarkResult:
    session = SequentialSession(
        dataset.stream,
        market_at=dataset.market_at,
        knowledge_at=dataset.knowledge_at,
        config=config,
    )
    for stored in dataset.bars:
        session.advance(stored)
    return session.result()
