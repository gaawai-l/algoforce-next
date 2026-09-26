"""Boot the local stack in CI, verify the fixture pipeline, and stop owned processes."""

import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv-foundation/bin/python"


def main() -> None:
    for port in (1420, 8787, 8088):
        with socket.socket() as connection:
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is occupied; existing processes are preserved")
    log_path = ROOT / ".local/ci-a5.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [str(PYTHON), "scripts/foundation.py", "dev"],
            cwd=ROOT,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 90
            with httpx.Client(timeout=2) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"Workspace exited; see {log_path}")
                    try:
                        status = client.get("http://127.0.0.1:1420/api/wheelhouse/v1/status")
                        host = client.get("http://127.0.0.1:8088/api/v1/healthz")
                        if status.status_code == 200 and host.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError(f"Workspace readiness deadline exceeded; see {log_path}")
            subprocess.run([str(PYTHON), "scripts/verify_a5.py"], cwd=ROOT, check=True)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)


if __name__ == "__main__":
    main()
