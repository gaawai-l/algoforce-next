"""Daily on-chain series from bitview.space (Bitcoin Research Kit): public, read-only."""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import httpx

BITVIEW = "https://bitview.space/api/series/{}/day1"
EPOCH = date(2009, 1, 1)  # index 0 of bitview's day1 series

Daily = dict[str, list[float | None]]


class OnchainError(Exception):
    pass


def fetch_daily(names: Sequence[str], *, since: date, now: datetime) -> Daily:
    """Series from `since` through the last complete UTC day; bitview's current day is partial."""
    start = (since - EPOCH).days

    def one(client: httpx.Client, name: str) -> list[float | None]:
        response = client.get(BITVIEW.format(name), params={"start": start, "format": "json"})
        response.raise_for_status()
        body = response.json()
        if (
            not isinstance(body, dict)
            or body.get("index") != "day1"
            or body.get("start") != start
            or not isinstance(body.get("data"), list)
        ):
            raise OnchainError(f"unexpected bitview payload for {name}")
        return [None if v is None else float(v) for v in body["data"]]

    try:
        with httpx.Client(timeout=15) as client, ThreadPoolExecutor(max_workers=6) as pool:
            fetched = list(pool.map(lambda n: one(client, n), names))
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise OnchainError(str(exc)) from exc
    complete = (now.astimezone(UTC).date() - EPOCH).days - start
    length = min([complete, *(len(values) for values in fetched)])
    if length <= 0:
        raise OnchainError("no complete day from bitview")
    return {name: values[:length] for name, values in zip(names, fetched, strict=True)}


def last_day(since: date, series: Daily) -> date:
    return since + timedelta(days=len(next(iter(series.values()))) - 1)
