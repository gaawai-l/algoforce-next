import type { AgeCohortsView } from "./onchain-contract";
import { footTime, niceDomain, si, sma, ticks, type Measure } from "./sell-side";

// The age-cohort chart's choices and arithmetic, following the original state-report page's
// Chart 2: smoothing, the fold into six bands, the rows kept, the span and the shares all depend
// on the reader's choices, so they are worked out here from the twelve hourly bands the service
// sends.

// The service's twelve bands, youngest first, and the original's fold of them into six.
export const BANDS12 = [
  "<1d",
  "1d–1w",
  "1w–1m",
  "1m–3m",
  "3m–6m",
  "6m–1y",
  "1y–2y",
  "2y–3y",
  "3y–5y",
  "5y–7y",
  "7y–10y",
  "10y+",
] as const;
const FOLD = [[0, 1], [2], [3, 4], [5, 6], [7, 8], [9, 10, 11]];
const NAME6 = ["<1w", "1w–1m", "1m–6m", "6m–2y", "2y–5y", "5y+"];

export type Detail = 6 | 12;
export type Scale = "abs" | "pct";
export const DETAILS: readonly Detail[] = [6, 12];
export const SCALES: readonly Scale[] = ["pct", "abs"];

export interface AgeChoice {
  measure: Measure;
  // Hours in the trailing mean; 1 is no smoothing.
  smoothing: number;
  // Rows shown, counted after the rows without a positive total are left out.
  span: number;
  detail: Detail;
  scale: Scale;
  // Which of the twelve source bands are on; a band of six is shown when any of its sources is.
  on: readonly boolean[];
  // One at a time: a click on the legend shows that band alone.
  solo: boolean;
}

const ALL_ON: readonly boolean[] = new Array(12).fill(true);
// The original page's defaults.
export const DEFAULT_AGE_CHOICE: AgeChoice = {
  measure: "pnl",
  smoothing: 24,
  span: 720,
  detail: 6,
  scale: "abs",
  on: ALL_ON,
  solo: false,
};

export interface AgeBand {
  name: string;
  // The twelve-band indexes it adds up.
  src: readonly number[];
}

export const bandsFor = (detail: Detail): AgeBand[] =>
  detail === 6
    ? NAME6.map((name, i) => ({ name, src: FOLD[i] }))
    : BANDS12.map((name, i) => ({ name, src: [i] }));
export const isShown = (band: AgeBand, on: readonly boolean[]) =>
  band.src.some((source) => on[source]);

export interface AgeRow {
  t: number;
  px: number;
  // Each band's profit and loss, shown or not, in band order.
  p: number[];
  l: number[];
  // The shown bands' profit plus their loss: the denominator of the shares.
  tot: number;
}

// The rows the chart draws: smoothed, folded, with a positive total of the shown bands, the last
// `span`.
export function buildAgeRows(view: AgeCohortsView, choice: AgeChoice): AgeRow[] {
  if (!view.at.length) return [];
  const bands = bandsFor(choice.detail);
  const profit = view[choice.measure].profit.map((column) => sma(column, choice.smoothing));
  const loss = view[choice.measure].loss.map((column) => sma(column, choice.smoothing));
  const rows: AgeRow[] = [];
  for (let i = 0; i < view.at.length; i += 1) {
    if (profit[0][i] === undefined) continue;
    const p = bands.map((band) =>
      band.src.reduce((total, source) => total + (profit[source][i] as number), 0),
    );
    const l = bands.map((band) =>
      band.src.reduce((total, source) => total + (loss[source][i] as number), 0),
    );
    let tp = 0;
    let tl = 0;
    bands.forEach((band, b) => {
      if (!isShown(band, choice.on)) return;
      tp += p[b];
      tl += l[b];
    });
    // Nothing to share out: the row is left out. A smoothed band can end a hair below zero; it
    // is never drawn.
    if (!(tp + tl > 0)) continue;
    rows.push({ t: Date.parse(view.at[i]), px: view.price[i], p, l, tot: tp + tl });
  }
  return rows.slice(Math.max(0, rows.length - choice.span));
}

export interface Axis {
  lo: number;
  hi: number;
  ticks: number[];
}

