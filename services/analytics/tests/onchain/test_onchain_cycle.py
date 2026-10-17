import math
from datetime import date, timedelta

import pytest
from onchain_fixture import EPOCH, load_series

from wheelhouse_service.onchain.cycle import DEADBANDS, Cycle, classify, gate, raw_state
from wheelhouse_service.rules import Rules

Row = tuple[date, float | None, float | None, float | None, float | None]
V1: Rules = frozenset()
O1: Rules = frozenset({"O1"})
O4: Rules = frozenset({"O4"})

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
    assert classify([], rules=V1, closed_day=None) is None
    assert (
        classify(
            [(DAY, 100.0, None, 100.0, 100.0), (DAY, 100.0, 90.0, 100.0, 0.0)],
            rules=V1,
            closed_day=None,
        )
        is None
    )

    base: list[Row] = [
        (DAY, 110.0, 105.0, 100.0, 100.0),
        (DAY + timedelta(days=1), 110.0, 105.0, 100.0, 100.0),
    ]
    missing_sth = (DAY + timedelta(days=2), 110.0, None, 100.0, 100.0)
    zero_price = (DAY + timedelta(days=2), 110.0, 105.0, 100.0, 0.0)
    negative_w = (DAY + timedelta(days=2), -1.0, 105.0, 100.0, 100.0)
    for last in (missing_sth, zero_price, negative_w):
        cycle = classify([*base, last], rules=V1, closed_day=None)
        assert cycle is not None
        assert cycle.as_of == DAY + timedelta(days=1)
        assert cycle.day == 2
    # A skipped row in the middle does not count towards the length of the run.
    middle = classify([base[0], missing_sth, base[1]], rules=V1, closed_day=None)
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

    cycle = classify(rows, rules=V1, closed_day=None)

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

    held = classify(rows[:4], rules=V1, closed_day=None)
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

    cycle = classify(rows, rules=V1, closed_day=None)

    assert cycle is not None
    assert cycle.as_of == date(2026, 10, 16)
    assert cycle.latest_day == date(2026, 10, 16)
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


def spans(cycle: Cycle | None) -> list[tuple[str, date, date, int]]:
    assert cycle is not None
    return [(e.state, e.start, e.end, e.days) for e in cycle.episodes]


def test_o4_missing_day_keeps_the_state_and_belongs_to_its_episode():
    days = [DAY + timedelta(days=n) for n in range(8)]
    rows = [
        row(days[0], 10, 5),  # advance
        row(days[1], 10, 5),
        row(days[2], None),  # missing between complete days: keeps advance
        row(days[3], 10, -2),  # spread clears: breakout
        row(days[4], 10, -2),
        row(days[5], None),  # missing inside the run
        row(days[6], 10, -2),
        row(days[7], 10, -2),
    ]

    o4 = classify(rows, rules=O4, closed_day=None)

    assert o4 is not None
    # The episode ends the day before the next one starts, and its days include the missing one.
    assert spans(o4) == [
        ("advance", days[0], days[2], 3),
        ("breakout", days[3], days[7], 5),
    ]
    assert (o4.as_of, o4.state, o4.since, o4.day, o4.changes) == (
        days[7],
        "breakout",
        days[3],
        5,
        1,
    )
    # v1 skips the missing rows: they are in no episode and do not count.
    assert spans(classify(rows, rules=V1, closed_day=None)) == [
        ("advance", days[0], days[1], 2),
        ("breakout", days[3], days[7], 4),
    ]


def test_o4_counts_days_by_calendar():
    # Days with no row at all, as when BRK has none for them: the calendar counts them, v1 does not.
    days = [DAY, DAY + timedelta(days=3), DAY + timedelta(days=4), DAY + timedelta(days=9)]
    rows = [row(days[0], 10, 5), row(days[1], 10, 5), row(days[2], 10, -2), row(days[3], 10, -2)]

    o4 = classify(rows, rules=O4, closed_day=None)
    v1 = classify(rows, rules=V1, closed_day=None)

    assert spans(o4) == [
        ("advance", days[0], days[2] - timedelta(days=1), 4),
        ("breakout", days[2], days[3], 6),
    ]
    assert o4 is not None and (o4.since, o4.day) == (days[2], 6)
    assert spans(v1) == [("advance", days[0], days[1], 2), ("breakout", days[2], days[3], 2)]
    assert v1 is not None and (v1.since, v1.day) == (days[2], 2)


def test_o4_trailing_and_leading_missing_days_are_in_no_episode():
    days = [DAY + timedelta(days=n) for n in range(6)]
    rows = [
        row(days[0], None),  # before the first complete day
        row(days[1], 10, 5),
        row(days[2], 10, 5),
        row(days[3], 10, 5),
        row(days[4], None),  # after the last complete day: does not extend the run
        (days[5], 110.0, 105.0, 100.0, 0.0),
    ]

    o4 = classify(rows, rules=O4, closed_day=None)

    assert o4 is not None
    assert spans(o4) == [("advance", days[1], days[3], 3)]
    assert (o4.as_of, o4.since, o4.day, o4.latest_day) == (days[3], days[1], 3, days[3])


