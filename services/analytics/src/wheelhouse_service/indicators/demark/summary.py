"""Primary-sequence summary equivalent to TradingSignal's multi-timeframe `across` view.

Mapping evidence: docs/features/demark/ACROSS-PRIMARY-SEQUENCE.md (verified 2026-09-28).
Open questions keep their documented defaults: rounds rule B, deferred 13 stays at 12,
setup-phase lastSignal falls back to the previous countdown, `strong` is not produced.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from ...market import Bar
from .engine import text
from .models import DemarkResult, DemarkSequence, Model, Side

Trend = Literal["up", "down"]
TREND: dict[str, Trend] = {"buy": "down", "sell": "up"}
ACTIVE = ("active", "count13_unqualified")
ENDED = ("qualified13", "cancelled", "recycled")


class Round(Model):
    side: Side
    trend: Trend
    setup: int
    countdown: int
    setup9_at: datetime | None
    qualified13_at: datetime | None


class SignalRef(Model):
    kind: Literal[9, 13]
    at: datetime
    side: Side


class PrevCountdown(Model):
    side: Side
    countdown: int
    qualified: bool
    bars_ago: int


class SecondSetup(Model):
    side: Side
    trend: Trend
    step: int
    setup9_at: datetime | None


class SetupRun(Model):
    start: datetime
    side: Side
    count: int
    active: bool
    completed: bool


class NextBarNeeds(Model):
    direction: Literal["above", "below"]
    price: str


class SummaryRisk(Model):
    risk9: str | None
    risk9_at: datetime | None
    setup_close: str | None
    risk_level: str | None
    risk13_at: datetime | None
    provisional: bool
    close13: str | None
    tdst: str | None
    next_bar_needs: NextBarNeeds | None


class DemarkSummary(Model):
    side: Side
    trend: Trend
    phase: Literal["setup", "countdown"]
    step: int
    target: Literal[9, 13]
    setup_step: int
    countdown_step: int
    rounds: list[Round]
    last_signal: SignalRef | None
    prev: PrevCountdown | None
    second: SecondSetup | None
    bars_since_qualified13: int | None
    setup_run: SetupRun
    risk: SummaryRisk
    as_of: datetime
    close: str


def _t9(seq: DemarkSequence) -> datetime:
    return seq.setup_bars[8].open_time


def _t13(seq: DemarkSequence) -> datetime:
    return seq.countdown_bars[-1].open_time


def summarize(result: DemarkResult, bars: list[Bar], as_of: datetime) -> DemarkSummary | None:
    """Project `result` (computed on `bars`) onto one primary sequence per timeframe."""
    seqs = sorted(
        (s for s in result.sequences if s.continuity == "observed" and s.setup_bars),
        key=lambda s: s.setup_bars[0].open_time,
    )
    if not seqs or not bars:
        return None
    index = {bar.open_time: i for i, bar in enumerate(bars)}
    last = len(bars) - 1

    def true_high(i: int) -> Decimal:
        high = Decimal(bars[i].high)
        return max(high, Decimal(bars[i - 1].close)) if i else high

    def true_low(i: int) -> Decimal:
        low = Decimal(bars[i].low)
        return min(low, Decimal(bars[i - 1].close)) if i else low

    done = [s for s in seqs if s.setup_status == "completed"]
    run = seqs[-1]
    active = [s for s in seqs if s.countdown_status in ACTIVE]
    if active:
        primary = active[0]
        phase: Literal["setup", "countdown"] = "countdown"
        step = countdown_step = primary.countdown_count
        same_run = run is not primary and run.side == primary.side
        setup_step = run.setup_count if same_run else primary.setup_count
    else:
        primary = run
        phase = "setup"
        step = setup_step = run.setup_count
        countdown_step = 0
    side = primary.side

    # Rounds, rule B: a same-side chain that restarts on an opposite 9 or on a new 9
    # after any chain round already reached qualified 13; unperfected held-back 9s are skipped.
    chain: list[DemarkSequence] = []
    for seq in done:
        if chain and (
            seq.side != chain[0].side
            or any(
                c.countdown_status == "qualified13"
                and index[c.countdown_bars[-1].open_time] < index[seq.setup_bars[8].open_time]
                for c in chain
            )
        ):
            chain = []
        elif chain and seq.countdown_status == "inactive" and not seq.setup_perfected:
            # A same-side 9 held back by retain_active is listed only once perfected
            # (TradingSignal 2026-09-27 4h lists a perfected one; 2026-09-28 5m omits one).
            continue
        chain.append(seq)
    qualified = [c for c in chain if c.countdown_status == "qualified13"]
    if (
        not active
        and chain
        and not any(c.risk_status == "valid" for c in qualified)
        and (qualified or chain[0].side != run.side)
    ):
        # Outside countdown the chain drops once its 13's risk level has broken, whether the
        # run is opposite (2026-09-27 15m) or same-side (2026-09-28 09:15 5m); a 13 whose risk
        # level holds stays listed (2026-09-28 04:16 5m).
        chain = []
    if not any(c is run for c in chain):
        chain.append(run)
    rounds = [
        Round(
            side=s.side,
            trend=TREND[s.side],
            setup=s.setup_count,
            countdown=s.countdown_count,
            setup9_at=_t9(s) if s.setup_status == "completed" else None,
            qualified13_at=_t13(s) if s.countdown_status == "qualified13" else None,
        )
        for s in chain
    ]

    ended = [
        s
        for s in seqs
        if s is not primary and s.countdown_status in ENDED and s.countdown_count > 0
    ]
    prev_seq = max(ended, key=lambda s: index[s.countdown_bars[-1].open_time], default=None)
    prev = (
        PrevCountdown(
            side=prev_seq.side,
            countdown=prev_seq.countdown_count,
            qualified=prev_seq.countdown_status == "qualified13",
            bars_ago=last - index[prev_seq.countdown_bars[-1].open_time],
        )
        if prev_seq
        else None
    )
    if phase == "setup" and prev is not None and prev.qualified and prev.bars_ago == 0:
        # TradingSignal still reports the count on the bar the 13 qualifies (2026-09-28 5m).
        countdown_step = prev.countdown

    first = chain[0]
    last_signal: SignalRef | None
    if first.countdown_status == "qualified13":
        last_signal = SignalRef(kind=13, at=_t13(first), side=first.side)
    elif first.setup_status == "completed":
        last_signal = SignalRef(kind=9, at=_t9(first), side=first.side)
    elif prev_seq is not None and prev is not None:
        last_signal = SignalRef(
            kind=13 if prev.qualified else 9,
            at=_t13(prev_seq) if prev.qualified else _t9(prev_seq),
            side=prev_seq.side,
        )
    else:
        last_signal = None

    second = (
        SecondSetup(
            side=run.side,
            trend=TREND[run.side],
            step=run.setup_count,
            setup9_at=_t9(run) if run.setup_status == "completed" else None,
        )
        if phase == "countdown" and run is not primary
        else None
    )
    since13 = [s.bars_since_qualified13 for s in seqs if s.bars_since_qualified13 is not None]

    same_done = [s for s in done if s.side == side]
    setup9 = same_done[-1] if same_done else None
    risk9: Decimal | None = None
    if setup9 is not None:
        positions = [index[b.open_time] for b in setup9.setup_bars]
        if side == "buy":
            j = min(positions, key=lambda i: (true_low(i), i))
            risk9 = true_low(j) - (true_high(j) - true_low(j))
        else:
            # Ties take the earliest bar, as in the mapping note §5 and the engine's risk rule.
            j = max(positions, key=lambda i: (true_high(i), -i))
            risk9 = true_high(j) + (true_high(j) - true_low(j))
    same13 = [s for s in seqs if s.side == side and s.countdown_status == "qualified13"]
    risk13 = max(same13, key=_t13, default=None)
    close13 = (
        prev_seq.confirmation_close
        if prev_seq is not None and prev is not None and prev.qualified and prev_seq.side == side
        else None
    )
    if phase == "countdown":
        tdst = primary.tdst
        need = next((c for c in primary.next_conditions if c.purpose == "countdown"), None)
    else:
        tdst = done[-1].tdst if done else None
        need = next((c for c in run.next_conditions if c.purpose == "setup"), None)

    return DemarkSummary(
        side=side,
        trend=TREND[side],
        phase=phase,
        step=step,
        target=13 if phase == "countdown" else 9,
        setup_step=setup_step,
        countdown_step=countdown_step,
        rounds=rounds,
        last_signal=last_signal,
        prev=prev,
        second=second,
        bars_since_qualified13=min(since13) if since13 else None,
        setup_run=SetupRun(
            start=run.setup_bars[0].open_time,
            side=run.side,
            count=run.setup_count,
            active=run.setup_status == "forming",
            completed=run.setup_status == "completed",
        ),
        risk=SummaryRisk(
            risk9=text(risk9) if risk9 is not None else None,
            risk9_at=_t9(setup9) if setup9 is not None else None,
            # TradingSignal drops the close once the 9's countdown started and was cancelled
            # (2026-09-28 5m, cancelled at 12); cancelled before counting keeps it (2026-09-27 15m).
            setup_close=(
                setup9.setup_bars[8].close
                if setup9 is not None
                and not (setup9.countdown_status == "cancelled" and setup9.countdown_count > 0)
                else None
            ),
            risk_level=risk13.risk_level if risk13 is not None else None,
            risk13_at=_t13(risk13) if risk13 is not None else None,
            # Firm until a same-side 9 completes after the 13 (2026-09-28 1h, 5m 09:15).
            provisional=not (
                risk13 is not None and setup9 is not None and _t9(setup9) < _t13(risk13)
            ),
            close13=close13,
            tdst=tdst,
            next_bar_needs=(
                NextBarNeeds(
                    direction="below" if need.operator in ("<", "<=") else "above",
                    price=need.threshold,
                )
                if need is not None
                else None
            ),
        ),
        as_of=as_of,
        close=bars[-1].close,
    )


def as_tradingsignal(summary: DemarkSummary) -> tuple[dict[str, Any], dict[str, Any]]:
    """Field names and encodings of TradingSignal's across/risk payload, for parity checks."""

    def ts(value: datetime | None) -> int | None:
        return int(value.timestamp()) if value else None

    def signal(kind: int, at: datetime, side: str) -> dict[str, Any]:
        return {"kind": kind, "ts": ts(at), "side": side.upper()}

    rounds = []
    for r in summary.rounds:
        item: dict[str, Any] = {
            "side": r.side.upper(), "regime": r.trend, "setup": r.setup, "countdown": r.countdown
        }
        if r.setup9_at:
            item["establishedTs"] = ts(r.setup9_at)
        if r.qualified13_at:
            item["exhaustedTs"] = ts(r.qualified13_at)
        rounds.append(item)
    ls = summary.last_signal
    prev = summary.prev
    across: dict[str, Any] = {
        "side": summary.side.upper(),
        "rounds": rounds,
        "lastSignal": signal(ls.kind, ls.at, ls.side) if ls else None,
        "prev": (
            {"side": prev.side.upper(), "countdown": prev.countdown,
             "qualified": prev.qualified, "barsAgo": prev.bars_ago}
            if prev else None
        ),
        "barsSinceQualified13": summary.bars_since_qualified13,
        "regime": summary.trend,
        "phase": summary.phase,
        "step": summary.step,
        "target": summary.target,
        "setupStep": summary.setup_step,
        "countdownStep": summary.countdown_step,
        "asOf": ts(summary.as_of),
        "close": summary.close,
    }
    if summary.second:
        second: dict[str, Any] = {
            "phase": "setup",
            "side": summary.second.side.upper(),
            "regime": summary.second.trend,
            "step": summary.second.step,
            "target": 9,
        }
        if summary.second.setup9_at:
            second["lastSignal"] = signal(9, summary.second.setup9_at, summary.second.side)
        across["second"] = second
    risk = summary.risk
    run = summary.setup_run
    return across, {
        "riskLevel": risk.risk_level,
        "provisional": risk.provisional,
        "risk13Ts": ts(risk.risk13_at),
        "risk9": risk.risk9,
        "risk9Ts": ts(risk.risk9_at),
        "setupClose": risk.setup_close,
        "close13": risk.close13,
        "side": summary.side.upper(),
        "tdst": risk.tdst,
        "nextBarNeeds": (
            {"direction": risk.next_bar_needs.direction, "price": risk.next_bar_needs.price}
            if risk.next_bar_needs else None
        ),
        "setupRun": {"start": ts(run.start), "side": run.side.upper(), "n": run.count,
                     "active": run.active, "completed": run.completed},
    }
