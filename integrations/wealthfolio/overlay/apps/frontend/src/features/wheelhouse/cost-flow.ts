import type { EnginePeak, GmmComp, SideCurves, SideSetting } from "./cost-flow-engine";
import type { TextFn } from "./i18n";
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

// Chart 3's readings: the legend, the aging note, the two tables and the tooltip (A:1748-1904).
// The page's integers are d3's ",.0f", which rounds with toFixed.
const fmtInt = (v: number) => Number(v.toFixed(0)).toLocaleString("en-US");
// A:1583
export const fmtSigned = (v: number) => (v >= 0 ? "+" : "−") + fmtInt(Math.abs(v));
// A:1584
export const fmtPrice = (v: number) => "$" + fmtInt(v);
// A:1810 without its unit: the copy and the cells add " BTC".
export const fmtBtc = (v: number) => fmtInt(v);

// A:1811-1817: how far a level sits from spot; "—" without a spot.
export function vsSpot(text: TextFn, price: number, spot: number): string {
  if (!(spot > 0)) return "—";
  const pct = Math.abs(price / spot - 1) * 100;
  return text(price < spot ? "costflow.below" : "costflow.above", { pct: pct.toFixed(1) });
}

// A:1748-1779: the legend's totals, read off the drawn bars so they cannot disagree with them.
// sell is the size of the sell side. aging is the aging bars' size and share its fraction of the
// side they are drawn on (STH's sell side, LTH's buy side); both are null when no aging row is
// shown, that is for All or with Aging Hide.
export function flowTotals(
  rows: readonly FlowRow[],
  h: Holders,
  aging: boolean,
): { buy: number; sell: number; aging: number | null; share: number | null } {
  let buy = 0,
    sell = 0,
    age = 0;
  for (const r of rows)
    for (const sg of segments(r, h, aging)) {
      if (sg.v > 0) buy += sg.v;
      else sell += -sg.v;
      if (sg.aging) age += Math.abs(sg.v);
    }
  if (!aging || h === "all") return { buy, sell, aging: null, share: null };
  const side = h === "sth" ? sell : buy;
  return { buy, sell, aging: age, share: side > 0 ? age / side : 0 };
}

// A:1625-1633: the bars drawn per class; a bar of zero is not drawn.
export function barCounts(
  rows: readonly FlowRow[],
  h: Holders,
  aging: boolean,
): Record<Seg["cls"], number> {
  const n: Record<Seg["cls"], number> = {
    "bar-pos": 0,
    "bar-neg": 0,
    "bar-aging-pos": 0,
    "bar-aging-neg": 0,
  };
  for (const r of rows) for (const sg of segments(r, h, aging)) if (sg.v !== 0) n[sg.cls] += 1;
  return n;
}

// A:1786-1802: what the Aging button does for the holders shown, then the bucket size.
export function agingNote(text: TextFn, h: Holders, aging: boolean, step: number): string {
  const bins = text("costflow.bins", { step: step.toLocaleString("en-US") });
  if (h === "all") return text("costflow.note.all", { bins });
  if (h === "sth") return text(aging ? "costflow.note.sthShow" : "costflow.note.sthHide", { bins });
  return text(aging ? "costflow.note.lthShow" : "costflow.note.lthHide", { bins });
}

// One Clusters row: the KDE peaks of both sides by price, numbered in that order (A:1819-1823).
export interface Cluster {
  n: number;
  side: Side;
  peak: EnginePeak;
}

// A:1819-1840
export function clusters(pos: SideCurves | null, neg: SideCurves | null): Cluster[] {
  const rows: { side: Side; peak: EnginePeak }[] = [];
  for (const [side, curves] of [
    ["pos", pos],
    ["neg", neg],
  ] as const)
    for (const peak of curves?.peaks ?? []) rows.push({ side, peak });
  rows.sort((a, b) => a.peak.location - b.peak.location);
  return rows.map((r, i) => ({ n: i + 1, ...r }));
}

// One Bell curve components row: m numbers the bells within their side; Est. BTC is
// comp.w × totalW (A:1861-1864).
export interface MixRow {
  m: number;
  side: Side;
  comp: GmmComp;
  totalW: number;
}

