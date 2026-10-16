"""Golden cases exercise the public interface, with literal expected bar references."""

from datetime import UTC, datetime, timedelta

from wheelhouse_service.indicators.demark import DemarkConfig, evaluate_demark
from wheelhouse_service.market import Bar, Dataset, StoredBar, Stream

START = datetime(2026, 1, 1, tzinfo=UTC)
STREAM = Stream(source="fixture", symbol="BTCUSDT", timeframe="1h")


def dataset(closes, *, lows=None, highs=None):
    at = START + timedelta(hours=len(closes) + 1)
    return Dataset(
        stream=STREAM,
        market_at=at,
        knowledge_at=at,
        fetched_at=at,
        forming=[],
        bars=[
            StoredBar(
                revision_id=f"b{i}",
                revision=1,
                fetched_at=START + timedelta(hours=i + 1),
                bar=Bar(
                    open_time=START + timedelta(hours=i),
                    close_time=START + timedelta(hours=i + 1),
                    open=str(c),
                    close=str(c),
                    high=str(highs[i] if highs else c + 1),
                    low=str(lows[i] if lows else c - 1),
                    is_closed=True,
                ),
            )
            for i, c in enumerate(closes)
        ],
    )


# b4 closes above b0; b5 below b1 is the bearish flip.
# b5..b13 are Buy Setup 1..9. b13 also qualifies as Countdown 1.
BUY = [100, 101, 102, 103, 104, 99, 98, 97, 96, 95, 94, 93, 92, 91]


def test_buy_setup_nine_has_independent_countdown_and_perfection():
    result = evaluate_demark(dataset(BUY), DemarkConfig())
    seq = next(s for s in result.sequences if s.side == "buy")
    assert [b.revision_id for b in seq.setup_bars] == [f"b{i}" for i in range(5, 14)]
    assert seq.setup_count == 9
    assert seq.setup_status == "completed"
    assert seq.setup_perfected is True
    assert seq.perfected_at == START + timedelta(hours=14)
    assert seq.countdown_count == 1
    assert seq.countdown_status == "active"
    assert seq.tdst == "104"
    assert result.qualified13_count == 0
    assert result.history_status == "window_only"


def test_countdown_completes_on_thirteenth_qualifying_bar_with_evidence():
    # b13..b25 qualify: CD8=b20(close84), CD13=b25(low78 <= 84).
    result = evaluate_demark(dataset(BUY + list(range(90, 78, -1))))
    seq = next(s for s in result.sequences if s.side == "buy")
    assert seq.countdown_count == 13
    assert seq.countdown_status == "qualified13"
    assert seq.countdown_bar8.revision_id == "b20"
    assert seq.qualification_threshold == "84"
    assert seq.qualified_at == START + timedelta(hours=26)
    assert seq.confirmation_close == "79"
    assert result.qualified13_count == 1
    assert [e.bar.revision_id for e in result.events if e.kind == "qualified13"] == ["b25"]


def test_thirteen_is_deferred_when_extreme_does_not_reach_countdown_eight():
    # CD8=b20 close84; b21/22 pause. b27 close89 qualifies but low88 > 84.
    closes = BUY + [90, 89, 88, 87, 86, 85, 84, 94, 94, 93, 92, 91, 90, 89, 83]
    pending = evaluate_demark(dataset(closes[:-1])).sequences[0]
    assert pending.countdown_status == "count13_unqualified"
    assert pending.countdown_count == 12
    assert len(pending.countdown_bars) == 12
    assert pending.qualified_at is None
    done = evaluate_demark(dataset(closes)).sequences[0]
    assert done.countdown_status == "qualified13"
    assert done.countdown_bars[-1].revision_id == "b28"


def test_tdst_cancels_before_countdown_and_keeps_history():
    result = evaluate_demark(dataset(BUY + [106, 107]))
    seq = result.sequences[0]
    # b14 low=105 but true low=min(105,previous close91)=91: no cancellation.
    # b15 true low=106 > TDST104: cancellation.
    assert seq.countdown_status == "cancelled"
    assert seq.tdst_breached_at == START + timedelta(hours=16)
    assert [e.bar.revision_id for e in result.events if e.reason == "tdst_breach"] == ["b15"]


def test_opposite_setup_completion_cancels_old_countdown():
    closes = BUY + [92, 92, 94, 95, 96, 97, 98, 99, 100, 101, 102]
    result = evaluate_demark(dataset(closes))
    buy = result.sequences[0]
    sell = next(s for s in result.sequences if s.side == "sell")
    assert sell.setup_bars[0].revision_id == "b16"
    assert sell.setup_count == 9
    assert buy.countdown_status == "cancelled"
    assert [e.reason for e in result.events if e.kind == "cancelled"] == [
        "opposite_setup_completed"
    ]


