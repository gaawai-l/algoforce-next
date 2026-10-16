"""A user-exported market-data fixture; not an account or trading record."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from wheelhouse_service.indicators.demark import DemarkConfig, evaluate_demark
from wheelhouse_service.market import Bar, Dataset, StoredBar, Stream

FIXTURES = Path(__file__).parent / "fixtures"


def exported_input():
    candles = json.loads(
        (FIXTURES / "tradingsignal-btcusdt-15m-candles.json").read_text(), parse_float=Decimal
    )["candles"]
    # This retrospective algorithm fixture explicitly treats all exported rows
    # as observations. It does NOT certify the export's final row as closed live.
    end = datetime.fromtimestamp(candles[-1]["t"] + 900, UTC)
    bars = [
        StoredBar(
            revision_id=f"export:{c['t']}",
            revision=1,
            fetched_at=end,
            bar=Bar(
                open_time=datetime.fromtimestamp(c["t"], UTC),
                close_time=datetime.fromtimestamp(c["t"] + 900, UTC),
                open=str(c["o"]),
                high=str(c["h"]),
                low=str(c["l"]),
                close=str(c["c"]),
                volume=str(c["v"]),
                is_closed=True,
            ),
        )
        for c in candles
    ]
    return Dataset(
        stream=Stream(source="fixture", symbol="BTCUSDT", timeframe="15m"),
        market_at=end,
        knowledge_at=end,
        fetched_at=end,
        bars=bars,
        forming=[],
    )


def reference():
    return json.loads(
        (FIXTURES / "tradingsignal-btcusdt-15m-result.json").read_text(), parse_float=Decimal
    )["result"]


def test_exported_setup_countdown_and_thirteen_have_no_missing_or_extra_events():
    result = evaluate_demark(
        exported_input(),
        DemarkConfig(
            ruleset_version="wheelhouse-sequential-2",
            same_side_policy="retain_active",
            perfection_policy="strict_at_nine",
        ),
    )
    kinds = {
        "setup_count": "setup",
        "countdown_count": "countdown",
        "qualified13": "countdown_13",
        "deferred13": "countdown_def",
        "perfected": "setup_perfected",
        "recycled": "recycle",
    }
    local = set()
    for e in result.events:
        if e.kind == "cancelled":
            kind = "cancel_opp" if e.reason == "opposite_setup_completed" else "cancel_tdst"
        elif e.kind in kinds:
            if e.kind == "countdown_count" and e.count == 13:
                continue  # Provider represents the accepted 13 only as countdown_13.
            kind = kinds[e.kind]
        else:
            continue
        label = str(e.count) if kind in ("setup", "countdown") else kind
        local.add((int(e.bar.open_time.timestamp()), e.side.upper(), kind, label))
    expected = {
        (
            m["ts"],
            m["side"],
            m["kind"],
            m["label"] if m["kind"] in ("setup", "countdown") else m["kind"],
        )
        for m in reference()["markers"]
    }
    assert local == expected
    assert result.qualified13_count == 4


def test_exported_thirteen_risk_levels_and_stop_times_match():
    data = exported_input()
    result = evaluate_demark(
        data,
        DemarkConfig(
            ruleset_version="wheelhouse-sequential-2",
            same_side_policy="retain_active",
            perfection_policy="strict_at_nine",
        ),
    )
    actual = [s for s in result.sequences if s.qualified_at]
    expected = reference()["qualified13s"]
    assert len(actual) == len(expected) == 4
    for seq, expected13 in zip(actual, expected, strict=True):
        assert int(seq.countdown_bars[-1].open_time.timestamp()) == expected13["ts"]
        assert seq.side.upper() == expected13["side"]
        # Reference JSON uses binary floats; tolerate only representation noise.
        assert abs(Decimal(seq.risk_level) - expected13["riskLevel"]) < Decimal("0.00000001")
        ended = next(
            (
                e
                for e in result.events
                if e.sequence_id == seq.sequence_id and e.kind == "invalidated"
            ),
            None,
        )
        assert (int(ended.bar.open_time.timestamp()) if ended else None) == expected13["stoppedTs"]
    assert result.sequences[-1].setup_count == reference()["setupCount"]["BUY"] == 6
    assert (
        Decimal(result.sequences[-1].next_conditions[0].threshold)
        == reference()["snapshot"]["nextBarNeeds"]["price"]
    )


def test_closed_prefix_matches_reference_without_promoting_forming_bar():
    data = exported_input()
    closed = data.model_copy(
        update={"bars": data.bars[:-1], "market_at": data.bars[-1].bar.open_time}
    )
    result = evaluate_demark(
        closed,
        DemarkConfig(
            ruleset_version="wheelhouse-sequential-2",
            same_side_policy="retain_active",
            perfection_policy="strict_at_nine",
        ),
    )
    assert result.sequences[-1].side == "buy"
    assert result.sequences[-1].setup_count == 5
    assert result.qualified13_count == 4
    assert all(e.bar.close_time <= closed.market_at for e in result.events)
    assert result.history_end == closed.market_at
    assert reference()["setupCount"]["BUY"] == 6


def test_completed_setup_tdst_and_bar_evidence_match_reference():
    data = exported_input()
    result = evaluate_demark(
        data,
        DemarkConfig(
            ruleset_version="wheelhouse-sequential-2",
            same_side_policy="retain_active",
            perfection_policy="strict_at_nine",
        ),
    )
    for side in ("buy", "sell"):
        last = next(
            s
            for s in reversed(result.sequences)
            if s.side == side and s.setup_status == "completed"
        )
        expected = reference()["lastCompletedSetup"][side.upper()]
        assert Decimal(last.tdst) == expected["tdst"]
        assert [int(b.open_time.timestamp()) for b in last.setup_bars] == [
            int(data.bars[i].bar.open_time.timestamp()) for i in expected["barIdxs"]
        ]
        assert last.setup_perfected == expected["perfected"]


def test_retained_countdown_hands_over_when_later_setup_reaches_twenty_two():
    from test_sequential import BUY, dataset

    closes = BUY + [95, 96, 97, 98] + list(range(94, 72, -1))
    config = DemarkConfig(
        ruleset_version="wheelhouse-sequential-2",
        same_side_policy="retain_active",
        perfection_policy="strict_at_nine",
    )
    result = evaluate_demark(dataset(closes, lows=[c - 10 for c in closes]), config)
    assert result.sequences[0].countdown_status == "recycled"
    replacement = next(s for s in result.sequences if s.setup_bars[0].revision_id == "b18")
    assert replacement.countdown_status == "active"
    assert replacement.countdown_count == 0
