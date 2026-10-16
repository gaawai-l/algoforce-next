import type { Analysis } from "./client";

export type BarWindow = { start: number; end: number };
export type RangeChoice =
  | { kind: "all" }
  | { kind: "week" }
  | { kind: "friday" }
  | { kind: "custom"; from: string; to: string };

export function defaultBarCount(
  timeframe: string,
  width: number,
  total: number,
): number {
  const base = timeframe.endsWith("m") ? 160 : timeframe === "1h" ? 150 : 120;
  return Math.min(
    total,
    Math.max(base, Math.min(360, Math.floor(Math.max(0, width) / 5))),
  );
}

export function fridayWindow(at: number): { from: number; to: number } {
  const shifted = new Date(at + 8 * 3600000);
  const dayStart = Date.UTC(
    shifted.getUTCFullYear(),
    shifted.getUTCMonth(),
    shifted.getUTCDate(),
  );
  let friday = dayStart - ((shifted.getUTCDay() + 2) % 7) * 86400000 + 3600000;
  if (friday > at) friday -= 7 * 86400000;
  return { from: friday - 7 * 86400000, to: friday };
}

export function visibleWindow(
  bars: Analysis["bars"],
  timeframe: string,
  width: number,
  visibleBars: number,
  choice: RangeChoice | null,
): BarWindow & { clipped: boolean } {
  const total = bars.length;
  if (!total) return { start: 0, end: -1, clipped: false };
  const last = Date.parse(bars[total - 1].bar.close_time);
  if (choice?.kind === "all" || (!choice && visibleBars === -1))
    return { start: 0, end: total - 1, clipped: false };
  if (!choice) {
    const count =
      visibleBars === 0
        ? defaultBarCount(timeframe, width, total)
        : visibleBars;
    return {
      start: Math.max(0, total - count),
      end: total - 1,
      clipped: false,
    };
  }
  const requested =
    choice.kind === "week"
      ? { from: last - 7 * 86400000, to: last }
      : choice.kind === "friday"
        ? fridayWindow(last)
        : { from: Date.parse(choice.from), to: Date.parse(choice.to) };
  const start = bars.findIndex(
    (b) => Date.parse(b.bar.open_time) >= requested.from,
  );
  let end = total - 1;
  while (end >= 0 && Date.parse(bars[end].bar.close_time) > requested.to) end--;
  const first = Date.parse(bars[0].bar.open_time);
  return {
    start: start < 0 ? total : start,
    end,
    clipped: requested.from < first || requested.to > last,
  };
}
