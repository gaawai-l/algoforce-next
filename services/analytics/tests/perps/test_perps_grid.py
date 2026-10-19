"""Stored perp inputs folded into the 10m grid: mapping, data edge, Coinalyze's windows placed on
the buckets, the composite views and the Hyperliquid estimate."""

import csv
import json
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wheelhouse_service.perps.grid import (
    H4,
    REQUIRED,
    VIEW_VENUES,
    build_grid,
    cz_delta,
    cz_liquidations,
    cz_oi,
    estimate_liquidations,
)
from wheelhouse_service.perps.rows import CzKind, CzPoint, CzVenue, Exchange, Kline, OiPoint
from wheelhouse_service.perps.states import Grid, compute_states
from wheelhouse_service.perps.store import PerpsStore, Venue
from wheelhouse_service.rules import Rules

STEP = 600
DAY = 86_400
M5 = 300
T0 = 1_792_022_400  # 2026-10-15 00:00 UTC
W = T0  # a 4h window
FIXTURE = Path(__file__).parent / "fixtures" / "public-2026-10-15"
V1: Rules = frozenset()
O1O6: Rules = frozenset({"O1", "O6"})


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
    # Nothing from Coinalyze: liquidations uncovered, never 0; Binance's delta is its klines'.
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


def test_price_reads_closing_bar_and_vd_needs_both_bars(store: PerpsStore):
    """Price is the close of the bar opening at t+5m alone; vd needs the bars at t and t+5m."""
    rest(store, at("00:50"))
    with store.connection(write=True) as db:
        db.execute("DELETE FROM kline WHERE venue='bybit' AND t=?", (at("00:10"),))
        db.execute("DELETE FROM kline WHERE venue='bybit' AND t=?", (at("00:35"),))
        db.execute("DELETE FROM kline WHERE venue='binance' AND t=?", (at("00:25"),))
    grid = grid_of(store, "binance")
    assert grid.price[idx("00:10")] == 100.0  # its first bar is missing, its closing bar is not
    assert grid.price[idx("00:30")] is None  # its closing bar is missing
    assert grid.price[idx("00:00")] == grid.price[idx("00:40")] == 100.0
    assert grid.vd[idx("00:20")] is None  # its second bar is missing
    assert grid.vd[idx("00:10")] == 2 * (2 * 6.0 - 10.0)


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
    assert build_grid(store, "hyperliquid", T0) == ["bybit:oi"]
    assert REQUIRED == {
        "binance": ("bybit:price", "binance:oi", "binance:kline"),
        "bybit": ("bybit:price", "bybit:oi"),
        "all": ("bybit:price", "binance:oi", "binance:kline", "bybit:oi"),
        "hyperliquid": ("bybit:price", "binance:oi", "bybit:oi"),
    }


# --- Coinalyze columns (proposal §3.3, §3.4). ---


def point(t: int, a: float, b: float, *, filled: bool = False) -> CzPoint:
    return CzPoint(t=t, a=a, b=b, filled=filled)


def cz(
    store: PerpsStore,
    kind: CzKind,
    venue: CzVenue,
    step: int,
    first: int,
    last: int,
    a: float,
    b: float,
    skip: Collection[int] = (),
) -> None:
    """One venue's Coinalyze rows every `step` from `first` to `last`, but those in `skip`."""
    rows = [point(t, a, b) for t in range(first, last + 1, step) if t not in skip]
    store.upsert_cz(kind, step, venue, rows)


# Every 5min interval's liquidations (longs, shorts), volumes (volume, taker buy) and OI (open,
# close). A 10m bucket sums two liquidation intervals: Binance (0.5, 0.25), Bybit (1.0, 1.5) and
# OKX (2.0, 4.0), (3.5, 5.75) together. Its delta is 2·buy − volume over two: Bybit 4.0, OKX
# −2.0, Hyperliquid 2.0, and Binance's klines give 4.0. Its OI is the second interval's close.
LIQ5: dict[CzVenue, tuple[float, float]] = {
    "binance": (0.25, 0.125),
    "bybit": (0.5, 0.75),
    "okx": (1.0, 2.0),
}
OHLCV5: dict[CzVenue, tuple[float, float]] = {
    "bybit": (4.0, 3.0),
    "okx": (2.0, 0.5),
    "hyperliquid": (1.0, 1.0),
}
OI5: dict[CzVenue, tuple[float, float]] = {"okx": (240.0, 250.0), "hyperliquid": (430.0, 437.5)}


