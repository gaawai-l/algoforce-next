"""Stored perp inputs folded into the 10m grid: mapping, data edge, coverage and liquidations."""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wheelhouse_service.perps.grid import REQUIRED, build_grid
from wheelhouse_service.perps.rows import Exchange, Kline, OiPoint, RawLiquidation, Stream, Trade
from wheelhouse_service.perps.states import Grid
from wheelhouse_service.perps.store import PerpsStore, Venue

STEP = 600
T0 = 1_792_022_400  # 2026-10-15 00:00 UTC
FIXTURE = Path(__file__).parent / "fixtures" / "public-2026-10-15"


def at(hm: str) -> int:
    hours, minutes = hm.split(":")
    return T0 + int(hours) * 3600 + int(minutes) * 60


def idx(hm: str) -> int:
    return (at(hm) - T0) // STEP


@pytest.fixture
def store(tmp_path: Path) -> PerpsStore:
    return PerpsStore(tmp_path / "perps.sqlite3")


def grid_of(store: PerpsStore, exchange: Exchange, start: int = T0) -> Grid:
    grid = build_grid(store, exchange, start)
    assert isinstance(grid, Grid), grid
    return grid


# --- Synthetic rows: every 5m from `first` to `last` inclusive. ---


def spot(store: PerpsStore, first: int, last: int, close: float = 100.0) -> None:
    store.upsert_klines(
        "bybit",
        [
            Kline(t=t, close=close, volume=None, taker_buy=None, source="bybit_spot")
            for t in range(first, last + 1, 300)
        ],
    )


def perp(store: PerpsStore, first: int, last: int, volume: float = 10.0, buy: float = 6.0) -> None:
    store.upsert_klines(
        "binance",
        [
            Kline(t=t, close=100.0, volume=volume, taker_buy=buy, source="binance_perp")
            for t in range(first, last + 1, 300)
        ],
    )


def oi(
    store: PerpsStore, venue: Venue, first: int, last: int, value: float | None = 1000.0
) -> None:
    source = "bybit" if venue == "bybit" else "hist"
    store.upsert_oi(
        venue,
        [
            OiPoint.model_validate({"t": t, "oi": value, "source": source})
            for t in range(first, last + 1, 300)
        ],
    )


def rest(store: PerpsStore, last: int) -> None:
    """Every REST series from T0, so that each view's last bucket is `last`."""
    spot(store, T0, last + 300)
    perp(store, T0, last + 300)
    oi(store, "binance", T0, last + STEP)
    oi(store, "bybit", T0, last + STEP, value=500.0)


def cover(store: PerpsStore, stream: Stream, start: float, end: float, conn: int = 0) -> None:
    store.extend_coverage(store.open_coverage(stream, conn, start), end)


def binance_liq(
    ts: float, side: str, z: str, status: str = "FILLED", ap: str = "80000"
) -> RawLiquidation:
    ms = int(ts * 1000)
    raw = {
        "s": "BTCUSDT",
        "S": side,
        "o": "LIMIT",
        "f": "IOC",
        "q": z,
        "p": "79900",
        "ap": ap,
        "X": status,
        "l": z,
        "z": z,
        "T": ms,
        "ps": "BTCUSDT",
        "st": 1,
    }
    return RawLiquidation(event_ts=ts, key=f"{ms}|{side}|{z}|{ap}", raw=json.dumps(raw))


def bybit_liq(ts: float, side: str, v: str, p: str = "80000") -> RawLiquidation:
    ms = int(ts * 1000)
    raw = {"T": ms, "s": "BTCUSDT", "S": side, "v": v, "p": p}
    return RawLiquidation(event_ts=ts, key=f"{ms}|{side}|{v}|{p}", raw=json.dumps(raw))


# --- Public fixture, 2026-10-15. ---


