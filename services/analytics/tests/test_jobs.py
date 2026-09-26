from datetime import timedelta

import pytest
from test_data import START, STREAM, batch

from wheelhouse_service.market import JobRequest
from wheelhouse_service.repository import Repository
from wheelhouse_service.runtime import Runtime


def test_checkpoint_resumes_after_expired_lease_without_refetch(tmp_path):
    repo = Repository(tmp_path / "jobs.sqlite")
    at = START + timedelta(hours=4)
    request = JobRequest(stream=STREAM)
    job = repo.enqueue(request, "refresh-1", now=at)
    assert repo.enqueue(request, "refresh-1", now=at).job_id == job.job_id
    claim = repo.claim(now=at, lease_seconds=30)
    assert claim is not None
    batch_id = repo.ingest(batch())
    repo.checkpoint(claim, batch_id, now=at)
    reopened = Repository(tmp_path / "jobs.sqlite")

    def unavailable_provider(stream, now):
        pytest.fail("Persisted checkpoint must be used after restart")

    runtime = Runtime(reopened, fetch=unavailable_provider)
    assert runtime.run_once(now=at + timedelta(seconds=31)) is True
    done = reopened.job(job.job_id)
    assert done.state == "succeeded"
    assert done.attempts == 2
    assert reopened.snapshot(done.snapshot_id).bars[-1].bar.close == "102"
    assert any(e.reason == "lease_recovered" for e in reopened.job_events(job.job_id))


def test_retry_backoff_is_bounded_and_keeps_previous_snapshot(tmp_path):
    from wheelhouse_service.sources import FetchError

    repo = Repository(tmp_path / "jobs.sqlite")
    at = START + timedelta(hours=4)
    success = Runtime(repo, fetch=lambda stream, now: batch(fetched=now))
    good = repo.enqueue(JobRequest(stream=STREAM), "good", now=at)
    success.run_once(now=at)
    saved = repo.job(good.job_id).snapshot_id

    def outage(stream, now):
        raise FetchError("provider_unavailable")

    runtime = Runtime(repo, fetch=outage)
    bad = repo.enqueue(JobRequest(stream=STREAM), "outage", now=at)
    runtime.run_once(now=at)
    assert repo.job(bad.job_id).state == "retry_wait"
    assert runtime.run_once(now=at + timedelta(seconds=1)) is False
    runtime.run_once(now=at + timedelta(seconds=2))
    runtime.run_once(now=at + timedelta(seconds=6))
    assert repo.job(bad.job_id).state == "failed"
    assert repo.job(bad.job_id).attempts == 3
    assert repo.live_snapshot(STREAM).snapshot_id == saved
    assert repo.stats().snapshots == 1


def test_schedules_survive_restart_and_coalesce_missed_intervals(tmp_path):
    from wheelhouse_service.market import ScheduleRequest

    repo = Repository(tmp_path / "jobs.sqlite")
    at = START + timedelta(hours=4)
    repo.set_schedule(ScheduleRequest(stream=STREAM, enabled=True), now=at)
    later = START + timedelta(hours=10, seconds=3)
    restarted = Repository(tmp_path / "jobs.sqlite")
    assert restarted.dispatch_due(now=later) == 1
    assert restarted.dispatch_due(now=later) == 0
    assert restarted.schedule(STREAM).next_due == START + timedelta(hours=11, seconds=2)
    with pytest.raises(ValueError, match="another request"):
        request = JobRequest(stream=STREAM)
        restarted.enqueue(request, "same", now=at)
        restarted.enqueue(request.model_copy(update={"kind": "analyze"}), "same", now=at)


def test_expired_owner_cannot_complete_or_overwrite_new_owner(tmp_path):
    from wheelhouse_service.repository import LeaseLost

    repo = Repository(tmp_path / "jobs.sqlite")
    at = START + timedelta(hours=4)
    repo.enqueue(JobRequest(stream=STREAM), "one", now=at)
    first = repo.claim(now=at, lease_seconds=1)
    assert repo.claim(now=at) is None
    second = repo.claim(now=at + timedelta(seconds=2))
    assert first.token != second.token
    with pytest.raises(LeaseLost):
        repo.fail(first, now=at + timedelta(seconds=2), code="old_owner", retryable=False)
    assert repo.job(first.job.job_id).state == "running"


def test_older_checkpoint_finishing_last_cannot_replace_newer_current_data(tmp_path):
    from wheelhouse_service.calculation import calculate
    from wheelhouse_service.market import Rules

    repo = Repository(tmp_path / "ordered.sqlite")
    at = START + timedelta(hours=4)
    old_job = repo.enqueue(JobRequest(stream=STREAM), "old", now=at)
    old = repo.claim(now=at, lease_seconds=100)
    old_batch = repo.ingest(batch((100,), at))
    repo.checkpoint(old, old_batch, now=at)
    newer = at + timedelta(seconds=10)
    new_job = repo.enqueue(JobRequest(stream=STREAM), "new", now=newer)
    new = repo.claim(now=newer, lease_seconds=100)
    new_batch = repo.ingest(batch((110,), newer))
    repo.checkpoint(new, new_batch, now=newer)
    new_result = calculate(repo.read(STREAM, market_at=newer, knowledge_at=newer), Rules())
    repo.complete(new, new_result, now=newer)
    old_result = calculate(repo.read(STREAM, market_at=at, knowledge_at=at), Rules())
    repo.complete(old, old_result, now=newer + timedelta(seconds=1))
    assert repo.job(old_job.job_id).state == repo.job(new_job.job_id).state == "succeeded"
    assert repo.live_snapshot(STREAM).bars[-1].bar.close == "110"


def test_historical_query_does_not_hide_the_latest_provider_failure(tmp_path):
    from wheelhouse_service.sources import FetchError

    repo = Repository(tmp_path / "provider-state.sqlite")
    at = START + timedelta(hours=4)

    def outage(stream, now):
        raise FetchError("provider_unavailable", retryable=False)

    failed = repo.enqueue(JobRequest(stream=STREAM), "refresh-failed", now=at)
    worker = Runtime(repo, fetch=outage)
    worker.run_once(now=at)
    replay = repo.enqueue(
        JobRequest(kind="analyze", stream=STREAM, market_at=at, knowledge_at=at),
        "historical",
        now=at + timedelta(seconds=1),
    )
    worker.run_once(now=at + timedelta(seconds=1))
    assert repo.latest_job(STREAM).job_id == replay.job_id
    provider = repo.latest_job(STREAM, refresh_only=True)
    assert provider.job_id == failed.job_id
    assert provider.error_code == "provider_unavailable"