def five_min(
    store: PerpsStore,
    last: int,
    skip: Mapping[tuple[CzKind, CzVenue], Collection[int]] | None = None,
) -> None:
    """Every venue's 5min intervals that the buckets up to `last` read, but those in `skip`."""
    kinds: tuple[tuple[CzKind, dict[CzVenue, tuple[float, float]]], ...] = (
        ("liq", LIQ5),
        ("ohlcv", OHLCV5),
        ("oi", OI5),
    )
    for kind, values in kinds:
        for venue, (a, b) in values.items():
            gone = (skip or {}).get((kind, venue), ())
            cz(store, kind, venue, M5, W, last + M5, a, b, gone)


def test_closed_window_value_sits_in_its_last_bucket():
    longs, shorts = cz_liquidations({W: CzPoint(t=W, a=3.0, b=1.0)}, {}, W, W + H4 - STEP)
    assert longs.values == [0.0] * 23 + [3.0] and shorts.values == [0.0] * 23 + [1.0]
    assert all(longs.covered) and longs.whole == [False] * 23 + [True]
    assert shorts.covered == longs.covered and shorts.whole == longs.whole


def test_window_past_last_uses_5min():
    rows5 = {W + k * 300: CzPoint(t=W + k * 300, a=0.1, b=0.0) for k in range(12)}
    longs, _ = cz_liquidations({W: CzPoint(t=W, a=9.0, b=0.0)}, rows5, W, W + 5 * STEP)
    assert longs.values == [0.2] * 6 and all(longs.covered)  # never the 9.0 window total
    assert not any(longs.whole)


def test_bucket_missing_a_5min_point_is_uncovered():
    # A closed window without its 4hour row is read from 5min too; W+15m is missing.
    rows5 = {t: point(t, 0.25, 0.5) for t in range(W, W + H4, M5) if t != W + 3 * M5}
    longs, shorts = cz_liquidations({}, rows5, W, W + H4 - STEP)
    assert longs.values == [0.5, None] + [0.5] * 22
    assert shorts.values == [1.0, None] + [1.0] * 22
    assert longs.covered == shorts.covered == [True, False] + [True] * 22
    assert not any(longs.whole)
    delta = cz_delta({}, rows5, W, W + H4 - STEP)
    assert delta.values == [1.5, None] + [1.5] * 22
    assert delta.covered == longs.covered
    # OI reads the bucket's second interval alone: only bucket 1 lacks it.
    oi = cz_oi({}, rows5, W, W + H4 - STEP)
    assert oi.values == [0.5, None] + [0.5] * 22 and all(oi.covered)


