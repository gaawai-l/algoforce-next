"""AlphaBTC's DeMark Regime interpretation, ported from its client (v2.95.0, 2026-09-28).

Source notes: research/alphabtc-regime-cycle-source-2026-09-28.md §2 (§2.6 tdNew).
Deliberate deviation: missing or stale anchor data yields "unavailable" instead of
AlphaBTC's default "decay".
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from ..demark.models import Model, Side
from ..demark.summary import DemarkSummary, Trend

S9 = Literal["up", "down", "none"]
RegimeValue = Literal["decay", "rev", "pump", "none", "unavailable"]
USABLE_STATUS = ("fresh", "delayed", "simulated")
BASE_LEVEL = {1: 2, 2: 3}


class TimeframeState(Model):
    s9: S9
    s13: bool
    carry13: bool
    countdown: int
    setup9_at: datetime | None
    qualified13_at: datetime | None
    setup9_seconds_ago: int | None
    qualified13_seconds_ago: int | None
    beyond_risk9: bool | None


class Signal(Model):
    n: Literal[1, 2]
    side: Side
    active: bool
    price: str | None
    base_level: int | None
    intraday_level: int | None
    swing_level: int | None


class NewTrend(Model):
    present: bool
    trend: Trend
    step: int
    confirmed: bool
    seconds: int | None


def _ago(as_of: datetime, at: datetime | None) -> int | None:
    return int((as_of - at).total_seconds()) if at is not None and as_of >= at else None


def derive_state(summary: DemarkSummary) -> TimeframeState:
    """AlphaBTC `dmkLive`: 9/13 status, keeping a just-finished 13 until a new 9 confirms."""
    prev = summary.prev
    prev_q13 = bool(prev and prev.qualified and prev.countdown >= 13)
    exhausted = [r.qualified13_at for r in summary.rounds if r.qualified13_at and r.countdown >= 13]
    last_ex13 = exhausted[-1] if exhausted else None
    ls = summary.last_signal
    last9 = ls.at if ls is not None and ls.kind == 9 else None
    last_is_13 = bool(
        (ls is not None and ls.kind == 13)
        or (last_ex13 is not None and (last9 is None or last_ex13 > last9))
    )
    # DemarkSummary reports countdown_step 0 outside countdown, so AlphaBTC's alternative
    # `countdownStep >= 13` cannot occur here; a carried 13 always has a qualified prev.
    carry13 = (
        last_is_13
        and summary.phase != "countdown"
        and summary.setup_step < 9
        and prev_q13
    )
    up = prev.side == "sell" if carry13 and prev is not None else summary.trend == "up"
    setup_done = carry13 or summary.phase == "countdown" or summary.setup_step >= 9
    countdown = 13 if carry13 else (summary.step if summary.phase == "countdown" else 0)

    setup9_at: datetime | None = None
    if ls is not None and ls.kind == 9:
        setup9_at = ls.at
    elif carry13:
        rounds = [r for r in summary.rounds if r.setup9_at and r.qualified13_at] or [
            r for r in summary.rounds if r.setup9_at
        ]
        setup9_at = rounds[-1].setup9_at if rounds else summary.risk.risk9_at
    if ls is not None and ls.kind == 13:
        qualified13_at: datetime | None = ls.at
    elif carry13 and last_ex13 is not None:
        qualified13_at = last_ex13
    elif summary.risk.risk13_at is not None and not summary.risk.provisional:
        qualified13_at = summary.risk.risk13_at
    else:
        qualified13_at = None

    # risk9 belongs to the primary sequence's side, so compare in that direction. AlphaBTC uses the
    # carried round's direction here (only for bar tint); that contradicts the displayed "<"/">".
    risk9 = summary.risk.risk9
    close = Decimal(summary.close)
    rising = summary.trend == "up"
    beyond = (
        None if risk9 is None else (close > Decimal(risk9) if rising else close < Decimal(risk9))
    )
    return TimeframeState(
        s9=("up" if up else "down") if setup_done else "none",
        s13=countdown >= 13,
        carry13=carry13,
        countdown=countdown,
        setup9_at=setup9_at,
        qualified13_at=qualified13_at,
        setup9_seconds_ago=_ago(summary.as_of, setup9_at),
        qualified13_seconds_ago=_ago(summary.as_of, qualified13_at),
        beyond_risk9=beyond,
    )


def regime_of(state: TimeframeState | None, status: str) -> RegimeValue:
    """AlphaBTC `cycAuto` for an anchor timeframe (1h intraday, 4h swing)."""
    if state is None or status not in USABLE_STATUS:
        return "unavailable"
    if state.s9 == "none":
        return "none"
    if state.s9 == "down":
        return "pump" if state.s13 else "rev"
    return "rev" if state.s13 else "decay"


def adjust(level: int, side: Side, regime: RegimeValue) -> int:
    """AlphaBTC `regimeDelta`: pump favours BUY, rev favours SELL, one level, clamped 1..5."""
    delta = {"pump": 1, "rev": -1}.get(regime, 0) * (1 if side == "buy" else -1)
    return max(1, min(5, level + delta))


def signals(
    state: TimeframeState, summary: DemarkSummary, intraday: RegimeValue, swing: RegimeValue
) -> list[Signal]:
    """AlphaBTC `sigBlock`: signal 1 at a confirmed 9, signal 2 at 13."""
    side: Side = "buy" if state.s9 == "down" else "sell"
    out = []
    for n, active, price in (
        (1, state.s9 != "none", summary.risk.setup_close),
        (2, state.s13, summary.risk.close13),
    ):
        base = BASE_LEVEL[n]
        out.append(
            Signal(
                n=n,  # type: ignore[arg-type]
                side=side,
                active=active,
                price=price,
                base_level=base if active else None,
                intraday_level=adjust(base, side, intraday) if active else None,
                swing_level=adjust(base, side, swing) if active else None,
            )
        )
    return out


def new_trend(summary: DemarkSummary) -> NewTrend:
    """AlphaBTC `tdNew`: the setup forming beside an old countdown, or the setup itself."""
    if summary.second is not None:
        trend, step = summary.second.trend, summary.second.step
        setup9_at = summary.second.setup9_at
    elif summary.phase == "setup":
        trend, step = summary.trend, summary.step
        ls = summary.last_signal
        setup9_at = ls.at if ls is not None and ls.kind == 9 else None
    else:
        return NewTrend(present=False, trend=summary.trend, step=0, confirmed=False, seconds=None)
    confirmed = step >= 9
    # setup_run is the same run as `second` or the setup-phase primary.
    start = summary.setup_run.start
    return NewTrend(
        present=True,
        trend=trend,
        step=step,
        confirmed=confirmed,
        seconds=_ago(summary.as_of, setup9_at if confirmed else start),
    )