def test_o4_treats_a_value_at_or_below_zero_as_missing():
    days = [DAY + timedelta(days=n) for n in range(5)]
    _, w, sth, tmm, close = row(days[2], 10, -2)  # would switch to breakout
    assert w is not None and sth is not None and tmm is not None and close is not None
    rows = [
        row(days[0], 10, 5),  # advance
        row(days[1], 10, 5),
        (days[2], w, sth, tmm, 0.0),  # a zero price: missing, so it cannot switch
        (days[3], -w, sth, tmm, close),  # a negative W: missing as well
        row(days[4], 10, 5),
    ]

    o4 = classify(rows, rules=O4, closed_day=None)

    assert o4 is not None
    assert spans(o4) == [("advance", days[0], days[4], 5)]
    assert (o4.state, o4.since, o4.day, o4.changes) == ("advance", days[0], 5, 0)
    v1 = classify(rows, rules=V1, closed_day=None)
    assert v1 is not None and (v1.state, v1.day) == ("advance", 3)


def test_o1_ignores_rows_after_the_closed_day():
    days = [DAY + timedelta(days=n) for n in range(4)]
    rows = [
        row(days[0], 10, 5),  # advance
        row(days[1], 10, 4),
        row(days[2], 10, -2),  # would switch to breakout, but it is not closed yet
        row(days[3], 10, -2),
    ]

    o1 = classify(rows, rules=O1, closed_day=days[1])

    assert o1 is not None
    assert (o1.as_of, o1.state, o1.since, o1.day, o1.changes) == (
        days[1],
        "advance",
        days[0],
        2,
        0,
    )
    assert spans(o1) == [("advance", days[0], days[1], 2)]
    # The reading is the closed day's.
    assert [c.value for c in o1.components] == pytest.approx([10, 6, 4])
    # The newest complete day is known whatever the rules: freshness follows it.
    assert o1.latest_day == days[3]

    # Without O1 the closed day is not used.
    v1 = classify(rows, rules=V1, closed_day=days[1])
    assert v1 is not None
    assert (v1.as_of, v1.state, v1.since, v1.latest_day) == (days[3], "breakout", days[2], days[3])


def test_o1_with_o4_leaves_a_missing_closed_day_trailing():
    days = [DAY + timedelta(days=n) for n in range(3)]
    rows = [row(days[0], 10, 5), row(days[1], None), row(days[2], 10, 5)]

    both = classify(rows, rules=frozenset({"O1", "O4"}), closed_day=days[1])

    # Once the open day is left out, the missing closed day is the last one: it is not counted.
    assert both is not None
    assert (both.as_of, both.day, both.latest_day) == (days[0], 1, days[2])
    assert spans(both) == [("advance", days[0], days[0], 1)]


def test_o1_without_a_closed_complete_day_has_no_cycle():
    rows = [row(DAY, None), row(DAY + timedelta(days=1), 10, 5)]
    assert classify(rows, rules=O1, closed_day=DAY) is None


# closed_day(2026-10-16T10:40Z): the fixture's last day was still open then.
P1_CLOSED = date(2026, 10, 15)


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (V1, (date(2026, 10, 16), "breakout", date(2026, 9, 23), 24, 48)),
        (O4, (date(2026, 10, 16), "breakout", date(2026, 9, 23), 24, 48)),
        (O1, (date(2026, 10, 15), "breakout", date(2026, 9, 23), 23, 48)),
        (frozenset({"O1", "O4"}), (date(2026, 10, 15), "breakout", date(2026, 9, 23), 23, 48)),
    ],
)
def test_fixture_under_each_rule(rules: Rules, expected: tuple[date, str, date, int, int]):
    cycle = classify(fixture_rows(), rules=rules, closed_day=P1_CLOSED)

    assert cycle is not None
    assert (cycle.as_of, cycle.state, cycle.since, cycle.day, cycle.changes) == expected
    # The open day still tells how recent the data is.
    assert cycle.latest_day == date(2026, 10, 16)


def test_o4_changes_nothing_on_the_fixture():
    rows = fixture_rows()
    # Every calendar day from the first row to the last has all four values, all positive: no day
    # is missing, so counting calendar days and counting rows give the same numbers.
    assert [r[0] for r in rows] == [
        rows[0][0] + timedelta(days=n) for n in range((rows[-1][0] - rows[0][0]).days + 1)
    ]
    assert all(value is not None and value > 0 for r in rows for value in r[1:])

    for closed, base in ((None, V1), (P1_CLOSED, V1), (P1_CLOSED, O1)):
        assert classify(rows, rules=base | O4, closed_day=closed) == classify(
            rows, rules=base, closed_day=closed
        )
