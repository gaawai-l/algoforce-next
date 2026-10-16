import math
from datetime import date, timedelta

import pytest
from onchain_fixture import EPOCH, load_series

from wheelhouse_service.onchain.cycle import DEADBANDS, classify, gate, raw_state

Row = tuple[date, float | None, float | None, float | None, float | None]

# (depth > 0, pvs > 0, spread > 0) -> state
TRIPLETS = [
    ((1, 1, 1), "advance"),
    ((1, 1, 0), "breakout"),
    ((1, 0, 1), "pressure"),
    ((0, 1, 0), "repair"),
    ((0, 0, 1), "breakdown"),
    ((0, 0, 0), "capitulation"),
]
DAY = date(2026, 1, 1)


def test_raw_state_maps_sign_triplets():
    for (depth, pvs, spread), state in TRIPLETS:
        assert raw_state(depth * 2.0 - 1, pvs * 2.0 - 1, spread * 2.0 - 1) == state
    # A component that is exactly zero counts as negative.
    assert raw_state(0.0, 0.0, 0.0) == "capitulation"
    assert raw_state(1.0, 1.0, 0.0) == "breakout"
    assert raw_state(0.0, 1.0, 0.0) == "repair"
    # The other two sign combinations cannot occur when pvs = depth - spread.
    with pytest.raises(ValueError, match="inconsistent"):
        raw_state(-1.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="inconsistent"):
        raw_state(1.0, -1.0, -1.0)


def test_gate_boundary_is_strict():
    assert DEADBANDS == {"depth": 7.0, "pvs": 6.8, "spread": 1.25}
    # Only spread flips, and it sits exactly on its deadband.
    assert gate("breakout", 8, 9, 1.25) == "breakout"
    assert gate("breakout", 8, 9, 1.26) == "advance"
    # Nothing flips: the state is returned as is, whatever the magnitudes.
    assert gate("breakout", 0.1, 0.2, -0.1) == "breakout"


def test_gate_needs_every_flipped_component():
    # advance -> repair flips depth and spread; depth clears 7.0 but spread does not clear 1.25.
    assert gate("advance", -7.5, 3, -1.0) == "advance"
    # Now spread clears and depth does not; the earlier partial flip is not remembered.
    assert gate("advance", -6.0, 3, -1.5) == "advance"
    # Both clear their deadbands.
    assert gate("advance", -7.5, 3, -1.5) == "repair"


def row(day: date, depth: float | None, spread: float = 0.0) -> Row:
    """A row whose depth/spread are as given, with TMM = 100 and a positive price."""
    if depth is None:
        return (day, None, 100.0, 100.0, 100.0)
    return (day, 100 * math.exp(depth / 100), 100 * math.exp(spread / 100), 100.0, 100.0)


def test_classify_skips_rows_with_missing_or_nonpositive_values():
    assert classify([]) is None
    assert classify([(DAY, 100.0, None, 100.0, 100.0), (DAY, 100.0, 90.0, 100.0, 0.0)]) is None

    base: list[Row] = [
        (DAY, 110.0, 105.0, 100.0, 100.0),
        (DAY + timedelta(days=1), 110.0, 105.0, 100.0, 100.0),
    ]
    missing_sth = (DAY + timedelta(days=2), 110.0, None, 100.0, 100.0)
    zero_price = (DAY + timedelta(days=2), 110.0, 105.0, 100.0, 0.0)
    negative_w = (DAY + timedelta(days=2), -1.0, 105.0, 100.0, 100.0)
    for last in (missing_sth, zero_price, negative_w):
        cycle = classify([*base, last])
        assert cycle is not None
        assert cycle.as_of == DAY + timedelta(days=1)
        assert cycle.day == 2
    # A skipped row in the middle does not count towards the length of the run.
    middle = classify([base[0], missing_sth, base[1]])
    assert middle is not None
    assert middle.as_of == DAY + timedelta(days=1)
    assert middle.day == 2


def test_classify_builds_episodes_and_support():
    days = [DAY + timedelta(days=n) for n in range(6)]
    rows = [
        row(days[0], 10, 5),  # advance (first row takes the raw state)
        row(days[1], 10, -2),  # spread flips and clears 1.25: breakout
        row(days[2], 10, -2),
        row(days[3], 10, 1),  # raw advance, but spread 1 does not clear 1.25: stays breakout
        row(days[4], None),  # missing: skipped
        row(days[5], 10, 3),  # spread clears again: advance
    ]

    cycle = classify(rows)

    assert cycle is not None
    assert (cycle.as_of, cycle.state, cycle.since, cycle.day) == (days[5], "advance", days[5], 1)
    assert cycle.changes == 2
    assert [(e.state, e.start, e.end, e.days) for e in cycle.episodes] == [
        ("advance", days[0], days[0], 1),
        ("breakout", days[1], days[3], 3),
        ("advance", days[5], days[5], 1),
    ]
    assert [c.name for c in cycle.components] == ["depth", "pvs", "spread"]
    assert [c.deadband for c in cycle.components] == [7.0, 6.8, 1.25]
    assert [c.value for c in cycle.components] == pytest.approx([10, 7, 3])
    assert all(c.supports for c in cycle.components)

    held = classify(rows[:4])
    assert held is not None
    assert (held.state, held.since, held.day) == ("breakout", days[1], 3)
    # The held state still expects spread <= 0 while spread is +1: it no longer supports it.
    assert [c.supports for c in held.components] == [True, True, False]
    assert held.components[2].value == pytest.approx(1)


def fixture_rows() -> list[Row]:
    names = (
        "utxos_1d_to_1w_old_realized_price",
        "sth_realized_price",
        "true_market_mean",
        "price_close",
    )
    series = [load_series(name, "day1") for name in names]
    assert {(s.start, len(s.data)) for s in series} == {(series[0].start, len(series[0].data))}
    return [
        (EPOCH + timedelta(days=series[0].start + k), *(s.data[k] for s in series))
        for k in range(len(series[0].data))
    ]


def test_fixture_parity_breakout_since_sep_23():
    rows = fixture_rows()
    assert (rows[0][0], rows[-1][0]) == (date(2013, 1, 1), date(2026, 10, 16))

    cycle = classify(rows)

    assert cycle is not None
    assert cycle.as_of == date(2026, 10, 16)
    assert cycle.state == "breakout"
    assert cycle.since == date(2026, 9, 23)
    assert cycle.day == 24
    assert cycle.changes == 48
    assert len(cycle.episodes) == 49
    assert cycle.episodes[-1].start == date(2026, 9, 23)
    assert cycle.episodes[-1].days == 24
    assert [c.name for c in cycle.components] == ["depth", "pvs", "spread"]
    assert all(c.supports for c in cycle.components)

    def depth(day: date) -> float:
        _, w, _, tmm, _ = next(r for r in rows if r[0] == day)
        assert w is not None and tmm is not None
        return round(100 * math.log(w / tmm), 2)

    # Depth was still below its 7.0 deadband the day before the switch and above it on the day.
    assert depth(date(2026, 9, 22)) == 4.41
    assert depth(date(2026, 9, 23)) == 7.46
