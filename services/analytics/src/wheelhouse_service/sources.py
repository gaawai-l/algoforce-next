"""Market adapters behind one normalized batch interface."""

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from .market import DURATIONS, Bar, Batch, Stream

FIXTURE_END = datetime(2026, 9, 25, tzinfo=UTC)


class FetchError(Exception):
    def __init__(self, code: str, *, retryable: bool = True) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class SourceAdapter(Protocol):
    def fetch(self, stream: Stream, now: datetime) -> Batch: ...


class FixtureSource:
    def fetch(self, stream: Stream, now: datetime) -> Batch:
        step = DURATIONS[stream.timeframe]
        end = min(FIXTURE_END, datetime.fromtimestamp(int(now.timestamp()) // step * step, UTC))
        scale = 84000 if stream.symbol == "BTCUSDT" else 3200
        bars = []
        for i in range(320):
            close_at = end - timedelta(seconds=(319 - i) * step)
            opened = close_at - timedelta(seconds=step)
            previous = scale * (1 + 0.025 * math.sin((i - 1) / 22) + 0.008 * math.sin((i - 1) / 4))
            close = scale * (1 + 0.025 * math.sin(i / 22) + 0.008 * math.sin(i / 4))
            bars.append(
                Bar(
                    open_time=opened,
                    close_time=close_at,
                    open=f"{previous:.2f}",
                    high=f"{max(previous, close) + scale * 0.001:.2f}",
                    low=f"{min(previous, close) - scale * 0.001:.2f}",
                    close=f"{close:.2f}",
                    volume=f"{500 + (i % 19) * 31:.6f}",
                    is_closed=True,
                )
            )
        return Batch(
            stream=stream,
            fetched_at=now,
            bars=bars,
            raw_payload={
                "generator": "fixture-v1",
                "count": 320,
                "seed": 0,
                "bars": [b.model_dump(mode="json") for b in bars],
            },
        )


class BinanceSource:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    @staticmethod
    def normalize(
        stream: Stream, rows: list[Any], fetched_at: datetime, *, closed_before: datetime
    ) -> Batch:
        bars = []
        for row in rows:
            opened = datetime.fromtimestamp(int(row[0]) / 1000, UTC)
            closed = datetime.fromtimestamp((int(row[6]) + 1) / 1000, UTC)
            bars.append(
                Bar(
                    open_time=opened,
                    close_time=closed,
                    open=str(row[1]),
                    high=str(row[2]),
                    low=str(row[3]),
                    close=str(row[4]),
                    volume=None if row[5] is None else str(row[5]),
                    is_closed=closed <= closed_before,
                )
            )
        return Batch(
            stream=stream,
            fetched_at=fetched_at,
            bars=bars,
            raw_payload={
                "endpoint": "/fapi/v1/klines",
                "rows": rows,
                "closed_before": closed_before.isoformat(),
            },
        )

    def fetch(self, stream: Stream, now: datetime) -> Batch:
        if stream.venue != "binance-usdm-perpetual":
            raise FetchError("unsupported_market", retryable=False)
        try:
            requested_at = datetime.now(UTC)
            if self.client:
                response = self.client.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={"symbol": stream.symbol, "interval": stream.timeframe, "limit": 500},
                )
            else:
                with httpx.Client(timeout=5, follow_redirects=False) as client:
                    response = client.get(
                        "https://fapi.binance.com/fapi/v1/klines",
                        params={
                            "symbol": stream.symbol,
                            "interval": stream.timeframe,
                            "limit": 500,
                        },
                    )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise ValueError("Invalid OHLCV envelope")
            # Acquisition time follows response receipt, not request dispatch.
            return self.normalize(
                stream, rows, datetime.now(UTC), closed_before=requested_at - timedelta(seconds=2)
            )
        except httpx.HTTPError as exc:
            raise FetchError("provider_unavailable") from exc
        except (ValueError, ValidationError, IndexError, KeyError, TypeError) as exc:
            raise FetchError("provider_invalid_data", retryable=False) from exc


class BybitSource:
    INTERVALS = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    @staticmethod
    def normalize(
        stream: Stream, rows: list[Any], fetched_at: datetime, *, closed_before: datetime
    ) -> Batch:
        bars = []
        for row in sorted(rows, key=lambda item: int(item[0])):
            opened = datetime.fromtimestamp(int(row[0]) / 1000, UTC)
            closed = opened + timedelta(seconds=DURATIONS[stream.timeframe])
            bars.append(
                Bar(
                    open_time=opened,
                    close_time=closed,
                    open=str(row[1]),
                    high=str(row[2]),
                    low=str(row[3]),
                    close=str(row[4]),
                    volume=str(row[5]),
                    is_closed=closed <= closed_before,
                )
            )
        return Batch(
            stream=stream,
            fetched_at=fetched_at,
            bars=bars,
            raw_payload={
                "endpoint": "/v5/market/kline",
                "category": "spot",
                "rows": rows,
                "closed_before": closed_before.isoformat(),
            },
        )

    def fetch(self, stream: Stream, now: datetime) -> Batch:
        if stream.source != "bybit" or stream.venue != "bybit-spot":
            raise FetchError("unsupported_market", retryable=False)
        params = {
            "category": "spot",
            "symbol": stream.symbol,
            "interval": self.INTERVALS[stream.timeframe],
            "limit": 500,
        }
        try:
            requested_at = datetime.now(UTC)
            if self.client:
                response = self.client.get("https://api.bybit.com/v5/market/kline", params=params)
            else:
                with httpx.Client(timeout=5, follow_redirects=False) as client:
                    response = client.get("https://api.bybit.com/v5/market/kline", params=params)
            response.raise_for_status()
            body = response.json()
            if body.get("retCode") in {10006, 10016}:
                raise FetchError("provider_unavailable")
            result = body.get("result", {})
            if (
                body.get("retCode") != 0
                or result.get("category") != "spot"
                or result.get("symbol") != stream.symbol
            ):
                raise ValueError("Invalid Bybit market response")
            rows = result.get("list")
            if not isinstance(rows, list) or not rows:
                raise ValueError("Empty or invalid OHLCV envelope")
            return self.normalize(
                stream, rows, datetime.now(UTC), closed_before=requested_at - timedelta(seconds=2)
            )
        except httpx.HTTPError as exc:
            raise FetchError("provider_unavailable") from exc
        except (
            ValueError,
            ValidationError,
            IndexError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            raise FetchError("provider_invalid_data", retryable=False) from exc


def fetch_market(stream: Stream, now: datetime) -> Batch:
    adapters: dict[str, SourceAdapter] = {
        "fixture": FixtureSource(),
        "binance": BinanceSource(),
        "bybit": BybitSource(),
    }
    return adapters[stream.source].fetch(stream, now)
