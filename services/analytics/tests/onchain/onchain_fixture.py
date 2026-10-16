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
    """A position (negative means the last N points) or an ISO date."""
    try:
        return int(start)
    except ValueError:
        return (date.fromisoformat(start) - EPOCH).days


def _bulk(params: dict[str, str], missing: Set[str]) -> httpx.Response:
    names = params["series"].split(",")
    if not missing.isdisjoint(names):
        return _error(404, "series_not_found")
    start = _position(params["start"])
    body = []
    for name in names:
        raw = _raw(f"{params['index']}_{name}.json")
        # A negative start is the last -start points. Either way the body carries the absolute
        # position of its first row. A fixture holds only what was captured, so a request that
        # reaches back further than that gets the fixture from its own start.
        first = max(raw["end"] + start if start < 0 else start, raw["start"])
        body.append({**raw, "start": first, "data": raw["data"][first - raw["start"] :]})
    # BRK weighs the points it was asked for, not the fewer a fixture can replay.
    points = -start if start < 0 else body[0]["end"] - start
    if points * len(names) * WEIGHT_PER_POINT > WEIGHT_CAP:
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
    fail_index: Set[str] = frozenset(),
    urpd_dates: Set[date] | None = None,
) -> tuple[httpx.MockTransport, Calls]:
    """A fake BRK serving the fixtures; `urpd_dates=None` means every date has a snapshot.

    Series requests for an index in `fail_index` always get a 503.
    """
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
            if params.get("index") in fail_index:
                return httpx.Response(503)
            return _bulk(params, missing)
        if path.startswith("/api/urpd/"):
            _, _, _, cohort, day = path.split("/")
            if urpd_dates is not None and date.fromisoformat(day) not in urpd_dates:
                return _error(404, "not_found")
            return _urpd(cohort, day, params)
        return _error(404, "not_found")

    return httpx.MockTransport(handler), calls
