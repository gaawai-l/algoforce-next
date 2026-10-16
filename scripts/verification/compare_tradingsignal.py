"""Compare user-exported TradingSignal observations offline, without credentials."""

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from wheelhouse_service.indicators.demark import DemarkConfig, evaluate_demark
from wheelhouse_service.market import DURATIONS, Bar, Dataset, StoredBar, Stream
from wheelhouse_service.sources import BinanceSource


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--binance-bars", type=Path)
    source.add_argument("--exported-bars", type=Path)
    parser.add_argument("--td-result", type=Path, required=True)
    parser.add_argument("--closed-before", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=["classic", "tradingsignal"], default="tradingsignal")
    parser.add_argument(
        "--include-forming-observation",
        action="store_true",
        help="Diagnostic only: replay the export's final observation as supplied",
    )
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.closed_before.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        parser.error("closed-before requires a timezone")
    reference = json.loads(args.td_result.read_text(), parse_float=Decimal)
    if reference.get("method") != "td9" or reference.get("result", {}).get("mode") != "sequential":
        parser.error("Expected an exported td9 Sequential response")
    stream = Stream(
        source="fixture" if args.exported_bars else "binance",
        symbol=reference["symbol"].replace("/", ""),
        timeframe=reference["timeframe"],
    )
    seconds = DURATIONS[stream.timeframe]
    observed = datetime.now(UTC)
    input_cutoff = cutoff
    if args.exported_bars:
        exported = json.loads(args.exported_bars.read_text(), parse_float=Decimal)
        if (
            exported["symbol"] != reference["symbol"]
            or exported["timeframe"] != reference["timeframe"]
        ):
            parser.error("Reference and candle stream do not match")
        candles = exported["candles"]
        if args.include_forming_observation:
            input_cutoff = datetime.fromtimestamp(candles[-1]["t"] + seconds, UTC)
        bars = [
            Bar(
                open_time=datetime.fromtimestamp(c["t"], UTC),
                close_time=datetime.fromtimestamp(c["t"] + seconds, UTC),
                open=str(c["o"]),
                high=str(c["h"]),
                low=str(c["l"]),
                close=str(c["c"]),
                volume=str(c["v"]) if c.get("v") is not None else None,
                is_closed=True,
            )
            for c in candles
            if datetime.fromtimestamp(c["t"] + seconds, UTC) <= input_cutoff
        ]
    else:
        if args.include_forming_observation:
            parser.error("Forming observation comparison requires the exported candle file")
        rows = json.loads(args.binance_bars.read_text())
        bars = [
            b
            for b in BinanceSource.normalize(stream, rows, observed, closed_before=cutoff).bars
            if b.is_closed
        ]
    acquired = max(observed, input_cutoff)
    data = Dataset(
        stream=stream,
        market_at=input_cutoff,
        knowledge_at=acquired,
        fetched_at=acquired,
        bars=[
            StoredBar(
                revision_id=f"comparison:{b.open_time.isoformat()}",
                revision=1,
                fetched_at=acquired,
                bar=b,
            )
            for b in bars
        ],
        forming=[],
    )
    config = (
        DemarkConfig()
        if args.profile == "classic"
        else DemarkConfig(
            ruleset_version="wheelhouse-sequential-2",
            same_side_policy="retain_active",
            perfection_policy="strict_at_nine",
        )
    )
    result = evaluate_demark(data, config)
    kinds = {
        "setup_count": "setup",
        "countdown_count": "countdown",
        "qualified13": "countdown_13",
        "deferred13": "countdown_def",
        "perfected": "setup_perfected",
        "recycled": "recycle",
    }
    local = set()
    for e in result.events:
        if e.kind == "cancelled":
            kind = "cancel_opp" if e.reason == "opposite_setup_completed" else "cancel_tdst"
        elif e.kind in kinds:
            if e.kind == "countdown_count" and e.count == 13:
                continue
            kind = kinds[e.kind]
        else:
            continue
        label = str(e.count) if kind in ("setup", "countdown") else kind
        local.add((int(e.bar.open_time.timestamp()), e.side.upper(), kind, label))
    times = {int(b.open_time.timestamp()) for b in bars}
    expected = {
        (
            m["ts"],
            m["side"],
            m["kind"],
            m["label"] if m["kind"] in ("setup", "countdown") else m["kind"],
        )
        for m in reference["result"]["markers"]
        if m["ts"] in times
    }
    risk_differences = []
    qualified = {
        (int(s.countdown_bars[-1].open_time.timestamp()), s.side.upper()): s
        for s in result.sequences
        if s.qualified_at
    }
    for q in reference["result"]["qualified13s"]:
        if q["ts"] not in times:
            continue
        seq = qualified.get((q["ts"], q["side"]))
        if seq is None or abs(
            Decimal(seq.risk_level or "0") - Decimal(str(q["riskLevel"]))
        ) >= Decimal("1e-8"):
            risk_differences.append(
                {
                    "at": q["ts"],
                    "reference": q["riskLevel"],
                    "local": seq.risk_level if seq else None,
                }
            )
    report = {
        "scope": "exported_window_only",
        "provider": "unverified_export" if args.exported_bars else "binance_spot",
        "includes_forming_observation": args.include_forming_observation,
        "warning": (
            "A match proves this captured sample only, "
            "not all market regimes or live provider equivalence."
        ),
        "closed_before": cutoff.isoformat(),
        "evaluated_through": input_cutoff.isoformat(),
        "bar_count": len(bars),
        "config": config.model_dump(),
        "reference_markers": len(expected),
        "matched_markers": len(expected & local),
        "reference_only": sorted(expected - local),
        "local_only": sorted(local - expected),
        "reference_qualified13_count": len(reference["result"]["qualified13s"]),
        "local_qualified13_count": result.qualified13_count,
        "risk_differences": risk_differences,
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n")
    print(
        json.dumps(
            {
                "bars": len(bars),
                "matched": len(expected & local),
                "reference": len(expected),
                "missing": len(expected - local),
                "extra": len(local - expected),
                "risk_differences": len(risk_differences),
                "qualified13": result.qualified13_count,
            }
        )
    )


if __name__ == "__main__":
    main()
