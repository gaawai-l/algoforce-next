"""Reproducible local Wealthfolio + Python workspace. Never deletes files or data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
HOST = LOCAL / "wealthfolio"
INTEGRATION = ROOT / "integrations/wealthfolio"
PIN = json.loads((INTEGRATION / "upstream.json").read_text())
PYTHON = ROOT / ".venv-foundation/bin/python"
PNPM = ["npx", "--yes", PIN["package_manager"], "--dir", str(HOST)]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]


def run(args: list[str], cwd: Path = ROOT, **kwargs: object) -> None:
    subprocess.run(args, cwd=cwd, check=True, **kwargs)


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(HOST), *args], text=True).strip()


def sync_host() -> None:
    if not (HOST / ".git").exists():
        raise SystemExit("Run make setup first")
    if git_output("rev-parse", "HEAD") != PIN["commit"]:
        raise SystemExit("Upstream checkout does not match the pinned commit; refusing to patch")
    for patch in sorted((INTEGRATION / "patches").glob("*.patch")):
        applied = subprocess.run(
            ["git", "-C", str(HOST), "apply", "--reverse", "--check", str(patch)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if applied.returncode != 0:
            run(["git", "-C", str(HOST), "apply", "--check", str(patch)])
            run(["git", "-C", str(HOST), "apply", str(patch)])
    # Compare complete tracked trees, not just whether individual patch hunks match.
    index_path = LOCAL / ("host-validation-index-" + secrets.token_hex(6))
    index_env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
    run(["git", "-C", str(HOST), "read-tree", "HEAD"], env=index_env)
    for patch in sorted((INTEGRATION / "patches").glob("*.patch")):
        run(["git", "-C", str(HOST), "apply", "--cached", str(patch)], env=index_env)
    expected = subprocess.check_output(
        ["git", "-C", str(HOST), "diff", "--cached", "--binary", "HEAD"], env=index_env
    )
    actual = subprocess.check_output(["git", "-C", str(HOST), "diff", "--binary", "HEAD"])
    if actual != expected:
        raise SystemExit("Unknown tracked host edits; preserving them and refusing to sync")
    state_path = LOCAL / "overlay-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    pending: list[tuple[Path, bytes, str, str]] = []
    for source in sorted((INTEGRATION / "overlay").rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(INTEGRATION / "overlay").as_posix()
        target = HOST / relative
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if target.exists() and target.read_bytes() != content:
            existing = hashlib.sha256(target.read_bytes()).hexdigest()
            if state.get(relative) != existing:
                raise SystemExit(f"Local host edit detected: {relative}; refusing to overwrite")
        pending.append((target, content, relative, digest))
    for target, content, relative, digest in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != content:
            target.write_bytes(content)
        state[relative] = digest
    state_path.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Wealthfolio {PIN['tag']} source and extension synchronized", flush=True)


def setup() -> None:
    LOCAL.mkdir(exist_ok=True)
    if not (HOST / ".git").exists():
        if HOST.exists():
            raise SystemExit("Existing non-checkout host directory; preserving it")
        run(["git", "clone", "--depth", "1", "--branch", PIN["tag"], PIN["repository"], str(HOST)])
    sync_host()
    if not PYTHON.exists():
        run([sys.executable, "-m", "venv", str(PYTHON.parent.parent)])
    run([str(PYTHON), "-m", "pip", "install", "-r", "services/analytics/requirements.lock"])
    run([str(PYTHON), "-m", "pip", "install", "--no-deps", "-e", "services/analytics"])
    run([*PNPM, "install", "--frozen-lockfile"])
    secret_file = LOCAL / "wealthfolio.env"
    if not secret_file.exists():
        import base64

        encoded = base64.b64encode(secrets.token_bytes(32)).decode()
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(f"WF_SECRET_KEY={encoded}\n")
    (LOCAL / "wealthfolio-data").mkdir(exist_ok=True)
    print("Setup complete. Run make dev. Local data and secrets are ignored by Git.")


def setup_broker() -> None:
    interpreter = ROOT / ".venv-moomoo/bin/python"
    if not interpreter.exists():
        run([sys.executable, "-m", "venv", str(interpreter.parent.parent)])
    run([str(interpreter), "-m", "pip", "install", "-r", "scripts/broker/requirements.lock"])
    print("Official SDK ready. Start official moomoo OpenD and sign in locally; no trading unlock.")


def check_port(port: int) -> None:
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"Port {port} is already in use; preserving that process")


def workspace_env() -> dict[str, str]:
    env = {
        **os.environ,
        "WF_ENABLE_VITE_PROXY": "true",
        "VITE_DEV_PORT": "1420",
        "WF_API_TARGET": "http://127.0.0.1:8088",
        "VITE_API_TARGET": "http://127.0.0.1:8088",
        "WHEELHOUSE_PORT": "8787",
        "WHEELHOUSE_API_TARGET": "http://127.0.0.1:8787",
    }
    env.pop("TAURI_DEV_HOST", None)
    return env


def wait_healthy(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f"{url} did not become healthy; inspect the wealthfolio container")
        time.sleep(1)


def overlay() -> None:
    """Serve only the overlay, for preview launchers that start it without make dev.

    Without the Wealthfolio server the whole host shows "Backend unavailable", so bring
    it up first; the Python service is started separately and may be absent."""
    sync_host()
    check_port(1420)
    docker = subprocess.run(
        ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    if docker.returncode != 0:
        raise SystemExit("Docker is not running; start Docker Desktop, then the overlay again")
    run([*COMPOSE, "up", "-d", "--no-recreate", "wealthfolio"])
    wait_healthy("http://127.0.0.1:8088/api/v1/healthz")
    os.chdir(ROOT)
    os.execvpe(PNPM[0], [*PNPM, "--filter", "frontend", "dev"], workspace_env())


def dev() -> None:
    sync_host()
    check_port(1420)
    check_port(8787)
    run([*COMPOSE, "up", "-d", "--no-recreate", "wealthfolio"])
    env = workspace_env()
    children: list[subprocess.Popen[bytes]] = []

    def interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        children.append(
            subprocess.Popen(
                [str(PYTHON), "-m", "wheelhouse_service"], cwd=ROOT, env=env, start_new_session=True
            )
        )
        children.append(
            subprocess.Popen(
                [*PNPM, "--filter", "frontend", "dev"], cwd=ROOT, env=env, start_new_session=True
            )
        )
        print("Workspace: http://127.0.0.1:1420/market-intelligence", flush=True)
        restarts: list[float] = []
        while children[1].poll() is None:
            if children[0].poll() is not None:
                now = time.monotonic()
                restarts = [at for at in restarts if now - at < 60]
                if len(restarts) >= 3:
                    raise SystemExit("Python repeatedly failed; inspect its output above")
                restarts.append(now)
                print("Python exited; restarting with persisted task recovery", flush=True)
                children[0] = subprocess.Popen(
                    [str(PYTHON), "-m", "wheelhouse_service"],
                    cwd=ROOT,
                    env=env,
                    start_new_session=True,
                )
            time.sleep(0.5)
        raise SystemExit("The Wealthfolio frontend exited; inspect its output above")
    except KeyboardInterrupt:
        print("Stopping workspace processes; all data is preserved.", flush=True)
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        run([*COMPOSE, "stop", "wealthfolio"])


def check() -> None:
    sync_host()
    service = ROOT / "services/analytics"
    run([str(PYTHON), "-m", "ruff", "check", "."], cwd=service)
    run([str(PYTHON), "-m", "mypy", "src/wheelhouse_service"], cwd=service)
    run([str(PYTHON), "-m", "pytest", "-q"], cwd=service)
    run([*PNPM, "build:types"])
    run([*PNPM, "--filter", "frontend", "type-check"])
    run([*PNPM, "--filter", "frontend", "exec", "vitest", "run", "src/features/wheelhouse"])


def doctor() -> None:
    failed = False
    for name, url in (
        ("Wealthfolio server", "http://127.0.0.1:8088/api/v1/healthz"),
        ("Python service", "http://127.0.0.1:8787/api/wheelhouse/v1/status"),
        ("Host → Python proxy", "http://127.0.0.1:1420/api/wheelhouse/v1/status"),
    ):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status != 200:
                    raise ValueError("Non-success response")
                if "wheelhouse" in url:
                    status = json.load(response)
                    if (
                        status.get("service") != "wheelhouse-python"
                        or status.get("contract_version") != "1"
                    ):
                        raise ValueError("Unexpected service contract")
            print(f"OK   {name}")
        except (OSError, ValueError):
            failed = True
            print(f"FAIL {name}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "setup",
            "sync",
            "dev",
            "overlay",
            "check",
            "build",
            "doctor",
            "stop",
            "setup-broker",
        ],
    )
    command = parser.parse_args().command
    if command == "build":
        sync_host()
        run([*PNPM, "build:types"])
        run([*PNPM, "build"])
    elif command == "setup-broker":
        setup_broker()
    elif command == "stop":
        run([*COMPOSE, "stop", "wealthfolio"])
    else:
        {
            "setup": setup,
            "sync": sync_host,
            "dev": dev,
            "overlay": overlay,
            "check": check,
            "doctor": doctor,
        }[command]()
