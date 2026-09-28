"""Replay an AlphaBTC /api/td9 capture against the local context (forming bar rebuilt).

Reads Binance public klines only; never contacts AlphaBTC or TradingSignal and reads no
credentials. The capture JSON is saved by the user or via their logged-in browser.
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/analytics/src"))

from wheelhouse_service.context import CONFIG, WINDOW  # noqa: E402
from wheelhouse_service.indicators.demark import evaluate_demark  # noqa: E402
from wheelhouse_service.indicators.demark.summary import (  # noqa: E402
    as_tradingsignal,
    summarize,
)
from wheelhouse_service.indicators.regime.alphabtc import (  # noqa: E402
    adjust,
    derive_state,
    regime_of,
    signals,
)
from wheelhouse_service.market import (  # noqa: E402
    DURATIONS,
    Bar,
    Dataset,
    StoredBar,
    Stream,
)

API = "https://data-api.binance.vision/api/v3/klines"
# TradingSignal's crypto candles equal Bybit spot BTCUSDT (OHLCV, verified 2026-09-28).
# api.bybit.nl serves the same public market data where api.bybit.com is unreachable.
BYBIT = "https://api.bybit.nl/v5/market/kline"
BYBIT_INTERVALS = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
TF_NAMES = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d", "1D": "1d"}
STRUCTURAL = (
    "side", "regime", "phase", "step", "target", "setupStep", "countdownStep",
    "barsSinceQualified13", "lastSignal", "prev", "second", "rounds",
)
RISK_STRUCTURAL = ("side", "risk9Ts", "risk13Ts", "provisional", "setupRun")


def klines(client, interval, *, end_ms, limit):
    rows = client.get(
        API,
        params={"symbol": "BTCUSDT", "interval": interval, "endTime": end_ms, "limit": limit},
    )
    rows.raise_for_status()
    return rows.json()


def bybit_klines(client, interval, start_s, end_s):
    """Bybit spot klines opened in [start_s, end_s], ascending, as [t, o, h, l, c]."""
    rows = {}
    end = end_s
    while end >= start_s:
        batch = client.get(
            BYBIT,
            params={"category": "spot", "symbol": "BTCUSDT",
                    "interval": BYBIT_INTERVALS[interval],
                    "start": start_s * 1000, "end": end * 1000, "limit": 1000},
        ).json()["result"]["list"]
        if not batch:
            break
        for r in batch:
            rows[int(r[0]) // 1000] = [int(r[0]) // 1000, r[1], r[2], r[3], r[4]]
        earliest = min(int(r[0]) // 1000 for r in batch)
        if len(batch) < 1000:
            break
        end = earliest - 1
    return [rows[t] for t in sorted(rows)]


def bybit_cut(client, as_of, close, captured):
    """Minute (<= captured) whose range contains TradingSignal's close, latest first."""
    minutes = bybit_klines(client, "1m", max(as_of, captured - 1200), (captured - 1) // 60 * 60)
    target = Decimal(str(close))
    inside = [m for m in minutes if Decimal(m[3]) <= target <= Decimal(m[2])]
    if inside:
        return inside[-1][0]
    return min(minutes, key=lambda m: (abs(Decimal(m[4]) - target), -m[0]))[0]


def bybit_forming(client, open_ts, cut, close):
    """Bar opened at open_ts as it stood inside minute `cut`, closing at TradingSignal's close.

    Bybit has no 1s klines, so the cut minute contributes only its open and the known close;
    `ambiguous` flags a cut minute whose full range would move the bar's high or low.
    """
    minutes = bybit_klines(client, "1m", open_ts, cut)
    if not minutes or minutes[0][0] != open_ts or minutes[-1][0] != cut:
        raise SystemExit(f"cannot rebuild forming bar {open_ts}")
    done, last = minutes[:-1], minutes[-1]
    closing = Decimal(str(close))
    highs = [Decimal(m[2]) for m in done] + [Decimal(last[1]), closing]
    lows = [Decimal(m[3]) for m in done] + [Decimal(last[1]), closing]
    high, low = max(highs), min(lows)
    ambiguous = Decimal(last[2]) > high or Decimal(last[3]) < low
    return [open_ts, minutes[0][1], str(high), str(low), str(closing)], ambiguous


def forming(client, open_ts, captured):
    """OHLC of the bar opened at open_ts as it stood at `captured` (1m, then 1s for the tail)."""
    minutes = []
    start = open_ts * 1000
    while True:
        batch = client.get(
            API,
            params={"symbol": "BTCUSDT", "interval": "1m", "startTime": start, "limit": 1000},
        ).json()
        minutes += [r for r in batch if r[0] // 1000 + 60 <= captured]
        if len(batch) < 1000 or batch[-1][0] // 1000 + 60 > captured:
            break
        start = batch[-1][0] + 60000
    tail = captured - captured % 60
    seconds = (
        client.get(
            API,
            params={"symbol": "BTCUSDT", "interval": "1s", "startTime": tail * 1000,
                    "endTime": captured * 1000 - 1, "limit": 1000},
        ).json()
        if captured % 60
        else []
    )
    rows = minutes + seconds
    if not rows or rows[0][0] // 1000 != open_ts:
        raise SystemExit(f"cannot rebuild forming bar {open_ts}")
    return [open_ts, rows[0][1], str(max(Decimal(r[2]) for r in rows)),
            str(min(Decimal(r[3]) for r in rows)), rows[-1][4]]


def computed_at(client, as_of, close, captured):
    """Second (<= captured) when TradingSignal most likely computed this timeframe.

    Its cached data can be minutes old, and its last bar keeps taking the live price even
    after that bar's close time. Pick the latest second in the 20 minutes before capture
    whose Binance close is within 5 USDT of TradingSignal's close (feeds differ by a few
    USDT), else the nearest one.
    """
    start = max(as_of, captured - 1200)
    seconds = []
    while start < captured:
        batch = client.get(
            API,
            params={"symbol": "BTCUSDT", "interval": "1s", "startTime": start * 1000,
                    "endTime": captured * 1000 - 1, "limit": 1000},
        ).json()
        if not batch:
            break
        seconds += batch
        start = batch[-1][0] // 1000 + 1
    if not seconds:
        return captured
    target = Decimal(str(close))
    near = [r for r in seconds if abs(Decimal(r[4]) - target) <= 5]
    best = near[-1] if near else min(seconds, key=lambda r: (abs(Decimal(r[4]) - target), -r[0]))
    return best[0] // 1000 + 1


def replay(client, tf, as_of, captured, bar=None):
    """`bar` replaces the Binance-rebuilt forming bar and switches closed bars to Bybit."""
    step = DURATIONS[tf]
    if bar is None:
        closed = [
            [r[0] // 1000, r[1], r[2], r[3], r[4]]
            for r in klines(client, tf, end_ms=as_of * 1000 - 1, limit=WINDOW)
        ]
        bar = forming(client, as_of, captured)
    else:
        closed = bybit_klines(client, tf, as_of - step * WINDOW, as_of - step)
        if len(closed) != WINDOW or closed[-1][0] != as_of - step:
            raise SystemExit(f"Bybit {tf}: {len(closed)} closed bars before {as_of}")
    rows = closed[-WINDOW:] + [bar]
    bars = []
    for t, o, h, low, c in rows:
        opened = datetime.fromtimestamp(t, UTC)
        bars.append(StoredBar(
            revision_id=f"cmp:{tf}:{t}", revision=1, fetched_at=opened + timedelta(seconds=step),
            bar=Bar(open_time=opened, close_time=opened + timedelta(seconds=step),
                    open=o, high=h, low=low, close=c, is_closed=True)))
    end = bars[-1].bar.close_time
    data = Dataset(stream=Stream(source="binance", symbol="BTCUSDT", timeframe=tf),
                   market_at=end, knowledge_at=end, fetched_at=end, bars=bars, forming=[])
    return summarize(evaluate_demark(data, CONFIG), [b.bar for b in bars],
                     datetime.fromtimestamp(as_of, UTC))


def normalize(capture):
    """Accept `across` as a list with `timeframe` or as a dict keyed by timeframe."""
    across = capture["across"]
    pairs = across.items() if isinstance(across, dict) else ((x["timeframe"], x) for x in across)

    def name(key):
        if str(key) not in TF_NAMES:
            raise SystemExit(f"unknown timeframe in capture: {key!r}")
        return TF_NAMES[str(key)]

    return (
        {name(k): v for k, v in pairs},
        {name(k): v for k, v in capture.get("risk", {}).items()},
    )


def ts_state(x):
    """AlphaBTC dmkLive on the captured TradingSignal fields -> (s9, s13)."""
    p = x.get("prev") or {}
    prev_q13 = bool(p.get("qualified")) and (p.get("countdown") or 0) >= 13
    ex = [r["exhaustedTs"] for r in x.get("rounds") or []
          if (r.get("countdown") or 0) >= 13 and r.get("exhaustedTs")]
    ts_ex13 = ex[-1] if ex else 0
    ls = x.get("lastSignal") or {}
    ts9 = ls.get("ts", 0) if ls.get("kind") == 9 else 0
    last13 = ls.get("kind") == 13 or bool(ts_ex13 and ts_ex13 > ts9)
    carry = bool(last13 and x["phase"] != "countdown" and (x.get("setupStep") or 0) < 9
                 and (prev_q13 or (x.get("countdownStep") or 0) >= 13))
    if carry and p.get("side"):
        up = p["side"] == "SELL"
    elif carry:
        done13 = [r for r in x.get("rounds") or [] if r.get("exhaustedTs")]
        up = (done13[-1]["regime"] if done13 else x.get("regime")) == "up"
    else:
        up = x.get("regime") == "up"
    done = carry or x["phase"] == "countdown" or (x.get("setupStep") or 0) >= 9
    cd = 13 if carry else ((x.get("step") or 0) if x["phase"] == "countdown" else 0)
    return (("up" if up else "down") if done else "none"), cd >= 13


def table(s9, s13):
    if s9 == "none":
        return "none"
    return ("pump" if s13 else "rev") if s9 == "down" else ("rev" if s13 else "decay")


def ts_levels(s9, s13, intraday, swing):
    side = "buy" if s9 == "down" else "sell"
    return [
        (adjust(base, side, intraday), adjust(base, side, swing)) if active else (None, None)
        for base, active in ((2, s9 != "none"), (3, s13))
    ]


def strip(value):
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k != "strong"}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--td9", type=Path, required=True)
    parser.add_argument("--captured-at", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-align", action="store_true",
                        help="rebuild every forming bar at --captured-at instead of per-timeframe")
    parser.add_argument("--feed", choices=("binance", "bybit"), default="bybit",
                        help="bybit (TradingSignal's own feed) or binance spot")
    args = parser.parse_args()
    by_tf, risk = normalize(json.loads(args.td9.read_text()))
    report = {"captured_at": args.captured_at, "timeframes": {}}
    summaries, states = {}, {}
    with httpx.Client(timeout=10) as client:
        for tf, ts_across in by_tf.items():
            ambiguous = None
            if args.feed == "bybit":
                cut = bybit_cut(client, ts_across["asOf"], ts_across["close"], args.captured_at)
                bar, ambiguous = bybit_forming(client, ts_across["asOf"], cut, ts_across["close"])
                summary = replay(client, tf, ts_across["asOf"], cut, bar)
            else:
                cut = args.captured_at if args.no_align else computed_at(
                    client, ts_across["asOf"], ts_across["close"], args.captured_at)
                summary = replay(client, tf, ts_across["asOf"], cut)
            across, local_risk = as_tradingsignal(summary)
            summaries[tf], states[tf] = summary, derive_state(summary)
            report["timeframes"][tf] = {
                "replayed_at": cut,
                "forming_ambiguous": ambiguous,
                "structural_mismatches": {
                    k: {"ts": ts_across.get(k), "local": across.get(k)}
                    for k in STRUCTURAL
                    if strip(ts_across.get(k)) != strip(across.get(k))
                },
                "prices": {k: {"ts": risk.get(tf, {}).get(k), "local": local_risk.get(k)}
                           for k in ("risk9", "setupClose", "riskLevel", "close13", "tdst")},
                "risk_mismatches": {
                    k: {"ts": risk.get(tf, {}).get(k), "local": local_risk.get(k)}
                    for k in RISK_STRUCTURAL
                    if risk.get(tf, {}).get(k) != local_risk.get(k)
                },
            }
            ts_next = (risk.get(tf, {}).get("nextBarNeeds") or {}).get("direction")
            local_next = (local_risk.get("nextBarNeeds") or {}).get("direction")
            if ts_next != local_next:
                report["timeframes"][tf]["risk_mismatches"]["nextBarNeeds.direction"] = {
                    "ts": ts_next, "local": local_next}
    ts_s = {tf: ts_state(x) for tf, x in by_tf.items()}
    ts_reg = {k: table(*ts_s[a]) if a in ts_s else "unavailable"
              for k, a in (("intraday", "1h"), ("swing", "4h"))}
    anchors = (("intraday", "1h"), ("swing", "4h"))
    local_reg = {k: regime_of(states.get(a), "fresh") for k, a in anchors}
    report["regime"] = {"alphabtc": ts_reg, "local": local_reg, "match": ts_reg == local_reg}
    for tf, item in report["timeframes"].items():
        local = [(sg.intraday_level, sg.swing_level) for sg in
                 signals(states[tf], summaries[tf], local_reg["intraday"], local_reg["swing"])]
        expected = ts_levels(*ts_s[tf], ts_reg["intraday"], ts_reg["swing"])
        s9, s13 = ts_s[tf]
        item["state"] = {"alphabtc": [s9, s13], "local": [states[tf].s9, states[tf].s13],
                         "match": (s9, s13) == (states[tf].s9, states[tf].s13)}
        item["levels"] = {"alphabtc": expected, "local": local, "match": expected == local}
    text = json.dumps(report, indent=1, ensure_ascii=False, default=str)
    if args.output:
        args.output.write_text(text)
    for tf, item in report["timeframes"].items():
        flags = f"state={'OK' if item['state']['match'] else 'DIFF'} " \
                f"levels={'OK' if item['levels']['match'] else 'DIFF'}"
        prices = [p for p in item["prices"].values()
                  if p["ts"] is not None and p["local"] is not None]
        worst = max((abs(Decimal(str(p["ts"])) - Decimal(str(p["local"]))) for p in prices),
                    default=Decimal(0))
        nulls = [k for k, p in item["prices"].items() if (p["ts"] is None) != (p["local"] is None)]
        flags += f" price|Δ|max={worst:.1f}" + (f" null-diff={nulls}" if nulls else "")
        if item["forming_ambiguous"]:
            flags += " forming-ambiguous"
        print(tf, datetime.fromtimestamp(item["replayed_at"], UTC).strftime("%H:%M:%S"), flags,
              "structure OK" if not item["structural_mismatches"]
              else sorted(item["structural_mismatches"]),
              "risk OK" if not item["risk_mismatches"] else sorted(item["risk_mismatches"]))
    print("regime", report["regime"])


if __name__ == "__main__":
    main()
