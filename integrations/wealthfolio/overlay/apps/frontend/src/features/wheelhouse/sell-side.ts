import type { TextFn } from "./i18n";
import type { SellSideView } from "./onchain-contract";

// The sell-side chart's choices and arithmetic, following the original state-report page:
// smoothing, the rows kept, the span and the shares all depend on the reader's choices, so they
// are worked out here from the hourly legs the service sends.

export type Measure = "pnl" | "volb" | "volu";
export type Exclude = "" | "x1" | "x24";
// LTH profit and loss, STH profit and loss, stacked in this order from the bottom.
export type Leg = "LP" | "LL" | "SP" | "SL";
export const LEGS: readonly Leg[] = ["LP", "LL", "SP", "SL"];
export const SPANS = [
  { label: "1d", rows: 24 },
  { label: "7d", rows: 168 },
  { label: "30d", rows: 720 },
  { label: "90d", rows: 2160 },
] as const;
export const SMOOTHINGS = [1, 24, 168] as const;
export const MEASURES: readonly Measure[] = ["pnl", "volb", "volu"];
export const EXCLUDES: readonly Exclude[] = ["", "x1", "x24"];
const HOUR = 3_600_000;

export interface Choice {
  measure: Measure;
  exclude: Exclude;
  // Hours in the trailing mean; 1 is no smoothing.
  smoothing: number;
  // Rows shown, counted after the rows without a positive total are left out.
  span: number;
  shown: readonly Leg[];
}
// The original page's defaults.
export const DEFAULT_CHOICE: Choice = {
  measure: "pnl",
  exclude: "x24",
  smoothing: 24,
  span: 720,
  shown: LEGS,
};

export interface SellSideRow {
  t: number;
  px: number;
  vals: Record<Leg, number>;
  // The shown legs added up: the denominator of the shares and the bar's height.
  tot: number;
  // One clock hour after the payload's row before it, whatever was left out of the chart since:
  // the price line joins only such rows, as on the original.
  contig: boolean;
}

// A trailing mean over a fixed window; the first w-1 rows have none rather than a partial one.
export function sma(values: readonly number[], w: number): (number | undefined)[] {
  if (w <= 1) return values.slice();
  const out: (number | undefined)[] = new Array(values.length).fill(undefined);
  let run = 0;
  for (let i = 0; i < values.length; i += 1) {
    run += values[i];
    if (i >= w) run -= values[i - w];
    if (i >= w - 1) out[i] = run / w;
  }
  return out;
}

function legColumns(view: SellSideView, measure: Measure, exclude: Exclude) {
  const legs = view[measure];
  return {
    LP: legs.lth_profit,
    LL: legs.lth_loss,
    SP: exclude === "" ? legs.sth_profit : legs[`sth_profit_${exclude}`],
    SL: exclude === "" ? legs.sth_loss : legs[`sth_loss_${exclude}`],
  } satisfies Record<Leg, number[]>;
}

// The rows the charts draw: smoothed, with a positive total of the shown legs, the last `span`.
export function buildRows(view: SellSideView, choice: Choice): SellSideRow[] {
  const columns = legColumns(view, choice.measure, choice.exclude);
  const smoothed = Object.fromEntries(
    LEGS.map((leg) => [leg, sma(columns[leg], choice.smoothing)]),
  ) as Record<Leg, (number | undefined)[]>;
  const rows: SellSideRow[] = [];
  for (let i = 0; i < view.at.length; i += 1) {
    if (smoothed.LP[i] === undefined) continue;
    const vals = Object.fromEntries(
      LEGS.map((leg) => [leg, smoothed[leg][i] as number]),
    ) as Record<Leg, number>;
    let tot = 0;
    for (const leg of choice.shown) tot += vals[leg];
    // Nothing to share out: the row is left out, never drawn as an empty bar.
    if (!(tot > 0)) continue;
    const t = Date.parse(view.at[i]);
    const contig = i === 0 || t - Date.parse(view.at[i - 1]) === HOUR;
    rows.push({ t, px: view.price[i], vals, tot, contig });
  }
  return rows.slice(Math.max(0, rows.length - choice.span));
}

// d3's tick arithmetic (d3-array 3, d3-scale 4), which the original page's axes use.
const E10 = Math.sqrt(50);
const E5 = Math.sqrt(10);
const E2 = Math.sqrt(2);

function tickSpec(start: number, stop: number, count: number): [number, number, number] {
  const step = (stop - start) / Math.max(0, count);
  const power = Math.floor(Math.log10(step));
  const error = step / 10 ** power;
  const factor = error >= E10 ? 10 : error >= E5 ? 5 : error >= E2 ? 2 : 1;
  let i1: number;
  let i2: number;
  let inc: number;
  if (power < 0) {
    inc = 10 ** -power / factor;
    i1 = Math.round(start * inc);
    i2 = Math.round(stop * inc);
    if (i1 / inc < start) i1 += 1;
    if (i2 / inc > stop) i2 -= 1;
    inc = -inc;
  } else {
    inc = 10 ** power * factor;
    i1 = Math.round(start / inc);
    i2 = Math.round(stop / inc);
    if (i1 * inc < start) i1 += 1;
    if (i2 * inc > stop) i2 -= 1;
  }
  if (i2 < i1 && count >= 0.5 && count < 2) return tickSpec(start, stop, count * 2);
  return [i1, i2, inc];
}

