"""Allowlisted local subprocess adapter; credentials remain exclusively in official OpenD."""

import json
import os
import socket
import subprocess
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .models import PortfolioCapture, Position, SyncRequest

ROOT = Path(__file__).resolve().parents[5]


class BrokerUnavailable(RuntimeError):
    pass


class MoomooReader:
    def __init__(self, python: Path | None = None) -> None:
        self.python = python or ROOT / ".venv-moomoo/bin/python"

    def status(self) -> dict[str, Any]:
        connected = False
        with socket.socket() as connection:
            connection.settimeout(0.25)
            connected = connection.connect_ex(("127.0.0.1", 11111)) == 0
        return {
            "sdk_installed": self.python.exists(),
            "gateway_reachable": connected,
            "host": "127.0.0.1",
            "port": 11111,
            "firm": "FUTUSG",
            "environment": "REAL",
            "account_verified": False,
            "read_only": True,
            "message": "Select and verify an account"
            if connected
            else "Start official moomoo OpenD and sign in locally. No trading unlock is needed.",
        }

    def _run(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("operation") not in {"accounts", "sync", "fees"}:
            raise ValueError("Unsupported reader operation")
        state = self.status()
        if not state["sdk_installed"] or not state["gateway_reachable"]:
            raise BrokerUnavailable("OpenD or its isolated SDK is unavailable")
        # SDK logging is disabled by the child; capture pipes are never forwarded to logs.
        private = ROOT / ".local" / "broker-runtime"
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            process = subprocess.run(
                [str(self.python), str(ROOT / "scripts/broker/moomoo_reader.py")],
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=50,
                cwd=private,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            result = json.loads(process.stdout)
            if process.returncode or not result.get("ok"):
                raise BrokerUnavailable(
                    "Official read-only query failed; verify OpenD login and account access"
                )
            return result  # type: ignore[no-any-return]
        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
            raise BrokerUnavailable(
                "OpenD query timed out or returned an invalid response"
            ) from exc

    def accounts(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._run({"operation": "accounts"})["accounts"]
        return result

    def fees(self, account: str, ids: list[str]) -> list[dict[str, Any]]:
        if not account.isdigit() or not 1 <= len(ids) <= 20 or len(ids) != len(set(ids)):
            raise ValueError("Invalid fee batch")
        result = self._run({"operation": "fees", "account_id": account, "order_ids": ids})
        rows: list[dict[str, Any]] = result["fees"]
        return rows

    def sync(self, request: SyncRequest, *, include_fees: bool = True) -> PortfolioCapture:
        payload = self._run(
            {"operation": "sync", "include_fees": include_fees, **request.model_dump(mode="json")}
        )
        now = datetime.now(UTC)
        errors = dict(payload.get("errors", {}))
        positions = []
        for row in payload.get("captures", {}).get("positions", []):
            try:
                quantity = Decimal(str(row["qty"]))
                side = row.get("position_side")
                if side == "SHORT":
                    quantity = -abs(quantity)
                elif side == "LONG":
                    quantity = abs(quantity)
                else:
                    errors["position_direction"] = (
                        "Unknown position direction; affected row not normalized"
                    )
                    continue
                code = str(row["code"])
                mark = row.get("nominal_price")
                if mark is None or not Decimal(str(mark)).is_finite() or Decimal(str(mark)) < 0:
                    mark = None
                positions.append(
                    Position(
                        code=code,
                        quantity=str(quantity),
                        mark=str(mark) if mark is not None else None,
                        observed_at=now,
                    )
                )
            except (KeyError, ValueError, InvalidOperation):
                errors["position_mapping"] = "Some positions need explicit mapping"
        errors["history_coverage"] = (
            "Requested interval only; earliest available history is not verified"
        )
        coverage = payload.get("captures", {}).get("_coverage", {}).get("cash_flows", {})
        if not coverage.get("query_succeeded"):
            errors["cash_flow_coverage"] = "Cash flow range query failed or coverage is unavailable"
        errors["metadata"] = "Contract multiplier and Greeks units require verified metadata"
        return PortfolioCapture(
            source="moomoo",
            account_id=request.account_id,
            captured_at=now,
            snapshot_observed_at=now,
            positions=positions,
            instruments=[],
            quotes=[],
            fx=[],
            raw=payload.get("captures", {}),
            errors=errors,
            history_start=request.start,
            history_end=request.end,
        )
