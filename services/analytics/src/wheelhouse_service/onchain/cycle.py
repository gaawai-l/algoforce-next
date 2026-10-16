"""BTC cycle state from three on-chain cost lines, with a joint deadband gate."""

import math
from collections.abc import Sequence
from datetime import date
from typing import Literal

from ..market import Model

CycleState = Literal["advance", "breakout", "pressure", "repair", "breakdown", "capitulation"]
ComponentName = Literal["depth", "pvs", "spread"]

# Each state as (depth > 0, pvs > 0, spread > 0).
SIGNS: dict[CycleState, tuple[bool, bool, bool]] = {
    "advance": (True, True, True),
    "breakout": (True, True, False),
    "pressure": (True, False, True),
    "repair": (False, True, False),
    "breakdown": (False, False, True),
    "capitulation": (False, False, False),
}
NAMES: tuple[ComponentName, ...] = ("depth", "pvs", "spread")
# In the units of the components: 100 * ln(price ratio).
DEADBANDS: dict[ComponentName, float] = {"depth": 7.0, "pvs": 6.8, "spread": 1.25}


class Component(Model):
    name: ComponentName
    value: float
    deadband: float
    supports: bool


class Episode(Model):
    state: CycleState
    start: date
    end: date
    days: int


class Cycle(Model):
    as_of: date
    state: CycleState
    since: date
    day: int
    components: list[Component]
    episodes: list[Episode]
    changes: int


def raw_state(depth: float, pvs: float, spread: float) -> CycleState:
    """The state implied by the signs alone; a component that is exactly 0 counts as negative."""
    signs = (depth > 0, pvs > 0, spread > 0)
    for state, state_signs in SIGNS.items():
        if state_signs == signs:
            return state
    # Cannot happen when pvs = depth - spread.
    raise ValueError(f"inconsistent signs for depth={depth}, pvs={pvs}, spread={spread}")


def gate(current: CycleState, depth: float, pvs: float, spread: float) -> CycleState:
    """Switch to the raw state only if every component that flips clears its deadband."""
    target = raw_state(depth, pvs, spread)
    if target == current:
        return current
    values = (depth, pvs, spread)
    flipped = [
        (name, value)
        for name, value, before, after in zip(
            NAMES, values, SIGNS[current], SIGNS[target], strict=True
        )
        if before != after
    ]
    # Strict: a value exactly on the deadband does not switch. Nothing is remembered between calls.
    if all(abs(value) > DEADBANDS[name] for name, value in flipped):
        return target
    return current


def classify(
    rows: Sequence[tuple[date, float | None, float | None, float | None, float | None]],
) -> Cycle | None:
    """Classify the latest day. `rows` are `(date, W, STH, TMM, price_close)` in date order.

    A row is dropped unless all four values are present and positive. The last kept row may be
    today's, still forming; it counts towards `day`.
    """
    state: CycleState | None = None
    depth = pvs = spread = 0.0
    run_start = run_end = date.min
    run_days = 0
    episodes: list[Episode] = []

    for day, w, sth, tmm, close in rows:
        if w is None or sth is None or tmm is None or close is None:
            continue
        if min(w, sth, tmm, close) <= 0:
            continue
        depth = 100 * math.log(w / tmm)
        spread = 100 * math.log(sth / tmm)
        pvs = depth - spread
        if state is None:
            new_state = raw_state(depth, pvs, spread)
            run_start, run_days = day, 0
        else:
            new_state = gate(state, depth, pvs, spread)
            if new_state != state:
                episodes.append(Episode(state=state, start=run_start, end=run_end, days=run_days))
                run_start, run_days = day, 0
        state = new_state
        run_end = day
        run_days += 1

    if state is None:
        return None
    episodes.append(Episode(state=state, start=run_start, end=run_end, days=run_days))
    values = (depth, pvs, spread)
    return Cycle(
        as_of=run_end,
        state=state,
        since=run_start,
        day=run_days,
        components=[
            Component(
                name=name,
                value=value,
                deadband=DEADBANDS[name],
                supports=(value > 0) == expected,
            )
            for name, value, expected in zip(NAMES, values, SIGNS[state], strict=True)
        ],
        episodes=episodes,
        changes=len(episodes) - 1,
    )
