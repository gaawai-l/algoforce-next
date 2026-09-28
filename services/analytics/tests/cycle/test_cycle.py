"""AlphaBTC on-chain cycle, pinned to its dashboard as read 2026-09-27T16:39Z."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wheelhouse_service import onchain
from wheelhouse_service.cycle import SERIES, build_cycle, compose_cycle
from wheelhouse_service.http import create_app
from wheelhouse_service.indicators.cycle.alphabtc import START, short_term_pressure, zone
from wheelhouse_service.onchain import EPOCH, OnchainError, fetch_daily

FIXTURE = Path(__file__).parent / "fixtures" / "bitview-2026-09-27T163948Z.json"
CHECKED = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)


def _series() -> dict[str, list[float | None]]:
    raw = json.loads(FIXTURE.read_text())
    first = (START - EPOCH).days
    last = (date.fromisoformat(raw["last_day"]) - EPOCH).days
    out = {}
    for name, entry in raw["series"].items():
        values = [None] * (last - first + 1)
        values[entry["start"] - first :] = entry["data"]
        out[name] = values
    return out


def test_states_match_dashboard():
    cycle = compose_cycle(_series(), since=START, checked_at=CHECKED)
    states = cycle.states
    assert states is not None
    assert (states.state, states.since, states.days, states.changes) == (
        "breakout", date(2026, 9, 23), 5, 42,
    )
    assert (round(states.depth * 100, 1), round(states.spread * 100, 1)) == (9.5, -5.6)
    breakout = next(s for s in states.stats if s.state == "breakout")
    assert (breakout.runs, breakout.days, breakout.mean_days, breakout.median_days) == (
        6, 136, 22.7, 27,
    )
    assert breakout.max_days == 42


def test_index_matches_dashboard():
    index = compose_cycle(_series(), since=START, checked_at=CHECKED).index
    assert index is not None
    parts = index.components
    assert [round(v) for v in (parts.unrealized, parts.realized, parts.supply,
                               parts.young_vs_seasoned)] == [45, 68, 46, 20]
    assert round(index.composite) == 45 and index.zone == "mid"
    assert {k: round(v) for k, v in index.change.items() if v is not None} == {
        "1d": 4, "7d": 9, "30d": 5, "90d": 33,
    }


def test_zone_bounds():
    assert [zone(v) for v in (0, 19.9, 20, 45, 60, 79.9, 80, 100)] == [
        "low", "low", "transition_low", "mid", "transition_high", "transition_high", "top", "top",
    ]


def test_short_term_pressure_uses_author_lines_unconfirmed():
    pressure = short_term_pressure(START, _series())
    assert pressure.history[-1].day == date(2026, 9, 27)
    assert round(pressure.value, 1) == 90.0
    assert (pressure.warn, pressure.confirm, pressure.thresholds_confirmed) == (84.5, 75.0, False)
    assert pressure.stage == "none"
    assert len(pressure.history) == 30


def test_status_goes_stale_after_a_missing_day():
    later = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)
    assert compose_cycle(_series(), since=START, checked_at=CHECKED).status == "fresh"
    assert compose_cycle(_series(), since=START, checked_at=later).status == "stale"


def test_fetch_failure_is_unavailable_not_zero():
    def broken(*_args, **_kwargs):
        raise OnchainError("bitview down")

    cycle = build_cycle(CHECKED, broken)
    assert cycle.status == "unavailable"
    assert (cycle.states, cycle.index, cycle.pressure) == (None, None, None)
    assert cycle.error == "bitview down"


def test_fetch_drops_the_partial_current_day(monkeypatch):
    start = (START - EPOCH).days
    today = (CHECKED.date() - EPOCH).days

    def handler(request: httpx.Request) -> httpx.Response:
        data = [1.0] * (today - start + 1)  # includes today's partial row
        return httpx.Response(200, json={"index": "day1", "start": start, "data": data})

    real = httpx.Client
    monkeypatch.setattr(
        onchain.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    series = fetch_daily(["a", "b"], since=START, now=CHECKED)
    assert onchain.last_day(START, series) == date(2026, 9, 27)


def test_endpoint_serves_cached_cycle(tmp_path):
    calls = []

    def fake(names, *, since, now):
        calls.append(now)
        assert set(names) == set(SERIES) and since == START
        return _series()

    app = create_app(tmp_path / "api.sqlite", start_worker=False, cycle_fetch=fake)
    with TestClient(app) as client:
        first = client.get("/api/wheelhouse/v1/market-cycle")
        second = client.get("/api/wheelhouse/v1/market-cycle")
        status = client.get("/api/wheelhouse/v1/status").json()
    assert first.status_code == 200 and first.json() == second.json()
    assert first.json()["states"]["state"] == "breakout"
    assert len(calls) == 1
    assert "market_cycle" in status["capabilities"]


@pytest.mark.parametrize("payload", [{"index": "hour1", "start": 2191, "data": []}, ["x"]])
def test_fetch_rejects_unexpected_payload(monkeypatch, payload):
    real = httpx.Client
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
    monkeypatch.setattr(onchain.httpx, "Client", lambda **kw: real(transport=transport, **kw))
    with pytest.raises(OnchainError):
        fetch_daily(["a"], since=START, now=CHECKED)
