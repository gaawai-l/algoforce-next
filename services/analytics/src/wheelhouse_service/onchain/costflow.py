"""Inputs of the state-report cost-basis flow, Charts 3 and 4, following the original loader (v1).

The worker does what the original page's loader does and nothing more: the supply columns of D
and of each window's then day on the $500 and $200 grids (L:250-300), the four young age groups
(L:306-312), the age floor of each $500 row (L:366-377) and a subset of the QC (L:448-494). The
kernel densities, peaks and mixtures are computed in the browser.

Snapshots are never mixed: a grid, or the age groups, whose D snapshots do not share the close of
D's `all lin500` are left out with a reason. A snapshot without buckets counts as missing.

Every sum is an explicit loop in row order: since Python 3.12 the builtin `sum()` compensates for
float rounding, which the original's JavaScript does not.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model
from ..rules import Rule
from .agecohorts import BANDS
from .brk import AGE_URPD_COHORTS, Urpd
from .costbasis import _cents

Window = Literal["1d", "7d", "30d", "90d"]
Rows = Sequence[tuple[datetime, float | None]]

# Days from each window's then day to D (L:94-97).
WINDOWS: dict[Window, int] = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
# How many young age groups count as bought in each window (L:260-261).
YOUNG: dict[Window, int] = {"1d": 1, "7d": 2, "30d": 3, "90d": 4}
# STH is read at $200, All and LTH at $500 (A:1302).
GRIDS: tuple[tuple[str, Literal[200, 500]], ...] = (("lin500", 500), ("lin200", 200))
# <1d, 1d–1w, 1w–1m and 1m–3m, and the cohorts each one adds up (L:38-41).
YOUNG_GROUPS: tuple[tuple[str, ...], ...] = tuple(cohorts for _, cohorts in BANDS[:4])
COHORTS = ("all", "sth", "lth")
# A row last traded at most this many days before D gets this band of the age floor (L:369).
FLOOR_EDGES: tuple[tuple[int, int], ...] = (
    (1, 0),
    (7, 1),
    (30, 2),
    (90, 3),
    (180, 4),
    (365, 5),
    (730, 6),
    (1095, 7),
    (1825, 8),
    (2555, 9),
    (3650, 10),
)
# Older, or never traded.
FLOOR_NEVER = 11
# The original's self-check tolerance, in BTC (L:454, L:481).
QC_TOLERANCE = 0.05
# The age-floor check reads only rows holding more than this (L:488).
QC_LIVE = 0.5


class CohortColumns(Model):
    # Supply per grid row, like the page's +toFixed(2).
    all: list[float]
    sth: list[float]
    lth: list[float]


class FlowWindow(Model):
    window: Window
    then_day: date
    then: CohortColumns


class FlowGrid(Model):
    step: Literal[200, 500]
    floors: list[float]
    now: CohortColumns
    # Only windows whose three then-day snapshots are closed and non-empty.
    windows: list[FlowWindow]


class AgeFlow(Model):
    # <1d, 1d–1w, 1w–1m and 1m–3m on the $500 grid, each summed over its cohorts, then rounded.
    groups: list[list[float]]
    # 0..11 per $500 row.
    band: list[int]


class StoredCostFlow(Model):
    now_day: date
    snapshot_at: AwareDatetime
    spot: float
    # $500 first, then $200; a grid that fails a check is left out.
    grids: list[FlowGrid]
    age: AgeFlow | None
    reasons: list[str]
    qc: list[str]
    rules: list[Rule] = []


def _present(urpd: Urpd | None) -> Urpd | None:
    """A snapshot without buckets is missing, never a column of zeros."""
    return urpd if urpd is not None and urpd.buckets else None


def _supply(urpd: Urpd) -> dict[int, float]:
    """Supply by floor, rounded as `Math.round` does (L:254, L:296)."""
    return {math.floor(b.price_floor + 0.5): b.supply for b in urpd.buckets}


def _columns(supply: Mapping[str, Mapping[int, float]], floors: Sequence[int]) -> CohortColumns:
    """Each cohort's supply on every floor, a floor it lacks reading 0, as the page's `||0`."""
    values = {c: [_cents(supply[c].get(floor, 0.0)) for floor in floors] for c in COHORTS}
    return CohortColumns(all=values["all"], sth=values["sth"], lth=values["lth"])


def _grid(
    day: date,
    agg: str,
    step: Literal[200, 500],
    spot: float,
    snapshots: Mapping[tuple[str, str, date], Urpd],
) -> tuple[FlowGrid | None, list[str]]:
    """One grid over D and every then snapshot there is (L:250-300), with the reasons it is
    missing or partial."""
    reasons: list[str] = []
    now: dict[str, dict[int, float]] = {}
    for cohort in COHORTS:
        urpd = _present(snapshots.get((cohort, agg, day)))
        if urpd is None:
            reasons.append(f"urpd_missing:{cohort}:{agg}")
        elif urpd.close != spot:
            reasons.append(f"urpd_mismatch:{cohort}:{agg}")
        else:
            now[cohort] = _supply(urpd)
    if reasons:
        return None, reasons

    then_days = {window: day - timedelta(days=n) for window, n in WINDOWS.items()}
    then: dict[Window, dict[str, dict[int, float]]] = {}
    for window, then_day in then_days.items():
        then[window] = {}
        for cohort in COHORTS:
            urpd = _present(snapshots.get((cohort, agg, then_day)))
            if urpd is not None:
                then[window][cohort] = _supply(urpd)
    keys: set[int] = set()
    for supply in [*now.values(), *(s for found in then.values() for s in found.values())]:
        keys.update(supply)
    floors = sorted(keys)

    windows: list[FlowWindow] = []
    gaps: list[str] = []
    for window, found in then.items():
        if len(found) < len(COHORTS):
            gaps.append(f"window_missing:{window}:{agg}")
            continue
        windows.append(
            FlowWindow(window=window, then_day=then_days[window], then=_columns(found, floors))
        )
    if gaps:
        reasons.append(f"urpd_grid_partial:{agg}")
    reasons += gaps
    grid = FlowGrid(
        step=step,
        floors=[float(floor) for floor in floors],
        now=_columns(now, floors),
        windows=windows,
    )
    return grid, reasons


def _ranges(high: Rows, low: Rows, day: date) -> list[tuple[datetime, float, float]]:
    """Each day's (high, low) up to `day`, newest first; a day missing either one is skipped."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    lows = dict(low)
    out: list[tuple[datetime, float, float]] = []
    for at, top in sorted(high, key=lambda row: row[0], reverse=True):
        bottom = lows.get(at)
        if top is None or bottom is None or at > start:
            continue
        out.append((at, top, bottom))
    return out


