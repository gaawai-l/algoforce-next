"""Public Binance and Bybit REST data for the perp states (spec §3.1 and §3.8), and the
authenticated Coinalyze GET (proposal §3.7).

Times are epoch seconds. A request window is half-open: `[start, end)` over the rows' own
timestamps. Nothing here retries: a failure raises `RestError` and the caller decides when to ask
again, after `RestError.until` if the host is backed off.
"""

import csv
import io
import logging
import math
import threading
import time
import zipfile
import zlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .rows import Kline, OiPoint

BINANCE_HOST = "fapi.binance.com"
ARCHIVE_HOST = "data.binance.vision"
BYBIT_HOST = "api.bybit.com"
CZ_HOST = "api.coinalyze.net"
SYMBOL = "BTCUSDT"
TIMEOUT = 20.0
BAR = 300  # one 5m kline or OI period
# No wait is longer than this, whatever Retry-After asks (Binance bans last up to three days).
MAX_BACKOFF = timedelta(days=3)

# Rows per page; Binance's OI history documents 500 and its klines 1500.
PAGE_LIMITS = {
    "binance_klines": 1500,
    "binance_oi_hist": 500,
    "bybit_spot_klines": 1000,
    "bybit_oi": 200,
}
# Seconds to stay away from a host after an HTTP status (spec §3.8). A longer Retry-After wins.
BINANCE_BACKOFF = {429: 120, 418: 1800, 403: 1800}
# 403 is the spec's. The 429 is an addition to the §3.8 table: the same rate-limit signal.
BYBIT_BACKOFF = {403: 600, 429: 600}
# Coinalyze (proposal §3.7): 429 is its rate limit, 403 is Cloudflare. 401 is not listed: it is
# given up on for the round with no backoff, so a new key works at the next one.
CZ_BACKOFF = {429: 60, 403: 600}
BACKOFF = {
    BINANCE_HOST: BINANCE_BACKOFF,
    ARCHIVE_HOST: BINANCE_BACKOFF,
    BYBIT_HOST: BYBIT_BACKOFF,
    CZ_HOST: CZ_BACKOFF,
}
# Bybit answers 200 with these retCodes when the API or the IP limit is exceeded. The spec's
# table names 10006 and "etc."; 10018 is an addition to it, a documented rate-limit code.
RATE_LIMIT_RETCODES = frozenset({10006, 10018})
RETCODE_BACKOFF = 600

logger = logging.getLogger("wheelhouse.perps.sources")


class RestError(Exception):
    """A request that gave no usable data; `until` is set when its host is now backed off."""

    def __init__(self, host: str, code: str, until: datetime | None = None) -> None:
        self.host = host
        self.code = code  # "429", "network", "bad_response", "backoff", "retcode:10006", ...
        self.until = until
        super().__init__(f"{host}: {code}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


_SHAPE_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    csv.Error,
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
)


@contextmanager
def _malformed(host: str) -> Iterator[None]:
    """Turn a response that does not have the documented shape into a RestError."""
    try:
        yield
    except _SHAPE_ERRORS as exc:
        raise RestError(host, "bad_response") from exc


def _retry_after(response: httpx.Response, now: datetime) -> timedelta:
    """The wait a Retry-After header asks for, in (possibly fractional) seconds or as an HTTP
    date; zero if absent or not usable.

    Never more than MAX_BACKOFF, so that no value can overflow a date.
    """
    value = response.headers.get("Retry-After")
    if value is None:
        return timedelta(0)
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return timedelta(0)
        wait = when.replace(tzinfo=when.tzinfo or UTC) - now
    else:
        if not math.isfinite(seconds):
            return timedelta(0)
        wait = timedelta(seconds=min(max(seconds, 0.0), MAX_BACKOFF.total_seconds()))
    return min(max(wait, timedelta(0)), MAX_BACKOFF)


