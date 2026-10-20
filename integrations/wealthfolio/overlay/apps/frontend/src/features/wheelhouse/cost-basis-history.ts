import type { CostBasisHistoryView } from "./onchain-contract";
import { tickSpec } from "./sell-side";

// The cost-basis history chart's arithmetic, following the original state-report page's Chart 8
// (`raw/script_2_app.js`, A:3914-4288): the window on screen, the rows Range and a dragged band
// keep, the Contrast quantiles, the colour of each cell, the axes, the key, the labels and the
// readouts all depend on the reader's choices, so they are worked out here from the days the
// service sends.
//
// Deliberate departures: every calendar day keeps its column, and a missing day stays null and is
// left out of every quantile and range, where the original drops it from the window (plan R9); a
// cell at or under the floor gets its own darker step instead of the empty ground (plan R11); the
// ramp is the local cyan one (plan R14).

export type SpanKey = CostBasisHistoryView["span"];
export type DayStatus = CostBasisHistoryView["status"][number];
// The original's spans; All is the last 1,461 days, as the original fetches (plan R2).
export const CBH_SPANS: readonly { key: SpanKey; days: number }[] = [
  { key: "30", days: 30 },
  { key: "90", days: 90 },
  { key: "365", days: 365 },
  { key: "all", days: 1461 },
];
// The original page's defaults (A:3914).
export const DEFAULT_SPAN: SpanKey = "365";
export const RANGES = [0, 50, 25, 10] as const;
export type RangePct = (typeof RANGES)[number];
export const DEFAULT_CONTRAST = { lo: 75, hi: 95 } as const;
// The data's own precision: a cell at or under it holds no coins (A:3959).
export const OCCUPIED = 0.005;
// The grid's bucket width in dollars.
export const STEP = 500;
// A cell holding coins at or under the Contrast floor (plan R11).
export const UNDER_FLOOR = "#233142";
// The four steps over the Contrast window, dim to bright (plan R14).
export const RAMP = ["#164a52", "#1f7f80", "#33b3a3", "#59e6cd"] as const;

// The columns on screen, one per calendar day; a missing day has a null close and row.
export interface Visible {
  days: string[];
  close: (number | null)[];
  supply: (number[] | null)[];
  status: DayStatus[];
}

// The days on screen: a dragged window of two days or more, else the whole span (A:3933-3944).
export function visibleWindow(
  view: CostBasisHistoryView,
  zx: [string, string] | null,
): { vis: Visible; zx: [string, string] | null } {
  if (zx) {
    const keep = view.days.flatMap((day, i) => (day >= zx[0] && day <= zx[1] ? [i] : []));
    if (keep.length >= 2) {
      return {
        vis: {
          days: keep.map((i) => view.days[i]),
          close: keep.map((i) => view.close[i]),
          supply: keep.map((i) => view.supply[i]),
          status: keep.map((i) => view.status[i]),
        },
        zx,
      };
    }
  }
  return {
    vis: { days: view.days, close: view.close, supply: view.supply, status: view.status },
    zx: null,
  };
}

// The rows drawn: the occupied ones of the stored days, narrowed by a dragged band, else by Range
// around the last stored day's close, either only when it keeps two rows or more; null when no
// cell holds coins (A:3960-3985). A band that keeps nothing is dropped.
export function occupiedRows(
  floors: number[],
  vis: Visible,
  range: RangePct,
  zy: [number, number] | null,
): { r0: number; r1: number; zy: [number, number] | null } | null {
  let lo = floors.length;
  let hi = -1;
  for (const row of vis.supply) {
    if (!row) continue;
    for (let i = 0; i < row.length; i += 1) {
      if (row[i] > OCCUPIED) {
        if (i < lo) lo = i;
        if (i > hi) hi = i;
      }
    }
  }
  if (hi < 0) return null;
  const band = (from: number, to: number): [number, number] => [
    Math.max(lo, Math.floor((from - floors[0]) / STEP)),
    Math.min(hi, Math.ceil((to - floors[0]) / STEP)),
  ];
  if (zy) {
    const [a, b] = band(zy[0], zy[1]);
    if (b > a) return { r0: a, r1: b, zy };
  }
  if (range > 0) {
    // The last stored day; there is one, since a row is occupied.
    let last = vis.supply.length - 1;
    while (vis.supply[last] === null) last -= 1;
    const spot = vis.close[last];
    if (spot) {
      const f = range / 100;
      const [a, b] = band(spot * (1 - f), spot * (1 + f));
      if (b > a) return { r0: a, r1: b, zy: null };
    }
  }
  return { r0: lo, r1: hi, zy: null };
}

// The cells on screen that hold coins, ascending: what the Contrast quantiles read (A:3987-3996).
export function sortedCells(vis: Visible, r0: number, r1: number): Float64Array {
  const out: number[] = [];
  for (const row of vis.supply) {
    if (!row) continue;
    for (let i = r0; i <= r1; i += 1) if (row[i] > OCCUPIED) out.push(row[i]);
  }
  return Float64Array.from(out).sort();
}

