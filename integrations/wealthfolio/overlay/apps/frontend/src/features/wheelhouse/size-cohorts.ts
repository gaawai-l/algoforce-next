import type { MessageKey, TextFn } from "./i18n";
import {
  SIZE_WINDOWS,
  type BandKey,
  type SizeCohortsView,
  type WindowKey,
} from "./onchain-contract";
import { grouped, heightFor, ticks } from "./sell-side";

// The size-cohort charts' choices and arithmetic, following the original state-report page's
// Charts 5 and 6 (`raw/script_2_app.js`, A:1993-2397): the fold into entity groups, the values,
// the axis, the formats, the legends and the readings all depend on the reader's choices, so they
// are worked out here from the twelve bands the service sends.
//
// One deliberate departure: the original has no missing value. Here a missing value stays null,
// prints "—" and draws no bar; a group with a missing member, and a legend over a missing row, are
// missing too; a percent needs a positive denominator, where the original draws 0.

// The original's entity groups: index ranges over the bands, smallest first (A:1993-1998).
export type GroupKey = "retail" | "small" | "mid" | "large";
export const GROUPS: readonly { key: GroupKey; from: number; to: number }[] = [
  { key: "retail", from: 0, to: 6 },
  { key: "small", from: 6, to: 8 },
  { key: "mid", from: 8, to: 10 },
  { key: "large", from: 10, to: 12 },
];

export type Breakdown = "bands" | "groups";
export interface SupplyChoice {
  win: WindowKey;
  group: Breakdown;
  scale: "btc" | "pct";
}
export interface PnlChoice {
  win: WindowKey;
  group: Breakdown;
  view: "net" | "gross";
  scale: "usd" | "pct";
}
// The original page's defaults (A:2029, A:2196).
export const SUPPLY_DEFAULT: SupplyChoice = { win: "7d", group: "groups", scale: "btc" };
export const PNL_DEFAULT: PnlChoice = { win: "7d", group: "groups", view: "gross", scale: "usd" };

// What a missing value prints.
export const DASH = "—";

// `change` is the window's supply change in BTC; `CohortRow.supply` is the amount held now.
export interface Cell {
  change: number | null;
  profit: number | null;
  loss: number | null;
}
export interface CohortRow {
  key: BandKey | GroupKey;
  group: boolean;
  supply: number | null;
  rcap: number | null;
  cells: Record<WindowKey, Cell>;
}

// d3.sum over the members in their order (A:2051-2052, A:2219-2221), but a missing member makes
// the total missing rather than being skipped.
function total(values: (number | null)[]): number | null {
  let sum = 0;
  for (const value of values) {
    if (value == null) return null;
    sum += value;
  }
  return sum;
}

const cellsOf = (members: CohortRow[]) =>
  Object.fromEntries(
    SIZE_WINDOWS.map((win) => [
      win,
      {
        change: total(members.map((member) => member.cells[win].change)),
        profit: total(members.map((member) => member.cells[win].profit)),
        loss: total(members.map((member) => member.cells[win].loss)),
      },
    ]),
  ) as Record<WindowKey, Cell>;

// The rows a chart draws, largest first, as the original reverses its bands (A:2066, A:2247):
// the twelve bands, or the four groups with their members added up (A:2048-2054, A:2216-2224).
export function cohortRows(view: SizeCohortsView, breakdown: Breakdown): CohortRow[] {
  const bands: CohortRow[] = view.bands.map((band) => ({
    key: band.band as BandKey,
    group: false,
    supply: band.supply,
    rcap: band.realized_cap,
    cells: Object.fromEntries(
      band.windows.map((cell) => [
        cell.window,
        { change: cell.supply_change, profit: cell.profit, loss: cell.loss },
      ]),
    ) as Record<WindowKey, Cell>,
  }));
  if (breakdown === "bands" || !bands.length) return bands.reverse();
  return GROUPS.map(({ key, from, to }) => {
    const members = bands.slice(from, to);
    return {
      key,
      group: true,
      supply: total(members.map((member) => member.supply)),
      rcap: total(members.map((member) => member.rcap)),
      cells: cellsOf(members),
    };
  }).reverse();
}

