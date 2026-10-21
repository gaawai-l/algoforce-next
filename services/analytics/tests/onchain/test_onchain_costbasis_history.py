import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from cbh_reference import fmt_btc, js_round, reference
from onchain_fixture import history_urpd
from pydantic import ValidationError

from wheelhouse_service.onchain.brk import Urpd, UrpdBucket
from wheelhouse_service.onchain.costbasis_history import (
    HistoryDay,
    cost_basis_history,
    history_row,
)

# SR-8-A §2.1 (lines 92-95), read from the local store on 2026-10-19 and matched against the
# original page's CBD.byDate to within Float32 error (SR-8 line 23): close, the sum over the >= $1k
# grid, the largest bucket ($84k), then the $60k, $74k, $82k and $100k buckets.
# fmt: off
STAGE_A = {
    date(2026, 7, 21): (
        66154.98, 16_390_537.77, 603_593.58, 181_182.11, 74_717.10, 58_801.84, 15_262.95
    ),
    date(2026, 9, 19): (
        81270.08, 16_431_116.67, 572_136.78, 152_736.77, 61_968.93, 53_571.71, 14_087.17
    ),
    date(2026, 10, 12): (
        81963.83, 16_444_750.01, 751_749.92, 138_931.51, 55_700.95, 171_554.40, 13_853.53
    ),
    date(2026, 10, 18): (
        81844.61, 16_448_789.77, 731_367.21, 138_054.69, 55_315.76, 218_667.66, 13_526.98
    ),
}
# fmt: on
FETCHED = datetime(2026, 10, 16, 18, 29, 37, tzinfo=UTC)
SAMPLE = (
    Path(__file__).parents[4]
    / "integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse"
)
D = date(2026, 10, 16)
# PLAN-SR8 Task 7: the original page and the service read at one moment, see its README.
ACCEPTANCE = Path(__file__).parent / "fixtures" / "sr8-acceptance-2026-10-21"
DAY = timedelta(days=1)
MICRO = timedelta(microseconds=1)


def at(floor: int) -> int:
    return (floor - 1000) // 500


def urpd_with(floors: dict[int, float]) -> Urpd:
    """An all-coins lin500 snapshot of D holding `floors` (price floor: supply)."""
    return Urpd(
        cohort="all",
        date=D,
        aggregation="lin500",
        close=1.0,
        total_supply=sum(floors.values()),
        buckets=[
            UrpdBucket(price_floor=floor, supply=supply, realized_cap=0.0, unrealized_pnl=0.0)
            for floor, supply in floors.items()
        ],
    )


def kept(day: date, supply: list[float]) -> HistoryDay:
    return HistoryDay(day=day, close=1.0, supply=supply, fetched_at=FETCHED)


def absent(day: date) -> HistoryDay:
    return HistoryDay(day=day, close=None, supply=None, fetched_at=FETCHED)


@pytest.mark.parametrize("day", sorted(STAGE_A))
def test_history_row_matches_stage_a_cell_by_cell(day: date):
    snapshot = history_urpd(day)
    row = history_row(snapshot)
    close, total, top, p60, p74, p82, p100 = STAGE_A[day]
    assert snapshot.close == close
    assert len(row) == 250 and sum(v > 0.005 for v in row) == 250
    assert max(range(250), key=row.__getitem__) == at(84_000) and row[at(84_000)] == top
    assert [row[at(f)] for f in (60_000, 74_000, 82_000, 100_000)] == [p60, p74, p82, p100]
    # Stage A summed unrounded cells; 250 cells rounded to 0.01 move a sum by at most 1.25.
    assert sum(row) == pytest.approx(total, abs=1.26)


