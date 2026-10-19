import json
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from wheelhouse_service.onchain.agecohorts import BANDS
from wheelhouse_service.onchain.brk import (
    AGE_COHORTS,
    AGE_URPD_COHORTS,
    EPOCH,
    SeriesData,
    Urpd,
    UrpdBucket,
)
from wheelhouse_service.onchain.costbasis import _cents
from wheelhouse_service.onchain.costflow import (
    GRIDS,
    WINDOWS,
    YOUNG,
    YOUNG_GROUPS,
    AgeFlow,
    CohortColumns,
    FlowGrid,
    FlowWindow,
    StoredCostFlow,
    Window,
    age_band,
    age_groups,
    cost_flow,
    qc_codes,
)

COSTFLOW = Path(__file__).parent / "fixtures" / "brk-2026-10-19T0512Z-costflow"
D = date(2026, 10, 19)
# D minus 1, 7, 30 and 90 days: the then days of the four windows.
THEN_DAYS = [date(2026, 10, 18), date(2026, 10, 12), date(2026, 9, 19), date(2026, 7, 21)]
SPOT = 82347.76
SNAPSHOT_AT = datetime(2026, 10, 19, 5, 12, 6, 701470, tzinfo=UTC)
DAY = timedelta(days=1)
Key = tuple[str, str, date]
Rows = list[tuple[datetime, float | None]]


@pytest.fixture(scope="module")
def golden() -> dict[Key, Urpd]:
    """The 30 snapshots of the sample, keyed (cohort, agg, day)."""
    out: dict[Key, Urpd] = {}
    for path in sorted(COSTFLOW.glob("urpd_*.json")):
        urpd = Urpd.model_validate_json(path.read_text())
        out[(urpd.cohort, urpd.aggregation, urpd.date)] = urpd
    assert len(out) == 30
    return out


def hilo(name: str, since: date | None = None) -> Rows:
    """The day1 rows of `price_high` or `price_low`, from `since` on when it is given."""
    series = SeriesData.model_validate_json((COSTFLOW / f"day1_{name}.json").read_text())
    rows = [(EPOCH + DAY * (series.start + k), v) for k, v in enumerate(series.data)]
    return [(at, v) for at, v in rows if since is None or at.date() >= since]


@cache
def oracle(window: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (COSTFLOW / "oracle-c4" / f"c4_{window}_z0_2026-10-19.json").read_text()
    )
    return payload


def snapshot(cohort: str, buckets: list[tuple[float, float]], close: float = SPOT) -> Urpd:
    return Urpd(
        cohort=cohort,
        date=D,
        aggregation="lin500",
        close=close,
        total_supply=0.0,
        buckets=[
            UrpdBucket(price_floor=f, supply=s, realized_cap=0.0, unrealized_pnl=0.0)
            for f, s in buckets
        ],
    )


def six_ages(close: float = SPOT) -> dict[str, Urpd]:
    """Six age snapshots of D at `close`, each holding a little supply around spot."""
    return {
        cohort: snapshot(cohort, [(81500.0, 1.0 + k), (82000.0, 2.0 + k)], close)
        for k, cohort in enumerate(AGE_URPD_COHORTS)
    }


def with_close(urpd: Urpd, close: float) -> Urpd:
    return urpd.model_copy(update={"close": close})


def emptied(urpd: Urpd) -> Urpd:
    return urpd.model_copy(update={"buckets": []})


def flow_of(
    snapshots: dict[Key, Urpd],
    ages: dict[str, Urpd] | None = None,
    high: Rows | None = None,
    low: Rows | None = None,
) -> StoredCostFlow:
    flow = cost_flow(D, snapshots, ages or {}, high or [], low or [], snapshot_at=SNAPSHOT_AT)
    assert flow is not None
    return flow


def grid(flow: StoredCostFlow, step: int) -> FlowGrid:
    return next(g for g in flow.grids if g.step == step)


