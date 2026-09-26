from datetime import UTC, datetime, timedelta

from wheelhouse_service.portfolio.models import PortfolioCapture, SyncRequest
from wheelhouse_service.portfolio.store import PortfolioStore
from wheelhouse_service.portfolio.sync import BrokerSync

NOW = datetime(2026, 9, 25, tzinfo=UTC)
REQUEST = SyncRequest(account_id="17", start=NOW.date() - timedelta(days=2), end=NOW.date())


class Reader:
    def __init__(self):
        self.batches = []

    def sync(self, request, *, include_fees=True):
        assert not include_fees
        return PortfolioCapture(
            source="moomoo",
            account_id="17",
            captured_at=NOW,
            positions=[],
            instruments=[],
            quotes=[],
            fx=[],
            errors={},
            raw={"deals": [{"deal_id": str(i), "order_id": str(i)} for i in range(45)]},
        )

    def fees(self, account, ids):
        assert account == "17" and len(ids) <= 20
        self.batches.append(ids)
        return [{"order_id": i, "fee_amount": 1} for i in ids]


def test_all_fee_batches_are_persisted_and_resume_after_recreating_worker(tmp_path):
    store = PortfolioStore(tmp_path / "portfolio.sqlite")
    reader = Reader()
    sync = BrokerSync(store, reader)
    job = sync.submit(REQUEST, "first", now=NOW)
    assert sync.submit(REQUEST, "first", now=NOW).job_id == job.job_id
    sync.run_once(now=NOW)
    assert store.capture("moomoo", "17") is not None
    sync.run_once(now=NOW + timedelta(seconds=1))
    assert sync.job(job.job_id).completed_orders == 20
    restarted = BrokerSync(PortfolioStore(store.path), reader)
    assert restarted.run_once(now=NOW + timedelta(seconds=2)) is False
    restarted.run_once(now=NOW + timedelta(seconds=5))
    restarted.run_once(now=NOW + timedelta(seconds=9))
    final = restarted.job(job.job_id)
    assert final.state == "succeeded"
    assert final.completed_orders == 45
    assert [len(ids) for ids in reader.batches] == [20, 20, 5]
    assert len([r for r in store.records("moomoo", "17") if r["kind"] == "fees"]) == 45


def test_missing_fee_row_is_partial_and_does_not_fabricate_zero(tmp_path):
    class MissingReader(Reader):
        def fees(self, account, ids):
            return [{"order_id": i, "fee_amount": 1} for i in ids if i != "3"]

    store = PortfolioStore(tmp_path / "partial.sqlite")
    sync = BrokerSync(store, MissingReader())
    job = sync.submit(REQUEST, "missing", now=NOW)
    for seconds in (0, 1, 5, 9):
        sync.run_once(now=NOW + timedelta(seconds=seconds))
    assert sync.job(job.job_id).state == "partial"
    assert sync.job(job.job_id).completed_orders == 44
    assert sync.job(job.job_id).missing_orders == 1
    capture = store.capture("moomoo", "17")
    assert capture.raw["_coverage"]["fees"]["missing_order_ids"] == ["3"]
    assert capture.raw["_coverage"]["fees"]["query_complete"] is False
    assert "fees" in capture.errors


def test_retry_resumes_only_failed_batch_and_preserves_successful_snapshot(tmp_path):
    from wheelhouse_service.portfolio.broker import BrokerUnavailable

    class FlakyReader(Reader):
        def fees(self, account, ids):
            if not self.batches:
                self.batches.append(ids)
                raise BrokerUnavailable("offline")
            return super().fees(account, ids)

    store = PortfolioStore(tmp_path / "retry.sqlite")
    reader = FlakyReader()
    sync = BrokerSync(store, reader)
    job = sync.submit(REQUEST, "retry", now=NOW)
    sync.run_once(now=NOW)
    sync.run_once(now=NOW + timedelta(seconds=1))
    assert sync.job(job.job_id).state == "retry_wait"
    assert store.capture("moomoo", "17").raw["_coverage"]["fees"]["pending_orders"] == 45
    sync.run_once(now=NOW + timedelta(seconds=6))
    assert sync.job(job.job_id).completed_orders == 20
    assert reader.batches[0] == reader.batches[1]


def test_batch_checkpoint_and_capture_are_atomic_when_publication_fails(tmp_path):
    class UnwritableStore(PortfolioStore):
        def ingest(self, capture, *, transaction=None):
            if capture.raw.get("fees"):
                raise OSError("Simulated full disk")
            return super().ingest(capture, transaction=transaction)

    store = UnwritableStore(tmp_path / "atomic.sqlite")
    sync = BrokerSync(store, Reader())
    job = sync.submit(REQUEST, "atomic", now=NOW)
    sync.run_once(now=NOW)
    sync.run_once(now=NOW + timedelta(seconds=1))
    assert sync.job(job.job_id).state == "retry_wait"
    assert sync.job(job.job_id).completed_orders == 0
    assert not store.capture("moomoo", "17").raw.get("fees")


