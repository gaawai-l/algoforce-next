"""Generators of the frontend samples of Charts 3 and 4, from the 2026-10-19 cost-flow sample.

The README of `fixtures/brk-2026-10-19T0512Z-costflow` has the command that writes them;
`test_onchain_api.test_samples_regenerate_identically` checks the committed files against these
functions. Each sample view is what GET /cost-flow serves for its stored payload at its clock.
"""

import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from wheelhouse_service.market import Model
from wheelhouse_service.onchain.api import create_router
from wheelhouse_service.onchain.brk import Urpd
from wheelhouse_service.onchain.costbasis import (
    MAX_COMPONENTS,
    GmmComponent,
    Peak,
    _cents,
    find_peaks,
    fit_gmm,
    select_components,
    weighted_kde,
)
from wheelhouse_service.onchain.costflow import (
    COHORTS,
    WINDOWS,
    AgeFlow,
    CohortColumns,
    FlowGrid,
    FlowWindow,
    StoredCostFlow,
    Window,
    _columns,
    _supply,
    cost_flow,
    qc_codes,
)
from wheelhouse_service.onchain.models import CostFlowView
from wheelhouse_service.onchain.store import OnchainStore

SAMPLE = Path(__file__).parent / "fixtures" / "brk-2026-10-19T0512Z-costflow"
WHEELHOUSE = (
    Path(__file__).resolve().parents[4]
    / "integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse"
)
D = date(2026, 10, 19)

# S1, stage A: the sample's 30 snapshots, D fetched at 05:12:06Z, derived at 05:12:30Z.
S1_SNAPSHOT_AT = datetime(2026, 10, 19, 5, 12, 6, tzinfo=UTC)
S1_COMPUTED_AT = datetime(2026, 10, 19, 5, 12, 30, tzinfo=UTC)
S1_READ_AT = datetime(2026, 10, 19, 5, 20, tzinfo=UTC)
# S2: the snapshot the oracle fetched at 06:04:42Z, the same one as the page's Chart 4 readings.
S2_SPOT = 82361.33
S2_SNAPSHOT_AT = datetime(2026, 10, 19, 6, 4, 42, tzinfo=UTC)
S2_COMPUTED_AT = datetime(2026, 10, 19, 6, 5, tzinfo=UTC)
S2_READ_AT = datetime(2026, 10, 19, 6, 10, tzinfo=UTC)
# The oracle kept no $200 data, so S2 has no $200 grid: these reasons are part of how it is built.
S2_REASONS = ["urpd_missing:all:lin200", "urpd_missing:sth:lin200", "urpd_missing:lth:lin200"]
# The oracle's 1d rows rebuilt from S2, within this much of the rows it wrote.
ORACLE_TOLERANCE = 1e-6
# The page's default smoothing width, as a share of the price span (A:1284-1285, A:1685).
BW = 0.02
# Half a cent, below which a bucket draws no bar under Zoom All (A:1328).
EPS = 0.005

Holders = Literal["all", "sth"]
Side = Literal["pos", "neg"]
Row = tuple[float, float, float, float]  # price, all, sth, lth


@dataclass(frozen=True)
class Sample:
    """A stored payload, when the worker derived it and when the sample reads it."""

    stored: StoredCostFlow
    computed_at: datetime
    read_at: datetime


class GmmFit(Model):
    """costbasis.fit_gmm with k bells over a side's rows with weight."""

    k: int
    comps: list[GmmComponent]
    log_l: float


class CrossSide(Model):
    """One side of one Chart 3 view: its rows and weights (A:1304-1401), and what costbasis.py's
    KDE, peaks and mixture make of them."""

    window: Window
    holders: Holders
    aging: bool
    zoom: Literal[0]
    side: Side
    centers: list[float]
    weights: list[float]
    # BW times the span of the centers, as the page's curve uses (A:1685).
    h: float
    kde: list[float]
    peaks: list[Peak]
    # fit_gmm over the rows with weight, for k = 1 up to the cap select_components allows.
    gmm: list[GmmFit]
    # select_components under v1, with the side's peak count and with none (k by BIC).
    select_peaks: list[GmmComponent]
    select_bic: list[GmmComponent]


class Crosscheck(Model):
    sides: list[CrossSide]