const isGroup = (key: CohortRow["key"]): key is GroupKey =>
  GROUPS.some((group) => group.key === key);

// A row's name on the chart: a band's range or a group's name (L:48-54, A:1994-1997).
export const rowName = (text: TextFn, key: CohortRow["key"]) =>
  isGroup(key) ? text(`sizes.group.${key}`) : text(`sizes.band.${key}`);

export interface PlotRow {
  key: CohortRow["key"];
  group: boolean;
  bars: { v: number; pos: boolean }[]; // [] when the value is missing
  value: number | null; // what the label prints; in Gross also where the net tick sits
}

// `v` over a positive denominator, in percent; missing without one (the original draws 0).
const percentOf = (v: number, of: number | null) => (of != null && of > 0 ? (v / of) * 100 : null);

// Chart 5: the window's change in BTC, or as a percent of what the row holds now (A:2056-2059);
// one bar, positive when the value is >= 0 (A:2083).
export function supplyPlot(rows: CohortRow[], choice: SupplyChoice): PlotRow[] {
  return rows.map((row) => {
    const d = row.cells[choice.win].change;
    const value = d == null ? null : choice.scale === "pct" ? percentOf(d, row.supply) : d;
    return {
      key: row.key,
      group: row.group,
      bars: value == null ? [] : [{ v: value, pos: value >= 0 }],
      value,
    };
  });
}

// Chart 6: profit and loss in dollars, or as a percent of the row's realized cap (A:2227-2234).
// Gross draws profit right and loss left with the net as the label; Net draws the net alone
// (A:2269-2280). A row needs both sides.
export function pnlPlot(rows: CohortRow[], choice: PnlChoice): PlotRow[] {
  return rows.map((row) => {
    const { profit: p, loss: l } = row.cells[choice.win];
    const scaled = (v: number) => (choice.scale === "pct" ? percentOf(v, row.rcap) : v);
    const empty = { key: row.key, group: row.group, bars: [], value: null };
    if (p == null || l == null) return empty;
    const [pv, lv, net] = [scaled(p), scaled(-l), scaled(p - l)];
    if (pv == null || lv == null || net == null) return empty;
    const bars =
      choice.view === "gross"
        ? [
            { v: pv, pos: true },
            { v: lv, pos: false },
          ]
        : [{ v: net, pos: net >= 0 }];
    return { key: row.key, group: row.group, bars, value: net };
  });
}

export interface Axis {
  lo: number;
  hi: number;
  ticks: number[];
}

// A symmetric axis 12% past the longest bar, 1 when every bar is 0 (A:2067-2073, A:2250-2263);
// none when no row has a bar.
export function axis(rows: PlotRow[], count: number): Axis | null {
  const bars = rows.flatMap((row) => row.bars);
  if (!bars.length) return null;
  let mag = 0;
  for (const bar of bars) if (Math.abs(bar.v) > mag) mag = Math.abs(bar.v);
  mag = mag || 1;
  const [lo, hi] = [-mag * 1.12, mag * 1.12];
  return { lo, hi, ticks: ticks(lo, hi, count) };
}

// d3's scaleBand with equal inner and outer padding, centred (A:2071, A:2261): row i's top edge
// is start + i * step and its bars are width tall.
export function band(n: number, extent: number, padding: number) {
  const step = extent / (n + padding);
  return { start: step * padding, step, width: step * (1 - padding) };
}

export interface Layout {
  compact: boolean;
  left: number;
  right: number;
  top: number;
  bottom: number;
  height: number;
  padding: number;
  ticks: number;
}

