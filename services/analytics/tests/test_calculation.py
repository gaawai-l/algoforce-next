from datetime import timedelta

from test_data import START, STREAM, batch

from wheelhouse_service.calculation import calculate
from wheelhouse_service.market import Rules
from wheelhouse_service.repository import Repository


def test_calculation_has_explicit_warmup_and_prior_levels_without_future_bars(tmp_path):
    repo = Repository(tmp_path / "market.sqlite")
    repo.ingest(batch((100, 101, 102, 103), START + timedelta(hours=5)))
    view = repo.read(
        STREAM, market_at=START + timedelta(hours=4), knowledge_at=START + timedelta(hours=5)
    )
    result = calculate(view, Rules(window=3))
    assert result.points[0].sma is None
    assert result.points[2].sma == "101"
    assert result.points[3].sma == "102"
    assert result.points[3].prior_high == "103"
    assert result.points[3].prior_low == "99"
    assert result.warmup_complete is True
    assert result.mode == "retrospective"
    assert result.data_state == "simulated"
    assert calculate(view, Rules(window=3)) == result
    old = repo.read(
        STREAM, market_at=START + timedelta(hours=3), knowledge_at=START + timedelta(hours=5)
    )
    assert calculate(old, Rules(window=3)).points == result.points[:3]
    not_yet_known = repo.read(
        STREAM, market_at=START + timedelta(hours=3), knowledge_at=START + timedelta(hours=3)
    )
    assert calculate(not_yet_known, Rules()).data_state == "unavailable"


def test_gap_resets_warmup_and_old_snapshot_survives_correction(tmp_path):
    repo = Repository(tmp_path / "data.sqlite")
    capture = batch((100, 101, 102, 103, 104), START + timedelta(hours=6))
    repo.ingest(capture)
    at = START + timedelta(hours=5)
    original = calculate(
        repo.read(STREAM, market_at=at, knowledge_at=capture.fetched_at), Rules(window=2)
    )
    repo.save_snapshot(original, created_at=capture.fetched_at)
    repo.ingest(batch((100, 101, 102, 103, 109), START + timedelta(hours=7)))
    latest = calculate(
        repo.read(STREAM, market_at=at, knowledge_at=START + timedelta(hours=7)), Rules(window=2)
    )
    assert original.points[-1].sma == "103.5"
    assert latest.points[-1].sma == "106"
    assert repo.snapshot(original.snapshot_id) == original
    gap_repo = Repository(tmp_path / "gap.sqlite")
    gap_repo.ingest(capture.model_copy(update={"bars": capture.bars[:2] + capture.bars[3:]}))
    gap = calculate(
        gap_repo.read(STREAM, market_at=at, knowledge_at=capture.fetched_at), Rules(window=2)
    )
    assert gap.data_state == "unavailable"
    assert gap.points[2].sma is None
    assert gap.warmup_complete is False


def test_sma_precision_is_explicit_and_large_prices_are_not_truncated(tmp_path):
    from wheelhouse_service.market import Bar, Batch

    repo = Repository(tmp_path / "precision.sqlite")
    at = START + timedelta(hours=4)
    price = "123456789012345678.123456789012345678"
    bars = [
        Bar(
            open_time=START + timedelta(hours=i),
            close_time=START + timedelta(hours=i + 1),
            open=price,
            high="123456789012345679",
            low="123456789012345677",
            close=price,
            is_closed=True,
        )
        for i in range(3)
    ]
    repo.ingest(Batch(stream=STREAM, fetched_at=at, bars=bars, raw_payload={}))
    result = calculate(repo.read(STREAM, market_at=at, knowledge_at=at), Rules(window=2))
    assert result.points[-1].sma == price
    small = Repository(tmp_path / "rounding.sqlite")
    small.ingest(batch((10, 10, 11), at))
    rounded = calculate(small.read(STREAM, market_at=at, knowledge_at=at), Rules(window=3))
    assert rounded.points[-1].sma == "10.333333333333333333"
