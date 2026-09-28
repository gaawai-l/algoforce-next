"""AlphaBTC's on-chain market cycle: six cost-basis states and the four-part 0-100 index.

Ported from its /onchain/cycle-dashboard client (classifier v2, read 2026-09-28).
Rules: research/alphabtc-regime-cycle-source-2026-09-28.md §3 (states) and §4 (index).
Inputs are bitview.space (Bitcoin Research Kit) daily series aligned on one calendar.
"""

import math
import statistics
from bisect import bisect_right, insort
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from typing import Literal

from ..demark.models import Model

State = Literal["advance", "breakout", "pressure", "repair", "breakdown", "capitulation"]
Zone = Literal["low", "transition_low", "mid", "transition_high", "top"]
Values = Sequence[float | None]

W = "utxos_1d_to_1w_old_realized_price"
STH = "sth_realized_price"
TMM = "true_market_mean"
STATE_SERIES = (W, STH, TMM)
HOT = tuple(
    f"utxos_{age}_old_realized_cap"
    for age in ("under_1h", "1h_to_1d", "1d_to_1w", "1w_to_1m", "1m_to_2m", "2m_to_3m")
)
SEASONED = ("utxos_1y_to_18m_old_realized_cap", "utxos_18m_to_2y_old_realized_cap")
INDEX_SERIES = (
    "unrealized_profit_to_mcap_ratio",
    "unrealized_loss_to_mcap_ratio",
    "realized_profit_sum_24h",
    "realized_loss_sum_24h",
    "supply_in_profit",
    "supply_in_loss",
    "realized_cap",
    *HOT,
    *SEASONED,
)
# Per-comparison deadbands, proportional to each gap's daily standard deviation; the
# dashboard's slider scales them 1-7x and defaults to 5x.
DEADBAND = {"depth": 0.0139, "pvs": 0.0133, "spread": 0.0028}
MULTIPLIER = 5
START = date(2015, 1, 1)
WINDOW = 1460
MIN_HISTORY = 365
SMOOTHING = 7
EPS = 1e-9
IMPOSSIBLE = {(False, True, True), (True, False, False)}
ORDER: tuple[State, ...] = (
    "advance", "pressure", "breakdown", "capitulation", "repair", "breakout",
)


class StateStats(Model):
    state: State
    runs: int
    days: int
    mean_days: float | None
    median_days: float | None
    max_days: int | None


class CycleStates(Model):
    state: State
    since: date
    days: int
    changes: int
    depth: float
    spread: float
    multiplier: int
    stats: list[StateStats]


class IndexComponents(Model):
    unrealized: float
    realized: float
    supply: float
    young_vs_seasoned: float


class CycleIndex(Model):
    components: IndexComponents
    composite: float
    zone: Zone
    change: dict[str, float | None]


def _classify(depth: bool, pvs: bool, spread: bool) -> State:
    # depth: W above TMM; pvs: W above STH; spread: STH above TMM.
    if depth and pvs:
        return "advance" if spread else "breakout"
    if not depth and not pvs:
        return "breakdown" if spread else "capitulation"
    return "pressure" if spread else "repair"


def states(first: date, series: Mapping[str, Values], multiplier: int = MULTIPLIER) -> CycleStates:
    """Hysteresis per comparison from 2015-01-01; an impossible or missing day keeps the label."""
    flags: dict[str, bool] = {}
    labels: list[State] = []
    last: State | None = None
    depth = spread = 0.0
    for i in range(len(series[W])):
        w, sth, tmm = (series[k][i] for k in STATE_SERIES)
        if first + timedelta(days=i) < START or not (w and sth and tmm):
            if last is not None:
                labels.append(last)
            continue
        depth, spread = math.log(w / tmm), math.log(sth / tmm)
        for key, gap in (("depth", depth), ("pvs", depth - spread), ("spread", spread)):
            threshold = DEADBAND[key] * multiplier
            if key not in flags:
                flags[key] = gap >= 0
            elif gap > threshold:
                flags[key] = True
            elif gap < -threshold:
                flags[key] = False
        tri = (flags["depth"], flags["pvs"], flags["spread"])
        if tri not in IMPOSSIBLE or last is None:
            last = _classify(*tri)
        labels.append(last)
    if not labels or last is None:
        raise ValueError("no on-chain cost basis data since 2015-01-01")
    runs: list[tuple[State, int]] = []
    for label in labels:
        if runs and runs[-1][0] == label:
            runs[-1] = (label, runs[-1][1] + 1)
        else:
            runs.append((label, 1))
    current, days = runs[-1]
    end = first + timedelta(days=len(series[W]) - 1)
    stats = []
    for state in ORDER:
        lengths = [n for s, n in runs if s == state]
        stats.append(
            StateStats(
                state=state,
                runs=len(lengths),
                days=sum(lengths),
                mean_days=round(statistics.mean(lengths), 1) if lengths else None,
                median_days=statistics.median(lengths) if lengths else None,
                max_days=max(lengths) if lengths else None,
            )
        )
    return CycleStates(
        state=current,
        since=end - timedelta(days=days - 1),
        days=days,
        changes=len(runs) - 1,
        depth=depth,
        spread=spread,
        multiplier=multiplier,
        stats=stats,
    )


def _rolling_percentile(values: Values) -> list[float | None]:
    """Share of the last WINDOW entries (itself included) at or below each value."""
    out: list[float | None] = []
    window: list[float] = []
    for i, v in enumerate(values):
        old = values[i - WINDOW] if i >= WINDOW else None
        if old is not None:
            window.pop(bisect_right(window, old) - 1)
        if v is None:
            out.append(None)
            continue
        insort(window, v)
        out.append(bisect_right(window, v) / len(window) if len(window) >= MIN_HISTORY else None)
    return out


