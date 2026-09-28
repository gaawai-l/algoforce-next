"""Two market adapters behind one normalized batch interface."""

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


def fetch_market(stream: Stream, now: datetime) -> Batch:
    adapter: SourceAdapter = FixtureSource() if stream.source == "fixture" else BinanceSource()
    return adapter.fetch(stream, now)
