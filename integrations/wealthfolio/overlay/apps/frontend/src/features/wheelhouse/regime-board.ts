import type { TimeframeContext } from "./regime-contract";

export type Board = "cta" | "opt" | "all";
export type RegimeSide = "intraday" | "swing";
type Signal = TimeframeContext["signals"][number];

/** AlphaBTC: grid board uses the 1h regime, option board the 4h, "all" splits by timeframe. */
export function regimeSideFor(
  board: Board,
  timeframe: TimeframeContext["timeframe"],
): RegimeSide {
  if (board === "cta") return "intraday";
  if (board === "opt") return "swing";
  return timeframe === "5m" || timeframe === "15m" || timeframe === "1h"
    ? "intraday"
    : "swing";
}

export function signalLevel(
  signal: Signal,
  side: RegimeSide,
  calibrated: boolean,
): number | null {
  if (!signal.active) return null;
  if (!calibrated) return signal.base_level;
  return side === "intraday" ? signal.intraday_level : signal.swing_level;
}

/** AlphaBTC `tdShort`: "<1h", hours below two days, then days. */
export function shortAge(seconds: number | null): string | null {
  if (seconds == null) return null;
  const hours = Math.round(seconds / 3600);
  if (hours < 1) return "<1h";
  if (hours < 48) return `${hours}h`;
  return `${Math.round(hours / 24)}D`;
}
