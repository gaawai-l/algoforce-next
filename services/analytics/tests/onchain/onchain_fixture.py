"""Replay of public BRK (bitview.space) responses captured on 2026-10-16."""

import json
from collections.abc import Iterable, Set
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from wheelhouse_service.onchain.brk import Index, SeriesData, Urpd
from wheelhouse_service.onchain.costbasis import PAST_DAYS
from wheelhouse_service.onchain.levels import LINE_SERIES
from wheelhouse_service.onchain.store import OnchainStore
from wheelhouse_service.onchain.sync import URPD_SET

FIXTURES = Path(__file__).parent / "fixtures" / "brk-2026-10-16"
# The cost-basis golden sample: D = 10-16 has undated files, every other day dated ones.
GOLDEN = Path(__file__).parent / "fixtures" / "brk-2026-10-16T1829Z"
GOLDEN_D = date(2026, 10, 16)
# D and the day before, the closed day at 10:40 on D, each with the past days of its grid: all nine
# days the sample has.
GOLDEN_DAYS = sorted(
    {
        day - timedelta(days=n)
        for day in (GOLDEN_D, GOLDEN_D - timedelta(days=1))
        for n in (0, *PAST_DAYS)
    }
)
# BRK positions count from 2009-01-01T00:00Z for both day1 and hour1.
EPOCH = date(2009, 1, 1)
# Observed on the live API: a bulk request over 320,000 weight is rejected, ~16 weight per point.
WEIGHT_CAP = 320_000
WEIGHT_PER_POINT = 16
# Observed on 2026-10-19: a decoded `series` parameter of 1,997 characters passed and one of 2,053
# was refused with HTTP 400 ("series: Given parameter is too long").
SERIES_CHARS_CAP = 2_048


def _raw(filename: str) -> dict[str, Any]:
    """The captured response verbatim, including fields the client models ignore."""
    payload: dict[str, Any] = json.loads((FIXTURES / filename).read_text())
    return payload


def load_series(name: str, index: Index) -> SeriesData:
    return SeriesData.model_validate(_raw(f"{index}_{name}.json"))


def load_urpd(cohort: str) -> Urpd:
    return Urpd.model_validate(_raw(f"urpd_{cohort}_lin500.json"))


def golden_urpd(cohort: str, agg: str, day: date) -> Urpd:
    """One snapshot of the golden sample."""
    suffix = "" if day == GOLDEN_D else f"_{day.isoformat()}"
    return Urpd.model_validate_json((GOLDEN / f"urpd_{cohort}_{agg}{suffix}.json").read_text())


def seed_golden(store: OnchainStore, days: Iterable[date], fetched_at: datetime) -> None:
    """Store the golden sample's day1 rows and the URPD_SET snapshots of `days`, all as fetched
    at `fetched_at`. The sample has no W series, so there is no cycle."""
    for name in (*LINE_SERIES.values(), "price_close"):
        data = SeriesData.model_validate_json((GOLDEN / f"day1_{name}.json").read_text())
        store.replace_series({name: data}, "day1", fetched_at)
    for day in days:
        for cohort, agg in URPD_SET:
            store.save_urpd(golden_urpd(cohort, agg, day), fetched_at)


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
    if len(params["series"]) > SERIES_CHARS_CAP:
        return _error(400, "bad_request", "invalid_request")
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


def _urpd(directory: Path, cohort: str, day: str, agg: str) -> httpx.Response:
    """The snapshot captured for `day`, else the directory's undated one, dated `day`."""
    for name in (f"urpd_{cohort}_{agg}_{day}.json", f"urpd_{cohort}_{agg}.json"):
        path = directory / name
        if path.exists():
            return httpx.Response(200, json={**json.loads(path.read_text()), "date": day})
    return _error(404, "not_found")


def brk_transport(
    *,
    version: str = "0.12.2",
    missing: Set[str] = frozenset(),
    fail_paths: Set[str] = frozenset(),
    fail_index: Set[str] = frozenset(),
    urpd_dates: Set[date] | None = None,
    urpd_dir: Path | None = None,
    urpd_missing: Set[tuple[str, str]] = frozenset(),
    urpd_fail: Set[tuple[str, str]] = frozenset(),
    age_dir: Path | None = None,
) -> tuple[httpx.MockTransport, Calls]:
    """A fake BRK serving the fixtures; `urpd_dates=None` means every date has a snapshot.

    Series requests for an index in `fail_index` always get a 503. URPD snapshots come from
    `urpd_dir` (the P1 fixtures by default), those of the age cohorts (`utxos_*`) from `age_dir`,
    and none at all without it; a (cohort, agg) in `urpd_missing` gets a 404 for every date, and
    one in `urpd_fail` a 500.
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
            agg = params["agg"]
            if (cohort, agg) in urpd_fail:
                return httpx.Response(500)
            if (cohort, agg) in urpd_missing:
                return _error(404, "not_found")
            if urpd_dates is not None and date.fromisoformat(day) not in urpd_dates:
                return _error(404, "not_found")
            if cohort.startswith("utxos_"):
                if age_dir is None:
                    return _error(404, "not_found")
                return _urpd(age_dir, cohort, day, agg)
            return _urpd(urpd_dir or FIXTURES, cohort, day, agg)
        return _error(404, "not_found")

    return httpx.MockTransport(handler), calls