def load_public(store: PerpsStore, *, hist: bool = True) -> None:
    klines = json.loads((FIXTURE / "binance_klines_5m.json").read_text())
    store.upsert_klines(
        "binance",
        [
            Kline(
                t=k[0] // 1000,
                close=float(k[4]),
                volume=float(k[5]),
                taker_buy=float(k[9]),
                source="binance_perp",
            )
            for k in klines
        ],
    )
    bybit = json.loads((FIXTURE / "bybit_spot_klines_5m.json").read_text())["result"]["list"]
    store.upsert_klines(
        "bybit",
        [
            Kline(
                t=int(r[0]) // 1000,
                close=float(r[4]),
                volume=None,
                taker_buy=None,
                source="bybit_spot",
            )
            for r in bybit
        ],
    )
    if hist:
        rows = json.loads((FIXTURE / "binance_oi_hist_5m.json").read_text())
        store.upsert_oi(
            "binance",
            [
                OiPoint(t=r["timestamp"] // 1000, oi=float(r["sumOpenInterest"]), source="hist")
                for r in rows
            ],
        )


def test_grid_public_1015(store: PerpsStore):
    load_public(store)
    grid = grid_of(store, "binance")

    # OI's last row (23:55) maps to no bucket, so OI ends at 23:40; the klines end at 23:50.
    assert grid.start == T0
    assert grid.last == at("23:40")
    assert len(grid.price) == idx("23:40") + 1
    # price: the spot close of the bar opening at t+5m; oi: hist at t+10m;
    # vd: 2·takerBuy − volume over the bars opening at t and t+5m.
    assert grid.price[idx("00:00")] == 81741.4
    assert grid.oi[idx("00:00")] == 93112.742
    assert grid.vd[idx("00:00")] == pytest.approx((2 * 205.552 - 352.686) + (2 * 162.715 - 349.857))
    assert grid.price[idx("12:00")] == 80903.9
    assert grid.oi[idx("12:00")] == 92212.143
    assert grid.vd[idx("12:00")] == pytest.approx((2 * 172.008 - 402.579) + (2 * 160.971 - 272.569))
    assert grid.price[idx("23:40")] == 82195.0
    assert grid.oi[idx("23:40")] == 94418.15
    assert grid.vd[idx("23:40")] == pytest.approx((2 * 30.440 - 70.575) + (2 * 56.774 - 87.320))
    assert None not in grid.price + grid.oi + grid.vd
    # Nothing collected: liquidations uncovered, never 0; Binance's delta needs no collector.
    assert set(grid.long_liq) == set(grid.short_liq) == {None}
    assert not any(grid.liq_covered)
    assert all(grid.vd_covered)
    assert grid.rest_series == {
        "bybit:price": grid.price,
        "binance:oi": grid.oi,
        "binance:kline": grid.vd,
    }
    assert grid.quarantined_days == 0


def test_grid_archive_quarantine_1015(store: PerpsStore):
    """The daily archive alone, quarantined from its first anomaly (10:50) as sources would."""
    load_public(store, hist=False)
    with (FIXTURE / "BTCUSDT-metrics-2026-10-15.csv").open() as handle:
        rows = sorted(csv.DictReader(handle), key=lambda r: r["create_time"])
    archive = []
    for row in rows:
        created = datetime.strptime(row["create_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        value = (
            None if row["create_time"] >= "2026-10-15 10:50:00" else float(row["sum_open_interest"])
        )
        archive.append(OiPoint(t=int(created.timestamp()) + 300, oi=value, source="archive"))
    store.upsert_oi("binance", archive)

    grid = grid_of(store, "binance")
    # The quarantined 23:55 row is stored at 00:00 and still counts toward the edge.
    assert grid.last == at("23:50")
    assert grid.oi[idx("10:40")] == 92072.082  # equal to hist at 10:50
    assert grid.oi[idx("10:50") :] == [None] * (idx("23:50") - idx("10:50") + 1)
    assert grid.quarantined_days == 1

    load_public(store)  # hist replaces the archive rows it has
    with_hist = grid_of(store, "binance")
    hist_only = json.loads((FIXTURE / "binance_oi_hist_5m.json").read_text())
    by_t = {r["timestamp"] // 1000: float(r["sumOpenInterest"]) for r in hist_only}
    assert with_hist.oi[: idx("23:40") + 1] == [
        by_t[t + STEP] for t in range(T0, at("23:40") + 1, STEP)
    ]
    # Hist has no 10-16 00:00 row, so the quarantined archive row there remains.
    assert with_hist.oi[idx("23:50")] is None
    assert with_hist.quarantined_days == 1


def test_grid_edge_is_min_of_series_last(store: PerpsStore):
    spot(store, T0, at("00:55"))  # price through 00:50
    perp(store, T0, at("00:25"))  # vd through 00:20
    oi(store, "binance", T0, at("00:40"))  # oi through 00:30
    oi(store, "bybit", T0, at("01:00"))  # oi through 00:50

    assert grid_of(store, "binance").last == at("00:20")
    assert grid_of(store, "bybit").last == at("00:50")
    assert grid_of(store, "all").last == at("00:20")

    perp(store, T0, at("00:55"))
    assert grid_of(store, "binance").last == at("00:30")
    assert grid_of(store, "all").last == at("00:30")


def test_price_and_vd_need_both_bars(store: PerpsStore):
    rest(store, at("00:50"))
    with store.connection(write=True) as db:
        db.execute("DELETE FROM kline WHERE venue='bybit' AND t=?", (at("00:10"),))
        db.execute("DELETE FROM kline WHERE venue='binance' AND t=?", (at("00:25"),))
    grid = grid_of(store, "binance")
    assert grid.price[idx("00:00")] is not None
    assert grid.price[idx("00:10")] is None  # its first bar is missing
    assert grid.price[idx("00:00")] == grid.price[idx("00:30")] == 100.0
    assert grid.vd[idx("00:20")] is None  # its second bar is missing
    assert grid.vd[idx("00:10")] == 2 * (2 * 6.0 - 10.0)


def test_bucket_coverage_union_one_connection_down_vs_both(store: PerpsStore):
    rest(store, at("01:50"))
    # Connection 0 drops at 1500 s and again at 3200 s; connection 1 is down from 3000 s to 3700 s.
    cover(store, "binance_liq", T0, T0 + 1500, conn=0)
    cover(store, "binance_liq", T0 + 1700, T0 + 3200, conn=0)
    cover(store, "binance_liq", T0 + 3800, T0 + 6000, conn=0)
    cover(store, "binance_liq", T0 + 60, T0 + 3000, conn=1)
    cover(store, "binance_liq", T0 + 3700, T0 + 6000, conn=1)

    grid = grid_of(store, "binance")
    # Union: [0, 3200] and [3700, 6000]. A bucket counts only if it lies wholly inside.
    expected = [True] * 5 + [False] * 2 + [True] * 3 + [False] * 2
    assert grid.liq_covered == expected
    assert grid.long_liq == [0.0 if c else None for c in expected]
    assert grid.short_liq == grid.long_liq


def test_liquidation_max_count_per_connection(store: PerpsStore):
    rest(store, at("00:50"))
    cover(store, "binance_liq", T0, T0 + 3600, conn=0)
    cover(store, "binance_liq", T0, T0 + 3600, conn=1)
    twin = binance_liq(T0 + 100, "SELL", "0.5")
    missed = binance_liq(T0 + 200, "SELL", "0.2")
    # Two real liquidations share a key; connection 1 saw one of them and one that 0 missed.
    store.insert_liquidations("binance", 0, [twin, twin])
    store.insert_liquidations("binance", 1, [twin, missed])

    grid = grid_of(store, "binance")
    assert grid.long_liq[0] == pytest.approx(2 * 0.5 + 0.2)
    assert grid.short_liq[0] == 0.0
    assert grid.long_liq[1:] == [0.0] * 5


def test_binance_filled_only_and_sides(store: PerpsStore):
    rest(store, at("00:50"))
    cover(store, "binance_liq", T0, T0 + 3600)
    store.insert_liquidations(
        "binance",
        0,
        [
            binance_liq(T0 + 10, "SELL", "0.5"),  # a long position liquidated
            binance_liq(T0 + 20, "BUY", "0.3"),  # a short position liquidated
            binance_liq(T0 + 30, "SELL", "0.1", status="PARTIALLY_FILLED"),
            binance_liq(T0 + 610, "BUY", "0.7", status="NEW"),
            binance_liq(T0 + 620, "BUY", "0.4"),
        ],
    )
    grid = grid_of(store, "binance")
    assert grid.long_liq[:2] == [0.5, 0.0]
    assert grid.short_liq[:2] == [0.3, 0.4]


def test_bybit_sides_and_qty(store: PerpsStore):
    rest(store, at("00:50"))
    cover(store, "bybit_liq", T0, T0 + 3600)
    store.insert_liquidations(
        "bybit",
        0,
        [
            bybit_liq(T0 + 10, "Buy", "0.4"),  # a long position liquidated
            bybit_liq(T0 + 20, "Buy", "0.15"),
            bybit_liq(T0 + 30, "Sell", "0.25"),  # a short position liquidated
        ],
    )
    grid = grid_of(store, "bybit")
    assert grid.long_liq[0] == pytest.approx(0.55)
    assert grid.short_liq[0] == 0.25
    assert grid.long_liq[1:] == grid.short_liq[1:] == [0.0] * 5


def test_covered_empty_bucket_is_zero_uncovered_is_none(store: PerpsStore):
    rest(store, at("00:50"))
    cover(store, "bybit_liq", T0, T0 + 1200)  # buckets 00:00 and 00:10
    cover(store, "bybit_trades", T0 + 600, T0 + 3600)  # buckets 00:10 to 00:50
    store.insert_liquidations(
        "bybit", 0, [bybit_liq(T0 + 700, "Buy", "1"), bybit_liq(T0 + 1300, "Sell", "2")]
    )
    store.record_trades(
        "bybit",
        [
            Trade(id="1", ts=T0 + 5, side="Buy", qty=9.0),  # in an uncovered bucket
            Trade(id="2", ts=T0 + 1250, side="Buy", qty=3.0),
            Trade(id="3", ts=T0 + 1260, side="Sell", qty=1.0),
        ],
    )
    grid = grid_of(store, "bybit")
    assert grid.liq_covered == [True, True, False, False, False, False]
    assert grid.long_liq == [0.0, 1.0, None, None, None, None]
    assert grid.short_liq == [0.0, 0.0, None, None, None, None]  # the 1300 s event is uncovered
    assert grid.vd_covered == [False, True, True, True, True, True]
    assert grid.vd == [None, 0.0, 2.0, 0.0, 0.0, 0.0]
    assert grid.rest_series == {"bybit:price": grid.price, "bybit:oi": grid.oi}


def test_null_rows_count_toward_last(store: PerpsStore):
    spot(store, T0, at("00:55"))
    perp(store, T0, at("00:55"))
    oi(store, "binance", T0, at("00:30"))
    store.upsert_oi(
        "binance",
        [OiPoint(t=t, oi=None, source="archive") for t in range(at("00:35"), at("00:50") + 1, 300)],
    )
    grid = grid_of(store, "binance")
    assert grid.last == at("00:40")  # from the NULL row at 00:50
    assert grid.oi == [1000.0] * 3 + [None] * 2
    assert grid.quarantined_days == 1


def test_missing_series_returned(store: PerpsStore):
    assert build_grid(store, "all", T0) == list(REQUIRED["all"])
    spot(store, T0, at("00:55"))
    perp(store, T0, at("00:55"))
    oi(store, "binance", T0, at("01:00"))
    oi(store, "bybit", T0 - 3600, T0 - 300)  # only rows before the start

    assert isinstance(build_grid(store, "binance", T0), Grid)
    assert build_grid(store, "bybit", T0) == ["bybit:oi"]
    assert build_grid(store, "all", T0) == ["bybit:oi"]
    assert REQUIRED == {
        "binance": ("bybit:price", "binance:oi", "binance:kline"),
        "bybit": ("bybit:price", "bybit:oi"),
        "all": ("bybit:price", "binance:oi", "binance:kline", "bybit:oi"),
    }


def test_all_view_none_if_any_venue_none(store: PerpsStore):
    rest(store, at("00:30"))
    store.upsert_oi("bybit", [OiPoint(t=at("00:20"), oi=None, source="bybit")])  # bucket 00:10
    cover(store, "binance_liq", T0, T0 + 2400)
    cover(store, "bybit_liq", T0 + 600, T0 + 2400)  # not bucket 00:00
    cover(store, "bybit_trades", T0, T0 + 1800)  # not bucket 00:30
    store.insert_liquidations("binance", 0, [binance_liq(T0 + 700, "SELL", "1")])
    store.insert_liquidations(
        "bybit", 0, [bybit_liq(T0 + 800, "Buy", "2"), bybit_liq(T0 + 5, "Sell", "4")]
    )
    store.record_trades("bybit", [Trade(id="1", ts=T0 + 1300, side="Sell", qty=0.5)])

    grid = grid_of(store, "all")
    bn_vd = 2 * (2 * 6.0 - 10.0)
    assert grid.oi == [1500.0, None, 1500.0, 1500.0]
    assert grid.rest_series["binance:oi"] == [1000.0] * 4
    assert grid.rest_series["bybit:oi"] == [500.0, None, 500.0, 500.0]
    assert grid.vd == [bn_vd, bn_vd, bn_vd - 0.5, None]
    assert grid.rest_series["binance:kline"] == [bn_vd] * 4
    assert grid.vd_covered == [True, True, True, False]
    assert grid.liq_covered == [False, True, True, True]
    assert grid.long_liq == [None, 3.0, 0.0, 0.0]
    assert grid.short_liq == [None, 0.0, 0.0, 0.0]
    assert list(grid.rest_series) == list(REQUIRED["all"])