// Wide: the original's margins (A:2033), less the bottom captions that moved out of the SVG.
// Compact: row names above the bars, the height by the row count. Fewer ticks on a narrow plot.
export function layout(width: number, rows: number): Layout {
  const frame =
    width >= 560
      ? { compact: false, left: 164, right: 158, padding: 0.28, height: heightFor(width) }
      : {
          compact: true,
          left: 56,
          right: 64,
          padding: 0.5,
          height: Math.min(440, Math.max(300, rows * 26 + 42)),
        };
  return {
    ...frame,
    top: 16,
    bottom: 26,
    ticks: width - frame.left - frame.right >= 480 ? 7 : 3,
  };
}

// The original's formats, character for character: a "+" for zero and above, negative zero
// included, else U+2212.
export const signed = (v: number) => (v >= 0 ? "+" : "−");
const percent = (v: number) => `${signed(v)}${Math.abs(v).toFixed(3)}%`;

// Chart 5's labels and ticks (A:2060-2062).
export function supplyLabel(v: number, scale: SupplyChoice["scale"]) {
  return scale === "pct" ? percent(v) : `${signed(v)}${grouped(Math.abs(v))}`;
}

// Chart 6's labels and ticks (A:2235-2243).
export function pnlLabel(v: number, scale: PnlChoice["scale"]) {
  if (scale === "pct") return percent(v);
  const a = Math.abs(v);
  return (
    signed(v) +
    (a >= 1e9
      ? `$${(a / 1e9).toFixed(2)}B`
      : a >= 1e6
        ? `$${(a / 1e6).toFixed(1)}M`
        : a >= 1e3
          ? `$${(a / 1e3).toFixed(0)}k`
          : `$${grouped(a)}`)
  );
}

// Chart 6's legend dollars (A:2333-2334).
export function usdLegend(v: number) {
  const a = Math.abs(v);
  return signed(v) + (a >= 1e9 ? `$${(a / 1e9).toFixed(2)}B` : `$${(a / 1e6).toFixed(0)}M`);
}

// Chart 6's reading dollars (A:2357-2360).
export function usdTip(v: number) {
  const a = Math.abs(v);
  return (
    signed(v) +
    (a >= 1e9
      ? `$${(a / 1e9).toFixed(2)}B`
      : a >= 1e6
        ? `$${(a / 1e6).toFixed(1)}M`
        : `$${grouped(a)}`)
  );
}

// A bar's label, "—" when its value is missing.
export const valueLabel = (value: number | null, fmt: (v: number) => string) =>
  value == null ? DASH : fmt(value);

// What a value label (11px JetBrains Mono) is taken to be wide: 6.6px a character.
export const LABEL_CHAR_PX = 6.6;

export interface LabelSpot {
  x: number;
  anchor: "start" | "end";
  inside: boolean; // over the bar's end rather than past its tip
}

// Where a row's value label goes (A:2092-2100, A:2296-2307): 7px past the bar's tip, left of a
// negative one; just right of the zero line when the value is missing; Gross parks every label at
// plotW + 12. One departure: in the wide layout the row's name ends at x = −10 on the same line,
// so a negative label that would start left of −6 goes inside the bar's end instead. A positive
// label has no such neighbour: past the longest bar's tip lie 0.12 / 2.24 of the plot and the
// 158px margin, over 150px less the 7px gap, room for more than 20 characters.
export function labelSpot(
  value: number | null,
  label: string,
  x: (v: number) => number,
  frame: { plotW: number; gross: boolean; compact: boolean },
): LabelSpot {
  if (frame.gross) return { x: frame.plotW + 12, anchor: "start", inside: false };
  if (value === null) return { x: x(0) + 7, anchor: "start", inside: false };
  const tip = x(value);
  if (value >= 0) return { x: tip + 7, anchor: "start", inside: false };
  if (!frame.compact && tip - 7 - label.length * LABEL_CHAR_PX < -6)
    return { x: tip + 7, anchor: "start", inside: true };
  return { x: tip - 7, anchor: "end", inside: false };
}
// An axis tick's label: "0" at zero, else the bar labels' format (A:2102, A:2244).
export const tickLabel = (v: number, fmt: (v: number) => string) => (v === 0 ? "0" : fmt(v));