// Profit above the axis and loss below it; Absolute widens the domain to whole steps.
export function ageAxis(rows: AgeRow[], choice: AgeChoice): Axis {
  const bands = bandsFor(choice.detail);
  const pct = choice.scale === "pct";
  let up = 0;
  let dn = 0;
  for (const row of rows) {
    let a = 0;
    let b = 0;
    bands.forEach((band, i) => {
      if (!isShown(band, choice.on)) return;
      a += row.p[i];
      b += row.l[i];
    });
    if (pct) {
      a /= row.tot;
      b /= row.tot;
    }
    up = Math.max(up, a);
    dn = Math.max(dn, b);
  }
  let [lo, hi] = [-dn * 1.04 || -1, up * 1.04 || 1];
  if (!pct) [lo, hi] = niceDomain(lo, hi);
  return { lo, hi, ticks: ticks(lo, hi, 6) };
}

// The price axis: the shown rows' range with 8% either side, not widened to whole steps.
export function priceAxis(rows: AgeRow[]): Axis {
  const prices = rows.map((row) => row.px);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const pad = (max - min) * 0.08 || 1;
  return { lo: min - pad, hi: max + pad, ticks: ticks(min - pad, max + pad, 5) };
}

// The original's formats: d3 "~s" with a $ or " BTC", and ".0%".
export function fmtAge(value: number, measure: Measure) {
  const sign = value < 0 ? "−" : "";
  const amount = si(Math.abs(value));
  return measure === "volb" ? `${sign}${amount} BTC` : `${sign}$${amount}`;
}
export const fmtShare = (value: number) => `${(value * 100).toFixed(0)}%`;

// A band's legend value on the newest row, or "off" when it is hidden.
export function legendValue(row: AgeRow, band: number, choice: AgeChoice, off: string) {
  if (!isShown(bandsFor(choice.detail)[band], choice.on)) return off;
  const value = row.p[band] + row.l[band];
  return choice.scale === "pct" ? fmtShare(value / row.tot) : fmtAge(value, choice.measure);
}

export interface AgeTip {
  title: string;
  lines: { band: number; name: string; text: string }[];
  // The original's foot reads "profit / loss · total {total} · spot ${spot}".
  total: string;
  spot: string;
}

// The original's tooltip: every shown band with something that hour, its profit and its loss.
export function ageTip(row: AgeRow, choice: AgeChoice): AgeTip {
  const lines = bandsFor(choice.detail).flatMap((band, i) =>
    isShown(band, choice.on) && row.p[i] + row.l[i] > 0
      ? [
          {
            band: i,
            name: band.name,
            text: `${fmtAge(row.p[i], choice.measure)} / ${fmtAge(-row.l[i], choice.measure)}`,
          },
        ]
      : [],
  );
  return {
    title: footTime(row.t),
    lines,
    total: fmtAge(row.tot, choice.measure),
    spot: `$${Number(row.px.toFixed(0)).toLocaleString("en-US")}`,
  };
}

const soloOn = (detail: Detail, band: number) => {
  const on = new Array<boolean>(12).fill(false);
  for (const source of bandsFor(detail)[band].src) on[source] = true;
  return on;
};

// A legend click: one band alone under One at a time, else a toggle that never empties the chart.
export function toggleBand(choice: AgeChoice, band: number): AgeChoice {
  if (choice.solo) return { ...choice, on: soloOn(choice.detail, band) };
  const bands = bandsFor(choice.detail);
  const shown = isShown(bands[band], choice.on);
  if (shown && bands.filter((item) => isShown(item, choice.on)).length === 1) return choice;
  const on = choice.on.slice();
  for (const source of bands[band].src) on[source] = !shown;
  return { ...choice, on };
}

// Re-banding renumbers every band, so a selection cannot survive it.
export const withDetail = (choice: AgeChoice, detail: Detail): AgeChoice => ({
  ...choice,
  detail,
  on: choice.solo ? soloOn(detail, 0) : ALL_ON,
});

// Ticked, the first band shown is kept alone; unticked, every band is back.
export function withSolo(choice: AgeChoice, solo: boolean): AgeChoice {
  if (!solo) return { ...choice, solo, on: ALL_ON };
  const first = bandsFor(choice.detail).findIndex((band) => isShown(band, choice.on));
  return { ...choice, solo, on: soloOn(choice.detail, Math.max(0, first)) };
}