def test_only_a_subsequent_setup_twenty_two_recycles_an_older_countdown():
    closes = BUY + list(range(90, 77, -1))
    result = evaluate_demark(dataset(closes, lows=[c - 10 for c in closes]))
    assert not any(e.kind == "recycled" for e in result.events)
    # New Buy run begins at b18. Its first-nine range22 < old range23,
    # so range recycling does not fire; it reaches22 at b39.
    closes = BUY + [95, 96, 97, 98] + list(range(94, 72, -1))
    result = evaluate_demark(dataset(closes, lows=[c - 10 for c in closes]))
    events = [e for e in result.events if e.kind == "recycled"]
    assert len(events) == 1
    assert events[0].reason == "subsequent_setup_extended_to_22"
    assert events[0].bar.revision_id == "b39"


def test_gap_loses_continuity_without_faking_a_cancellation():
    data = dataset(BUY + [90, 89, 88])
    data = data.model_copy(update={"bars": data.bars[:14] + data.bars[15:]})
    result = evaluate_demark(data)
    seq = result.sequences[0]
    assert result.history_status == "gapped"
    assert result.status == "unavailable"
    assert seq.continuity == "lost"
    assert seq.countdown_count == 1
    assert any(e.kind == "continuity_lost" for e in result.events)


def test_public_interface_rejects_order_duplicates_and_future_versions():
    import pytest

    data = dataset(BUY)
    for bars in (data.bars[::-1], data.bars + data.bars[-1:]):
        with pytest.raises(ValueError):
            evaluate_demark(data.model_copy(update={"bars": bars}))
    with pytest.raises(ValueError):
        evaluate_demark(data.model_copy(update={"knowledge_at": START}))


def test_risk_uses_countdown_span_and_invalidation_does_not_erase_thirteen():
    closes = BUY + list(range(90, 78, -1))
    seq = evaluate_demark(dataset(closes)).sequences[0]
    assert seq.risk_level == "76"  # b25 true low78 - true range2.
    assert seq.risk_source.revision_id == "b25"
    assert seq.risk_status == "valid"
    result = evaluate_demark(dataset(closes + [75]))
    seq = result.sequences[0]
    assert seq.risk_status == "invalidated"
    assert seq.countdown_status == "qualified13"
    assert result.qualified13_count == 1
    assert seq.bars_since_qualified13 == 1


def test_expiry_is_explicit_and_never_defaults_to_twenty_four_bars():
    closes = BUY + list(range(90, 78, -1)) + [80] * 25
    assert evaluate_demark(dataset(closes)).sequences[0].risk_status == "valid"
    expired = evaluate_demark(dataset(closes), DemarkConfig(validity_bars=3))
    assert expired.sequences[0].risk_status == "expired"
    assert next(e for e in expired.events if e.kind == "expired").bar.revision_id == "b28"


def test_equal_previous_comparison_allows_flip_but_equal_current_breaks_setup():
    # b4==b0 counts as the pre-flip comparison; b5<b1 starts Buy Setup.
    result = evaluate_demark(dataset([100, 101, 102, 103, 100, 99]))
    assert result.sequences[0].setup_bars[0].revision_id == "b5"
    interrupted = evaluate_demark(dataset([100, 101, 102, 103, 100, 99, 102]))
    assert interrupted.sequences[0].setup_status == "interrupted"


def test_perfection_equal_extreme_waits_for_a_strict_break():
    lows = [c - 1 for c in BUY]
    lows[10] = lows[11] = lows[12] = lows[13] = 89
    pending = evaluate_demark(dataset(BUY, lows=lows)).sequences[0]
    assert pending.setup_perfected is False
    done = evaluate_demark(dataset(BUY + [90], lows=lows + [88])).sequences[0]
    assert done.setup_perfected is True
    assert done.perfected_at == START + timedelta(hours=15)


def test_sell_case_has_symmetric_counts_but_opposite_price_boundaries():
    # Reflect the hand-worked Buy path around 100, including OHLC extremes.
    closes = [200 - c for c in BUY + list(range(90, 78, -1))]
    seq = evaluate_demark(dataset(closes)).sequences[0]
    assert seq.side == "sell"
    assert seq.setup_bars[-1].revision_id == "b13"
    assert seq.countdown_bar8.close == "116"
    assert seq.countdown_bars[-1].revision_id == "b25"
    assert seq.tdst == "96"
    assert seq.risk_level == "124"