class PerpsRest:
    """The perp REST calls, one at a time, backing off per host."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] = _utc_now,
        *,
        page_limits: Mapping[str, int] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock
        self._limits = {**PAGE_LIMITS, **(page_limits or {})}
        # Re-entrant: a Bybit call holds it from the request to the retCode check.
        self._lock = threading.RLock()
        self._until: dict[str, datetime] = {}

    def backoff_until(self, host: str) -> datetime | None:
        """When `host` may be asked again, or None if it is not backed off."""
        until = self._until.get(host)
        return until if until is not None and until > self._clock() else None

    def binance_klines(self, start: int, end: int) -> list[Kline]:
        """Closed 5m perp klines opening in [start, end), oldest first."""
        limit = self._limits["binance_klines"]
        found: dict[int, Kline] = {}
        cursor = start
        while cursor < end:
            now = self._clock().timestamp()
            rows = self._binance(
                "/fapi/v1/klines",
                {
                    "symbol": SYMBOL,
                    "interval": "5m",
                    "startTime": cursor * 1000,
                    "endTime": end * 1000 - 1,
                    "limit": limit,
                },
            )
            with _malformed(BINANCE_HOST):
                opened = [int(row[0]) // 1000 for row in rows]
                for t, row in zip(opened, rows, strict=True):
                    if t + BAR <= now:  # the current bar is returned too, unfinished
                        found[t] = Kline(
                            t=t,
                            close=float(row[4]),
                            volume=float(row[5]),
                            taker_buy=float(row[9]),
                            source="binance_perp",
                        )
            if len(rows) < limit or max(opened) < cursor:
                break
            cursor = max(opened) + BAR
        return [found[t] for t in sorted(found)]

    def binance_oi_hist(self, start: int) -> list[OiPoint]:
        """The OI history rows stamped from `start` up to now, oldest first.

        With only a `startTime` the endpoint returns the latest `limit` rows, not the ones after
        it (checked live 2026-10-16). So this asks for consecutive windows with both ends given:
        each is half-open and exactly `limit` periods wide (`endTime` is inclusive, hence the
        `- 1`), so it holds `limit` stamps whatever the alignment of `start`, and the next window
        begins where it ends.
        """
        limit = self._limits["binance_oi_hist"]
        now = self._clock().timestamp()
        found: dict[int, OiPoint] = {}
        cursor = start
        while cursor <= now:
            following = cursor + limit * BAR
            rows = self._binance(
                "/futures/data/openInterestHist",
                {
                    "symbol": SYMBOL,
                    "period": "5m",
                    "startTime": cursor * 1000,
                    "endTime": following * 1000 - 1,
                    "limit": limit,
                },
            )
            with _malformed(BINANCE_HOST):
                for row in rows:
                    t = int(row["timestamp"]) // 1000
                    found[t] = OiPoint(t=t, oi=float(row["sumOpenInterest"]), source="hist")
            cursor = following
        return [found[t] for t in sorted(found)]

    def binance_oi_archive(self, day: date) -> tuple[list[OiPoint], bool] | None:
        """One UTC day of the daily archive as OI points stamped create_time + 5m, oldest first.

        Rows are de-duplicated and sorted, then quarantined (spec §3.1): from the first row that
        is not positive, or is the first of two equal ones in a row, to the end of the file, the
        points are kept with `oi` None. The flag says whether any were. None if there is no
        file for `day`; a file with no rows is a bad response.
        """
        name = f"{SYMBOL}-metrics-{day.isoformat()}"
        try:
            response = self._get(
                ARCHIVE_HOST, f"/data/futures/um/daily/metrics/{SYMBOL}/{name}.zip"
            )
        except RestError as exc:
            if exc.code == "404":
                return None
            raise
        with _malformed(ARCHIVE_HOST):
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                text = archive.read(f"{name}.csv").decode()
            by_time: dict[int, float] = {}
            for row in csv.DictReader(io.StringIO(text)):
                created = datetime.strptime(row["create_time"], "%Y-%m-%d %H:%M:%S")
                by_time.setdefault(int(created.replace(tzinfo=UTC).timestamp()), _number(row))
        if not by_time:
            raise RestError(ARCHIVE_HOST, "bad_response")
        times = sorted(by_time)
        values = [by_time[t] for t in times]
        first_bad = next(
            (
                i
                for i, value in enumerate(values)
                if not 0 < value < math.inf or (i + 1 < len(values) and values[i + 1] == value)
            ),
            len(values),
        )
        points = [
            OiPoint(t=t + BAR, oi=value if i < first_bad else None, source="archive")
            for i, (t, value) in enumerate(zip(times, values, strict=True))
        ]
        return points, first_bad < len(values)

    def bybit_spot_klines(self, start: int, end: int) -> list[Kline]:
        """Closed 5m spot klines opening in [start, end), oldest first.

        Of the rows in the range Bybit returns the NEWEST `limit`, newest first (checked live
        2026-10-16: start 20 bars before the end, limit 3 gave the last three bars). So the
        paging walks backwards: each page asks for what lies before the oldest row of the last.
        """
        limit = self._limits["bybit_spot_klines"]
        found: dict[int, Kline] = {}
        upper = end
        while start < upper:
            now = self._clock().timestamp()
            result = self._bybit(
                "/v5/market/kline",
                {
                    "category": "spot",
                    "symbol": SYMBOL,
                    "interval": "5",
                    "start": start * 1000,
                    "end": upper * 1000 - 1,
                    "limit": limit,
                },
            )
            with _malformed(BYBIT_HOST):
                rows = result["list"]
                opened = [int(row[0]) // 1000 for row in rows]
                for t, row in zip(opened, rows, strict=True):
                    if t + BAR <= now:
                        found[t] = Kline(
                            t=t,
                            close=float(row[4]),
                            volume=None,
                            taker_buy=None,
                            source="bybit_spot",
                        )
            # Newest first: the next page is whatever lies before the oldest row of this one.
            if len(rows) < limit or min(opened) >= upper:
                break
            upper = min(opened)
        return [found[t] for t in sorted(found)]

    def bybit_oi(self, start: int, end: int) -> list[OiPoint]:
        """Single-sided OI points stamped in [start, end), oldest first."""
        params: dict[str, str | int] = {
            "category": "linear",
            "symbol": SYMBOL,
            "intervalTime": "5min",
            "startTime": start * 1000,
            "endTime": end * 1000 - 1,
            "limit": self._limits["bybit_oi"],
        }
        found: dict[int, OiPoint] = {}
        used: set[str] = set()
        while True:
            result = self._bybit("/v5/market/open-interest", params)
            with _malformed(BYBIT_HOST):
                rows = result["list"]
                for row in rows:
                    # `openInterest` counts both sides; Binance's figure is single-sided.
                    t = int(row["timestamp"]) // 1000
                    found[t] = OiPoint(t=t, oi=float(row["singleOpenInterest"]), source="bybit")
                cursor = result.get("nextPageCursor")
            if not rows or not cursor or cursor in used:
                break
            used.add(cursor)
            params = {**params, "cursor": cursor}
        return [found[t] for t in sorted(found)]

    def coinalyze(self, path: str, params: Mapping[str, str | int], key: str) -> Any:
        """GET https://api.coinalyze.net{path} with the key in the `api_key` header only; the
        parsed JSON body. Errors and backoff as `_get`."""
        response = self._get(CZ_HOST, path, params, {"api_key": key})
        with _malformed(CZ_HOST):
            return response.json()

    def _binance(self, path: str, params: Mapping[str, str | int]) -> list[Any]:
        response = self._get(BINANCE_HOST, path, params)
        with _malformed(BINANCE_HOST):
            body = response.json()
        if not isinstance(body, list):
            raise RestError(BINANCE_HOST, "bad_response")
        return body

    def _bybit(self, path: str, params: Mapping[str, str | int]) -> dict[str, Any]:
        """The `result` of a Bybit reply; a non-zero retCode is an error, a limit one a backoff."""
        with self._lock:  # the backoff it may set must land before another request can go
            response = self._get(BYBIT_HOST, path, params)
            with _malformed(BYBIT_HOST):
                body = response.json()
                code = int(body["retCode"])
                result = body.get("result")
            if code != 0:
                self._log(BYBIT_HOST, path, f"retcode:{code}")
                limited = code in RATE_LIMIT_RETCODES
                until = self._back_off(BYBIT_HOST, RETCODE_BACKOFF, response) if limited else None
                raise RestError(BYBIT_HOST, f"retcode:{code}", until)
        if not isinstance(result, dict):
            raise RestError(BYBIT_HOST, "bad_response")
        return result

    def _get(
        self,
        host: str,
        path: str,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """One GET; raises unless the status is 2xx, and backs the host off for the listed ones.

        `headers` go on this request only, never into the client's defaults.
        """
        with self._lock:
            until = self.backoff_until(host)
            if until is not None:
                self._log(host, path, "backoff")
                raise RestError(host, "backoff", until)
            started = time.perf_counter()
            try:
                response = self._send(f"https://{host}{path}", params, headers)
            except httpx.RequestError as exc:
                self._log(host, path, "network", started)
                raise RestError(host, "network") from exc
            if response.is_success:
                self._log(host, path, "ok", started)
                return response
            code = str(response.status_code)
            self._log(host, path, code, started)
            seconds = BACKOFF[host].get(response.status_code)
            if seconds is None:
                raise RestError(host, code)
            raise RestError(host, code, self._back_off(host, seconds, response))

    def _back_off(self, host: str, seconds: int, response: httpx.Response) -> datetime:
        with self._lock:
            now = self._clock()
            wait = max(timedelta(seconds=seconds), _retry_after(response, now))
            self._until[host] = now + wait
            return self._until[host]

    def _send(
        self,
        url: str,
        params: Mapping[str, str | int] | None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, params=params, headers=headers, timeout=TIMEOUT)
        with httpx.Client(follow_redirects=False) as client:
            return client.get(url, params=params, headers=headers, timeout=TIMEOUT)

    @staticmethod
    def _log(host: str, path: str, outcome: str, started: float | None = None) -> None:
        # Host, route, outcome and duration only; never query values or payloads.
        elapsed = (
            ""
            if started is None
            else f" duration_ms={round((time.perf_counter() - started) * 1000)}"
        )
        logger.info("perps_request host=%s path=%s outcome=%s%s", host, path, outcome, elapsed)


def _number(row: Mapping[str, str]) -> float:
    """The row's `sum_open_interest`; NaN if it is not a number, which counts as an anomaly."""
    try:
        return float(row["sum_open_interest"])
    except ValueError:
        return float("nan")