// The Contrast window: the floor and cap at the handles' quantiles, by nearest rank (A:4009-4018).
// Without a cell it reads [0, 1], as the original's render8 does (A:4055).
export interface Contrast {
  floor: number;
  cap: number;
  span: number;
  clipped: boolean;
  dropped: boolean;
}
export function contrast(sorted: Float64Array, lo: number, hi: number): Contrast {
  const s = sorted.length ? sorted : Float64Array.of(0, 1);
  const n = s.length;
  const at = (q: number) => s[Math.min(n - 1, Math.max(0, Math.round((q / 100) * (n - 1))))];
  const top = s[n - 1];
  const floor = lo <= 0 ? 0 : at(lo);
  const cap = hi >= 100 ? top : Math.max(at(hi), floor + 1e-9);
  const span = Math.max(1e-9, cap - floor);
  return { floor, cap, span, clipped: cap < top, dropped: floor > 0 };
}

// 0 holds no coins, 1 is at or under the floor (plan R11), 2-5 are the ramp's four steps, linear in
// BTC over the window (A:4017, A:4041-4046).
export type Level = 0 | 1 | 2 | 3 | 4 | 5;
export function cellLevel(v: number, c: Contrast): Level {
  if (v <= OCCUPIED) return 0;
  if (v <= c.floor) return 1;
  return (2 + Math.min(3, Math.floor(Math.min(1, (v - c.floor) / c.span) * 4))) as Level;
}

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const COLOURS = [UNDER_FLOOR, ...RAMP].map(rgb);

// The heatmap's RGBA, one pixel per day and row, row r at y = r1 - r since a canvas runs top-down
// (A:4081); an empty cell and a missing day are transparent.
export function paint(
  vis: Visible,
  r0: number,
  r1: number,
  c: Contrast,
  out: Uint8ClampedArray,
): void {
  const width = vis.days.length;
  for (let x = 0; x < width; x += 1) {
    const row = vis.supply[x];
    for (let r = r0; r <= r1; r += 1) {
      const p = ((r1 - r) * width + x) * 4;
      const level = row ? cellLevel(row[r], c) : 0;
      if (level === 0) {
        out.fill(0, p, p + 4);
      } else {
        out.set(COLOURS[level - 1], p);
        out[p + 3] = 255;
      }
    }
  }
}

// The original's formats (A:3924-3927): supply in BTC, a price, and a bucket edge to one decimal.
export const fmtSupply = (v: number) =>
  v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : `${Math.round(v)}`;
export const fmtK = (v: number) => `$${(v / 1000).toFixed(v < 10000 ? 1 : 0)}k`;
export const fmtBucket = (v: number) => `$${(v / 1000).toFixed(1)}k`;

// The key: where each step starts, a minus (U+2212) on the first while the floor drops cells, and
// the cap with a plus while it clips them (A:4117-4130).
export function keyLabels(c: Contrast): string[] {
  const marks = [0, 1, 2, 3].map((k) => c.floor + (k / 4) * c.span);
  return [
    ...marks.map((v, k) => `${k === 0 && c.dropped ? "−" : ""}${fmtSupply(v)}`),
    `${fmtSupply(c.cap)}${c.clipped ? "+" : ""}`,
  ];
}

// The Contrast label, with en dashes (U+2013); null for the full range (A:4133-4139).
export function contrastLabel(c: Contrast, lo: number, hi: number): string | null {
  if (!c.dropped && !c.clipped) return null;
  const values = `${fmtSupply(c.floor)}–${fmtSupply(c.cap)}${c.clipped ? "+" : ""}`;
  return `${Math.round(lo)}–${Math.round(hi)}% · ${values}`;
}

// The handles clamp and never swap: the moved one stops a point short of the other (A:4164-4172).
export function clampHandle(
  which: "lo" | "hi",
  value: number,
  lo: number,
  hi: number,
): [number, number] {
  if (which === "lo") lo = Math.min(value, hi - 1);
  else hi = Math.max(value, lo + 1);
  return [Math.max(0, Math.min(99, lo)), Math.min(100, Math.max(1, hi))];
}

// A box of 6 px or more on either axis zooms (A:4189).
const DRAG_MIN = 6;

// A dragged box as whole days and a price band (A:4200-4219); null for a click.
export function zoomFromDrag(
  box: { x0: number; x1: number; y0: number; y1: number },
  plot: { width: number; height: number },
  days: string[],
  yLo: number,
  yHi: number,
): { zx: [string, string] | null; zy: [number, number] | null } | null {
  const dx = Math.abs(box.x1 - box.x0);
  const dy = Math.abs(box.y1 - box.y0);
  if (dx < DRAG_MIN && dy < DRAG_MIN) return null;
  let zx: [string, string] | null = null;
  let zy: [number, number] | null = null;
  if (dx >= DRAG_MIN) {
    const n = days.length;
    const day = (x: number) => days[Math.max(0, Math.min(n - 1, Math.floor(x / (plot.width / n))))];
    const a = day(Math.min(box.x0, box.x1));
    const b = day(Math.max(box.x0, box.x1));
    if (a < b) zx = [a, b];
  }
  if (dy >= DRAG_MIN) {
    const price = (y: number) => yHi - (y / plot.height) * (yHi - yLo);
    const p0 = price(box.y0);
    const p1 = price(box.y1);
    zy = [Math.min(p0, p1), Math.max(p0, p1)];
  }
  return { zx, zy };
}

