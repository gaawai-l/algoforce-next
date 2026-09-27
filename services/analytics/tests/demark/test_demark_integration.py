"""DeMark through the same storage and calculation interface used by jobs."""

from datetime import timedelta

from test_sequential import BUY, START, STREAM, dataset

from wheelhouse_service.calculation import calculate
from wheelhouse_service.market import Analysis, Batch, Rules
from wheelhouse_service.repository import Repository


def test_demark_is_optional_and_old_snapshot_payloads_remain_readable(tmp_path):
    data = dataset(BUY + list(range(90, 78, -1)))
    baseline = calculate(data, Rules())
    old_json = baseline.model_dump(mode="json")
    old_json.pop("demark", None)
    old_json["rules"].pop("demark", None)
    assert Analysis.model_validate(old_json).demark is None
    result = calculate(data, Rules(demark={}))
    assert result.demark.qualified13_count == 1
    assert result.snapshot_id != baseline.snapshot_id
    assert result.points == baseline.points
    repo = Repository(tmp_path / "snap.sqlite")
    repo.save_snapshot(baseline, created_at=data.knowledge_at)
    repo.save_snapshot(result, created_at=data.knowledge_at)
    assert repo.snapshot(baseline.snapshot_id).demark is None
    assert repo.snapshot(result.snapshot_id) == result


def test_revisions_recalculate_without_changing_old_knowledge_or_snapshot(tmp_path):
    repo = Repository(tmp_path / "revision.sqlite")
    original = dataset(BUY)
    capture = Batch(
        stream=STREAM,
        fetched_at=original.knowledge_at,
        bars=[b.bar for b in original.bars],
        raw_payload={},
    )
    repo.ingest(capture)
    selected = repo.read(STREAM, market_at=original.market_at, knowledge_at=capture.fetched_at)
    first = calculate(selected, Rules(demark={}))
    assert first.demark.sequences[0].setup_count == 9
    repo.save_snapshot(first, created_at=capture.fetched_at)
    changed = dataset(BUY[:-1] + [100])
    later = capture.fetched_at + timedelta(hours=1)
    repo.ingest(
        Batch(stream=STREAM, fetched_at=later, bars=[b.bar for b in changed.bars], raw_payload={})
    )
    revised = calculate(
        repo.read(STREAM, market_at=original.market_at, knowledge_at=later), Rules(demark={})
    )
    assert revised.demark.sequences[0].setup_status == "interrupted"
    assert repo.snapshot(first.snapshot_id) == first
    assert (
        calculate(
            repo.read(STREAM, market_at=original.market_at, knowledge_at=capture.fetched_at),
            Rules(demark={}),
        )
        == first
    )


def test_http_and_restarted_checkpoint_deliver_real_demark_result(tmp_path):
    from fastapi.testclient import TestClient

    from wheelhouse_service.http import create_app
    from wheelhouse_service.market import JobRequest
    from wheelhouse_service.runtime import Runtime

    path = tmp_path / "http.sqlite"
    data = dataset(BUY + list(range(90, 78, -1)))
    now = data.knowledge_at
    repo = Repository(path)
    request = JobRequest(stream=STREAM, rules=Rules(demark={}))
    job = repo.enqueue(request, "td-checkpoint", now=now)
    claim = repo.claim(now=now, lease_seconds=1)
    capture = Batch(stream=STREAM, fetched_at=now, bars=[b.bar for b in data.bars], raw_payload={})
    repo.checkpoint(claim, repo.ingest(capture), now=now)

    def no_refetch(stream, now):
        raise AssertionError("Persisted batch must be reused")

    restarted = Repository(path)
    Runtime(restarted, fetch=no_refetch).run_once(now=now + timedelta(seconds=2))
    done = restarted.job(job.job_id)
    assert done.state == "succeeded"
    with TestClient(create_app(path, start_worker=False)) as client:
        response = client.get(f"/api/wheelhouse/v1/snapshots/{done.snapshot_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["demark"]["qualified13_count"] == 1
        assert payload["demark"]["sequences"][0]["risk_level"] == "76"
        assert (
            "demark_sequential_basic"
            in client.get("/api/wheelhouse/v1/status").json()["capabilities"]
        )
        invalid = client.post(
            "/api/wheelhouse/v1/jobs",
            json={"stream": STREAM.model_dump(), "rules": {"demark": {"variant": "combo"}}},
            headers={"Idempotency-Key": "combo"},
        )
        assert invalid.status_code == 422


def test_demark_jobs_read_all_stored_history_instead_of_a_rolling_thousand(tmp_path):
    from wheelhouse_service.market import JobRequest
    from wheelhouse_service.runtime import Runtime

    data = dataset(BUY + list(range(90, 78, -1)) + [80] * 1005)
    repo = Repository(tmp_path / "history.sqlite")
    capture = Batch(
        stream=STREAM, fetched_at=data.knowledge_at, bars=[b.bar for b in data.bars], raw_payload={}
    )
    repo.ingest(capture)
    job = repo.enqueue(
        JobRequest(
            kind="analyze",
            stream=STREAM,
            rules=Rules(demark={}),
            market_at=data.market_at,
            knowledge_at=data.knowledge_at,
        ),
        "full-history",
        now=data.knowledge_at,
    )
    Runtime(repo).run_once(now=data.knowledge_at)
    result = repo.snapshot(repo.job(job.job_id).snapshot_id)
    assert len(result.bars) == 1031
    assert result.demark.qualified13_count == 1
    assert result.demark.sequences[0].qualified_at == START + timedelta(hours=26)
    assert (
        len(repo.read(STREAM, market_at=data.market_at, knowledge_at=data.knowledge_at).bars)
        == 1000
    )