def _floor_band(days: float) -> int:
    for limit, band in FLOOR_EDGES:
        if days <= limit:
            return band
    return FLOOR_NEVER


def age_band(high: Rows, low: Rows, floors: Sequence[float], step: float, day: date) -> list[int]:
    """The age floor of each row (L:366-377): the band of the days since price last traded
    through it, up to `day`; FLOOR_NEVER when it never did."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    last: dict[float, datetime] = {}
    for at, top, bottom in _ranges(high, low, day):
        k = math.floor(bottom / step) * step
        end = math.floor(top / step) * step
        while k <= end:
            if k not in last:
                last[k] = at
            k += step
    return [
        _floor_band((start - last[floor]).total_seconds() / 86400) if floor in last else FLOOR_NEVER
        for floor in floors
    ]


def age_groups(ages: Mapping[str, Urpd], floors: Sequence[float]) -> list[list[float]]:
    """Each young group's supply on the grid (L:306-312): the cohorts summed bucket by bucket in
    order, then rounded. A bucket off the grid is left out."""
    index = {floor: i for i, floor in enumerate(floors)}
    groups: list[list[float]] = []
    for cohorts in YOUNG_GROUPS:
        totals = [0.0] * len(floors)
        for cohort in cohorts:
            for bucket in ages[cohort].buckets:
                i = index.get(math.floor(bucket.price_floor + 0.5))
                if i is not None:
                    totals[i] += bucket.supply
        groups.append([_cents(total) for total in totals])
    return groups


def _age(
    day: date, spot: float, ages: Mapping[str, Urpd], high: Rows, low: Rows, grid: FlowGrid
) -> tuple[AgeFlow | None, list[str]]:
    """The age groups and floor on the $500 grid, or the first reason there are none."""
    found = [_present(ages.get(cohort)) for cohort in AGE_URPD_COHORTS]
    if any(urpd is None for urpd in found):
        return None, ["age_urpd_missing"]
    if any(urpd is not None and urpd.close != spot for urpd in found):
        return None, ["age_urpd_mismatch"]
    ranges = _ranges(high, low, day)
    if not ranges:
        return None, ["age_floor_missing"]
    age = AgeFlow(
        groups=age_groups(ages, grid.floors),
        band=age_band(high, low, grid.floors, float(grid.step), day),
    )
    return age, ["age_floor_stale"] if ranges[0][0].date() < day else []


def _cohorts_add_up(grid: FlowGrid) -> bool:
    """sth + lth = all on every row of every day the grid holds (L:450-463)."""
    for columns in (grid.now, *(window.then for window in grid.windows)):
        for whole, short, long in zip(columns.all, columns.sth, columns.lth, strict=True):
            if not abs(whole - short - long) < QC_TOLERANCE:
                return False
    return True


def qc_codes(grids: Sequence[FlowGrid], age: AgeFlow | None) -> list[str]:
    """A code for each check of the original's self-check (L:448-494) that fails.

    Only the young age groups are stored, so "age bands = all" is not checked, and the age floor
    check sees coins under three months old only. The checks that read the age groups need them.
    """
    codes = [f"cohort_sum:lin{grid.step}" for grid in grids if not _cohorts_add_up(grid)]
    coarse = next((grid for grid in grids if grid.step == 500), None)
    if age is None or coarse is None:
        return codes
    now = coarse.now.all
    rows = range(len(coarse.floors))
    # sold = then - (now - bought) may not go below minus the tolerance (L:475-485).
    for window in coarse.windows:
        then = window.then.all
        for i in rows:
            bought = 0.0
            for group in age.groups[: YOUNG[window.window]]:
                bought += group[i]
            if then[i] - (now[i] - bought) < -QC_TOLERANCE:
                codes.append(f"sold_negative:{window.window}")
                break
    # No row holds coins younger than the price last traded through it (L:486-492).
    for i in rows:
        if now[i] <= QC_LIVE:
            continue
        young = 0.0
        for group in age.groups[: age.band[i]]:
            young += group[i]
        if young > QC_LIVE:
            codes.append("age_floor")
            break
    return codes


def cost_flow(
    day: date,
    snapshots: Mapping[tuple[str, str, date], Urpd],
    ages: Mapping[str, Urpd],
    high: Rows,
    low: Rows,
    *,
    snapshot_at: datetime,
) -> StoredCostFlow | None:
    """The stored inputs of Charts 3 and 4 for D = `day`; None without D's `all lin500`.

    `snapshots` holds URPD snapshots keyed (cohort, agg, day): D's and those of the then days
    that have closed. `ages` holds D's lin500 snapshots of AGE_URPD_COHORTS, and `high` and `low`
    the day1 rows of `price_high` and `price_low`.
    """
    head = _present(snapshots.get(("all", "lin500", day)))
    if head is None:
        return None
    spot = head.close
    grids: list[FlowGrid] = []
    reasons: list[str] = []
    for agg, step in GRIDS:
        grid, why = _grid(day, agg, step, spot, snapshots)
        reasons += why
        if grid is not None:
            grids.append(grid)
    age: AgeFlow | None = None
    coarse = next((grid for grid in grids if grid.step == 500), None)
    if coarse is not None:
        age, why = _age(day, spot, ages, high, low, coarse)
        reasons += why
    return StoredCostFlow(
        now_day=day,
        snapshot_at=snapshot_at,
        spot=spot,
        grids=grids,
        age=age,
        reasons=reasons,
        qc=qc_codes(grids, age),
    )
