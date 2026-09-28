"""Rate-expectation inputs AlphaBTC leaves as "待接数据": next FOMC decision and 10Y-1Y spread.

Both are public: the Federal Reserve's meeting calendar and FRED's DGS10/DGS1 CSV.
A failed source is reported as unavailable on its own; nothing is guessed.
"""

import csv
import io
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import httpx

from .indicators.demark.models import Model

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,DGS1"
# Statements are released at 2:00 p.m. Eastern on the meeting's last day.
DECISION = time(14, 0)
EASTERN = ZoneInfo("America/New_York")
MONTHS = {
    m: i
    for i, m in enumerate(
        (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ),
        start=1,
    )
}
SPREAD_DAYS = 30
Get = Callable[[str], str]


class Fomc(Model):
    decision_at: datetime
    meeting: str
    projections: bool


class SpreadPoint(Model):
    day: date
    spread: float


class YieldSpread(Model):
    day: date
    ten_year: float
    one_year: float
    spread: float
    inverted: bool
    history: list[SpreadPoint]


class MacroWatch(Model):
    checked_at: datetime
    fomc: Fomc | None
    fomc_error: str | None
    spread: YieldSpread | None
    spread_error: str | None


def meetings(page: str) -> list[Fomc]:
    """Scheduled meetings on the Fed calendar page; '*' marks economic projections."""
    out = []
    year = 0
    for block in re.split(r"(\d{4}) FOMC Meetings", page)[1:]:
        if block.isdigit():
            year = int(block)
            continue
        rows = re.findall(
            r'fomc-meeting__month[^>]*>\s*(?:<strong>)?\s*([A-Za-z/]+)\s*(?:</strong>)?\s*</div>'
            r'\s*<div class="fomc-meeting__date[^>]*>\s*([^<]+?)\s*<',
            block,
        )
        for months, days in rows:
            match = re.fullmatch(r"(\d{1,2})-(\d{1,2})(\*?)", days)
            if not match or any(m not in MONTHS for m in months.split("/")):
                continue  # unscheduled or notation votes carry other labels
            last_month = MONTHS[months.split("/")[-1]]
            end = date(year, last_month, int(match.group(2)))
            out.append(
                Fomc(
                    decision_at=datetime.combine(end, DECISION, EASTERN).astimezone(UTC),
                    meeting=f"{months} {match.group(1)}-{match.group(2)}, {year}",
                    projections=bool(match.group(3)),
                )
            )
    return sorted(out, key=lambda m: m.decision_at)


def next_fomc(page: str, now: datetime) -> Fomc:
    upcoming = [m for m in meetings(page) if m.decision_at > now]
    if not upcoming:
        raise ValueError("no upcoming FOMC meeting on the Fed calendar")
    return upcoming[0]


def yield_spread(text: str) -> YieldSpread:
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        day = row.get("observation_date") or row.get("DATE")
        ten, one = row.get("DGS10", ""), row.get("DGS1", "")
        try:
            rows.append((date.fromisoformat(day or ""), float(ten), float(one)))
        except ValueError:
            continue  # FRED leaves holidays blank or '.'
    if not rows:
        raise ValueError("no DGS10/DGS1 observations")
    day, ten, one = rows[-1]
    return YieldSpread(
        day=day,
        ten_year=ten,
        one_year=one,
        spread=round(ten - one, 2),
        inverted=ten < one,
        history=[SpreadPoint(day=d, spread=round(t - o, 2)) for d, t, o in rows[-SPREAD_DAYS:]],
    )


def http_get(url: str) -> str:
    # FRED stalls requests whose User-Agent imitates a browser; the default one is served.
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    return response.text


def build_macro(checked_at: datetime, get: Get = http_get) -> MacroWatch:
    fomc = spread = None
    fomc_error = spread_error = None
    try:
        fomc = next_fomc(get(FOMC_URL), checked_at)
    except (httpx.HTTPError, ValueError) as exc:
        fomc_error = str(exc) or type(exc).__name__
    try:
        spread = yield_spread(get(FRED_URL))
    except (httpx.HTTPError, ValueError) as exc:
        spread_error = str(exc) or type(exc).__name__
    return MacroWatch(
        checked_at=checked_at,
        fomc=fomc,
        fomc_error=fomc_error,
        spread=spread,
        spread_error=spread_error,
    )
