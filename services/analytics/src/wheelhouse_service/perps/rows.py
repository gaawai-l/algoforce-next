"""Rows the perp sources, collectors and store pass around, before they are folded into a grid."""

from typing import Literal

from ..market import Model

# The exchange views a page can show: Binance or Bybit on its own, All venues (Binance, Bybit and
# OKX summed), or Hyperliquid with its liquidations estimated from All's.
Exchange = Literal["all", "binance", "bybit", "hyperliquid"]
# The collected WebSocket streams; each one's coverage is recorded on its own.
Stream = Literal["binance_liq", "bybit_liq", "bybit_trades"]
# The venues Coinalyze reports on, and the kinds of series read from it.
CzVenue = Literal["binance", "bybit", "okx", "hyperliquid"]
CzKind = Literal["liq", "ohlcv", "oi"]


class Kline(Model):
    """One closed 5m kline. Bybit spot klines carry only the close."""

    t: int  # open time, epoch seconds
    close: float
    volume: float | None
    taker_buy: float | None
    source: Literal["binance_perp", "bybit_spot"]


class OiPoint(Model):
    """Open interest in BTC, timestamped the way Binance's openInterestHist stamps its rows."""

    t: int  # epoch seconds
    oi: float | None
    source: Literal["hist", "archive", "bybit"]


class RawLiquidation(Model):
    """One liquidation as the exchange sent it; side and size are mapped when deriving."""

    event_ts: float  # epoch seconds: Binance `o.T`, Bybit `T`
    # The raw fields joined with "|": Binance `T|S|z|ap`, Bybit `T|S|v|p`.
    key: str
    # JSON text: Binance's `o` object, or one element of Bybit's `data` list.
    raw: str


class Trade(Model):
    """One Bybit taker trade, in BTC."""

    id: str
    ts: float  # epoch seconds
    side: Literal["Buy", "Sell"]
    qty: float


class CzPoint(Model):
    """One closed Coinalyze interval, in BTC. liq: a = longs, b = shorts liquidated;
    ohlcv: a = volume, b = taker buy volume; oi: a = open, b = close interest."""

    t: int  # interval start, epoch seconds
    a: float
    b: float
    # liq only: inside a fetched range but absent from Coinalyze's reply, so stored as 0.
    filled: bool = False