const DASHES: [string, string, string] = [DASH, DASH, DASH];

// Chart 5's legend: accumulation, distribution and their net over the rows shown, always in BTC
// (A:2116-2125); missing when any row is.
export function supplyLegend(rows: CohortRow[], win: WindowKey): [string, string, string] {
  const changes = rows.map((row) => row.cells[win].change);
  if (!changes.length || changes.some((d) => d == null)) return DASHES;
  let pos = 0;
  let neg = 0;
  for (const d of changes as number[]) {
    pos += Math.max(0, d);
    neg += Math.min(0, d);
  }
  return [
    `+${grouped(pos)} BTC`,
    `−${grouped(Math.abs(neg))} BTC`,
    `${signed(pos + neg)}${grouped(Math.abs(pos + neg))} BTC`,
  ];
}

// Chart 6's legend: profit, loss and net over the rows shown, always in dollars (A:2330-2339);
// missing when any row is.
export function pnlLegend(rows: CohortRow[], win: WindowKey): [string, string, string] {
  const cells = rows.map((row) => row.cells[win]);
  if (!cells.length || cells.some((cell) => cell.profit == null || cell.loss == null))
    return DASHES;
  let p = 0;
  let l = 0;
  for (const cell of cells) {
    p += cell.profit as number;
    l += cell.loss as number;
  }
  return [usdLegend(p), usdLegend(-l), usdLegend(p - l)];
}

// One row's reading, the original's tooltip as a line under the chart: the row's name (a group's
// with its description), its values, and a foot.
export interface Reading {
  head: string;
  lines: [MessageKey, string][];
  foot: string;
}

const headOf = (text: TextFn, key: CohortRow["key"]) =>
  isGroup(key) ? `${rowName(text, key)} · ${text(`sizes.sub.${key}`)}` : rowName(text, key);

// Chart 5's reading (A:2142-2150).
export function supplyRead(text: TextFn, row: CohortRow, win: WindowKey): Reading {
  const d = row.cells[win].change;
  const share = d == null ? null : percentOf(d, row.supply);
  return {
    head: headOf(text, row.key),
    lines: [
      ["sizes.supply.change", d == null ? DASH : `${supplyLabel(d, "btc")} BTC`],
      ["sizes.supply.share", valueLabel(share, percent)],
      ["sizes.supply.held", row.supply == null ? DASH : `${grouped(row.supply)} BTC`],
    ],
    foot: d == null ? text("sizes.gap") : text("sizes.supply.foot", { win }),
  };
}

// The share of what a row booked that was profit, in the original's words (A:2368-2372).
function verdict(text: TextFn, p: number, l: number) {
  if (p === 0 && l === 0) return text("sizes.pnl.none");
  if (l === 0) return text("sizes.pnl.allProfit");
  if (p === 0) return text("sizes.pnl.allLoss");
  return text("sizes.pnl.share", { n: ((p / (p + l)) * 100).toFixed(0) });
}

// Chart 6's reading (A:2356-2373); vs realized cap is "—" without a positive cap, where the
// original writes n/a.
export function pnlRead(text: TextFn, row: CohortRow, win: WindowKey): Reading {
  const { profit: p, loss: l } = row.cells[win];
  const whole = p != null && l != null;
  return {
    head: headOf(text, row.key),
    lines: [
      ["sizes.pnl.profit", valueLabel(p, usdTip)],
      ["sizes.pnl.loss", l == null ? DASH : usdTip(-l)],
      ["sizes.pnl.net", whole ? usdTip(p - l) : DASH],
      ["sizes.pnl.vsCap", whole ? valueLabel(percentOf(p - l, row.rcap), percent) : DASH],
    ],
    foot: whole ? text("sizes.pnl.foot", { verdict: verdict(text, p, l), win }) : text("sizes.gap"),
  };
}
