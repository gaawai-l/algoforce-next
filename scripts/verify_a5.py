"""Verify the running local host/data/task chain, with optional public feed and crash recovery."""

import argparse
import json
import os
import platform
import signal
import subprocess
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

import httpx
from wheelhouse_service.calculation import calculate
from wheelhouse_service.market import Bar, Batch, JobRequest, Rules, Stream
from wheelhouse_service.repository import Repository
from wheelhouse_service.settings import Settings
from wheelhouse_service.sources import FixtureSource

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:1420/api/wheelhouse/v1"


def wait_job(client: httpx.Client, job_id: str, timeout: float = 45) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = client.get(f"{BASE}/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job["state"] == "failed":
                raise AssertionError(f"Task failed: {job['error_code']}")
            if job["state"] == "succeeded":
                return job
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise AssertionError("Task did not complete before verification deadline")


def refresh(client: httpx.Client, source: str) -> dict:
    key = "verify-" + uuid4().hex
    request = {
        "kind": "refresh",
        "stream": {"source": source, "symbol": "BTCUSDT", "timeframe": "1h"},
    }
    first = client.post(BASE + "/jobs", json=request, headers={"Idempotency-Key": key})
    first.raise_for_status()
    second = client.post(BASE + "/jobs", json=request, headers={"Idempotency-Key": key})
    second.raise_for_status()
    assert first.json()["job_id"] == second.json()["job_id"]
    job = wait_job(client, first.json()["job_id"])
    response = client.get(BASE + "/snapshots/" + job["snapshot_id"])
    response.raise_for_status()
    snapshot = response.json()
    assert len(snapshot["bars"]) >= 300
    assert snapshot["stream"]["source"] == source
    assert snapshot["signal_status"] == "not_implemented"
    assert (snapshot["data_state"] == "simulated") == (source == "fixture")
    return snapshot


def restart_with_checkpoint(client: httpx.Client) -> dict:
    pid = int(
        subprocess.check_output(["lsof", "-t", "-iTCP:8787", "-sTCP:LISTEN"], text=True).strip()
    )
    assert "wheelhouse_service" in subprocess.check_output(
        ["ps", "-p", str(pid), "-o", "args="], text=True
    )
    repo = Repository(Settings.from_env().data_dir / "analytics.sqlite")
    assert repo.stats().model_dump() == client.get(BASE + "/storage").json()
    os.kill(pid, signal.SIGSTOP)
    killed = False
    try:
        at = datetime.now(UTC)
        stream = Stream(source="fixture", symbol="ETHUSDT", timeframe="15m")
        job = repo.enqueue(JobRequest(stream=stream), "crash-probe-" + uuid4().hex, now=at)
        claim = repo.claim(now=at, lease_seconds=5)
        assert claim and claim.job.job_id == job.job_id, "Complete other queued work first"
        batch_id = repo.ingest(FixtureSource().fetch(stream, at))
        repo.checkpoint(claim, batch_id, now=at)
        os.kill(pid, signal.SIGKILL)
        killed = True
    finally:
        if not killed:
            os.kill(pid, signal.SIGCONT)
    resumed = wait_job(client, job.job_id)
    assert resumed["attempts"] == 2
    assert resumed["checkpoint_batch_id"] == batch_id
    audit = client.get(BASE + "/jobs/" + job.job_id + "/events").json()
    assert any(event["reason"] == "lease_recovered" for event in audit)
    assert sum(event["reason"] == "ingested" for event in audit) == 1
    return {"attempts": resumed["attempts"], "checkpoint_reused": True, "lease_recovered": True}


def benchmark() -> dict:
    artifact_root = ROOT / ".local" / "a5-verification"
    artifact_root.mkdir(parents=True, exist_ok=True)
    path = Path(mkdtemp(prefix="benchmark-", dir=artifact_root)) / "market.sqlite"
    repo = Repository(path)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    bars = []
    for i in range(1000):
        price = Decimal(100) + Decimal(i) / 100
        bars.append(
            Bar(
                open_time=start + timedelta(minutes=i * 5),
                close_time=start + timedelta(minutes=(i + 1) * 5),
                open=str(price),
                high=str(price + 1),
                low=str(price - 1),
                close=str(price),
                volume=None,
                is_closed=True,
            )
        )
    at = bars[-1].close_time
    stream = Stream(source="fixture", symbol="BTCUSDT", timeframe="5m")
    capture = Batch(
        stream=stream, fetched_at=at, bars=bars, raw_payload={"sanitized_benchmark": True}
    )
    began = time.perf_counter()
    repo.ingest(capture)
    result = calculate(repo.read(stream, market_at=at, knowledge_at=at), Rules(window=20))
    repo.save_snapshot(result, created_at=at)
    elapsed = time.perf_counter() - began
    assert len(result.points) == 1000
    assert result.points[-1].sma == "109.895"
    assert elapsed < 2, f"Performance acceptance exceeded: {elapsed:.3f}s"
    return {
        "bars": 1000,
        "ingest_read_calculate_persist_seconds": round(elapsed, 4),
        "target_seconds": 2,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    report = {
        "verified_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    with httpx.Client(timeout=8) as client:
        fixture = refresh(client, "fixture")
        report["fixture"] = {
            "bars": len(fixture["bars"]),
            "state": fixture["data_state"],
            "duplicate_job_idempotent": True,
        }
        if args.live:
            live = refresh(client, "binance")
            report["public_feed"] = {
                "bars": len(live["bars"]),
                "state": live["data_state"],
                "forming_excluded": live["forming_bar_time"] is not None,
            }
        if args.restart:
            report["restart"] = restart_with_checkpoint(client)
            assert client.get(BASE + "/snapshots/" + fixture["snapshot_id"]).json() == fixture
        report["benchmark"] = benchmark()
    output = (
        ROOT
        / ".local"
        / "a5-verification"
        / ("report-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + ".json")
    )
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"Evidence saved: {output}")


if __name__ == "__main__":
    main()
