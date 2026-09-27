"""Cross-timeframe context: windows, freshness, composition and the read-only endpoint."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from regime_fixture import TIMEFRAMES, V2, replay_dataset

from wheelhouse_service.context import (
    WINDOW,
    WindowResult,
    build_context,
    compose,
    load_window,
)
from wheelhouse_service.http import create_app
from wheelhouse_service.indicators.demark import evaluate_demark
from wheelhouse_service.indicators.demark.summary import summarize
from wheelhouse_service.market import DURATIONS, Bar, Batch, Stream
from wheelhouse_service.repository import Repository

START = datetime(2026, 1, 1, tzinfo=UTC)


def _ingest(repo, source, tf, count=None, *, symbol="BTCUSDT", closes=None, forming=False):
    closes = closes or [100 + i % 7 for i in range(count)]
    step = timedelta(seconds=DURATIONS[tf])
    bars = [
        Bar(open_time=START + step * i, close_time=START + step * (i + 1),
            open=str(c), high=str(c + 1), low=str(c - 1), close=str(c), is_closed=True)
        for i, c in enumerate(closes)
    ]
    if forming:  # an unfinished bar at the fetch moment must never enter the window
        opened = bars[-1].close_time
        bars.append(Bar(open_time=opened, close_time=opened + step, open="100", high="101",
                        low="99", close="100", is_closed=False))
    stream = Stream(source=source, symbol=symbol, timeframe=tf)
    end = max(b.close_time for b in bars if b.is_closed)
    repo.ingest(Batch(stream=stream, fetched_at=end, bars=bars, raw_payload={}))
    return stream, end


def test_window_takes_last_499_closed_bars_and_flags_short_history(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    stream, end = _ingest(repo, "fixture", "1h", 520, forming=True)
    status, window = load_window(repo, stream, market_at=end, knowledge_at=end)
    assert status == "simulated"
    assert len(window.bars) == WINDOW and window.forming == []
    assert window.bars[-1].bar.close_time == end
    short, _ = _ingest(repo, "fixture", "4h", 30)
    _, few = load_window(repo, short, market_at=end + timedelta(days=5), knowledge_at=end)
    assert len(few.bars) == 30


def test_replay_cutoff_excludes_later_bars(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    stream, end = _ingest(repo, "fixture", "1h", 100)
    cut = end - timedelta(hours=10)
    _, window = load_window(repo, stream, market_at=cut, knowledge_at=end)
    assert window.bars[-1].bar.close_time == cut


def test_empty_repository_is_unavailable_not_an_error(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    now = datetime(2026, 9, 28, tzinfo=UTC)
    ctx = build_context(repo, "binance", "BTCUSDT", market_at=now, knowledge_at=now, checked_at=now)
    assert [tf.status for tf in ctx.timeframes] == ["unavailable"] * 5
    assert all(
        tf.summary is None and tf.state is None and tf.signals == [] for tf in ctx.timeframes
    )
    assert (ctx.intraday.value, ctx.swing.value) == ("unavailable", "unavailable")


def test_stale_binance_anchor_makes_regime_unavailable(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    _, end = _ingest(repo, "binance", "1h", 60)
    later = end + timedelta(hours=5)
    ctx = build_context(repo, "binance", "BTCUSDT", market_at=later, knowledge_at=later,
                        checked_at=later)
    hour = next(tf for tf in ctx.timeframes if tf.timeframe == "1h")
    assert hour.status == "stale"
    assert hour.summary is None and hour.state is None and hour.signals == []
    assert hour.new_trend is None and hour.bars_used == 60
    assert ctx.intraday.value == "unavailable"


def test_eth_fixture_source_is_simulated_and_usable(tmp_path):
    repo = Repository(tmp_path / "ctx.sqlite")
    # Buy Setup 9 followed by a qualified 13 (same pattern as tests/demark/test_sequential.py).
    closes = [100, 101, 102, 103, 104, 99, 98, 97, 96, 95, 94, 93, 92, 91, *range(90, 78, -1)]
    _, end = _ingest(repo, "fixture", "1h", symbol="ETHUSDT", closes=closes)
    ctx = build_context(repo, "fixture", "ETHUSDT", market_at=end, knowledge_at=end, checked_at=end)
    hour = next(tf for tf in ctx.timeframes if tf.timeframe == "1h")
    assert hour.status == "simulated"
    assert hour.summary is not None
    assert hour.history_complete is False and hour.bars_used == len(closes)
    # Completed Buy Setup with a qualified 13 and no carry: s9=down, s13=false -> rev.
    assert ctx.intraday.value == "rev"


def _golden_windows():
    windows = {}
    for tf in TIMEFRAMES:
        data, as_of = replay_dataset(tf)
        summary = summarize(evaluate_demark(data, V2), [b.bar for b in data.bars], as_of)
        windows[tf] = WindowResult(status="fresh", bars_used=500, gapped=False,
                                   last_closed_at=data.bars[-1].bar.close_time, summary=summary)
    return windows


def test_compose_reproduces_alphabtc_regimes_and_levels():
    now = datetime(2026, 9, 27, 16, 30, tzinfo=UTC)
    ctx = compose("binance", "BTCUSDT", _golden_windows(), checked_at=now, market_at=now,
                  knowledge_at=now)
    assert (ctx.intraday.anchor, ctx.intraday.value) == ("1h", "pump")
    assert (ctx.swing.anchor, ctx.swing.value) == ("4h", "decay")
    five = next(tf for tf in ctx.timeframes if tf.timeframe == "5m")
    assert [(s.side, s.intraday_level) for s in five.signals] == [("buy", 3), ("buy", None)]


def test_compose_falls_back_to_base_levels_when_anchor_is_stale():
    windows = _golden_windows()
    windows["1h"] = windows["1h"].model_copy(update={"status": "stale"})
    now = datetime(2026, 9, 27, 16, 30, tzinfo=UTC)
    ctx = compose("binance", "BTCUSDT", windows, checked_at=now, market_at=now, knowledge_at=now)
    assert ctx.intraday.value == "unavailable"
    five = next(tf for tf in ctx.timeframes if tf.timeframe == "5m")
    assert five.signals[0].intraday_level == five.signals[0].base_level == 2


def test_endpoint_is_read_only_and_validates_replay_cutoffs(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite", start_worker=False)) as client:
        before = client.get("/api/wheelhouse/v1/storage").json()
        ok = client.get("/api/wheelhouse/v1/market-context?source=binance&symbol=BTCUSDT")
        assert ok.status_code == 200
        assert ok.json()["window"] == WINDOW
        assert len(ok.json()["timeframes"]) == 5
        after = client.get("/api/wheelhouse/v1/storage").json()
        assert after == before
        base = "/api/wheelhouse/v1/market-context?source=binance&symbol=BTCUSDT"
        only_one = client.get(base + "&market_at=2026-09-01T00:00:00Z")
        assert only_one.status_code == 422
        future = client.get(
            base + "&market_at=2999-01-01T00:00:00Z&knowledge_at=2999-01-01T00:00:00Z"
        )
        assert future.status_code == 422
        naive = client.get(
            base + "&market_at=2026-09-01T00:00:00&knowledge_at=2026-09-01T00:00:00"
        )
        assert naive.status_code == 422
        assert client.get(base.replace("BTCUSDT", "SOLUSDT")).status_code == 422
        replay = client.get(
            base + "&market_at=2026-09-01T00:00:00Z&knowledge_at=2026-09-02T00:00:00Z"
        )
        assert replay.status_code == 200
        assert replay.json()["mode"] == "retrospective"
        assert client.post(base).status_code == 405
        status = client.get("/api/wheelhouse/v1/status").json()
        assert "market_context" in status["capabilities"]