def test_filled_run_is_uncovered():
    end = W + 3 * H4 - STEP
    rows5 = {t: point(t, 0.5, 0.5) for t in range(W - H4, W + 3 * H4, M5)}
    # Two filled windows in a row: 48 buckets uncovered, and 5min does not fill them in.
    run = {
        W: point(W, 0.0, 0.0, filled=True),
        W + H4: point(W + H4, 0.0, 0.0, filled=True),
        W + 2 * H4: point(W + 2 * H4, 2.0, 1.0),
    }
    longs, shorts = cz_liquidations(run, rows5, W, end)
    assert longs.values == [None] * 48 + [0.0] * 23 + [2.0]
    assert shorts.values == [None] * 48 + [0.0] * 23 + [1.0]
    assert longs.covered == [False] * 48 + [True] * 24
    assert longs.whole == [False] * 71 + [True]
    # A lone filled window is 24 zeros, covered: no liquidations in it.
    lone = {
        W: point(W, 1.0, 1.0),
        W + H4: point(W + H4, 0.0, 0.0, filled=True),
        W + 2 * H4: point(W + 2 * H4, 2.0, 1.0),
    }
    longs, _ = cz_liquidations(lone, rows5, W, end)
    assert longs.values[24:48] == [0.0] * 24 and all(longs.covered)
    assert longs.whole[47]
    # The newest filled window shows 0 until the next one is filled too.
    longs, _ = cz_liquidations({W: point(W, 0.0, 0.0, filled=True)}, rows5, W, W + H4 - STEP)
    assert longs.values == [0.0] * 24 and all(longs.covered)
    # A filled window at the start whose previous one (read from start - H4) is filled.
    before = {W - H4: point(W - H4, 0.0, 0.0, filled=True), W: point(W, 0.0, 0.0, filled=True)}
    longs, _ = cz_liquidations(before, rows5, W, W + H4 - STEP)
    assert longs.values == [None] * 24 and not any(longs.covered)
    # One whose next window is filled too, though past `last`: uncovered as well.
    after = {W: point(W, 0.0, 0.0, filled=True), W + H4: point(W + H4, 0.0, 0.0, filled=True)}
    longs, _ = cz_liquidations(after, rows5, W, W + 5 * STEP)
    assert longs.values == [None] * 6 and not any(longs.covered)


def test_oi_window_open_first_close_last_middle_none():
    rows4 = {W: point(W, 100.0, 130.0)}
    oi = cz_oi(rows4, {}, W, W + H4 - STEP)
    assert oi.values == [100.0] + [None] * 22 + [130.0]
    assert all(oi.covered) and oi.whole == [True] + [False] * 22 + [True]
    # The window past `last` reads its buckets' second 5min interval: no first one is stored,
    # and bucket 2's second one is missing.
    w1 = W + H4
    rows5 = {
        t + M5: point(t + M5, 0.0, float(k))
        for k, t in enumerate(range(w1, w1 + 4 * STEP, STEP))
        if k != 2
    }
    oi = cz_oi(rows4, rows5, W, w1 + 3 * STEP)
    assert oi.values == [100.0] + [None] * 22 + [130.0] + [0.0, 1.0, None, 3.0]
    assert all(oi.covered)
    assert oi.whole == [True] + [False] * 22 + [True] + [False] * 4


def test_delta_is_two_buy_minus_volume():
    rows4 = {W: point(W, 10.0, 7.0)}  # 2 · 7 − 10
    rows5 = {W + H4 + k * M5: point(W + H4 + k * M5, 3.0, 1.0 + k) for k in range(4)}
    delta = cz_delta(rows4, rows5, W, W + H4 + STEP)
    # 2 · (1 + 2) − (3 + 3) and 2 · (3 + 4) − (3 + 3)
    assert delta.values == [0.0] * 23 + [4.0] + [0.0, 8.0]
    assert all(delta.covered) and delta.whole == [False] * 23 + [True] + [False] * 2


def test_composite_rest_gap_at_window_end_uncovers_the_window(store: PerpsStore):
    last = W + 2 * H4 - STEP  # two closed windows, W1 the second
    w1 = W + H4
    rest(store, last)
    for venue in ("bybit", "okx"):
        cz(store, "ohlcv", venue, H4, W, w1, 10.0, 7.0)
    cz(store, "oi", "okx", H4, W, w1, 300.0, 310.0)
    for venue in VIEW_VENUES["all"]:
        cz(store, "liq", venue, H4, W, w1, 1.0, 2.0)
    # Binance's kline and OI are missing at W1's end bucket.
    with store.connection(write=True) as db:
        db.execute("DELETE FROM kline WHERE venue='binance' AND t=?", (last,))
    store.upsert_oi("binance", [OiPoint(t=last + STEP, oi=None, source="hist")])

    grid = grid_of(store, "all")
    bn_vd = 2 * (2 * 6.0 - 10.0)
    assert grid.rest_series["binance:kline"][24:] == [bn_vd] * 23 + [None]
    assert grid.vd[:24] == [bn_vd] * 23 + [bn_vd + 4.0 + 4.0]
    assert grid.vd[24:] == [None] * 24
    assert grid.vd_covered == [True] * 24 + [False] * 24
    assert grid.oi[:24] == [1500.0 + 300.0] + [None] * 22 + [1500.0 + 310.0]
    assert grid.oi[24:] == [None] * 24
    # The liquidations have no gap at W1's end.
    assert grid.long_liq[24:] == [0.0] * 23 + [3.0] and all(grid.liq_covered)

    first, second = compute_states(grid, "4h", rules=V1).blocks
    assert first.delta_covered and first.delta_sum == 24 * bn_vd + 8.0
    assert first.oi_close == 1810.0
    # Not the Binance-only partial sum, nor W1's OI four hours before its end.
    assert not second.delta_covered and second.delta_sum is None
    assert second.oi_close is None and second.imputed.doi