def test_history_row_of_an_old_and_a_recent_snapshot():
    old = history_row(history_urpd(date(2022, 10, 20)))
    assert len(old) == 135  # $1,000-$68,000 (137 buckets from $0)
    assert [old[0], old[at(20_000)], old[at(60_000)]] == [120_929.22, 397_011.71, 100_863.01]
    assert sum(old) == pytest.approx(14_985_650.82, abs=0.005)
    recent = history_row(history_urpd(date(2025, 10, 20)))
    assert len(recent) == 250
    assert [recent[at(f)] for f in (60_000, 74_000, 82_000, 100_000)] == [
        140_446.02,
        4_494.45,
        70_630.70,
        44_050.67,
    ]
    assert sum(recent) == pytest.approx(16_214_671.32, abs=0.005)


def test_history_row_skips_low_and_off_grid_buckets_and_zero_fills_gaps():
    # floors 0, 500 dropped (< $1,000); 1700 is off the $500 grid; 1500 absent inside the range
    assert history_row(urpd_with({0: 9.0, 500: 9.0, 1000: 1.234, 1700: 5.0, 2000: 2.0})) == [
        1.23,
        0.0,
        2.0,
    ]


def test_window_is_1461_calendar_days_with_their_statuses():
    rows = {
        D: kept(D, [1.0, 2.0, 3.0]),
        D - DAY: kept(D - DAY, [1.0, 2.0, 3.0]),
        D - 3 * DAY: absent(D - 3 * DAY),
    }
    result = cost_basis_history(rows, D)
    assert result is not None and result.latest_day == D and result.rules == []
    assert result.floors == [1000, 1500, 2000]
    assert len(result.days) == 1461
    assert result.days[0] == date(2022, 10, 17) and result.days[-1] == D
    assert result.status[-4:] == ["absent", "pending", "closed", "forming"]
    assert result.status.count("pending") == 1458
    assert result.supply[-3] is None and result.close[-3] is None and result.supply[-4] is None


def test_older_rows_are_padded_with_zero_and_cut_to_the_grid():
    rows = {
        D: kept(D, [1.0, 2.0, 3.0]),
        D - DAY: kept(D - DAY, [4.0, 5.0]),
        D - 2 * DAY: kept(D - 2 * DAY, [6.0, 7.0, 8.0, 9.0]),
    }
    result = cost_basis_history(rows, D)
    assert result is not None
    assert result.supply[-2] == [4.0, 5.0, 0.0] and result.supply[-3] == [6.0, 7.0, 8.0]


def test_no_history_without_the_newest_snapshot():
    assert cost_basis_history({}, D) is None
    assert cost_basis_history({D: absent(D)}, D) is None


def test_history_day_needs_close_and_supply_together():
    with pytest.raises(ValidationError):
        HistoryDay(day=D, close=None, supply=[1.0], fetched_at=FETCHED)


def test_history_row_is_empty_without_a_bucket_from_1000():
    assert history_row(urpd_with({0: 9.0, 500: 9.0})) == []
    assert cost_basis_history({D: kept(D, [])}, D) is None


def test_a_row_is_forming_until_its_day_ends_and_keeps_its_close():
    # The boundary is the end of the day (00:00 UTC after it), not final_from's grace hour.
    midnight = datetime(2026, 10, 16, tzinfo=UTC)
    rows = {
        D: HistoryDay(day=D, close=3.0, supply=[1.0], fetched_at=midnight + DAY - MICRO),
        D - DAY: HistoryDay(day=D - DAY, close=2.0, supply=[1.0], fetched_at=midnight),
    }
    result = cost_basis_history(rows, D)
    assert result is not None and result.backfill_error is None
    assert result.status[-2:] == ["closed", "forming"]
    assert result.close[-2:] == [2.0, 3.0]


def test_history_day_needs_supply_with_a_close():
    with pytest.raises(ValidationError):
        HistoryDay(day=D, close=1.0, supply=None, fetched_at=FETCHED)


def test_an_empty_older_row_is_missing_not_zeros():
    result = cost_basis_history({D: kept(D, [1.0, 2.0]), D - DAY: kept(D - DAY, [])}, D)
    assert result is not None
    assert result.supply[-2] is None and result.close[-2] is None
    assert result.status[-2] == "absent"


