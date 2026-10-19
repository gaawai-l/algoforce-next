import type { CostFlowView, FlowGrid } from "./onchain-contract";

// Chart 3's rows, bars and side weights (Buy & Sell Side By Cost Basis), following the original
// state-report page (A = raw/script_2_app.js, H = raw/state-report.html): the reader's window,
// holders, aging and zoom pick them out of the grids the service sends.

export type Window = "1d" | "7d" | "30d" | "90d";
// 0 is Zoom All; the others are ±% of spot.
export type Zoom = 0 | 50 | 25 | 10;
export type Holders = "all" | "sth" | "lth";
export type Side = "pos" | "neg";
// The buttons, in the page's order: H:790, H:804 (Chart 3) and H:973 (Chart 4).
export const WINDOWS: readonly Window[] = ["1d", "7d", "30d", "90d"];
export const ZOOMS3: readonly Zoom[] = [0, 50, 25, 10];
export const ZOOMS4: readonly Zoom[] = [0, 50, 25];

// One grid row: its floor, its middle price and each cohort's change over the window.
export interface FlowRow {
  b: number;
  price: number;
  all: number;
  sth: number;
  lth: number;
}
export interface Seg {
  v: number;
  cls: "bar-pos" | "bar-neg" | "bar-aging-pos" | "bar-aging-neg";
  aging: boolean;
}
export type Found<T> = { ok: true; value: T } | { ok: false; missing: "grid" | "window" | "age" };

// Snapshots are stored to the cent, so differencing two leaves float noise in almost every
// bucket; half of the last stored digit is the real floor of a bar (A:1324-1328).
const EPS = 0.005;

// A:1302: STH reads the $200 grid, All and LTH the $500 one; null when the service has none.
export function gridFor(view: CostFlowView, h: Holders): FlowGrid | null {
  const step = h === "sth" ? 200 : 500;
  return view.grids.find((grid) => grid.step === step) ?? null;
}

// A:1304-1335: each row's change from the window's then day to D. A ±% zoom keeps the rows priced
// within that band of spot; Zoom All trims both ends to the first and last row that draws a bar,
// asking segments(), so it follows the holders and the aging setting.
export function udiff(
  grid: FlowGrid,
  w: Window,
  h: Holders,
  aging: boolean,
  z: Zoom,
  spot: number,
): Found<FlowRow[]> {
  const then = grid.windows.find((found) => found.window === w)?.then;
  if (!then) return { ok: false, missing: "window" };
  const now = grid.now;
  const half = grid.step / 2;
  let rows = grid.floors.map((b, i) => {
    const all = now.all[i] - then.all[i];
    const sth = now.sth[i] - then.sth[i];
    const lth = now.lth[i] - then.lth[i];
    return { b, price: b + half, all, sth, lth };
  });
  if (z > 0) {
    const lo = spot * (1 - z / 100),
      hi = spot * (1 + z / 100);
    rows = rows.filter((r) => r.price >= lo && r.price <= hi);
  } else {
    let i = 0,
      j = rows.length - 1;
    const live = (r: FlowRow) => segments(r, h, aging).some((sg) => Math.abs(sg.v) >= EPS);
    while (i < j && !live(rows[i])) i++;
    while (j > i && !live(rows[j])) j--;
    rows = rows.slice(i, j + 1);
  }
  return { ok: true, value: rows };
}

// A:1346-1394: the bars a bucket draws. A bar's sign picks its side, so a bucket can be on both.
// All draws its change; STH and LTH with Aging Hide their own apparent change. With Aging Show
// they draw the real flow and, only when it is ageing, the correction: coins leaving STH by age
// (a decrease, on the sell side) or arriving in LTH (an increase, on the buy side). It is a lower
// bound, since real spending from the same bucket nets against it.
export function segments(r: FlowRow, h: Holders, aging: boolean): Seg[] {
  if (h === "all") {
    return [{ v: r.all, cls: r.all >= 0 ? "bar-pos" : "bar-neg", aging: false }];
  }
  if (!aging) {
    const raw = h === "sth" ? r.sth : r.lth;
    return [{ v: raw, cls: raw >= 0 ? "bar-pos" : "bar-neg", aging: false }];
  }
  const real: Seg = { v: r.all, cls: r.all >= 0 ? "bar-pos" : "bar-neg", aging: false };
  const av = h === "sth" ? -r.lth : -r.sth;
  const isAging = h === "sth" ? av < 0 : av > 0;
  if (!isAging) return [real];
  return [real, { v: av, aging: true, cls: av >= 0 ? "bar-aging-pos" : "bar-aging-neg" }];
}

// A:1397
function bucketTotal(r: FlowRow, h: Holders, aging: boolean): number {
  return segments(r, h, aging).reduce((a, s) => a + s.v, 0);
}

// A:1398-1401: what each row weighs on one side for the KDE and the mixture: the size of its
// bars' sum when the sum is on that side, else 0.
export function sideWeights(
  rows: readonly FlowRow[],
  h: Holders,
  aging: boolean,
  side: Side,
): number[] {
  return rows.map((r) => {
    const t = bucketTotal(r, h, aging);
    return side === "pos" ? Math.max(0, t) : Math.max(0, -t);
  });
}