@cache
def snapshots() -> dict[tuple[str, str, date], Urpd]:
    """The sample's 30 URPD snapshots, keyed (cohort, agg, day)."""
    out: dict[tuple[str, str, date], Urpd] = {}
    for path in sorted(SAMPLE.glob("urpd_*.json")):
        urpd = Urpd.model_validate_json(path.read_text())
        out[(urpd.cohort, urpd.aggregation, urpd.date)] = urpd
    assert len(out) == 30
    return out


def oracle(window: Window) -> list[dict[str, Any]]:
    """The oracle's Chart 4 rows of `window` at Zoom All."""
    path = SAMPLE / "oracle-c4" / f"c4_{window}_z0_2026-10-19.json"
    payload = json.loads(path.read_text())
    assert (payload["now"], payload["fetched"]) == (D.isoformat(), S2_SNAPSHOT_AT.isoformat())
    assert payload["spot"] == S2_SPOT
    rows: list[dict[str, Any]] = payload["rows"]
    return rows


def sample_0512() -> Sample:
    """S1: the real `cost_flow` on the sample's 30 snapshots, without age snapshots."""
    stored = cost_flow(D, snapshots(), {}, [], [], snapshot_at=S1_SNAPSHOT_AT)
    assert stored is not None
    return Sample(stored, S1_COMPUTED_AT, S1_READ_AT)


def _then(window: Window, floors: list[int]) -> CohortColumns:
    """The sample's lin500 snapshots of the window's then day on `floors`, as the worker rounds
    them."""
    day = D - timedelta(days=WINDOWS[window])
    supply = {cohort: _supply(snapshots()[(cohort, "lin500", day)]) for cohort in COHORTS}
    for found in supply.values():
        assert set(found) <= set(floors), "the oracle's rows miss a floor of a then day"
    return _columns(supply, floors)