const DAY = 864e5;
// d3-time's tick intervals from a day up (d3 v7.9.0, which the original embeds): the interval, its
// step and its length in days; a month is 30 days and a year 365.
type Unit = "day" | "week" | "month" | "year";
const INTERVALS: readonly [Unit, number, number][] = [
  ["day", 1, 1],
  ["day", 2, 2],
  ["week", 1, 7],
  ["month", 1, 30],
  ["month", 3, 90],
  ["year", 1, 365],
];

// Whether midnight `t` starts an interval. utcTicks counts days by d3's unixDay, days since
// 1970-01-01, so two-day ticks fall on even ones; weeks start on Sunday; months and years count
// from January.
function onInterval(t: number, unit: Unit, step: number) {
  const date = new Date(t);
  if (unit === "day") return Math.floor(t / DAY) % step === 0;
  if (unit === "week") return date.getUTCDay() === 0;
  const first = date.getUTCDate() === 1;
  if (unit === "month") return first && date.getUTCMonth() % step === 0;
  return first && date.getUTCMonth() === 0 && date.getUTCFullYear() % step === 0;
}

// The days d3's utcTicks(first, last, count) lands on (d3-time tickInterval, A:4093). A window
// under a day per tick ticks every day, where d3 would tick hours and print each date twice.
export function dayTicks(first: string, last: string, count: number): string[] {
  const t0 = Date.parse(`${first}T00:00:00Z`);
  const t1 = Date.parse(`${last}T00:00:00Z`);
  const target = (t1 - t0) / count;
  const i = INTERVALS.findIndex(([, , days]) => days * DAY > target);
  let unit: Unit = "day";
  let step = 1;
  if (i < 0) {
    // d3's tickStep over years of 365 days.
    const [, , inc] = tickSpec(t0 / (365 * DAY), t1 / (365 * DAY), count);
    unit = "year";
    step = Math.floor(inc < 0 ? 1 / -inc : inc);
  } else if (i > 0) {
    const below = INTERVALS[i - 1][2] * DAY;
    const above = INTERVALS[i][2] * DAY;
    [unit, step] = INTERVALS[target / below < above / target ? i - 1 : i];
  }
  const out: string[] = [];
  for (let t = t0; t <= t1; t += DAY) {
    if (onInterval(t, unit, step)) out.push(new Date(t).toISOString().slice(0, 10));
  }
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// A time tick's label by the window's length in days, last minus first (A:4091-4092): %d %b up to
// 120 days, %b %y up to 800, else %Y.
export function dayLabel(day: string, spanDays: number): string {
  const [year, month, date] = day.split("-");
  const name = MONTHS[Number(month) - 1];
  if (spanDays <= 120) return `${date} ${name}`;
  if (spanDays <= 800) return `${name} ${year.slice(2)}`;
  return year;
}

// The tooltip's parts (A:4282-4287); a missing day names only why.
export type TipParts =
  | { day: string; bucket: string; supply: string; spot: string | null }
  | { day: string; missing: "pending" | "absent" };
export function tipParts(vis: Visible, i: number, r: number, floors: number[]): TipParts {
  const day = vis.days[i];
  const row = vis.supply[i];
  if (!row) return { day, missing: vis.status[i] === "absent" ? "absent" : "pending" };
  const close = vis.close[i];
  return {
    day,
    bucket: `${fmtBucket(floors[r])}–${fmtBucket(floors[r] + STEP)}`,
    supply: `${Math.round(row[r]).toLocaleString("en-US")} BTC`,
    spot: close === null ? null : fmtK(close),
  };
}

// The zoom note without its hint (A:4239-4242): the dragged days and the price band.
export function zoomText(zx: [string, string] | null, zy: [number, number] | null): string {
  const bits: string[] = [];
  if (zx) bits.push(`${zx[0].slice(5)}–${zx[1].slice(5)}`);
  if (zy) bits.push(`${fmtK(zy[0])}–${fmtK(zy[1])}`);
  return bits.join(" · ");
}

// How many days on screen have a snapshot, of how many, and why the rest are missing.
export function coverage(vis: Visible): {
  have: number;
  want: number;
  pending: number;
  absent: number;
  forming: number;
} {
  const count = (status: DayStatus) => vis.status.filter((s) => s === status).length;
  const forming = count("forming");
  return {
    have: count("closed") + forming,
    want: vis.days.length,
    pending: count("pending"),
    absent: count("absent"),
    forming,
  };
}
