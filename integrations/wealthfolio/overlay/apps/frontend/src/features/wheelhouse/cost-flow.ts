import { BANDS12 } from "./age-cohorts";
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
// A:1810 without its unit: the legend copy and the cell builders below add " BTC".
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
export interface FlowTotals {
  buy: number;
  sell: number;
  aging: number | null;
  share: number | null;
}
export function flowTotals(rows: readonly FlowRow[], h: Holders, aging: boolean): FlowTotals {
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

// One legend row: side is the colour it takes (A:1758-1767); the aging row is drawn hollow.
export interface LegendRow {
  key: "buy" | "sell" | "aging";
  side: Side;
  label: string;
  value: string;
}

// A:1758-1770: Net Buy, Net Sell (shown negative), then, when flowTotals has one, the aging row on
// the side it is drawn on: STH's sell side, LTH's buy side.
export function legendRows(text: TextFn, t: FlowTotals, h: Holders): LegendRow[] {
  const rows: LegendRow[] = [
    { key: "buy", side: "pos", label: text("costflow.buy"), value: `${fmtSigned(t.buy)} BTC` },
    { key: "sell", side: "neg", label: text("costflow.sell"), value: `${fmtSigned(-t.sell)} BTC` },
  ];
  if (t.aging !== null && t.share !== null) {
    const onSell = h === "sth";
    const vars = { btc: fmtBtc(t.aging), pct: `${(t.share * 100).toFixed(0)}%` };
    rows.push({
      key: "aging",
      side: onSell ? "neg" : "pos",
      label: text("costflow.agingRow"),
      value: text(onSell ? "costflow.ofSell" : "costflow.ofBuy", vars),
    });
  }
  return rows;
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

// A table row's text after its number and side pill, and whether its level is below spot, which
// picks the vs-spot tag's colour (A:1813-1816).
export interface TableCells {
  cells: string[];
  below: boolean;
}

// A:1828-1835: Price level, Width, BTC, Share, Strength, vs spot.
export function clusterCells(text: TextFn, c: Cluster, spot: number): TableCells {
  const p = c.peak;
  return {
    cells: [
      fmtPrice(p.location),
      fmtPrice(p.width),
      `${fmtBtc(p.supply)} BTC`,
      `${(p.share * 100).toFixed(1)}%`,
      `${(p.strength * 100).toFixed(0)}%`,
      vsSpot(text, p.location, spot),
    ],
    below: p.location < spot,
  };
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

// A:1856-1863: Centre and Spread rounded to the dollar, Share, Est. BTC (w × totalW), vs spot.
export function mixCells(text: TextFn, r: MixRow, spot: number): TableCells {
  const c = r.comp;
  return {
    cells: [
      fmtPrice(Math.round(c.mu)),
      fmtPrice(Math.round(c.sigma)),
      `${(c.w * 100).toFixed(1)}%`,
      `${fmtBtc(c.w * r.totalW)} BTC`,
      vsSpot(text, c.mu, spot),
    ],
    below: c.mu < spot,
  };
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

// A:1947, A:1949-1953: a width and a peak cutoff as the chip and the sliders show them.
export const fmtBw = (bw: number) => bw.toFixed(3);
export const fmtCutoff = (minProm: number) => minProm.toFixed(2);

// A:1944-1948: the ⚙ chip; Manual shows its width and peak cutoff.
export function chip(s: SideSetting): string {
  if (s.smoothing === "none") return "raw";
  if (s.smoothing === "auto") return "auto";
  return `${fmtBw(s.bw)} / ${fmtCutoff(s.minProm)}`;
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

// Chart 4, the Age Breakdown (A:3460-3845): the same window and zoom as Chart 3 on the $500 grid,
// with the bought side split exactly by age group and the sold side grouped by the band of when
// price last traded at the level, the youngest those coins can be. The legend's rows hide and show
// their bars; the toggles are the plan's (U2, N1), not the page's (A:3491).

// L:260-261: how many young groups, youngest first, are younger than each window.
export const YOUNG: Record<Window, number> = { "1d": 1, "7d": 2, "30d": 3, "90d": 4 };

// One $500 row: its floor, middle price and age-floor band (L:366-377), each cohort's change over
// the window, the young groups' supply now (buy), their sum, and what left the bucket: its supply
// at the window's start less what is still there and older than the window.
export interface AgeRow {
  b: number;
  price: number;
  band: number;
  all: number;
  sth: number;
  lth: number;
  buy: number[];
  bought: number;
  sold: number;
}

// Which bars are drawn: the four bought groups and the twelve sold bands. The page kept three
// bought entries, so 90d hid its 1m–3m group from the start (A:3491); every group is on here.
export interface Toggles {
  bought: boolean[];
  sold: boolean[];
}
export const ALL_ON: Toggles = {
  bought: [true, true, true, true],
  sold: [true, true, true, true, true, true, true, true, true, true, true, true],
};

// A:3498-3526. Zoom All keeps three rows either side of the first and last row where a cohort
// moved more than half a coin; a ±% zoom keeps the rows priced in that band of spot. Spot is the
// close of D's $500 snapshot, so without it the $500 grid is what is missing.
export function ageRows(view: CostFlowView, w: Window, z: Zoom): Found<AgeRow[]> {
  const grid = gridFor(view, "all");
  const spot = view.spot;
  if (!grid || spot === null) return { ok: false, missing: "grid" };
  const age = view.age;
  if (!age) return { ok: false, missing: "age" };
  const then = grid.windows.find((found) => found.window === w)?.then;
  if (!then) return { ok: false, missing: "window" };
  const now = grid.now;
  const half = grid.step / 2;
  let rows = grid.floors.map((b, i) => {
    const buy = age.groups.slice(0, YOUNG[w]).map((group) => group[i]);
    const bought = buy.reduce((a, v) => a + v, 0);
    const sold = then.all[i] - (now.all[i] - bought);
    return {
      b,
      price: b + half,
      band: age.band[i],
      all: now.all[i] - then.all[i],
      sth: now.sth[i] - then.sth[i],
      lth: now.lth[i] - then.lth[i],
      buy,
      bought,
      sold,
    };
  });
  if (z > 0) {
    const lo = spot * (1 - z / 100),
      hi = spot * (1 + z / 100);
    rows = rows.filter((r) => r.price >= lo && r.price <= hi);
  } else {
    const live = (r: AgeRow) =>
      Math.abs(r.all) > 0.5 || Math.abs(r.sth) > 0.5 || Math.abs(r.lth) > 0.5;
    let i = 0,
      j = rows.length - 1;
    while (i < j && !live(rows[i])) i++;
    while (j > i && !live(rows[j])) j--;
    rows = rows.slice(Math.max(0, i - 3), Math.min(rows.length, j + 4));
  }
  return { ok: true, value: rows };
}

// One bar: a bought group's ("a<group>") or the row's sold bar ("s<band>"), which is drawn negated.
export interface AgeSeg {
  v: number;
  key: string;
  band: number;
  sold: boolean;
}

// A:3528-3536: each shown bought group, then the sold bar when its band is shown.
export function ageSegments(r: AgeRow, t: Toggles): AgeSeg[] {
  const segs: AgeSeg[] = [];
  r.buy.forEach((v, g) => {
    if (t.bought[g]) segs.push({ v, key: `a${g}`, band: g, sold: false });
  });
  if (t.sold[r.band]) segs.push({ v: -r.sold, key: `s${r.band}`, band: r.band, sold: true });
  return segs;
}

// A:3549
const ageTotal = (r: AgeRow, t: Toggles) => ageSegments(r, t).reduce((a, s) => a + s.v, 0);

// A:3550: what each row weighs on one side, the size of its shown bars' sum on that side.
export function ageWeights(rows: readonly AgeRow[], t: Toggles, side: Side): number[] {
  return rows.map((r) => {
    const v = ageTotal(r, t);
    return side === "pos" ? Math.max(0, v) : Math.max(0, -v);
  });
}

// Any of the 16 toggles off, whether or not its row is in the legend (N1, rule 4).
export const anyHidden = (t: Toggles) => t.bought.some((on) => !on) || t.sold.some((on) => !on);

// One legend row: band picks the colour of a bought or sold row (the net row has none, -1); on is
// false for a hidden row, whose value reads "off".
export interface AgeLegendRow {
  key: string;
  band: number;
  label: string;
  value: string;
  on: boolean;
  kind: "bought" | "sold" | "net";
}

// A:3705-3726: the window's young groups; the sold rows of every band with a bucket that lost more
// than half a coin, by band; then the net of the drawn bars. Summed over Zoom All it is the coins
// mined in the window, so it is named issuance only there with every toggle on (N1, rule 4).
export function ageLegend(
  text: TextFn,
  rows: readonly AgeRow[],
  young: number,
  t: Toggles,
  z: Zoom,
): AgeLegendRow[] {
  const off = text("costflow.age.off");
  const legend: AgeLegendRow[] = [];
  for (let g = 0; g < young; g++) {
    const on = t.bought[g];
    const sum = rows.reduce((a, r) => a + r.buy[g], 0);
    legend.push({
      key: `a${g}`,
      band: g,
      label: text("costflow.age.bought", { group: BANDS12[g] }),
      value: on ? `+${fmtBtc(sum)}` : off,
      on,
      kind: "bought",
    });
  }
  const byBand = new Map<number, number>();
  for (const r of rows) if (r.sold > 0.5) byBand.set(r.band, (byBand.get(r.band) ?? 0) + r.sold);
  for (const [band, sum] of [...byBand].sort((a, b) => a[0] - b[0])) {
    const on = t.sold[band];
    legend.push({
      key: `s${band}`,
      band,
      label: text("costflow.age.sold", { group: BANDS12[band] }),
      value: on ? `−${fmtBtc(sum)}` : off,
      on,
      kind: "sold",
    });
  }
  const issuance = z === 0 && !anyHidden(t);
  legend.push({
    key: "net",
    band: -1,
    label: text(issuance ? "costflow.age.netIssuance" : "costflow.age.netShown"),
    value: fmtSigned(rows.reduce((a, r) => a + ageTotal(r, t), 0)),
    on: true,
    kind: "net",
  });
  return legend;
}

// A:3743-3751: a click on a bought or sold row flips it, unless it is the last one shown. The
// legend is the one drawn with t, as on the page.
export function toggle(t: Toggles, key: string, legend: readonly AgeLegendRow[]): Toggles {
  const row = legend.find((r) => r.key === key);
  if (!row || row.kind === "net") return t;
  const live = legend.filter((r) => r.kind !== "net" && r.on).length;
  if (row.on && live <= 1) return t;
  const flip = (ons: boolean[]) => ons.map((on, i) => (i === row.band ? !row.on : on));
  return row.kind === "bought" ? { ...t, bought: flip(t.bought) } : { ...t, sold: flip(t.sold) };
}

// A zoom keeps the toggles (A:3824-3826), unless the new zoom's legend, built with them, shows no
// bought or sold row; then every row is on again, so a legend of only "off" rows never appears.
export function afterZoom(t: Toggles, legend: readonly AgeLegendRow[]): Toggles {
  return legend.some((r) => r.kind !== "net" && r.on) ? t : ALL_ON;
}

// A:3788-3794: one bucket's tooltip: its price range, each young group above half a coin, the sold
// coins (none below 0) with their band, the net, then the window. It reads every group, shown or
// not.
export function ageTip(text: TextFn, r: AgeRow, step: number, w: Window): string[] {
  const lines = [`${fmtPrice(r.b)} – ${fmtPrice(r.b + step)}`];
  r.buy.forEach((v, g) => {
    if (v > 0.5)
      lines.push(`${text("costflow.age.tipBought", { group: BANDS12[g] })} +${fmtBtc(v)}`);
  });
  lines.push(
    `${text("costflow.age.tipSold", { group: BANDS12[r.band] })} −${fmtBtc(Math.max(0, r.sold))}`,
  );
  lines.push(`${text("costflow.age.tipNet")} ${fmtSigned(r.bought - r.sold)}`);
  lines.push(text("costflow.age.tipFoot", { window: w }));
  return lines;
}

// The plot's frame at a chart width, shared by Charts 3 and 4. Below 500 px the margins, tick
// counts and K/M labels shrink so the plot keeps at least 200 px at 330; the spot label is
// right-aligned at spotX, inside the right margin, clear of the buy side's K labels.
export interface Frame {
  left: number;
  right: number;
  top: number;
  bottom: number;
  plotW: number;
  xTicks: number;
  yTicks: number;
  labelPx: number;
  spotX: number;
}
export function plotFrame(width: number): Frame {
  const narrow = width < 500;
  const left = narrow ? 44 : 64;
  const right = narrow ? 76 : 96;
  return {
    left,
    right,
    top: narrow ? 8 : 10,
    bottom: narrow ? 34 : 36,
    plotW: width - left - right,
    xTicks: narrow ? 3 : 7,
    yTicks: narrow ? 6 : 10,
    labelPx: narrow ? 10 : 11,
    spotX: width - 2,
  };
}

// Where a K or M label is anchored: 8 px off its point, away from zero (A:1709, A:1740), kept
// inside the plot. A label is at most 3 characters, about 0.62 em each; a sell label ends at the
// x returned, a buy label starts there.
export function labelX(x: number, side: Side, f: Frame): number {
  const w = Math.ceil(3 * 0.62 * f.labelPx);
  return side === "neg" ? Math.max(x - 8, f.left + w) : Math.min(x + 8, f.left + f.plotW - w);
}