def _smoothed(values: Values) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        recent = [v for v in values[max(0, i - SMOOTHING + 1) : i + 1] if v is not None]
        out.append(statistics.median(recent) if recent else None)
    return out


def _component(channel: list[float | None], present: list[bool]) -> list[float | None]:
    """Percentiles run over the days where the channel's inputs exist, as the dashboard does."""
    idx = [i for i, ok in enumerate(present) if ok]
    smoothed = _smoothed(_rolling_percentile([channel[i] for i in idx]))
    out: list[float | None] = [None] * len(channel)
    for i, v in zip(idx, smoothed, strict=True):
        out[i] = v
    return out


def _ratio_log(a: float, b: float) -> float:
    return math.log((a + EPS) / (b + EPS))


def index_series(series: Mapping[str, Values]) -> list[tuple[float, float, float, float] | None]:
    n = len(series["realized_cap"])

    def ok(names: Sequence[str], i: int) -> bool:
        return all(series[k][i] is not None for k in names)

    def get(name: str, i: int) -> float:
        value = series[name][i]
        assert value is not None
        return value

    def channel(names: Sequence[str], fn: Callable[[int], float | None]) -> list[float | None]:
        present = [ok(names, i) for i in range(n)]
        return _component([fn(i) if present[i] else None for i in range(n)], present)

    def supply(i: int) -> float | None:
        total = get("supply_in_profit", i) + get("supply_in_loss", i)
        return get("supply_in_profit", i) / total if total else None

    def young(i: int) -> float | None:
        cap = get("realized_cap", i)
        if not cap:
            return None
        hot = sum(get(k, i) for k in HOT) / cap
        seasoned = sum(get(k, i) for k in SEASONED) / cap
        return _ratio_log(hot, seasoned)

    parts = (
        channel(
            ("unrealized_profit_to_mcap_ratio", "unrealized_loss_to_mcap_ratio"),
            lambda i: get("unrealized_profit_to_mcap_ratio", i)
            - get("unrealized_loss_to_mcap_ratio", i),
        ),
        channel(
            ("realized_profit_sum_24h", "realized_loss_sum_24h"),
            lambda i: _ratio_log(
                get("realized_profit_sum_24h", i), get("realized_loss_sum_24h", i)
            ),
        ),
        channel(("supply_in_profit", "supply_in_loss"), supply),
        channel(("realized_cap", *HOT, *SEASONED), young),
    )
    out: list[tuple[float, float, float, float] | None] = []
    for a, b, c, d in zip(*parts, strict=True):
        if a is None or b is None or c is None or d is None:
            out.append(None)
        else:
            out.append((a * 100, b * 100, c * 100, d * 100))
    return out


def zone(composite: float) -> Zone:
    if composite < 20:
        return "low"
    if composite < 40:
        return "transition_low"
    if composite < 60:
        return "mid"
    if composite < 80:
        return "transition_high"
    return "top"


def cycle_index(series: Mapping[str, Values]) -> CycleIndex:
    """Latest day's components, equal-weight composite, and its 1/7/30/90-day changes."""
    rows = index_series(series)
    latest = rows[-1]
    if latest is None:
        raise ValueError("cycle index inputs missing on the latest day")

    def composite(row: tuple[float, float, float, float] | None) -> float | None:
        return sum(row) / 4 if row is not None else None

    now = composite(latest)
    assert now is not None
    change: dict[str, float | None] = {}
    for back in (1, 7, 30, 90):
        then = composite(rows[-1 - back]) if len(rows) > back else None
        change[f"{back}d"] = now - then if then is not None else None
    a, b, c, d = latest
    return CycleIndex(
        components=IndexComponents(unrealized=a, realized=b, supply=c, young_vs_seasoned=d),
        composite=now,
        zone=zone(now),
        change=change,
    )


# AlphaBTC's grind-down monitor ("短线抛压"): STH supply in profit as a share of STH supply.
# Its thresholds are hard-coded author values whose σ basis is not yet confirmed.
PRESSURE_SERIES = ("sth_supply_in_profit", "sth_supply")
PRESSURE_WARN = 84.5
PRESSURE_CONFIRM = 75.0
PRESSURE_DAYS = 30


class PressurePoint(Model):
    day: date
    value: float


class ShortTermPressure(Model):
    value: float
    history: list[PressurePoint]
    warn: float
    confirm: float
    thresholds_confirmed: bool
    stage: Literal["none", "warning", "confirmed"]


def short_term_pressure(first: date, series: Mapping[str, Values]) -> ShortTermPressure:
    points = [
        PressurePoint(day=first + timedelta(days=i), value=profit / supply * 100)
        for i, (profit, supply) in enumerate(
            zip(*(series[k] for k in PRESSURE_SERIES), strict=True)
        )
        if profit is not None and supply
    ][-PRESSURE_DAYS:]
    if not points or points[-1].day != first + timedelta(days=len(series[PRESSURE_SERIES[0]]) - 1):
        raise ValueError("short-term holder supply missing on the latest day")
    value = points[-1].value
    return ShortTermPressure(
        value=value,
        history=points,
        warn=PRESSURE_WARN,
        confirm=PRESSURE_CONFIRM,
        thresholds_confirmed=False,
        # AlphaBTC triggers on falling to or below each line.
        stage=(
            "confirmed"
            if value <= PRESSURE_CONFIRM
            else "warning"
            if value <= PRESSURE_WARN
            else "none"
        ),
    )
