"""Replay of public BRK (bitview.space) responses captured on 2026-10-16."""

import json
from collections.abc import Set
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from wheelhouse_service.onchain.brk import Index, SeriesData, Urpd

FIXTURES = Path(__file__).parent / "fixtures" / "brk-2026-10-16"
# BRK positions count from 2009-01-01T00:00Z for both day1 and hour1.
EPOCH = date(2009, 1, 1)
# Observed on the live API: a bulk request over 320,000 weight is rejected, ~16 weight per point.
WEIGHT_CAP = 320_000
WEIGHT_PER_POINT = 16


def _raw(filename: str) -> dict[str, Any]:
    """The captured response verbatim, including fields the client models ignore."""
    payload: dict[str, Any] = json.loads((FIXTURES / filename).read_text())
    return payload


def load_series(name: str, index: Index) -> SeriesData:
    return SeriesData.model_validate(_raw(f"{index}_{name}.json"))


def load_urpd(cohort: str) -> Urpd:
    return Urpd.model_validate(_raw(f"urpd_{cohort}_lin500.json"))


class Calls(list[tuple[str, dict[str, str]]]):
    """Requests seen by the fake BRK, in order: (path, query parameters)."""


def _error(status: int, code: str, kind: str = "not_found") -> httpx.Response:
    return httpx.Response(status, json={"error": {"type": kind, "code": code}})


def _position(start: str) -> int:
    return int(start) if start.isdigit() else (date.fromisoformat(start) - EPOCH).days


def _bulk(params: dict[str, str], missing: Set[str]) -> httpx.Response:
    names = params["series"].split(",")
    if not missing.isdisjoint(names):
        return _error(404, "series_not_found")
    start = _position(params["start"])
    body = []
    for name in names:
        raw = _raw(f"{params['index']}_{name}.json")
        assert start >= raw["start"], f"fixture {name} starts at {raw['start']}, asked for {start}"
        body.append({**raw, "start": start, "data": raw["data"][start - raw["start"] :]})
    if (body[0]["end"] - start) * len(names) * WEIGHT_PER_POINT > WEIGHT_CAP:
        return _error(400, "weight_exceeded", "invalid_request")
    return httpx.Response(200, json=body)


def _urpd(cohort: str, day: str, params: dict[str, str]) -> httpx.Response:
    if not (FIXTURES / f"urpd_{cohort}_lin500.json").exists():
        return _error(404, "not_found")
    if params.get("agg") != "lin500":
        return _error(400, "bad_request", "invalid_request")
    return httpx.Response(200, json={**_raw(f"urpd_{cohort}_lin500.json"), "date": day})


def brk_transport(
    *,
    version: str = "0.12.2",
    missing: Set[str] = frozenset(),
    fail_paths: Set[str] = frozenset(),
    urpd_dates: Set[date] | None = None,
) -> tuple[httpx.MockTransport, Calls]:
    """A fake BRK serving the fixtures; `urpd_dates=None` means every date has a snapshot."""
    calls = Calls()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        calls.append((path, params))
        if any(path.startswith(prefix) for prefix in fail_paths):
            return httpx.Response(503)
        if path == "/version":
            return httpx.Response(200, json=version)
        if path == "/api/series/bulk":
            return _bulk(params, missing)
        if path.startswith("/api/urpd/"):
            _, _, _, cohort, day = path.split("/")
            if urpd_dates is not None and date.fromisoformat(day) not in urpd_dates:
                return _error(404, "not_found")
            return _urpd(cohort, day, params)
        return _error(404, "not_found")

    return httpx.MockTransport(handler), calls
