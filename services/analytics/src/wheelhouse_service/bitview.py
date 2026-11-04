"""Daily on-chain series from bitview.space (Bitcoin Research Kit): public, read-only."""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import httpx

BITVIEW = "https://bitview.space/api/series/{}/day1"
EPOCH = date(2009, 1, 1)  # index 0 of bitview's day1 series

Daily = dict[str, list[float | None]]


# BRK's upgrade of 2026-10-30 renamed the age cohorts (`utxos_X_old_*` became `age_X_*`) and
# dropped the two unrealized-to-market-cap ratios, which are now the quotient of two series. The
# local names, the ones the indicators and fixtures use, stay; only requests use BRK's.
RATIOS = {
    "unrealized_profit_to_mcap_ratio": ("unrealized_profit", "market_cap"),
    "unrealized_loss_to_mcap_ratio": ("unrealized_loss", "market_cap"),
}


class OnchainError(Exception):
    pass


def remote_names(name: str) -> tuple[str, ...]:
    if name in RATIOS:
        return RATIOS[name]
    if name.startswith("utxos_") and "_old_" in name:
        return ("age_" + name.removeprefix("utxos_").replace("_old_", "_", 1),)
    return (name,)


def _ratio(numerator: list[float | None], denominator: list[float | None]) -> list[float | None]:
    return [
        None if n is None or not d else n / d
        for n, d in zip(numerator, denominator, strict=False)
    ]


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

    wanted = list(dict.fromkeys(part for name in names for part in remote_names(name)))
    try:
        with httpx.Client(timeout=15) as client, ThreadPoolExecutor(max_workers=6) as pool:
            remote = dict(zip(wanted, pool.map(lambda n: one(client, n), wanted), strict=True))
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise OnchainError(str(exc)) from exc
    fetched = [
        _ratio(*(remote[part] for part in parts)) if len(parts) == 2 else remote[parts[0]]
        for parts in map(remote_names, names)
    ]
    complete = (now.astimezone(UTC).date() - EPOCH).days - start
    length = min([complete, *(len(values) for values in fetched)])
    if length <= 0:
        raise OnchainError("no complete day from bitview")
    return {name: values[:length] for name, values in zip(names, fetched, strict=True)}


def last_day(since: date, series: Daily) -> date:
    return since + timedelta(days=len(next(iter(series.values()))) - 1)