def test_estimate_liquidations():
    longs, shorts, cov = estimate_liquidations(
        [0.0, 4.0, 4.0, None, 4.0, 4.0],
        [0.0, 2.0, 2.0, None, 2.0, 2.0],
        [True, True, True, False, True, True],
        [None, 100.0, None, 100.0, 0.0, 100.0],
        [10.0, 25.0, 25.0, 25.0, 25.0, None],
    )
    assert longs == [0.0, 1.0, None, None, None, None]
    assert shorts == [0.0, 0.5, None, None, None, None]
    assert cov == [True, True, False, False, False, False]


def test_all_view_none_if_any_venue_none(store: PerpsStore):
    last = at("00:30")
    rest(store, last)
    store.upsert_oi("bybit", [OiPoint(t=at("00:20"), oi=None, source="bybit")])  # bucket 00:10
    # Binance's liquidations lack the 00:05 interval (bucket 00:00), Bybit's volumes the 00:35
    # one (bucket 00:30).
    five_min(store, last, {("liq", "binance"): {at("00:05")}, ("ohlcv", "bybit"): {at("00:35")}})

    grid = grid_of(store, "all")
    assert grid.oi == [1750.0, None, 1750.0, 1750.0]
    assert grid.rest_series["binance:oi"] == [1000.0] * 4
    assert grid.rest_series["bybit:oi"] == [500.0, None, 500.0, 500.0]
    assert grid.vd == [6.0, 6.0, 6.0, None]
    assert grid.rest_series["binance:kline"] == [4.0] * 4
    assert grid.vd_covered == [True, True, True, False]
    assert grid.liq_covered == [False, True, True, True]
    assert grid.long_liq == [None, 3.5, 3.5, 3.5]
    assert grid.short_liq == [None, 5.75, 5.75, 5.75]
    assert list(grid.rest_series) == list(REQUIRED["all"])


def test_all_view_sums_three_venues_and_is_none_where_okx_is(store: PerpsStore):
    last = at("00:30")
    rest(store, last)
    five_min(
        store,
        last,
        {
            ("liq", "okx"): {at("00:15")},  # bucket 00:10
            ("ohlcv", "okx"): {at("00:20")},  # bucket 00:20
            ("oi", "okx"): {at("00:35")},  # bucket 00:30
        },
    )

    grid = grid_of(store, "all")
    assert grid.long_liq == [0.5 + 1.0 + 2.0, None, 3.5, 3.5]
    assert grid.short_liq == [0.25 + 1.5 + 4.0, None, 5.75, 5.75]
    assert grid.liq_covered == [True, False, True, True]
    assert grid.vd == [4.0 + 4.0 - 2.0, 6.0, None, 6.0]
    assert grid.vd_covered == [True, True, False, True]
    assert grid.oi == [1000.0 + 500.0 + 250.0, 1750.0, 1750.0, None]
    # OKX only joins All: the single-venue views are whole.
    bybit = grid_of(store, "bybit")
    assert (bybit.long_liq, bybit.vd, bybit.oi) == ([1.0] * 4, [4.0] * 4, [500.0] * 4)
    binance = grid_of(store, "binance")
    assert (binance.long_liq, binance.vd, binance.oi) == ([0.5] * 4, [4.0] * 4, [1000.0] * 4)
    assert all(binance.liq_covered) and all(bybit.vd_covered)


