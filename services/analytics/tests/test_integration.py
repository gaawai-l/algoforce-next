from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from wheelhouse_service.http import create_app
from wheelhouse_service.repository import Repository
from wheelhouse_service.runtime import Runtime
from wheelhouse_service.sources import FixtureSource

PREFIX = "/api/wheelhouse/v1"


def test_http_refresh_replay_and_restart_preserve_provenance(tmp_path):
    path = tmp_path / "application.sqlite"
    stream = {"source": "fixture", "symbol": "BTCUSDT", "timeframe": "1h"}
    with TestClient(create_app(path, start_worker=False)) as client:
        response = client.post(
            PREFIX + "/jobs", json={"stream": stream}, headers={"Idempotency-Key": "fixture-run"}
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert (
            client.post(
                PREFIX + "/jobs",
                json={"stream": stream},
                headers={"Idempotency-Key": "fixture-run"},
            ).json()["job_id"]
            == job_id
        )
        runtime = Runtime(Repository(path), fetch=FixtureSource().fetch)
        runtime.run_once()
        job = client.get(PREFIX + "/jobs/" + job_id).json()
        assert job["state"] == "succeeded"
        snapshot_id = job["snapshot_id"]
        snapshot = client.get(PREFIX + "/snapshots/" + snapshot_id).json()
        assert len(snapshot["bars"]) == 320
        assert snapshot["data_state"] == "simulated"
        assert snapshot["signal_status"] == "not_implemented"
        workspace = client.get(PREFIX + "/workspace", params=stream).json()
        assert workspace["snapshot"]["snapshot_id"] == snapshot_id
        audit = client.get(PREFIX + "/jobs/" + job_id + "/events").json()
        assert [e["reason"] for e in audit] == [
            "requested",
            "claimed",
            "ingested",
            "snapshot_saved",
        ]
        cutoff = snapshot["bars"][-11]["bar"]["close_time"]
        replay_request = {
            "kind": "analyze",
            "stream": stream,
            "market_at": cutoff,
            "knowledge_at": snapshot["knowledge_at"],
        }
        replay = client.post(
            PREFIX + "/jobs", json=replay_request, headers={"Idempotency-Key": "replay"}
        ).json()
        runtime.run_once()
        replay_job = client.get(PREFIX + "/jobs/" + replay["job_id"]).json()
        historic = client.get(PREFIX + "/snapshots/" + replay_job["snapshot_id"]).json()
        assert historic["points"] == snapshot["points"][:-10]
        assert (
            client.get(PREFIX + "/workspace", params=stream).json()["snapshot"]["snapshot_id"]
            == snapshot_id
        )
        invalid = {
            **replay_request,
            "market_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        }
        assert (
            client.post(
                PREFIX + "/jobs", json=invalid, headers={"Idempotency-Key": "future"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                PREFIX + "/jobs",
                json={"stream": stream},
                headers={"Idempotency-Key": "cross-origin", "Origin": "https://unrelated.example"},
            ).status_code
            == 403
        )
    with TestClient(create_app(path, start_worker=False)) as restarted:
        assert restarted.get(PREFIX + "/snapshots/" + snapshot_id).json() == snapshot
        assert restarted.get(PREFIX + "/storage").json()["revisions"] == 320
        assert (
            restarted.get(PREFIX + "/status").json()["integrations"]["market_data"] == "available"
        )