// A:1842-1866: the bells of both sides, by centre.
export function mixRows(pos: SideCurves | null, neg: SideCurves | null): MixRow[] {
  const rows: MixRow[] = [];
  for (const [side, curves] of [
    ["pos", pos],
    ["neg", neg],
  ] as const) {
    const f = curves?.mix;
    if (f) f.comps.forEach((comp, i) => rows.push({ m: i + 1, side, comp, totalW: f.totalW }));
  }
  rows.sort((a, b) => a.comp.mu - b.comp.mu);
  return rows;
}

// A:1838: how many clusters, and how many are on each side; empty without one.
export function clusterMeta(text: TextFn, cs: readonly Cluster[]): string {
  if (!cs.length) return "";
  const vars = {
    n: cs.length,
    in: cs.filter((c) => c.side === "pos").length,
    out: cs.filter((c) => c.side === "neg").length,
  };
  return text(cs.length === 1 ? "costflow.clusters.one" : "costflow.clusters.many", vars);
}

// A:1867-1876: where each side's k came from: the marked peaks, the peaks capped at 5, or BIC.
// A side without bells says nothing.
export function mixtureMeta(text: TextFn, pos: SideCurves | null, neg: SideCurves | null): string {
  const part = (curves: SideCurves | null, name: string) => {
    const f = curves?.mix;
    if (!f) return null;
    const side = text(name === "in" ? "costflow.mix.in" : "costflow.mix.out");
    const n = text(f.k === 1 ? "costflow.mix.one" : "costflow.mix.many", { side, k: f.k });
    if (f.src === "bic") return text("costflow.mix.bic", { part: n });
    if (f.raw && f.raw > f.k) return text("costflow.mix.of", { side, k: f.k, n: f.raw });
    return n;
  };
  return [part(pos, "in"), part(neg, "out")].filter((p) => p !== null).join(" · ");
}

// A:1719-1724, worked out on every render: the How many option "auto" names the k auto chose.
// A manual k, or no fit on the side, reads plain "auto"; the page kept a stale k there.
export function kLabel(text: TextFn, s: SideSetting, curves: SideCurves | null): string {
  const f = curves?.mix;
  if (s.kMode !== "auto" || !f) return text("costflow.k.auto");
  if (f.src === "bic") return text("costflow.k.autoBic", { k: f.k });
  if (f.raw && f.raw > f.k) return text("costflow.k.autoOf", { k: f.k, n: f.raw });
  return text("costflow.k.autoK", { k: f.k });
}

// A:1944-1948: the ⚙ chip; Manual shows its width and peak cutoff.
export function chip(s: SideSetting): string {
  if (s.smoothing === "none") return "raw";
  if (s.smoothing === "auto") return "auto";
  return `${s.bw.toFixed(3)} / ${s.minProm.toFixed(2)}`;
}

// A:1880-1904: one bucket's tooltip: its price range, the real flow, the LTH change (aging in or
// LTH selling), the STH change, then what the bucket's change most likely was.
export function flowTip(text: TextFn, r: FlowRow, step: number, w: Window): string[] {
  let verdict: string;
  if (r.sth < 0 && r.lth > 0) {
    const share = (r.lth / (r.lth + Math.abs(Math.min(0, r.all)))) * 100;
    verdict = text("costflow.tip.agingShare", { pct: share.toFixed(0) });
  } else if (r.sth > 0) verdict = text("costflow.tip.sthBought");
  else verdict = text("costflow.tip.left");
  return [
    `${fmtPrice(r.b)} – ${fmtPrice(r.b + step)}`,
    `${text("costflow.tip.real")} ${fmtSigned(r.all)}`,
    `${text(r.lth >= 0 ? "costflow.tip.agingToLth" : "costflow.tip.lthDist")} ${fmtSigned(-r.lth)}`,
    `${text("costflow.tip.sth")} ${fmtSigned(r.sth)}`,
    text("costflow.tip.window", { verdict, window: w }),
  ];
}