def test_hyperliquid_view_last_is_bounded_by_binance_and_bybit_oi(store: PerpsStore):
    spot(store, T0, at("00:55"))  # price through 00:50
    perp(store, T0, at("00:15"))  # Binance's delta through 00:10, which the view does not read
    oi(store, "binance", T0, at("00:40"))  # OI through 00:30
    oi(store, "bybit", T0, at("01:00"))  # OI through 00:50

    assert grid_of(store, "hyperliquid").last == at("00:30")
    assert grid_of(store, "all").last == at("00:10")
    oi(store, "binance", T0, at("01:00"))
    grid = grid_of(store, "hyperliquid")
    assert grid.last == at("00:50")
    assert list(grid.rest_series) == list(REQUIRED["hyperliquid"])
    # Nothing from Coinalyze: no OI, no delta and no estimate.
    assert set(grid.oi) == set(grid.vd) == set(grid.long_liq) == {None}
    assert not any(grid.vd_covered) and not any(grid.liq_covered)


def test_hyperliquid_view_reads_its_own_oi_and_delta_and_estimates_liquidations(
    store: PerpsStore,
):
    last = at("00:30")
    rest(store, last)
    five_min(
        store,
        last,
        {
            ("oi", "okx"): {at("00:15")},  # All's OI at 00:10
            ("oi", "hyperliquid"): {at("00:25")},  # Hyperliquid's at 00:20
            ("liq", "bybit"): {at("00:35")},  # All's liquidations at 00:30
        },
    )

    grid = grid_of(store, "hyperliquid")
    assert grid.oi == [437.5, 437.5, None, 437.5]
    assert grid.vd == [2.0] * 4 and all(grid.vd_covered)
    # All's liquidations times Hyperliquid's OI over All's (437.5 / 1750 = 0.25).
    assert grid.long_liq == [3.5 * 0.25, None, None, None]
    assert grid.short_liq == [5.75 * 0.25, None, None, None]
    assert grid.liq_covered == [True, False, False, False]


def test_hyperliquid_estimate_of_a_whole_window_takes_its_end_share(store: PerpsStore):
    last = W + H4 - STEP
    rest(store, last)
    for venue in VIEW_VENUES["all"]:
        cz(store, "liq", venue, H4, W, W, 1.0, 2.0)
    cz(store, "oi", "okx", H4, W, W, 240.0, 250.0)
    cz(store, "oi", "hyperliquid", H4, W, W, 400.0, 437.5)
    cz(store, "ohlcv", "hyperliquid", H4, W, W, 10.0, 7.0)

    grid = grid_of(store, "hyperliquid")
    # The window's (3, 6) at its end, times 437.5 / 1750; its other buckets have none.
    assert grid.long_liq == [0.0] * 23 + [0.75] and grid.short_liq == [0.0] * 23 + [1.5]
    assert all(grid.liq_covered)
    assert grid.oi == [400.0] + [None] * 22 + [437.5]
    assert grid.vd == [0.0] * 23 + [4.0]

    # Without All's OI at the end there is no share for the window: all of it is uncovered.
    store.upsert_oi("binance", [OiPoint(t=last + STEP, oi=None, source="hist")])
    grid = grid_of(store, "hyperliquid")
    assert grid.long_liq == grid.short_liq == [None] * 24
    assert not any(grid.liq_covered)


