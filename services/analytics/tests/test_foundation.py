"""The overlay launcher a preview tool runs must bring up the Wealthfolio backend it proxies to."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/foundation.py"


@pytest.fixture
def foundation():
    spec = importlib.util.spec_from_file_location("foundation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def calls(foundation, monkeypatch):
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(foundation, "sync_host", lambda: calls.append(("sync", None)))
    monkeypatch.setattr(foundation, "check_port", lambda port: calls.append(("port", port)))
    monkeypatch.setattr(foundation, "run", lambda args, **_: calls.append(("run", args)))
    monkeypatch.setattr(foundation, "wait_healthy", lambda url: calls.append(("wait", url)))

    def execvpe(file, args, env):
        calls.append(("exec", (args, env)))
        raise SystemExit(0)

    monkeypatch.setattr(foundation.os, "execvpe", execvpe)
    return calls


def test_overlay_starts_the_backend_before_serving(foundation, calls, monkeypatch):
    monkeypatch.setattr(
        foundation.subprocess, "run", lambda *_, **__: subprocess.CompletedProcess([], 0)
    )
    with pytest.raises(SystemExit):
        foundation.overlay()
    steps = [step for step, _ in calls]
    assert steps == ["sync", "port", "run", "wait", "exec"]
    assert calls[2][1] == [*foundation.COMPOSE, "up", "-d", "--no-recreate", "wealthfolio"]
    assert calls[3][1] == "http://127.0.0.1:8088/api/v1/healthz"
    args, env = calls[4][1]
    assert args == [*foundation.PNPM, "--filter", "frontend", "dev"]
    assert env["VITE_DEV_PORT"] == "1420"
    assert env["WF_API_TARGET"] == "http://127.0.0.1:8088"
    assert env["WHEELHOUSE_API_TARGET"] == "http://127.0.0.1:8787"


def test_overlay_refuses_to_serve_without_docker(foundation, calls, monkeypatch):
    monkeypatch.setattr(
        foundation.subprocess, "run", lambda *_, **__: subprocess.CompletedProcess([], 1)
    )
    with pytest.raises(SystemExit, match="Docker is not running"):
        foundation.overlay()
    assert [step for step, _ in calls] == ["sync", "port"]
