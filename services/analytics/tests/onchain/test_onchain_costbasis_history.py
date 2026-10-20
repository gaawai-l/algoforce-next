from datetime import UTC, date, datetime, timedelta

import pytest
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
D = date(2026, 10, 16)
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
