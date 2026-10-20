"""The original page's Chart 5 and 6 readings at 2026-10-19 06:00Z, and hour1 rows that give them.

The rows are back-solved from the page's readings, not BRK's own values: see the README of
`fixtures/sr5-6-page-2026-10-19T0600Z`. They hold values only at the hour the page read and at its
four window anchors, so that reading any other hour gives a None. Band names and windows are
copied from the original loader, not imported from the code under test.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SAMPLE = Path(__file__).parent / "fixtures" / "sr5-6-page-2026-10-19T0600Z"
HOUR = timedelta(hours=1)
# The hour the page read, still forming: hour1 position 156006.
SE = datetime(2026, 10, 19, 6, tzinfo=UTC)
# The original's twelve bands, smallest first (`raw/script_3_app.js` lines 48-54).
BANDS = (
    "addrs_under_1k_sats",
    "addrs_1k_sats_to_10k_sats",
    "addrs_10k_sats_to_100k_sats",
    "addrs_100k_sats_to_1m_sats",
    "addrs_1m_sats_to_10m_sats",
    "addrs_10m_sats_to_1btc",
    "addrs_1btc_to_10btc",
    "addrs_10btc_to_100btc",
    "addrs_100btc_to_1k_btc",
    "addrs_1k_btc_to_10k_btc",
    "addrs_10k_btc_to_100k_btc",
    "addrs_over_100k_btc",
)
# The original's windows in hours (line 325), in the order of a PNL row.
WINDOWS = (("1d", 24), ("7d", 168), ("30d", 720), ("90d", 2160))
# The cumulatives at SE. Whole dollars and halves stay exact below it, so each difference is too.
BASE = 1e12
# The two profits the page rounded up from exactly half a dollar (SR-6.md lines 43-45): the raw
# difference, by band and window.
HALVES = {(0, "1d"): 88.5, (5, "90d"): 2425253218.5}


def page_size() -> list[dict[str, Any]]:
    """The page's SIZE bands: label, supply and the change `d` of each window, smallest first."""
    bands: list[dict[str, Any]] = json.loads((SAMPLE / "page_size.json").read_text())["SIZE"]
    return bands


def page_pnl() -> list[list[int]]:
    """The page's PNL rows: [rcap, 1d p, 1d l, 7d p, 7d l, 30d p, 30d l, 90d p, 90d l]."""
    rows: list[list[int]] = json.loads((SAMPLE / "page_pnl.json").read_text())
    return rows


def golden_rows() -> dict[str, list[tuple[datetime, float | None]]]:
    """Every size series from SE - 2160h through SE, None except at SE and the four anchors.

    The supply at an anchor is the page's supply less its change; profit and loss are BASE at SE
    and BASE less the page's dollars at an anchor, except for the two half-dollar cells; the
    realized cap is the page's at SE only.
    """
    hours = [SE - HOUR * n for n in range(WINDOWS[-1][1], -1, -1)]
    rows: dict[str, list[tuple[datetime, float | None]]] = {}
    for place, (band, size, pnl) in enumerate(zip(BANDS, page_size(), page_pnl(), strict=True)):
        supply: dict[datetime, float] = {SE: size["supply"]}
        profit: dict[datetime, float] = {SE: BASE}
        loss: dict[datetime, float] = {SE: BASE}
        for column, (window, n) in enumerate(WINDOWS):
            anchor = SE - HOUR * n
            supply[anchor] = size["supply"] - size["d"][window]
            profit[anchor] = BASE - HALVES.get((place, window), pnl[1 + 2 * column])
            loss[anchor] = BASE - pnl[2 + 2 * column]
        cap: dict[datetime, float] = {SE: float(pnl[0])}
        for suffix, values in (
            ("_supply", supply),
            ("_realized_profit_cumulative", profit),
            ("_realized_loss_cumulative", loss),
            ("_realized_cap", cap),
        ):
            rows[f"{band}{suffix}"] = [(at, values.get(at)) for at in hours]
    return rows
