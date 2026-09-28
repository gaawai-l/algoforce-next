"""Rate-expectation inputs: Fed meeting calendar and FRED 10Y-1Y spread."""

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from wheelhouse_service.http import create_app
from wheelhouse_service.macro import FOMC_URL, FRED_URL, build_macro, meetings, next_fomc

FIXTURES = Path(__file__).parent / "fixtures"
FED = (FIXTURES / "fomccalendars-2026-09-28.html").read_text()
FRED = (FIXTURES / "fred-dgs10-dgs1-2026-09-28.csv").read_text()
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


def test_meetings_parse_both_years_and_projection_marks():
    found = meetings(FED)
    assert len(found) == 16
    assert found[0].meeting == "January 27-28, 2026"
    assert [m.projections for m in found[:8]] == [False, True] * 4


def test_next_decision_is_2pm_eastern_on_the_last_day():
    fomc = next_fomc(FED, NOW)
    assert fomc.meeting == "October 27-28, 2026"
    assert fomc.decision_at == datetime(2026, 10, 28, 18, 0, tzinfo=UTC)  # EDT
    december = next_fomc(FED, datetime(2026, 11, 1, tzinfo=UTC))
    assert december.decision_at == datetime(2026, 12, 9, 19, 0, tzinfo=UTC)  # EST


def test_spread_uses_latest_complete_row_and_skips_holidays():
    watch = build_macro(NOW, {FOMC_URL: FED, FRED_URL: FRED}.__getitem__)
    spread = watch.spread
    assert spread is not None
    assert (spread.day, spread.ten_year, spread.one_year) == (date(2026, 9, 24), 5.18, 4.51)
    assert (spread.spread, spread.inverted) == (0.67, False)
    assert date(2026, 9, 7) not in [p.day for p in spread.history]  # blank holiday row
    assert len(spread.history) == 30


def test_each_source_fails_on_its_own():
    def get(url: str) -> str:
        if url == FRED_URL:
            raise httpx.ConnectTimeout("fred timed out")
        return FED

    watch = build_macro(NOW, get)
    assert watch.fomc is not None and watch.fomc_error is None
    assert watch.spread is None and watch.spread_error == "fred timed out"


def test_endpoint(tmp_path):
    calls: list[str] = []

    def get(url: str) -> str:
        calls.append(url)
        return {FOMC_URL: FED, FRED_URL: FRED}[url]

    app = create_app(tmp_path / "api.sqlite", start_worker=False, macro_get=get)
    with TestClient(app) as client:
        body = client.get("/api/wheelhouse/v1/macro-watch").json()
        client.get("/api/wheelhouse/v1/macro-watch")
        capabilities = client.get("/api/wheelhouse/v1/status").json()["capabilities"]
    assert body["spread"]["spread"] == 0.67
    assert body["fomc"]["meeting"].endswith("2026") or body["fomc"]["meeting"].endswith("2027")
    assert len(calls) == 2  # cached on the second request
    assert "macro_watch" in capabilities
