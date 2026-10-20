"""A reference for what the browser draws of Chart 8, written from the original page.

It follows the original's `occupiedRange`, `visibleSorted` and `shaper8` (state-report
`raw/script_2_app.js` lines 3961-4008) and its key and Contrast label (`drawKey8`, `clipLabel8`,
lines 4117-4139), on a view as the service sends it or a slice of one, with the standard library
only. The frontend's expected values in `cost-basis-history-expected.json` are its output, and
Task 7 checks it against the original page.
"""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# The grid of the view: rows of $500 from $1,000.
FLOOR0 = 1000
STEP = 500
# The data's own precision (the original's OCC): a cell at or under it holds no coins.
OCC = 0.005
# The steps of the colour ramp, each of which the key names.
STEPS = 4


def js_round(x: float) -> int:
    """JavaScript's Math.round: the nearest integer, a half going up. Unlike floor(x + 0.5) it
    holds where adding 0.5 itself rounds, as for 0.49999999999999994."""
    whole = math.floor(x)
    return whole + 1 if x - whole >= 0.5 else whole


def to_fixed(x: float, digits: int) -> str:
    """JavaScript's toFixed for x >= 0: the exact binary value rounded, a half going up."""
    return str(Decimal(x).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def fmt_btc(v: float) -> str:
    """The original's fmtBtc8."""
    if v >= 1e6:
        return to_fixed(v / 1e6, 2) + "M"
    if v >= 1e3:
        return f"{js_round(v / 1e3)}k"
    return str(js_round(v))


def reference(view: dict[str, Any], range_pct: int, lo: int = 75, hi: int = 95) -> dict[str, Any]:
    """The rows `r0`-`r1` the original shows of `view` at Range `range_pct` (0 is All), the `n`
    cells its Contrast quantiles are read from, the `floor` and `cap` of the handles `lo` and `hi`,
    the largest cell `top`, and the key and the label it writes for them."""
    supply = view["supply"]
    # The days with a snapshot: the original keeps only these (its `visDates`).
    stored = [i for i, row in enumerate(supply) if row is not None]
    occupied = [r for i in stored for r, v in enumerate(supply[i]) if v > OCC]
    if occupied:
        r0, r1 = min(occupied), max(occupied)
        spot = view["close"][stored[-1]]
        if range_pct > 0 and spot:
            f = range_pct / 100
            a = max(r0, math.floor((spot * (1 - f) - FLOOR0) / STEP))
            b = min(r1, math.ceil((spot * (1 + f) - FLOOR0) / STEP))
            if b > a:
                r0, r1 = a, b
    else:
        r0, r1 = 0, len(view["floors"]) - 1
    cells = sorted(v for i in stored for v in supply[i][r0 : r1 + 1] if v > OCC)
    n = len(cells)

    def at(q: float) -> float:
        # Without a cell the original reads `undefined || 0`.
        return cells[min(n - 1, max(0, js_round(q / 100 * (n - 1))))] if n else 0

    top = cells[-1] if n else 1
    floor = 0 if lo <= 0 else at(lo)
    cap = top if hi >= 100 else max(at(hi), floor + 1e-9)
    span = max(1e-9, cap - floor)
    clipped, dropped = cap < top, floor > 0
    # The key: the value each step starts at, a minus (U+2212) on the first once the floor drops
    # cells, and the cap with a plus once it clips them.
    key = [
        ("−" if k == 0 and dropped else "") + fmt_btc(floor + (k / STEPS) * span)
        for k in range(STEPS)
    ]
    key.append(fmt_btc(cap) + ("+" if clipped else ""))
    # The Contrast label, with en dashes (U+2013).
    label = (
        f"{js_round(lo)}–{js_round(hi)}% · {fmt_btc(floor)}–{fmt_btc(cap)}{'+' if clipped else ''}"
        if dropped or clipped
        else "full range"
    )
    return {
        "range": range_pct,
        "r0": r0,
        "r1": r1,
        "n": n,
        "floor": floor,
        "cap": cap,
        "top": top,
        "key": key,
        "label": label,
    }