def test_reference_reproduces_the_frontend_expected():
    view = json.loads((SAMPLE / "cost-basis-history-sample.json").read_text())
    expected = json.loads((SAMPLE / "cost-basis-history-expected.json").read_text())
    assert [reference(view, r) for r in (0, 50, 25, 10)] == expected
    assert reference(view, 0) == {
        "range": 0,
        "r0": 0,
        "r1": 249,
        "n": 1250,
        "floor": 87116.49,
        "cap": 197436.37,
        "top": 765418.85,
        "key": ["−87k", "115k", "142k", "170k", "197k+"],
        "label": "75–95% · 87k–197k+",
    }
    # Only + - * / floor and ceil, no libm result, so it is the same bytes on every platform: the
    # file is the reference's output as it is now, and a drift of either shows here.
    committed = (SAMPLE / "cost-basis-history-expected.json").read_text()
    rendered = json.dumps(
        [reference(view, r) for r in (0, 50, 25, 10)], indent=1, ensure_ascii=False
    )
    assert committed == rendered + "\n"


def test_reference_matches_the_independently_computed_table():
    # PLAN-SR8 Task 3 Step 5: rows r0-r1, cell count, floor, cap and key of Range All, +-50%, +-25%
    # and +-10%, computed separately when the plan was written and when it was reviewed. Spot is
    # 81,217.6, the close of 10-16, and the largest cell 765,418.85 in all four.
    view = json.loads((SAMPLE / "cost-basis-history-sample.json").read_text())
    assert view["close"][-1] == 81217.6
    table = {
        0: (0, 249, 1250, 87116.49, 197436.37, "−87k 115k 142k 170k 197k+"),
        50: (79, 242, 820, 100984.37, 211844.19, "−101k 129k 156k 184k 212k+"),
        25: (119, 202, 420, 142883.05, 238690.49, "−143k 167k 191k 215k 239k+"),
        10: (144, 177, 170, 160548.58, 302419.22, "−161k 196k 231k 267k 302k+"),
    }
    for range_pct, (r0, r1, n, floor, cap, key) in table.items():
        found = reference(view, range_pct)
        assert (found["r0"], found["r1"], found["n"]) == (r0, r1, n), range_pct
        assert (found["floor"], found["cap"], found["top"]) == (floor, cap, 765418.85), range_pct
        assert " ".join(found["key"]) == key, range_pct
        # Rows of $500 from $1,000: the y range of the table.
        assert (1000 + 500 * r0, 1000 + 500 * (r1 + 1)) == {
            0: (1000, 126000),
            50: (40500, 122500),
            25: (60500, 102500),
            10: (73000, 90000),
        }[range_pct]


def test_reference_follows_the_original_at_its_edges():
    view = json.loads((SAMPLE / "cost-basis-history-sample.json").read_text())
    # 0 and 100 are exactly no change: nothing dropped or clipped, and the label says so.
    whole = reference(view, 0, lo=0, hi=100)
    assert (whole["floor"], whole["cap"], whole["top"]) == (0, 765418.85, 765418.85)
    assert whole["key"] == ["0", "191k", "383k", "574k", "765k"]
    assert whole["label"] == "full range"
    # Millions take two decimals; under a thousand, a whole number.
    tiny = {**view, "supply": [None] * 29 + [[0.0, 0.5, 2.0, 1_234_567.0]], "floors": [1, 2, 3, 4]}
    found = reference(tiny, 0, lo=50, hi=99)
    assert (found["r0"], found["r1"], found["n"]) == (1, 3, 3)
    assert found["key"][0] == "−2" and found["key"][-1] == "1.23M"
    # A cell of the data's own precision, 0.005 BTC, holds no coins.
    precise = {**tiny, "supply": [None] * 29 + [[0.005, 0.5, 2.0, 1_234_567.0]]}
    assert (reference(precise, 0)["r0"], reference(precise, 0)["n"]) == (1, 3)
    # A Range around spot that leaves no two rows keeps the occupied rows.
    assert (reference(tiny, 10)["r0"], reference(tiny, 10)["r1"]) == (1, 3)
    # Without any stored day there is nothing to scale: the whole grid, and no cell.
    empty = {**view, "supply": [None] * 30, "close": [None] * 30}
    found = reference(empty, 50)
    assert (found["r0"], found["r1"], found["n"]) == (0, 249, 0)
    assert (found["floor"], found["cap"], found["top"]) == (0, 1e-9, 1)


