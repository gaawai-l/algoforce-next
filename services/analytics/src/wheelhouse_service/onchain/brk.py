"""Client for the public Bitcoin Research Kit (BRK) API at bitview.space."""

import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import httpx
from pydantic import AwareDatetime, ConfigDict, ValidationError

from ..market import Model

BASE_URL = "https://bitview.space"
TIMEOUT = 20.0
# A bulk request is rejected above 320,000 weight (about 16 per point), so chunks stay below this.
MAX_POINTS = 18_000
START = date(2013, 1, 1)
# Position 0 of both day1 and hour1.
EPOCH = datetime(2009, 1, 1, tzinfo=UTC)
DAY1_SERIES = (
    "price_close",
    "true_market_mean",
    "sth_realized_price",
    "lth_realized_price",
    "realized_price",
    "utxos_1d_to_1w_old_realized_price",
)
# Time comes from the position, so no timestamp series is fetched.
HOUR1_SERIES = (
    "price_close",
    "sth_realized_profit_cumulative",
    "sth_realized_loss_cumulative",
    "lth_realized_profit_cumulative",
    "lth_realized_loss_cumulative",
    "utxos_under_1h_old_realized_profit_cumulative",
    "utxos_under_1h_old_realized_loss_cumulative",
    "sth_supply_in_loss",
    "sth_supply_in_profit",
    "utxos_under_1h_old_supply_in_loss",
    "utxos_under_1h_old_supply_in_profit",
)
# First fill and full refetch of hour1 ask for the last N points (`start=-N`), never for `START`.
HOUR1_BACKFILL = 3000
URPD_COHORT = "all"
URPD_AGG = "lin500"
# The snapshots the cost basis needs: every cohort at every bucket width. The first one gives the
# median line and the day D that the others are fetched for.
URPD_SET: tuple[tuple[str, str], ...] = (
    (URPD_COHORT, URPD_AGG),
    ("sth", "lin500"),
    ("lth", "lin500"),
    ("all", "lin200"),
    ("sth", "lin200"),
    ("lth", "lin200"),
    ("all", "lin1000"),
    ("sth", "lin1000"),
    ("lth", "lin1000"),
)

Index = Literal["day1", "hour1"]

logger = logging.getLogger("wheelhouse.brk")


class BrkModel(Model):
    # Responses carry fields such as `type` and `weight` that are not modelled.
    model_config = ConfigDict(extra="ignore")


class SeriesData(BrkModel):
    version: int
    index: Index
    start: int
    end: int
    stamp: AwareDatetime
    data: list[float | None]


class UrpdBucket(BrkModel):
    price_floor: float
    supply: float
    realized_cap: float
    unrealized_pnl: float


class Urpd(BrkModel):
    cohort: str
    date: date
    aggregation: str
    close: float
    total_supply: float
    buckets: list[UrpdBucket]


class SeriesBatch(Model):
    found: dict[str, SeriesData]
    missing: list[str]


class BrkError(Exception):
    def __init__(self, code: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class _NotFound(BrkError):
    """HTTP 404; `error_code` is the `error.code` in the body, when there is one."""

    def __init__(self, error_code: str | None) -> None:
        super().__init__("brk_bad_request", False)
        self.error_code = error_code


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _error_code(response: httpx.Response) -> str | None:
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None
    return code if isinstance(code, str) else None


def _failure(response: httpx.Response) -> BrkError:
    status = response.status_code
    if status == 404:
        return _NotFound(_error_code(response))
    if status == 429 or status >= 500:
        return BrkError("brk_unavailable", True)
    return BrkError("brk_bad_request", False)


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise BrkError("brk_unavailable", True) from exc


class BrkClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = BASE_URL,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.client = client
        self.base_url = base_url
        self.clock = clock

    def version(self) -> str:
        body = _json(self._get("/version"))
        if not isinstance(body, str):
            raise BrkError("brk_unavailable", True)
        return body

    def series(self, names: Sequence[str], index: Index, start: int | date) -> SeriesBatch:
        """Fetch `names` from `start` through the latest position, in chunks under MAX_POINTS.

        A negative `start` asks BRK for the last `-start` points; each response still carries the
        absolute position of its first point.
        """
        size = max(1, MAX_POINTS // max(1, self._points(index, start)))
        found: dict[str, SeriesData] = {}
        missing: list[str] = []
        for offset in range(0, len(names), size):
            self._collect(names[offset : offset + size], index, start, found, missing)
        return SeriesBatch(found=found, missing=missing)

    def urpd(self, cohort: str, day: date, agg: str = "lin500") -> Urpd | None:
        try:
            response = self._get(f"/api/urpd/{cohort}/{day.isoformat()}", {"agg": agg})
        except _NotFound:
            return None
        try:
            return Urpd.model_validate(_json(response))
        except ValidationError as exc:
            raise BrkError("brk_unavailable", True) from exc

    def _points(self, index: Index, start: int | date) -> int:
        """Points one series returns for `start`, assuming the latest position is now."""
        if not isinstance(start, date) and start < 0:
            return -start
        unit = timedelta(days=1) if index == "day1" else timedelta(hours=1)
        latest = (self.clock().astimezone(UTC) - EPOCH) // unit
        if isinstance(start, date):
            first = (datetime(start.year, start.month, start.day, tzinfo=UTC) - EPOCH) // unit
        else:
            first = start
        return latest - first + 1

    def _collect(
        self,
        names: Sequence[str],
        index: Index,
        start: int | date,
        found: dict[str, SeriesData],
        missing: list[str],
    ) -> None:
        batch = self._bulk(names, index, start)
        if batch is not None:
            found.update(batch)
        elif len(names) == 1:
            missing.append(names[0])
        else:
            # An unknown name fails the whole request, so ask for each name on its own.
            for name in names:
                self._collect([name], index, start, found, missing)

    def _bulk(
        self, names: Sequence[str], index: Index, start: int | date
    ) -> dict[str, SeriesData] | None:
        """None when BRK does not know one of `names`."""
        params = {
            "series": ",".join(names),
            "index": index,
            "start": start.isoformat() if isinstance(start, date) else str(start),
        }
        try:
            response = self._get("/api/series/bulk", params)
        except _NotFound as exc:
            if exc.error_code == "series_not_found":
                return None
            raise
        body = _json(response)
        # The response is an array in request order, without series names.
        if not isinstance(body, list) or len(body) != len(names):
            raise BrkError("brk_unavailable", True)
        try:
            return {
                name: SeriesData.model_validate(item)
                for name, item in zip(names, body, strict=True)
            }
        except ValidationError as exc:
            raise BrkError("brk_unavailable", True) from exc

    def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = self._send(path, params)
        except httpx.RequestError as exc:
            self._log(path, "brk_unavailable", started)
            raise BrkError("brk_unavailable", True) from exc
        if response.is_success:
            self._log(path, "ok", started)
            return response
        error = _failure(response)
        self._log(path, error.code, started)
        raise error

    def _send(self, path: str, params: dict[str, str] | None) -> httpx.Response:
        url = self.base_url + path
        if self.client is not None:
            return self.client.get(url, params=params, timeout=TIMEOUT)
        with httpx.Client(follow_redirects=False) as client:
            return client.get(url, params=params, timeout=TIMEOUT)

    @staticmethod
    def _log(path: str, outcome: str, started: float) -> None:
        # Route, outcome and duration only; never query values or payloads.
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.info("brk_request path=%s outcome=%s duration_ms=%d", path, outcome, duration_ms)
