"""One deterministic entry point for live observations and point-in-time replay."""

import json
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal

from .indicators.demark import evaluate_demark
from .market import DURATIONS, Analysis, Dataset, Point, Rules, digest, timestamp

DataState = Literal["fresh", "delayed", "stale", "unavailable", "simulated"]


def data_state(
    source: str, closed_at: datetime | None, at: datetime, interval: int, *, valid: bool = True
) -> DataState:
    if closed_at is None or not valid:
        return "unavailable"
    if source == "fixture":
        return "simulated"
    age = (at - closed_at).total_seconds()
    return "stale" if age > interval * 2 else "delayed" if age > interval * 1.1 else "fresh"


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def calculate(dataset: Dataset, rules: Rules) -> Analysis:
    points: list[Point] = []
    issues: list[str] = []
    interval = DURATIONS[dataset.stream.timeframe]
    segment: list[tuple[Decimal, Decimal, Decimal]] = []
    previous = None
    for stored in dataset.bars:
        bar = stored.bar
        if previous is not None and (bar.open_time - previous).total_seconds() != interval:
            issues.append(f"Missing closed-bar interval before {timestamp(bar.open_time)}")
            segment = []
        previous = bar.open_time
        prior = segment[-rules.window :]
        high = (
            max((row[1] for row in prior), default=Decimal(0))
            if len(prior) == rules.window
            else None
        )
        low = (
            min((row[2] for row in prior), default=Decimal(0))
            if len(prior) == rules.window
            else None
        )
        segment.append((Decimal(bar.close), Decimal(bar.high), Decimal(bar.low)))
        with localcontext() as context:
            context.prec = 60
            average = (
                (
                    sum((row[0] for row in segment[-rules.window :]), Decimal(0)) / rules.window
                ).quantize(Decimal("1e-18"), rounding=ROUND_HALF_EVEN)
                if len(segment) >= rules.window
                else None
            )
        points.append(
            Point(
                at=bar.close_time,
                revision_id=stored.revision_id,
                sma=decimal_text(average) if average is not None else None,
                prior_high=decimal_text(high) if high is not None else None,
                prior_low=decimal_text(low) if low is not None else None,
            )
        )
    last = dataset.bars[-1].bar.close_time if dataset.bars else None
    warmup = len(segment) > rules.window
    if not warmup:
        issues.append(f"Warm-up requires {rules.window + 1} consecutive closed bars")
    if any(b.bar.volume is None for b in dataset.bars):
        issues.append("Volume unavailable for one or more bars; no zero substitution")
    if dataset.stream.source == "fixture":
        issues.append("Simulated dataset; not live market data")
    demark = evaluate_demark(dataset, rules.demark) if rules.demark is not None else None
    hash_payload = {"demark_input": demark.input_hash} if demark else {}
    input_hash = digest(
        json.dumps(
            {
                "stream": dataset.stream.model_dump(),
                "rules": rules.model_dump(exclude_none=True),
                **hash_payload,
                "closed": [b.revision_id for b in dataset.bars],
                "forming": [b.revision_id for b in dataset.forming],
            },
            sort_keys=True,
        )
    )
    gap = any(issue.startswith("Missing closed-bar") for issue in issues)
    return Analysis(
        snapshot_id=digest(
            input_hash + timestamp(dataset.market_at) + timestamp(dataset.knowledge_at)
        ),
        input_hash=input_hash,
        stream=dataset.stream,
        rules=rules,
        market_at=dataset.market_at,
        knowledge_at=dataset.knowledge_at,
        fetched_at=dataset.fetched_at,
        closed_bar_time=last,
        forming_bar_time=dataset.forming[-1].bar.open_time if dataset.forming else None,
        expected_next_close=last + timedelta(seconds=interval) if last else None,
        data_state=data_state(
            dataset.stream.source, last, dataset.market_at, interval, valid=not gap
        ),
        mode="retrospective" if dataset.knowledge_at > dataset.market_at else "as_known",
        warmup_required=rules.window + 1,
        warmup_complete=warmup,
        issues=issues,
        bars=dataset.bars,
        points=points,
        demark=demark,
    )