def _now(then: CohortColumns, rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    """D's columns, each the then column plus the oracle's difference, rounded to the cent."""
    return {
        cohort: [
            _cents(past + row[cohort])
            for past, row in zip(getattr(then, cohort), rows, strict=True)
        ]
        for cohort in COHORTS
    }


def sample_0604() -> Sample:
    """S2: the 06:04:42Z snapshot rebuilt from the oracle's rows on the $500 grid.

    D's columns are the finalized 2026-09-19 snapshots plus the 30d rows' differences; the 7d and
    90d rows must give the same columns and the 1d rows the same differences. The age groups are
    the 90d rows' `buy` and the age floor the 30d rows' `floor`.
    """
    rows = {window: oracle(window) for window in WINDOWS}
    floors = [int(row["b"]) for row in rows["30d"]]
    assert floors == [500 * i for i in range(len(floors))]
    for window in ("7d", "90d"):
        assert [row["b"] for row in rows[window]] == floors
    then = {window: _then(window, floors) for window in WINDOWS}

    now = _now(then["30d"], rows["30d"])
    for window in ("7d", "90d"):
        assert _now(then[window], rows[window]) == now, window
    index = {floor: i for i, floor in enumerate(floors)}
    for row in rows["1d"]:
        i = index[row["b"]]
        for cohort in COHORTS:
            diff = now[cohort][i] - getattr(then["1d"], cohort)[i]
            assert abs(diff - row[cohort]) <= ORACLE_TOLERANCE, (row["b"], cohort)

    grid = FlowGrid(
        step=500,
        floors=[float(floor) for floor in floors],
        now=CohortColumns(all=now["all"], sth=now["sth"], lth=now["lth"]),
        windows=[
            FlowWindow(window=window, then_day=D - timedelta(days=n), then=then[window])
            for window, n in WINDOWS.items()
        ],
    )
    age = AgeFlow(
        groups=[[row["buy"][g] for row in rows["90d"]] for g in range(4)],
        band=[row["floor"] for row in rows["30d"]],
    )
    qc = qc_codes([grid], age)
    assert qc == []
    stored = StoredCostFlow(
        now_day=D,
        snapshot_at=S2_SNAPSHOT_AT,
        spot=S2_SPOT,
        grids=[grid],
        age=age,
        reasons=S2_REASONS,
        qc=qc,
    )
    return Sample(stored, S2_COMPUTED_AT, S2_READ_AT)


def served(sample: Sample) -> CostFlowView:
    """What GET /cost-flow serves at `sample.read_at` with `sample.stored` in the store."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "onchain.sqlite"
        payload = sample.stored.model_dump_json()
        OnchainStore(path).save_derived("costflow", payload, sample.computed_at)
        app = FastAPI()
        app.include_router(
            create_router(path, rules=frozenset(), start_worker=False, clock=lambda: sample.read_at)
        )
        with TestClient(app) as http:
            response = http.get("/api/wheelhouse/v1/onchain/cost-flow")
        assert response.status_code == 200
        return CostFlowView.model_validate(response.json())


def _rows(grid: FlowGrid, window: Window, holders: Holders, aging: bool) -> list[Row]:
    """udiff at Zoom All (A:1304-1335): every bucket's difference, trimmed at both ends to the
    buckets that draw a bar."""
    then = next(found.then for found in grid.windows if found.window == window)
    half = grid.step / 2
    rows = [
        (floor + half, all_now - all_then, sth_now - sth_then, lth_now - lth_then)
        for floor, all_now, all_then, sth_now, sth_then, lth_now, lth_then in zip(
            grid.floors,
            grid.now.all,
            then.all,
            grid.now.sth,
            then.sth,
            grid.now.lth,
            then.lth,
            strict=True,
        )
    ]

    def live(row: Row) -> bool:
        return any(abs(v) >= EPS for v in _segments(row, holders, aging))

    i, j = 0, len(rows) - 1
    while i < j and not live(rows[i]):
        i += 1
    while j > i and not live(rows[j]):
        j -= 1
    return rows[i : j + 1]


def _segments(row: Row, holders: Holders, aging: bool) -> list[float]:
    """The values of a bucket's bars (A:1346-1394)."""
    _, whole, short, long = row
    if holders == "all":
        return [whole]
    if not aging:
        return [short]
    # Only coins leaving STH by age, a decrease, are drawn for STH.
    moved = -long
    return [whole, moved] if moved < 0 else [whole]


def _weight(row: Row, holders: Holders, aging: bool, side: Side) -> float:
    """A bucket's weight on one side (A:1397-1401), its bars summed in order from 0."""
    total = 0.0
    for v in _segments(row, holders, aging):
        total += v
    return max(0.0, total) if side == "pos" else max(0.0, -total)


def _gmm(centers: list[float], weights: list[float]) -> list[GmmFit]:
    """fit_gmm for every k up to select_components' cap, over the rows it fits: those with
    weight."""
    xs = [x for x, w in zip(centers, weights, strict=True) if w > 0]
    ws = [w for w in weights if w > 0]
    fits = []
    for k in range(1, max(1, min(MAX_COMPONENTS, len(xs) // 5)) + 1):
        fit = fit_gmm(xs, ws, k)
        assert fit is not None
        fits.append(GmmFit(k=k, comps=fit[0], log_l=fit[1]))
    return fits


def crosscheck() -> Crosscheck:
    """Both sides of 30d All and of 30d STH with Aging Show, at Zoom All, from S1."""
    grids = {grid.step: grid for grid in sample_0512().stored.grids}
    sides: list[CrossSide] = []
    for holders, aging, step in (("all", False, 500), ("sth", True, 200)):
        rows = _rows(grids[step], "30d", holders, aging)
        centers = [row[0] for row in rows]
        h = BW * (centers[-1] - centers[0])
        for side in ("pos", "neg"):
            weights = [_weight(row, holders, aging, side) for row in rows]
            peaks = find_peaks(centers, weights)
            sides.append(
                CrossSide(
                    window="30d",
                    holders=holders,
                    aging=aging,
                    zoom=0,
                    side=side,
                    centers=centers,
                    weights=weights,
                    h=h,
                    kde=weighted_kde(centers, weights, h),
                    peaks=peaks,
                    gmm=_gmm(centers, weights),
                    select_peaks=select_components(
                        centers, weights, len(peaks), len(centers), new_bic=False
                    ),
                    select_bic=select_components(centers, weights, 0, len(centers), new_bic=False),
                )
            )
    return Crosscheck(sides=sides)


def _render(model: Model) -> str:
    return json.dumps(model.model_dump(mode="json"), separators=(",", ":")) + "\n"


def render_sample_0512() -> str:
    return _render(served(sample_0512()))


def render_sample_0604() -> str:
    return _render(served(sample_0604()))


def render_crosscheck() -> str:
    return _render(crosscheck())