def test_expired_worker_cannot_overwrite_the_recovered_batch(tmp_path):
    store = PortfolioStore(tmp_path / "lease.sqlite")
    recovered = BrokerSync(store, Reader())

    class StalledReader(Reader):
        def fees(self, account, ids):
            assert recovered.run_once(now=NOW + timedelta(seconds=100)) is True
            return [{"order_id": i, "fee_amount": 999} for i in ids]

    original = BrokerSync(store, StalledReader())
    job = original.submit(REQUEST, "lease", now=NOW)
    original.run_once(now=NOW)
    original.run_once(now=NOW + timedelta(seconds=1))
    assert recovered.job(job.job_id).completed_orders == 20
    assert all(row["fee_amount"] == 1 for row in store.capture("moomoo", "17").raw["fees"])


def test_null_fee_and_missing_order_identity_never_count_as_complete(tmp_path):
    class IncompleteReader(Reader):
        def sync(self, request, *, include_fees=True):
            capture = super().sync(request, include_fees=include_fees)
            return capture.model_copy(
                update={
                    "raw": {"deals": [{"deal_id": "unknown"}, {"deal_id": "one", "order_id": "1"}]}
                }
            )

        def fees(self, account, ids):
            return [{"order_id": "1", "fee_amount": None}]

    store = PortfolioStore(tmp_path / "incomplete.sqlite")
    sync = BrokerSync(store, IncompleteReader())
    job = sync.submit(REQUEST, "incomplete", now=NOW)
    sync.run_once(now=NOW)
    sync.run_once(now=NOW + timedelta(seconds=1))
    result = sync.job(job.job_id)
    assert result.state == "partial"
    assert result.completed_orders == 0
    assert result.missing_orders == 1
    assert store.capture("moomoo", "17").raw["_coverage"]["fees"]["unidentified_executions"] == 1


def test_sync_http_returns_a_durable_job_instead_of_blocking_until_fees_finish(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from wheelhouse_service.portfolio.api import create_router

    class ConnectedReader(Reader):
        def status(self):
            return {"gateway_reachable": True, "sdk_installed": True}

    path = tmp_path / "http.sqlite"
    reader = ConnectedReader()
    app = FastAPI()
    app.include_router(create_router(path, reader, start_worker=False))
    with TestClient(app) as client:
        prefix = "/api/wheelhouse/v1/portfolio"
        response = client.post(
            prefix + "/sync",
            json=REQUEST.model_dump(mode="json"),
            headers={"Idempotency-Key": "http-test"},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        sync = BrokerSync(PortfolioStore(path), reader)
        sync.run_once()
        status = client.get(prefix + "/sync-jobs/" + job_id).json()
        assert status["phase"] == "fees"
        assert status["total_orders"] == 45
        assert (
            client.get(prefix + "/sync-status", params={"account_id": "17"}).json()["job_id"]
            == job_id
        )


def test_different_idempotency_keys_cannot_silently_alias_an_active_job(tmp_path):
    import pytest

    sync = BrokerSync(PortfolioStore(tmp_path / "keys.sqlite"), Reader())
    first = sync.submit(REQUEST, "a", now=NOW)
    with pytest.raises(ValueError, match="already active"):
        sync.submit(REQUEST, "b", now=NOW)
    assert sync.submit(REQUEST, "a", now=NOW).job_id == first.job_id


def test_next_day_fee_recovery_does_not_refresh_yesterdays_account_snapshot(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from wheelhouse_service.portfolio.api import create_router

    path = tmp_path / "stale.sqlite"
    store = PortfolioStore(path)
    sync = BrokerSync(store, Reader())
    sync.submit(REQUEST, "stale", now=NOW)
    sync.run_once(now=NOW)
    later = NOW + timedelta(days=1)
    for seconds in (0, 4, 8):
        sync.run_once(now=later + timedelta(seconds=seconds))
    capture = store.capture("moomoo", "17")
    assert capture.snapshot_observed_at == NOW
    assert capture.captured_at == later + timedelta(seconds=8)
    app = FastAPI()
    app.include_router(create_router(path, start_worker=False))
    with TestClient(app) as client:
        result = client.get(
            "/api/wheelhouse/v1/portfolio/workspace",
            params={"source": "moomoo", "account_id": "17"},
        ).json()
        assert result["state"] == "stale"


def test_legacy_fee_checkpoint_observation_time_is_frozen_before_resuming(tmp_path):
    import json

    store = PortfolioStore(tmp_path / "legacy-job.sqlite")
    sync = BrokerSync(store, Reader())
    job = sync.submit(REQUEST, "legacy-job", now=NOW)
    sync.run_once(now=NOW)
    with store.connection() as db:
        checkpoint = json.loads(
            db.execute("SELECT capture FROM broker_sync_jobs WHERE id=?", (job.job_id,)).fetchone()[
                0
            ]
        )
        checkpoint.pop("snapshot_observed_at")
        db.execute(
            "UPDATE broker_sync_jobs SET capture=? WHERE id=?", (json.dumps(checkpoint), job.job_id)
        )
    sync.run_once(now=NOW + timedelta(days=1))
    assert store.capture("moomoo", "17").snapshot_observed_at == NOW