def test_streaming_and_replay_are_equivalent_without_rewriting_events():
    from wheelhouse_service.indicators.demark import SequentialSession

    data = dataset(BUY + list(range(90, 78, -1)) + [75, 80])
    session = SequentialSession(STREAM, market_at=data.market_at, knowledge_at=data.knowledge_at)
    previous_events = []
    for i, bar in enumerate(data.bars):
        session.advance(bar)
        result = session.result()
        assert result == evaluate_demark(data.model_copy(update={"bars": data.bars[: i + 1]}))
        assert result.events[: len(previous_events)] == previous_events
        previous_events = result.events


def test_range_recycling_includes_both_endpoints_but_not_above_two_hundred_percent():
    closes = BUY + [95, 96, 97, 98] + list(range(94, 85, -1))
    for high, recycled in [(99, True), (113, True), (114, False)]:
        highs = [c + 1 for c in closes]
        highs[18] = high
        result = evaluate_demark(dataset(closes, highs=highs))
        first = result.sequences[0]
        assert (first.countdown_status == "recycled") is recycled
        if recycled:
            event = next(e for e in result.events if e.kind == "recycled")
            assert event.bar.revision_id == "b26"
            assert event.reason == "same_side_setup_range_100_to_200_percent"


def test_risk_includes_uncounted_bars_and_uses_earliest_tied_extreme():
    closes = BUY + [90, 89, 88, 87, 86, 85, 84, 94, 94, 93, 92, 91, 90, 89, 83]
    lows = [c - 1 for c in closes]
    lows[21] = lows[22] = 70
    result = evaluate_demark(dataset(closes, lows=lows))
    # Wide lows delay CD9, so continue until thirteen accepted bars exist.
    result = evaluate_demark(dataset(closes + [82, 81], lows=lows + [81, 80]))
    seq = result.sequences[0]
    assert seq.countdown_status == "qualified13"
    assert "b21" not in [b.revision_id for b in seq.countdown_bars]
    assert seq.risk_source.revision_id == "b21"
    assert seq.risk_level == "45"


def test_decimal_equality_forming_exclusion_and_config_validation():
    from decimal import Decimal, localcontext

    import pytest

    data = dataset([Decimal(c) + Decimal("0.000000000000000001") for c in BUY])
    with localcontext() as context:
        context.prec = 6
        small_context = evaluate_demark(data)
    assert small_context == evaluate_demark(data)
    forming = data.bars[-1].model_copy(
        update={"bar": data.bars[-1].bar.model_copy(update={"is_closed": False})}
    )
    assert evaluate_demark(data.model_copy(update={"forming": [forming]})) == evaluate_demark(data)
    with pytest.raises(ValueError):
        evaluate_demark(data.model_copy(update={"bars": data.bars[:-1] + [forming]}))
    with pytest.raises(ValueError):
        DemarkConfig(variant="combo")


def test_gap_stops_delayed_perfection_even_after_risk_has_failed():
    closes = BUY + list(range(90, 77, -1)) + [74] + [79] * 7
    lows = [c - 1 for c in closes]
    lows[10] = lows[11] = 1
    lows[-1] = 0.5
    data = dataset(closes, lows=lows)
    data = data.model_copy(update={"bars": data.bars[:28] + data.bars[29:]})
    result = evaluate_demark(data)
    seq = result.sequences[0]
    assert seq.countdown_status == "qualified13"
    assert seq.risk_status == "invalidated"
    assert seq.continuity == "lost"
    assert seq.perfected_at is None


def test_qualification_equality_counts_but_risk_equality_does_not_invalidate():
    closes = BUY + [90, 89, 88, 87, 86, 85, 84, 94, 94, 93, 92, 91, 90, 89, 85]
    seq = evaluate_demark(dataset(closes)).sequences[0]
    assert seq.countdown_status == "qualified13"  # Final low84 == CD8 close84.
    ordinary = BUY + list(range(90, 78, -1))
    equal = evaluate_demark(dataset(ordinary + [76])).sequences[0]
    assert equal.risk_level == "76"
    assert equal.risk_status == "valid"


def test_explicit_close_and_true_extreme_breach_policies_differ_on_gaps():
    close_only = evaluate_demark(dataset(BUY + [106]), DemarkConfig(tdst_breach="close"))
    assert close_only.sequences[0].countdown_status == "cancelled"
    assert evaluate_demark(dataset(BUY + [106])).sequences[0].countdown_status == "active"
    ordinary = BUY + list(range(90, 78, -1))
    first = evaluate_demark(dataset(ordinary + [75]), DemarkConfig(risk_breach="true_extreme"))
    assert first.sequences[0].risk_status == "valid"  # Previous close79 holds true high above76.
    second = evaluate_demark(dataset(ordinary + [75, 74]), DemarkConfig(risk_breach="true_extreme"))
    assert second.sequences[0].risk_status == "invalidated"