def test_young_groups_are_the_six_cohorts_the_chart_reads():
    assert AGE_URPD_COHORTS == tuple(c for group in YOUNG_GROUPS for c in group)
    assert [name for name, _ in BANDS[:4]] == ["<1d", "1d–1w", "1w–1m", "1m–3m"]
    assert AGE_URPD_COHORTS == AGE_COHORTS[:6]
    assert WINDOWS == {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
    assert YOUNG == {"1d": 1, "7d": 2, "30d": 3, "90d": 4}
    assert GRIDS == (("lin500", 500), ("lin200", 200))


def test_columns_match_the_stage_a_grid(golden):
    stage_a = json.loads((COSTFLOW / "expected_chart3.json").read_text())
    flow = flow_of(golden)

    assert flow.now_day == D
    assert flow.snapshot_at == SNAPSHOT_AT
    assert flow.spot == SPOT == stage_a["spot"]
    assert [g.step for g in flow.grids] == [500, 200]
    g500, g200 = flow.grids
    assert len(g500.floors) == 252
    assert (g500.floors[0], g500.floors[-1]) == (0, 125_500)
    assert len(g200.floors) == 629
    assert (g200.floors[0], g200.floors[-1]) == (0, 125_600)
    then_days = [date.fromisoformat(stage_a["days"][w]) for w in WINDOWS]
    assert then_days == THEN_DAYS
    for g in flow.grids:
        assert [w.window for w in g.windows] == list(WINDOWS)
        assert [w.then_day for w in g.windows] == THEN_DAYS
        for columns in (g.now, *(w.then for w in g.windows)):
            assert len(columns.all) == len(columns.sth) == len(columns.lth) == len(g.floors)
    totals = [
        (round(sum(g.now.all), 2), round(sum(g.now.sth), 2), round(sum(g.now.lth), 2))
        for g in flow.grids
    ]
    assert totals == [
        (20100107.36, 3648914.84, 16451192.56),
        (20100107.43, 3648914.86, 16451192.58),
    ]
    assert flow.age is None
    assert flow.reasons == ["age_urpd_missing"]
    assert flow.qc == []
    assert flow.rules == []


def test_columns_round_each_supply_like_the_page(golden):
    # +toFixed(2) of the supply BRK reports at that floor; a floor a snapshot lacks reads 0.
    g500 = grid(flow_of(golden), 500)
    sth = {b.price_floor: b.supply for b in golden[("sth", "lin500", D)].buckets}
    row = g500.floors.index(82000.0)
    assert sth[82000.0] != g500.now.sth[row]
    assert g500.now.sth[row] == _cents(sth[82000.0])
    assert 0.0 not in sth
    assert g500.now.sth[0] == 0.0

    # Math.round of the floor: a bucket at 57999.6 is the 58000 row and adds no row of its own.
    key = ("sth", "lin500", D)
    first, *rest = golden[key].buckets
    assert first.price_floor == 58000.0
    moved = first.model_copy(update={"price_floor": 57999.6})
    shifted = grid(
        flow_of({**golden, key: golden[key].model_copy(update={"buckets": [moved, *rest]})}), 500
    )
    assert shifted.floors == g500.floors
    assert shifted.now.sth == g500.now.sth


def test_cost_flow_needs_the_all_lin500_snapshot_of_d(golden):
    without = {k: v for k, v in golden.items() if k != ("all", "lin500", D)}
    assert cost_flow(D, without, {}, [], [], snapshot_at=SNAPSHOT_AT) is None
    empty = {**golden, ("all", "lin500", D): emptied(golden[("all", "lin500", D)])}
    assert cost_flow(D, empty, {}, [], [], snapshot_at=SNAPSHOT_AT) is None


def test_cost_flow_never_mixes_snapshots(golden):  # Review Focus 5
    high, low = hilo("price_high", date(2013, 1, 1)), hilo("price_low", date(2013, 1, 1))

    key = ("sth", "lin500", D)
    flow = flow_of({**golden, key: with_close(golden[key], 1.0)}, six_ages(), high, low)
    assert [g.step for g in flow.grids] == [200]
    assert flow.age is None
    assert "urpd_mismatch:sth:lin500" in flow.reasons

    key = ("all", "lin200", D)
    flow = flow_of({**golden, key: with_close(golden[key], 1.0)}, six_ages(), high, low)
    assert [g.step for g in flow.grids] == [500]
    assert "urpd_mismatch:all:lin200" in flow.reasons
    assert flow.age is not None


def test_empty_snapshot_is_missing(golden):
    key = ("sth", "lin500", D)
    flow = flow_of({**golden, key: emptied(golden[key])})
    assert [g.step for g in flow.grids] == [200]
    assert "urpd_missing:sth:lin500" in flow.reasons

    key = ("all", "lin200", date(2026, 10, 18))
    flow = flow_of({**golden, key: emptied(golden[key])})
    assert [w.window for w in grid(flow, 200).windows] == ["7d", "30d", "90d"]
    assert [w.window for w in grid(flow, 500).windows] == ["1d", "7d", "30d", "90d"]
    assert "window_missing:1d:lin200" in flow.reasons

    high, low = hilo("price_high", date(2013, 1, 1)), hilo("price_low", date(2013, 1, 1))
    ages = six_ages()
    ages["utxos_1w_to_1m_old"] = emptied(ages["utxos_1w_to_1m_old"])
    flow = flow_of(golden, ages, high, low)
    assert flow.age is None
    assert "age_urpd_missing" in flow.reasons


def test_cost_flow_names_missing_windows(golden):
    without = {k: v for k, v in golden.items() if k != ("sth", "lin200", date(2026, 7, 21))}
    flow = flow_of(without)
    assert [w.window for w in grid(flow, 200).windows] == ["1d", "7d", "30d"]
    assert "window_missing:90d:lin200" in flow.reasons
    assert "urpd_grid_partial:lin200" in flow.reasons
    assert [w.window for w in grid(flow, 500).windows] == ["1d", "7d", "30d", "90d"]
    assert not any(r.endswith(":lin500") for r in flow.reasons)


def test_missing_d_cohort_takes_its_grid_down(golden):
    without = {k: v for k, v in golden.items() if k != ("lth", "lin200", D)}
    flow = flow_of(without)
    assert [g.step for g in flow.grids] == [500]
    assert "urpd_missing:lth:lin200" in flow.reasons


def test_age_band_matches_the_page_histogram():
    # hilo from 2013-01-01 on, D 2026-10-19, floors 0..125,500 step 500
    floors = [500.0 * i for i in range(252)]
    high, low = hilo("price_high", date(2013, 1, 1)), hilo("price_low", date(2013, 1, 1))
    bands = age_band(high, low, floors, 500.0, D)
    assert [bands.count(g) for g in range(12)] == [4, 5, 6, 36, 8, 58, 19, 59, 26, 22, 8, 1]
    assert bands == [r["floor"] for r in oracle("30d")["rows"]]
    assert [r["b"] for r in oracle("30d")["rows"]] == floors
    # the whole 5,600 days give the same bands
    assert age_band(hilo("price_high"), hilo("price_low"), floors, 500.0, D) == bands


def test_age_band_skips_days_after_d_and_nulls():
    at = datetime(2026, 10, 19, tzinfo=UTC)
    high: Rows = [
        (at - 3 * DAY, 1200.0),
        (at - 2 * DAY, 2100.0),
        (at - DAY, None),
        (at, 600.0),
        (at + DAY, 2100.0),
    ]
    low: Rows = [
        (at - 3 * DAY, 900.0),
        (at - 2 * DAY, None),
        (at - DAY, 100.0),
        (at, 400.0),
        (at + DAY, 1600.0),
    ]
    # 0 traded on D, 500 on D and 3 days before, 1000 three days before; 1500 and 2000 only
    # after D or on days missing one side, so never
    assert age_band(high, low, [0.0, 500.0, 1000.0, 1500.0, 2000.0], 500.0, D) == [
        0,
        0,
        1,
        11,
        11,
    ]


def test_age_groups_sum_the_cohorts_then_round():
    ages = {cohort: snapshot(cohort, [(82000.0, 0.0)]) for cohort in AGE_URPD_COHORTS}
    ages["utxos_under_1h_old"] = snapshot("utxos_under_1h_old", [(82000.0, 1.004), (130000.0, 5.0)])
    ages["utxos_1h_to_1d_old"] = snapshot("utxos_1h_to_1d_old", [(82000.0, 1.002)])
    # Math.round of the floor puts 81999.6 on the 82000 row.
    ages["utxos_1d_to_1w_old"] = snapshot("utxos_1d_to_1w_old", [(81999.6, 3.0)])
    groups = age_groups(ages, [82000.0])
    assert groups[0] == [2.01]
    assert groups[1] == [3.0]
    assert groups[2:] == [[0.0], [0.0]]


def test_age_reasons(golden):
    high, low = hilo("price_high", date(2013, 1, 1)), hilo("price_low", date(2013, 1, 1))
    flow = flow_of(golden, six_ages(), high, low)
    assert flow.age is not None
    assert len(flow.age.groups) == 4
    assert all(len(g) == 252 for g in flow.age.groups)
    assert len(flow.age.band) == 252
    assert flow.reasons == []
    row = grid(flow, 500).floors.index(82000.0)
    assert [g[row] for g in flow.age.groups] == [5.0, 4.0, 5.0, 13.0]

    one_missing = {k: v for k, v in six_ages().items() if k != "utxos_1m_to_2m_old"}
    flow = flow_of(golden, one_missing, high, low)
    assert (flow.age, flow.reasons) == (None, ["age_urpd_missing"])

    off = six_ages()
    off["utxos_2m_to_3m_old"] = with_close(off["utxos_2m_to_3m_old"], 1.0)
    flow = flow_of(golden, off, high, low)
    assert (flow.age, flow.reasons) == (None, ["age_urpd_mismatch"])

    # The first reason that applies is the one given.
    flow = flow_of(golden, {k: v for k, v in off.items() if k != "utxos_under_1h_old"}, high, low)
    assert (flow.age, flow.reasons) == (None, ["age_urpd_missing"])

    flow = flow_of(golden, six_ages())
    assert (flow.age, flow.reasons) == (None, ["age_floor_missing"])

    until = datetime(2026, 10, 17, tzinfo=UTC)
    flow = flow_of(
        golden,
        six_ages(),
        [r for r in high if r[0] <= until],
        [r for r in low if r[0] <= until],
    )
    assert flow.age is not None
    assert flow.reasons == ["age_floor_stale"]


def columns(all_: list[float], sth: list[float], lth: list[float]) -> CohortColumns:
    return CohortColumns(all=all_, sth=sth, lth=lth)


def synthetic(
    step: int,
    then: dict[Window, CohortColumns] | None = None,
    now: CohortColumns | None = None,
) -> FlowGrid:
    """A 3-row grid whose four windows hold now's columns, unless `then` says otherwise."""
    now = now or columns([2.0, 3.0, 4.0], [1.0, 1.0, 1.0], [1.0, 2.0, 3.0])
    then = then or {}
    return FlowGrid(
        step=step,
        floors=[0.0, float(step), 2.0 * step],
        now=now,
        windows=[
            FlowWindow(window=w, then_day=D - DAY * n, then=then.get(w, now))
            for w, n in WINDOWS.items()
        ],
    )


def test_qc_codes():  # synthetic 3-row grids
    quiet = AgeFlow(groups=[[0.0, 0.0, 0.0] for _ in range(4)], band=[11, 11, 11])
    assert qc_codes([synthetic(500), synthetic(200)], quiet) == []

    # |all - sth - lth| == 0.06 on one day
    off = columns([2.06, 3.0, 4.0], [1.0, 1.0, 1.0], [1.0, 2.0, 3.0])
    assert qc_codes([synthetic(500, {"7d": off}), synthetic(200)], quiet) == ["cohort_sum:lin500"]
    assert qc_codes([synthetic(500), synthetic(200, {"90d": off})], None) == ["cohort_sum:lin200"]
    near = columns([2.04, 3.0, 4.0], [1.0, 1.0, 1.0], [1.0, 2.0, 3.0])
    assert qc_codes([synthetic(500, {"7d": near})], quiet) == []

    # sold = then - (now - bought) < -0.05 in 1d: 1.9 - (2.0 - 0.0)
    fell = columns([1.9, 3.0, 4.0], [0.9, 1.0, 1.0], [1.0, 2.0, 3.0])
    assert qc_codes([synthetic(500, {"1d": fell})], quiet) == ["sold_negative:1d"]
    # 7d counts two young groups as bought: 1.9 - (2.0 - 0.06) = -0.04
    bought = AgeFlow(
        groups=[[0.0, 0.0, 0.0], [0.06, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        band=[11, 11, 11],
    )
    assert qc_codes([synthetic(500, {"1d": fell, "7d": fell})], bought) == ["sold_negative:1d"]
    # without the age groups there is no bought, so no sold either
    assert qc_codes([synthetic(500, {"1d": fell})], None) == []

    # a row with now.all 2.0, band 2 and group <1d 1.0
    young = AgeFlow(
        groups=[[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        band=[2, 11, 11],
    )
    assert qc_codes([synthetic(500)], young) == ["age_floor"]
    # coins as young as the band itself are allowed
    assert qc_codes([synthetic(500)], young.model_copy(update={"band": [0, 11, 11]})) == []
    # a row holding 0.5 BTC or less is not read
    thin = columns([0.5, 3.0, 4.0], [0.5, 1.0, 1.0], [0.0, 2.0, 3.0])
    assert qc_codes([synthetic(500, now=thin)], young) == []