def test_window_qc_reports_missing_okx_oi(store: PerpsStore):
    # Twelve closed windows and a forming one, whose OI is not stored and not counted.
    last = T0 + 2 * DAY + 5 * STEP
    rest(store, last)
    cz(store, "oi", "okx", H4, W, W + 11 * H4, 240.0, 250.0)
    cz(store, "oi", "hyperliquid", H4, W, W + 11 * H4, 400.0, 437.5)
    grid = grid_of(store, "all")
    assert (grid.window_qc, grid.window_missing) == ((), ())
    assert compute_states(grid, "4h", rules=V1).qc == []

    # One window in twelve is over 1%.
    with store.connection(write=True) as db:
        db.execute("DELETE FROM cz_series WHERE venue='okx' AND t=?", (W + 5 * H4,))
    grid = grid_of(store, "all")
    assert (grid.window_qc, grid.window_missing) == (("missing:okx:oi",), ())
    states = compute_states(grid, "4h", rules=V1)
    assert states.qc == ["missing:okx:oi"] and states.series_missing == []
    assert grid_of(store, "hyperliquid").window_qc == ("missing:okx:oi",)
    # The single-venue views read no Coinalyze OI.
    for exchange in ("binance", "bybit"):
        assert (grid_of(store, exchange).window_qc, grid_of(store, exchange).window_missing) == (
            (),
            (),
        )

    # None at all in the reference: the series is missing.
    with store.connection(write=True) as db:
        db.execute("DELETE FROM cz_series WHERE kind='oi'")
    grid = grid_of(store, "all")
    assert (grid.window_qc, grid.window_missing) == (("missing:okx:oi",), ("okx:oi",))
    assert compute_states(grid, "4h", rules=V1).series_missing == ["okx:oi"]
    hyperliquid = grid_of(store, "hyperliquid")
    assert hyperliquid.window_qc == ("missing:okx:oi", "missing:hyperliquid:oi")
    assert hyperliquid.window_missing == ("okx:oi", "hyperliquid:oi")


def test_excluded_venue_is_uncovered(store: PerpsStore):
    last = at("00:30")
    rest(store, last)
    five_min(store, last)
    assert grid_of(store, "all").long_liq == [3.5] * 4

    def built(exchange: Exchange, venue: CzVenue) -> Grid:
        grid = build_grid(store, exchange, T0, frozenset({venue}))
        assert isinstance(grid, Grid), grid
        return grid

    # OKX's columns are all missing, so All's are.
    okx_out = built("all", "okx")
    assert okx_out.long_liq == okx_out.vd == okx_out.oi == [None] * 4
    assert not any(okx_out.liq_covered) and not any(okx_out.vd_covered)
    assert built("bybit", "okx") == grid_of(store, "bybit")
    # Binance's liquidations go; its OI and delta come from its own REST.
    binance = built("binance", "binance")
    assert binance.long_liq == [None] * 4 and not any(binance.liq_covered)
    assert (binance.oi, binance.vd) == ([1000.0] * 4, [4.0] * 4)
    # Hyperliquid's OI and delta go, and the estimate with its OI.
    hyperliquid = built("hyperliquid", "hyperliquid")
    assert hyperliquid.oi == hyperliquid.vd == hyperliquid.long_liq == [None] * 4


def test_only_4hour_history_is_judged_under_o6(store: PerpsStore):
    start = T0 - 100 * DAY
    last = T0 - STEP  # the end bucket of the window before T0: no forming block
    spot(store, start, last + M5)
    perp(store, start, last + M5)
    oi(store, "binance", start, last + STEP)
    oi(store, "bybit", start, last + STEP, value=500.0)
    windows = range(start, T0, H4)
    kinds: tuple[tuple[CzKind, tuple[CzVenue, ...]], ...] = (
        ("liq", VIEW_VENUES["all"]),
        ("ohlcv", ("bybit", "okx")),
        ("oi", ("okx",)),
    )
    for kind, venues in kinds:
        for n, venue in enumerate(venues):
            store.upsert_cz(
                kind,
                H4,
                venue,
                [
                    point(w, 300.0 + (k + n) % 7, 300.0 + (k + 2 * n) % 11)
                    for k, w in enumerate(windows)
                ],
            )

    grid = build_grid(store, "all", start)
    assert isinstance(grid, Grid) and grid.last == last
    states = compute_states(grid, "4h", rules=O1O6)
    assert len(states.blocks) >= 30 * 6 and not states.blocks[-1].forming
    assert all(block.covered for block in states.blocks)
    assert not any(block.imputed.sums or block.imputed.doi for block in states.blocks)
    assert all(block.state is not None for block in states.blocks)