export function ticks(start: number, stop: number, count: number): number[] {
  if (start === stop) return [start];
  const [i1, i2, inc] = tickSpec(start, stop, count);
  if (!(i2 >= i1)) return [];
  return Array.from({ length: i2 - i1 + 1 }, (_, i) =>
    inc < 0 ? (i1 + i) / -inc : (i1 + i) * inc,
  );
}

// A linear scale's nice(): widen the domain to whole steps, by default for ten ticks.
export function niceDomain(start: number, stop: number, count = 10): [number, number] {
  let prestep: number | undefined;
  for (let i = 0; i < 10; i += 1) {
    const step = tickSpec(start, stop, count)[2];
    if (step === prestep) break;
    if (step > 0) {
      start = Math.floor(start / step) * step;
      stop = Math.ceil(stop / step) * step;
    } else if (step < 0) {
      start = Math.ceil(start * step) / step;
      stop = Math.floor(stop * step) / step;
    } else break;
    prestep = step;
  }
  return [start, stop];
}

// Formats as the original prints them.
const grouped = (value: number) =>
  Number(value.toFixed(0)).toLocaleString("en-US");
export const fmtPct = (value: number) => `${(value * 100).toFixed(1)}%`;
export const fmtUsd = (value: number) =>
  value >= 1e9
    ? `$${(value / 1e9).toFixed(2)}B`
    : value >= 1e6
      ? `$${(value / 1e6).toFixed(1)}M`
      : `$${grouped(value)}`;
export const fmtBtc = (value: number) =>
  value >= 1e3 ? `${grouped(value)} BTC` : `${value.toFixed(1)} BTC`;
export const fmtVal = (value: number, measure: Measure) =>
  measure === "volb" ? fmtBtc(value) : fmtUsd(value);

// d3-format 3's formatDecimalParts: the significant digits of `x` to `p` places, and its exponent.
function decimalParts(x: number, p: number): [string, number] {
  const text = p ? x.toExponential(p - 1) : x.toExponential();
  const e = text.indexOf("e");
  const coefficient = text.slice(0, e);
  return [
    coefficient.length > 1 ? coefficient[0] + coefficient.slice(2) : coefficient,
    Number(text.slice(e + 1)),
  ];
}

// d3-format 3's formatTrim: insignificant trailing zeros dropped, and the point with them.
function trimZeros(s: string) {
  let i0 = -1;
  let i1 = -1;
  for (let i = 1; i < s.length; i += 1) {
    if (s[i] === ".") {
      i0 = i;
      i1 = i;
    } else if (s[i] === "0") {
      if (i0 === 0) i0 = i;
      i1 = i;
    } else {
      if (!Number(s[i])) break;
      if (i0 > 0) i0 = 0;
    }
  }
  return i0 > 0 ? s.slice(0, i0) + s.slice(i1 + 1) : s;
}

const PREFIXES = [
  ..."yzafpnµm",
  "",
  ..."kMBTPEZY",
];
// d3.format("~s") with G written as B, as the original prints it: six significant digits, an SI
// prefix, trailing zeros dropped (d3-format 3's formatPrefixAuto).
export function si(value: number) {
  const abs = Math.abs(value);
  const [coefficient, exponent] = decimalParts(abs, 6);
  const tier = Math.max(-8, Math.min(8, Math.floor(exponent / 3)));
  const i = exponent - tier * 3 + 1;
  const n = coefficient.length;
  const digits =
    i === n
      ? coefficient
      : i > n
        ? coefficient + "0".repeat(i - n)
        : i > 0
          ? `${coefficient.slice(0, i)}.${coefficient.slice(i)}`
          : `0.${"0".repeat(-i)}${decimalParts(abs, Math.max(0, 6 + i - 1))[0]}`;
  return `${value < 0 ? "−" : ""}${trimZeros(digits)}${PREFIXES[8 + tier]}`;
}
// An axis label: dollars carry a $, coins none, as on the original.
export const axisValue = (value: number, measure: Measure) =>
  measure === "volb" ? si(value) : `$${si(value)}`;

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
// "19 Oct 2026 · 05:00", always UTC.
export function footTime(t: number) {
  const d = new Date(t);
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hour = String(d.getUTCHours()).padStart(2, "0");
  return `${day} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()} · ${hour}:00`;
}

// The line under each chart, as on the original: when, how smoothed, what, the total of the shown
// legs, and which coins the short-term legs leave out.
export function footLine(text: TextFn, row: SellSideRow, choice: Choice) {
  const bits = [
    `${footTime(row.t)} UTC`,
    choice.smoothing === 1
      ? text("sellside.noSmoothing")
      : text("sellside.mean", { n: choice.smoothing }),
    text(`sellside.note.${choice.measure}`),
    text("sellside.total", { value: fmtVal(row.tot, choice.measure) }),
  ];
  if (choice.exclude) bits.push(text(`sellside.ex.${choice.exclude}`));
  return bits.join(" · ");
}
