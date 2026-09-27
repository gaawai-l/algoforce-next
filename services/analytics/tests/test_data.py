from datetime import UTC, datetime, timedelta

from wheelhouse_service.market import Bar, Batch, Stream
from wheelhouse_service.repository import Repository

START = datetime(2026, 9, 1, tzinfo=UTC)
STREAM = Stream(source="fixture", symbol="BTCUSDT", timeframe="1h")


def batch(prices=(100, 101, 102), fetched=None):
    at = fetched or START + timedelta(hours=4)
    return Batch(
        stream=STREAM,
        fetched_at=at,
        raw_payload={"sanitized": True},
        bars=[
            Bar(
                open_time=START + timedelta(hours=i),
                close_time=START + timedelta(hours=i + 1),
                open=str(p),
                high=str(p + 1),
                low=str(p - 1),
                close=str(p),
                volume=None,
                is_closed=True,
            )
            for i, p in enumerate(prices)
        ],
    )


def test_repeated_import_is_idempotent_but_corrections_retain_prior_knowledge(tmp_path):
    repo = Repository(tmp_path / "analytics.sqlite")
    original = batch()
    first = repo.ingest(original)
    assert repo.ingest(original) == first
    assert repo.stats().revisions == 3
    correction = batch((100, 101, 105), START + timedelta(hours=5))
    repo.ingest(correction)
    assert repo.stats().revisions == 4
    old = repo.read(STREAM, market_at=START + timedelta(hours=3), knowledge_at=original.fetched_at)
    new = repo.read(
        STREAM, market_at=START + timedelta(hours=3), knowledge_at=correction.fetched_at
    )
    assert old.bars[-1].bar.close == "102"
    assert new.bars[-1].bar.close == "105"
    assert old.bars[-1].revision_id != new.bars[-1].revision_id
    assert repo.batch(first).raw_payload == {"sanitized": True}
    reopened = Repository(tmp_path / "analytics.sqlite")
    assert reopened.stats().revisions == 4


def test_forming_bar_missing_volume_and_conflicting_batch_are_explicit(tmp_path):
    import pytest

    repo = Repository(tmp_path / "data.sqlite")
    closed = batch((100, 101))
    forming = Bar(
        open_time=START + timedelta(hours=4),
        close_time=START + timedelta(hours=5),
        open="102",
        high="103",
        low="101",
        close="102",
        is_closed=False,
    )
    capture = closed.model_copy(update={"bars": closed.bars + [forming]})
    repo.ingest(capture)
    selected = repo.read(
        STREAM, market_at=START + timedelta(hours=4, minutes=10), knowledge_at=capture.fetched_at
    )
    assert len(selected.bars) == 2
    assert selected.bars[0].bar.volume is None
    assert len(selected.forming) == 1
    changed = closed.bars[0].model_copy(update={"close": "100.5"})
    with pytest.raises(ValueError, match="Conflicting duplicates"):
        Batch(
            stream=STREAM,
            fetched_at=closed.fetched_at,
            raw_payload={},
            bars=[closed.bars[0], changed],
        )
    assert repo.stats().revisions == 3


def test_database_upgrades_from_first_migration_and_preserves_data(tmp_path):
    import sqlite3

    from wheelhouse_service.market import digest
    from wheelhouse_service.repository import MIGRATIONS

    path = tmp_path / "old.sqlite"
    sql = (MIGRATIONS / "001_market.sql").read_text()
    with sqlite3.connect(path) as db:
        db.executescript(sql)
        db.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)"
        )
        db.execute("INSERT INTO schema_migrations VALUES (1, ?)", (digest(sql),))
        db.execute(
            "INSERT INTO batches VALUES ('legacy', ?, ?, ?)",
            (STREAM.key, START.isoformat(), batch().model_dump_json()),
        )
    upgraded = Repository(path)
    assert upgraded.stats().schema_version == 3
    assert upgraded.batch("legacy").bars[0].close == "100"
    assert Repository(path).stats().batches == 1


def test_full_decimal_precision_and_last_digit_corrections_are_preserved(tmp_path):
    repo = Repository(tmp_path / "precise.sqlite")
    original = Bar(
        open_time=START,
        close_time=START + timedelta(hours=1),
        open="123456789012345678.123456789012345678",
        high="123456789012345679",
        low="123456789012345677",
        close="123456789012345678.123456789012345678",
        is_closed=True,
    )
    assert original.close == "123456789012345678.123456789012345678"
    repo.ingest(
        Batch(stream=STREAM, fetched_at=START + timedelta(hours=2), bars=[original], raw_payload={})
    )
    changed = Bar.model_validate(
        {**original.model_dump(), "close": "123456789012345678.123456789012345679"}
    )
    repo.ingest(
        Batch(stream=STREAM, fetched_at=START + timedelta(hours=3), bars=[changed], raw_payload={})
    )
    assert repo.stats().revisions == 2


def test_out_of_order_correction_cannot_override_a_later_identical_observation(tmp_path):
    import pytest

    repo = Repository(tmp_path / "history.sqlite")
    repo.ingest(batch((100,), START + timedelta(hours=2)))
    repo.ingest(batch((100,), START + timedelta(hours=4)))
    with pytest.raises(ValueError, match="observation"):
        repo.ingest(batch((200,), START + timedelta(hours=3)))
    view = repo.read(
        STREAM, market_at=START + timedelta(hours=4), knowledge_at=START + timedelta(hours=4)
    )
    assert view.bars[0].bar.close == "100"
    assert repo.stats().batches == 2


def test_same_timestamp_conflict_after_repeated_observation_is_rejected(tmp_path):
    import pytest

    repo = Repository(tmp_path / "same-time.sqlite")
    at = START + timedelta(hours=4)
    repo.ingest(batch((100,), START + timedelta(hours=2)))
    repeated = batch((100,), at)
    repo.ingest(repeated)
    assert repo.ingest(repeated)
    with pytest.raises(ValueError, match="same acquisition"):
        repo.ingest(batch((200,), at))
    assert repo.stats().revisions == 1