def test_reference_rounds_as_javascript_does():
    # Math.round: a half goes up, also below zero, and 0.49999999999999994 stays under it.
    assert [js_round(x) for x in (0.5, 2.5, 940.5, -2.5, 0.49999999999999994, 1.4)] == [
        1,
        3,
        941,
        -2,
        0,
        1,
    ]
    # toFixed rounds the exact binary value, a tie up: 1.125 is exact, 1.005 just under.
    assert [fmt_btc(1_125_000), fmt_btc(1_005_000), fmt_btc(999.5), fmt_btc(1_499.9)] == [
        "1.13M",
        "1.00M",
        "1000",
        "1k",
    ]


def test_reference_reads_spot_and_the_range_as_the_original_does():
    view = json.loads((SAMPLE / "cost-basis-history-sample.json").read_text())
    rows = [None] * 30
    close: list[float | None] = [None] * 30
    floors = [1000 + 500 * i for i in range(8)]
    # Spot is the close of the last day with a snapshot, not of the last day.
    rows[27], close[27] = [1.0] * 8, 2000.0
    found = reference({**view, "supply": rows, "close": close, "floors": floors}, 10)
    assert (found["r0"], found["r1"]) == (1, 3)
    # A Range that leaves a single row keeps the occupied rows: only b > a narrows them. At spot
    # 5,200, -10% falls in the top row ($4,500-$5,000), so both ends are row 7.
    close[27] = 5200.0
    found = reference({**view, "supply": rows, "close": close, "floors": floors}, 10)
    assert (found["r0"], found["r1"]) == (0, 7)
    # At 100 the cap is the largest cell, even when the floor already reaches it.
    found = reference({**view, "supply": rows, "close": close, "floors": floors}, 0, 99, 100)
    assert (found["floor"], found["cap"], found["top"]) == (1.0, 1.0, 1.0)


def test_sr8_acceptance_readings():
    # The service's ?span=365 body at the moment the original page was read. Both sides leave out
    # the forming last column; 30D and 90D are the last columns of 365D, as the service slices them.
    view = json.loads(gzip.decompress((ACCEPTANCE / "local-span365.json.gz").read_bytes()))
    expected = json.loads((ACCEPTANCE / "reference-output.json").read_text())
    original = json.loads((ACCEPTANCE / "original-readings.json").read_text())
    assert view["status"][-1] == "forming"
    settings = {
        "30D": (30, 0),
        "90D": (90, 0),
        "365D": (365, 0),
        "365D ±50%": (365, 50),
        "365D ±25%": (365, 25),
        "365D ±10%": (365, 10),
    }
    assert list(expected) == list(original["settings"]) == list(settings)
    found = {}
    for key, (span, range_pct) in settings.items():
        cut = {**view, **{k: view[k][-span:-1] for k in ("days", "close", "supply", "status")}}
        mine, page = reference(cut, range_pct), original["settings"][key]
        assert (cut["days"][0], cut["days"][-1]) == (page["first"], page["last"]), key
        # The same rows and cells; floor and cap within the original's Float32 against our 2dp.
        assert (mine["r0"], mine["r1"], mine["n"]) == (page["r0"], page["r1"], page["n"]), key
        assert abs(mine["floor"] - page["floor"]) <= 0.05, key
        assert abs(mine["cap"] - page["cap"]) <= 0.05, key
        found[key] = mine
    assert found == expected
    # The $60k, $74k, $82k and $100k cells of four closed days.
    for day, page in original["probes"].items():
        i = view["days"].index(day)
        assert view["close"][i] == page["close"], day
        cells = [view["supply"][i][at(floor)] for floor in (60000, 74000, 82000, 100000)]
        assert all(abs(a - b) <= 0.035 for a, b in zip(cells, page["cells"], strict=True)), day
