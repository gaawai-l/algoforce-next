"""Coinalyze data for the perp states (proposal §2 and §3): liquidations, OHLCV and open interest
of the BTC perpetuals, in BTC, closed intervals only.

One request per data kind carries all of that kind's symbols. Nothing here retries or paces:
a failure raises `RestError`, and the caller decides when to ask again.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from ..market import Model
from .rows import CzKind, CzPoint, CzVenue
from .sources import CZ_HOST as CZ_HOST  # defined there for the backoff table; re-exported here
from .sources import PerpsRest, RestError, _malformed, _utc_now

SYMBOLS: dict[CzVenue, str] = {
    "binance": "BTCUSDT_PERP.A",
    "bybit": "BTCUSDT.6",
    "okx": "BTCUSDT_PERP.3",
    "hyperliquid": "BTC.H",
}
# Hyperliquid has no liquidation data on Coinalyze; Binance's volumes come from its own REST.
KIND_VENUES: dict[CzKind, tuple[CzVenue, ...]] = {
    "liq": ("binance", "bybit", "okx"),
    "ohlcv": ("bybit", "okx", "hyperliquid"),
    "oi": ("okx", "hyperliquid"),
}
Interval = Literal["5min", "4hour"]
STEPS: dict[Interval, int] = {"5min": 300, "4hour": 14_400}

PATHS: dict[CzKind, str] = {
    "liq": "/v1/liquidation-history",
    "ohlcv": "/v1/ohlcv-history",
    "oi": "/v1/open-interest-history",
}
# The reply fields that become CzPoint.a and CzPoint.b.
FIELDS: dict[CzKind, tuple[str, str]] = {"liq": ("l", "s"), "ohlcv": ("v", "bv"), "oi": ("o", "c")}
# Liquidations and open interest come in USD unless asked for in the contract's own unit.
IN_COINS: frozenset[CzKind] = frozenset({"liq", "oi"})
MARKETS_PATH = "/v1/future-markets"
BASE_ASSET = "BASE_ASSET"


class MarketCheck(Model):
    """What `/future-markets` says about one of the symbols read here."""

    venue: CzVenue
    symbol: str
    denominated: str | None  # oi_lq_vol_denominated_in; None if the symbol is not listed
    buy_sell: bool | None  # has_buy_sell_data; None if not listed
    ok: bool  # listed, BASE_ASSET, and buy/sell data where KIND_VENUES["ohlcv"] reads it


class Coinalyze:
    def __init__(
        self, rest: PerpsRest, key: str | None, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._rest = rest
        self._key = key
        self._clock = clock

    def history(
        self, kind: CzKind, interval: Interval, frm: int, to: int
    ) -> dict[CzVenue, list[CzPoint]]:
        """The closed intervals of `kind` starting in [frm, to], per venue, oldest first.

        A liquidation interval inside that range which Coinalyze left out, a whole symbol
        included (it omits the ones with nothing to report), is returned as a zero point with
        `filled` set. For OHLCV and open interest nothing is invented: a missing interval or
        symbol is simply not in the list.
        """
        key = self._require_key()
        step = STEPS[interval]
        venues = KIND_VENUES[kind]
        params: dict[str, str | int] = {
            "symbols": ",".join(SYMBOLS[venue] for venue in venues),
            "interval": interval,
            "from": frm,
            "to": to,
        }
        if kind in IN_COINS:
            params["convert_to_usd"] = "false"
        # Taken before the request: a bar that closes while it is in flight was still open when
        # the server answered, so it is neither kept nor zero-filled.
        now = self._clock().timestamp()
        body = self._rest.coinalyze(PATHS[kind], params, key)
        found = _closed_points(body, kind, step, now)
        if kind == "liq":
            first = -(-frm // step) * step  # frm rounded up to the interval grid
            for t in range(first, to + 1, step):
                if t + step > now:
                    break
                for venue in venues:
                    found[venue].setdefault(t, CzPoint(t=t, a=0.0, b=0.0, filled=True))
        return {venue: [found[venue][t] for t in sorted(found[venue])] for venue in venues}

    def markets(self) -> list[MarketCheck]:
        """One check per symbol read here, from the market list."""
        key = self._require_key()
        body = self._rest.coinalyze(MARKETS_PATH, {}, key)
        with _malformed(CZ_HOST):
            if not isinstance(body, list):
                raise RestError(CZ_HOST, "bad_response")
            wanted = set(SYMBOLS.values())
            listed = {row["symbol"]: row for row in body if row["symbol"] in wanted}
            checks = []
            for venue, symbol in SYMBOLS.items():
                row = listed.get(symbol)
                denominated = None if row is None else row["oi_lq_vol_denominated_in"]
                buy_sell = None if row is None else row["has_buy_sell_data"]
                needs_buy_sell = venue in KIND_VENUES["ohlcv"]
                checks.append(
                    MarketCheck(
                        venue=venue,
                        symbol=symbol,
                        denominated=denominated,
                        buy_sell=buy_sell,
                        ok=denominated == BASE_ASSET and (buy_sell is True or not needs_buy_sell),
                    )
                )
        return checks

    def _require_key(self) -> str:
        if not self._key:
            raise RestError(CZ_HOST, "key_missing")
        return self._key


def _closed_points(
    body: Any, kind: CzKind, step: int, now: float
) -> dict[CzVenue, dict[int, CzPoint]]:
    """The reply's points that have closed by `now` (t + step <= now), per venue and start time.

    A symbol that is not in the reply, or one that was not asked for, gives nothing.
    """
    venue_of = {SYMBOLS[venue]: venue for venue in KIND_VENUES[kind]}
    first, second = FIELDS[kind]
    found: dict[CzVenue, dict[int, CzPoint]] = {venue: {} for venue in KIND_VENUES[kind]}
    with _malformed(CZ_HOST):
        if not isinstance(body, list):
            raise RestError(CZ_HOST, "bad_response")
        for row in body:
            venue = venue_of.get(row["symbol"])
            if venue is None:
                continue
            history = row["history"]
            if not isinstance(history, list):
                raise RestError(CZ_HOST, "bad_response")
            for raw in history:
                point = CzPoint(t=int(raw["t"]), a=float(raw[first]), b=float(raw[second]))
                if point.t + step <= now:
                    found[venue][point.t] = point
    return found
