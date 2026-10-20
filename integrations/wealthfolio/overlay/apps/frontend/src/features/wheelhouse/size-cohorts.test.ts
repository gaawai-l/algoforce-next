import { describe, expect, it } from "vitest";
import { phrase, type TextFn } from "./i18n";
import {
  sizeCohortsSchema,
  type BandKey,
  type SizeCohortsView,
  type WindowKey,
} from "./onchain-contract";
import expected from "./size-cohorts-expected.json";
import sample from "./size-cohorts-sample.json";
import { ticks } from "./sell-side";
import {
  DASH,
  GROUPS,
  NAME_GAP,
  PNL_DEFAULT,
  SUPPLY_DEFAULT,
  TEXT_EM,
  axis,
  band,
  cohortRows,
  labelSpot,
  layout,
  namesMet,
  pnlLabel,
  pnlLegend,
  pnlPlot,
  pnlRead,
  rowName,
  signed,
  supplyLabel,
  supplyLegend,
  supplyPlot,
  supplyRead,
  textPx,
  tickLabel,
  usdLegend,
  usdTip,
  valueLabel,
  type Breakdown,
  type LabelSpot,
  type PlotRow,
  type PnlChoice,
  type Reading,
  type SupplyChoice,
} from "./size-cohorts";

// The local service's size cohorts for the golden DB at 2026-10-19 06:00Z, the forming hour the
// original page was read at (Task 3's sample). It has no missing cell: every test of a missing
// value edits a copy of it.
const view = sizeCohortsSchema.parse(sample);
const text: TextFn = (key, vars) => phrase("en", key, vars);
const labels = (rows: PlotRow[], fmt: (v: number) => string) =>
  rows.map((row) => valueLabel(row.value, fmt));
// JSON imports type these fields as string, so they are narrowed here (as sell-side.test.ts does).
const win = (w: string) => w as WindowKey;
const english = (reading: Reading) => reading.lines.map(([key, value]) => [text(key), value]);
const btc = (v: number) => supplyLabel(v, "btc");
const pct = (v: number) => supplyLabel(v, "pct");
const usd = (v: number) => pnlLabel(v, "usd");
// The literal the brief pins for a missing value.
const MISSING = "—";

// A copy of the sample with some values changed, read through the contract like a payload.
function edited(
  change: (bands: SizeCohortsView["bands"]) => void,
  noBlock: WindowKey[] = [],
): SizeCohortsView {
  const copy = JSON.parse(JSON.stringify(sample)) as SizeCohortsView;
  change(copy.bands);
  return sizeCohortsSchema.parse({ ...copy, no_block: noBlock });
}
const bandOf = (bands: SizeCohortsView["bands"], key: BandKey) =>
  bands.find((item) => item.band === key)!;
const cellOf = (bands: SizeCohortsView["bands"], key: BandKey, w: WindowKey) =>
  bandOf(bands, key).windows.find((cell) => cell.window === w)!;

describe("size-cohort choices", () => {
  // Source: the original page's code, A:1993-1998 (groups), A:2029 and A:2196 (defaults).
  it("starts from the original page's groups and choices", () => {
    expect(GROUPS).toEqual([
      { key: "retail", from: 0, to: 6 },
      { key: "small", from: 6, to: 8 },
      { key: "mid", from: 8, to: 10 },
      { key: "large", from: 10, to: 12 },
    ]);
    expect(SUPPLY_DEFAULT).toEqual({ win: "7d", group: "groups", scale: "btc" });
    expect(PNL_DEFAULT).toEqual({ win: "7d", group: "groups", view: "gross", scale: "usd" });
    expect(DASH).toBe(MISSING);
  });

  // Source: the original page's code, A:2066 and A:2247 (largest row on top), L:48-54 (names).
  it("puts the largest row first and names it as the original", () => {
    const groups = cohortRows(view, "groups");
    expect(groups.map((row) => [row.key, row.group])).toEqual([
      ["large", true],
      ["mid", true],
      ["small", true],
      ["retail", true],
    ]);
    expect(groups.map((row) => rowName(text, row.key))).toEqual([
      "Large entities",
      "Mid-size entities",
      "Small entities",
      "Retail",
    ]);
    const bands = cohortRows(view, "bands");
    expect(bands.map((row) => row.key)).toEqual([...sample.bands.map((b) => b.band)].reverse());
    expect(bands.every((row) => !row.group)).toBe(true);
    expect(rowName(text, bands[0].key)).toBe("over 100k BTC");
    expect(rowName(text, bands[11].key)).toBe("under 1k sats");
  });

  it("has no rows, legend or axis without bands", () => {
    const empty = { ...view, data_state: "unavailable" as const, bands: [] };
    for (const group of ["bands", "groups"] as const) {
      const rows = cohortRows(empty, group);
      expect(rows).toEqual([]);
      expect(supplyLegend(rows, "7d")).toEqual([MISSING, MISSING, MISSING]);
      expect(pnlLegend(rows, "7d")).toEqual([MISSING, MISSING, MISSING]);
      expect(axis(supplyPlot(rows, { ...SUPPLY_DEFAULT, group }), 7)).toBeNull();
    }
  });
});

describe("Chart 5 against the original page", () => {
  // Source: page-recorded (SR-5.md:24-26 and 55-61; tick labels SR-5.md:50 and 53).
  it.each(expected.supply)("matches the original Chart 5 at $win / $scale", (c) => {
    const scale = c.scale as SupplyChoice["scale"];
    const rows = cohortRows(view, "groups");
    const plot = supplyPlot(rows, { win: win(c.win), group: "groups", scale });
    const fmt = (v: number) => supplyLabel(v, scale);
    expect(labels(plot, fmt)).toEqual(c.labels);
    if (c.legend) expect(supplyLegend(rows, win(c.win))).toEqual(c.legend);
    if (c.tickLabels)
      expect(axis(plot, 7)!.ticks.map((v) => tickLabel(v, fmt))).toEqual(c.tickLabels);
  });

  // Source: page-recorded (SR-5.md:39-51).
  it.each(expected.supplyTicks)(
    "puts Chart 5's axis at ±$max in steps of $step for $group/$scale/$win",
    (c) => {
      const choice = {
        win: win(c.win),
        group: c.group as Breakdown,
        scale: c.scale as SupplyChoice["scale"],
      };
      const t = axis(supplyPlot(cohortRows(view, choice.group), choice), 7)!.ticks;
      expect([t[0], t[t.length - 1], t[1] - t[0]].map((v) => +v.toFixed(6))).toEqual([
        -c.max,
        c.max,
        c.step,
      ]);
    },
  );

  // Source: the brief's legend formula over the page-recorded Large row (−7,385, SR-5.md:24).
  it("signs the legend's net by its total", () => {
    const [large] = cohortRows(view, "groups");
    expect(supplyLegend([large], "7d")).toEqual(["+0 BTC", "−7,385 BTC", "−7,385 BTC"]);
  });

  // Source: page-recorded (SR-5.md:30).
  it("reads Chart 5's default Large row as the original", () => {
    const r = expected.supplyRead;
    const row = cohortRows(view, "groups").find((item) => item.key === r.row)!;
    const reading = supplyRead(text, row, win(r.win));
    expect([reading.head, english(reading), reading.foot]).toEqual([r.head, r.lines, r.foot]);
  });

  // Source: page-recorded (SR-5.md:23, every band's value matches the BRK recompute); the bars
  // follow A:2083 (a bar is positive when its value is >= 0).
  it("draws one bar a row, its sign the value's", () => {
    const plot = supplyPlot(cohortRows(view, "groups"), SUPPLY_DEFAULT);
    expect(plot.map((row) => row.bars)).toEqual([
      [{ v: plot[0].value, pos: false }],
      [{ v: plot[1].value, pos: true }],
      [{ v: plot[2].value, pos: false }],
      [{ v: plot[3].value, pos: false }],
    ]);
  });
});

describe("Chart 6 against the original page", () => {
  // Source: page-recorded (SR-6.md:23-31). A two-entry `ticks` is the axis ends the page records.
  it.each(expected.pnl)(
    "matches the original Chart 6 at $win / $group / $view / $scale",
    (c) => {
      const choice: PnlChoice = {
        win: win(c.win),
        group: c.group as Breakdown,
        view: c.view as PnlChoice["view"],
        scale: c.scale as PnlChoice["scale"],
      };
      const rows = cohortRows(view, choice.group);
      const plot = pnlPlot(rows, choice);
      const fmt = (v: number) => pnlLabel(v, choice.scale);
      expect(labels(plot, fmt)).toEqual(c.labels);
      if (c.legend) expect(pnlLegend(rows, choice.win)).toEqual(c.legend);
      const t = axis(plot, 7)!.ticks;
      if (c.ticks) expect(c.ticks.length === 2 ? [t[0], t[t.length - 1]] : t).toEqual(c.ticks);
      if (c.tickLabels) expect(t.map((v) => tickLabel(v, fmt))).toEqual(c.tickLabels);
      const bars = plot.flatMap((row) => row.bars);
      if (c.bars != null) expect(bars).toHaveLength(c.bars);
      if (c.pos) expect(bars.map((bar) => bar.pos)).toEqual(c.pos);
    },
  );

  // Source: page-recorded (SR-6.md:25 and 28); the Mid, Small and Retail feet are derived from
  // page values (their recorded shares in the Large row's recorded wording).
  it.each(expected.pnlRead)("reads Chart 6's $row row at $win / $group as the original", (r) => {
    const row = cohortRows(view, r.group as Breakdown).find((item) => item.key === r.row)!;
    const reading = pnlRead(text, row, win(r.win));
    if (r.head != null) expect(reading.head).toBe(r.head);
    expect(english(reading)).toEqual(expect.arrayContaining(r.lines));
    expect(reading.foot).toBe(r.foot);
  });

  // Source: the original page's code, A:2269-2280: Gross is a profit bar and a loss bar a row,
  // the label and the net tick at the net; Net is one bar at the net. The dollars are the
  // sample's Large members (10k–100k BTC and over 100k BTC) at 7d.
  it("draws profit right and loss left in Gross, the net alone in Net", () => {
    const rows = cohortRows(view, "groups");
    const [profit, loss] = [255918914 + 0, 467565676 + 0];
    const gross = pnlPlot(rows, PNL_DEFAULT)[0];
    expect(gross.bars).toEqual([
      { v: profit, pos: true },
      { v: -loss, pos: false },
    ]);
    expect(gross.value).toBe(profit - loss);
    const net = pnlPlot(rows, { ...PNL_DEFAULT, view: "net" })[0];
    expect(net).toMatchObject({ value: profit - loss, bars: [{ v: profit - loss, pos: false }] });
  });
});

describe("missing values", () => {
  // Source: the brief (a group with a missing member is missing; the legend says so).
  it("folds a group with a missing member to null", () => {
    const missing = edited((bands) => {
      cellOf(bands, "addrs_over_100k_btc", "7d").supply_change = null;
    });
    const groups = cohortRows(missing, "groups");
    const plot = supplyPlot(groups, SUPPLY_DEFAULT);
    expect(plot[0]).toMatchObject({ key: "large", value: null, bars: [] });
    expect(labels(plot, btc)).toEqual([MISSING, ...expected.supply[0].labels.slice(1)]);
    expect(supplyLegend(groups, "7d")).toEqual([MISSING, MISSING, MISSING]);
    const bands = supplyPlot(cohortRows(missing, "bands"), { ...SUPPLY_DEFAULT, group: "bands" });
    expect(bands[0]).toMatchObject({ key: "addrs_over_100k_btc", value: null, bars: [] });
    // The other eleven still set the axis: the page's ±15,000 (SR-5.md:43), whose largest bar,
    // 10k–100k BTC, is still there.
    const t = axis(bands, 7)!.ticks;
    expect([t[0], t[t.length - 1]]).toEqual([-15000, 15000]);
  });

  it("folds every field of a group to null when one member lacks it", () => {
    const missing = edited((bands) => {
      bandOf(bands, "addrs_1btc_to_10btc").supply = null;
      bandOf(bands, "addrs_10btc_to_100btc").realized_cap = null;
      cellOf(bands, "addrs_100btc_to_1k_btc", "7d").profit = null;
      cellOf(bands, "addrs_10k_btc_to_100k_btc", "7d").loss = null;
    });
    const [large, mid, small, retail] = cohortRows(missing, "groups");
    expect(small.supply).toBeNull();
    expect(small.rcap).toBeNull();
    expect(mid.cells["7d"].profit).toBeNull();
    expect(large.cells["7d"].loss).toBeNull();
    expect(retail.supply).not.toBeNull();
    const supplyPct = supplyPlot([small], { ...SUPPLY_DEFAULT, scale: "pct" });
    expect(supplyPct[0].value).toBeNull();
    expect(english(supplyRead(text, small, "7d")).slice(1)).toEqual([
      ["Share of band", MISSING],
      ["Band supply", MISSING],
    ]);
    const pnlPct = pnlPlot([small], { ...PNL_DEFAULT, scale: "pct" });
    expect(pnlPct[0].value).toBeNull();
    expect(pnlPlot([large, mid], PNL_DEFAULT).map((row) => row.value)).toEqual([null, null]);
    expect(pnlLegend([large, mid, small, retail], "7d")).toEqual([MISSING, MISSING, MISSING]);
    // Every other window is whole.
    expect(pnlLegend([large, mid, small, retail], "1d")).toEqual(expected.pnl[4].legend);
  });

  // Source: the brief; the 1d values are page-recorded (SR-5.md:59, SR-6.md:31).
  it("null anchor", () => {
    const anchor = edited(
      (bands) => {
        for (const item of bands) {
          Object.assign(item.windows[1], { supply_change: null, profit: null, loss: null });
        }
      },
      ["7d"],
    );
    expect(anchor.no_block).toEqual(["7d"]);
    for (const group of ["bands", "groups"] as const) {
      const rows = cohortRows(anchor, group);
      const supply = supplyPlot(rows, { ...SUPPLY_DEFAULT, group });
      const pnl = pnlPlot(rows, { ...PNL_DEFAULT, group });
      expect(axis(supply, 7)).toBeNull();
      expect(axis(pnl, 7)).toBeNull();
      expect(supplyLegend(rows, "7d")).toEqual([MISSING, MISSING, MISSING]);
      expect(pnlLegend(rows, "7d")).toEqual([MISSING, MISSING, MISSING]);
      expect(labels(supply, btc)).toEqual(rows.map(() => MISSING));
      expect(labels(pnl, usd)).toEqual(rows.map(() => MISSING));
      expect(supply.every((row) => row.bars.length === 0)).toBe(true);
      expect(pnl.every((row) => row.bars.length === 0)).toBe(true);
      expect(axis(supplyPlot(rows, { ...SUPPLY_DEFAULT, group, win: "1d" }), 7)).not.toBeNull();
    }
    const groups = cohortRows(anchor, "groups");
    expect(labels(supplyPlot(groups, { ...SUPPLY_DEFAULT, win: "1d" }), btc)).toEqual(
      expected.supply[2].labels,
    );
    expect(labels(pnlPlot(groups, { ...PNL_DEFAULT, win: "1d" }), usd)).toEqual(
      expected.pnl[4].labels,
    );
    expect(pnlLegend(groups, "1d")).toEqual(expected.pnl[4].legend);
  });

  // Source: the brief (a missing value reads "—", the foot names the gap); the held supply is the
  // page-recorded 2,972,806 BTC (SR-5.md:30), which does not depend on the window.
  it("reads a missing window as a gap", () => {
    const anchor = edited((bands) => {
      for (const item of bands) {
        Object.assign(item.windows[1], { supply_change: null, profit: null, loss: null });
      }
    });
    const [large] = cohortRows(anchor, "groups");
    const supply = supplyRead(text, large, "7d");
    expect(english(supply)).toEqual([
      ["Net change", MISSING],
      ["Share of band", MISSING],
      ["Band supply", "2,972,806 BTC"],
    ]);
    expect(supply.foot).toBe("No data at one end of this window");
    const pnl = pnlRead(text, large, "7d");
    expect(english(pnl)).toEqual([
      ["Profit booked", MISSING],
      ["Loss booked", MISSING],
      ["Net", MISSING],
      ["vs realized cap", MISSING],
    ]);
    expect(pnl.foot).toBe("No data at one end of this window");
    expect(supply.head).toBe(expected.supplyRead.head);
  });

  // Source: the brief (a percent needs a positive denominator; the original's 0 is a "—" here).
  it("percent needs a positive denominator", () => {
    const zero = edited((bands) => {
      bandOf(bands, "addrs_1btc_to_10btc").supply = 0;
      bandOf(bands, "addrs_10btc_to_100btc").realized_cap = null;
      bandOf(bands, "addrs_100btc_to_1k_btc").realized_cap = 0;
    });
    const rows = cohortRows(zero, "bands");
    const at = (key: BandKey) => rows.findIndex((row) => row.key === key);
    const supplyPct = supplyPlot(rows, { ...SUPPLY_DEFAULT, group: "bands", scale: "pct" });
    expect(supplyPct[at("addrs_1btc_to_10btc")]).toMatchObject({ value: null, bars: [] });
    expect(supplyPct[at("addrs_10btc_to_100btc")].value).not.toBeNull();
    const supplyBtc = supplyPlot(rows, { ...SUPPLY_DEFAULT, group: "bands" });
    expect(supplyBtc[at("addrs_1btc_to_10btc")].value).toBe(-1368.08);
    const reading = supplyRead(text, rows[at("addrs_1btc_to_10btc")], "7d");
    expect(english(reading)).toEqual([
      // The brief's formula over the sample's (page-equal) value, −1,368.08.
      ["Net change", "−1,368 BTC"],
      ["Share of band", MISSING],
      // The brief's formula over the supply of 0 this test sets.
      ["Band supply", "0 BTC"],
    ]);
    const pnlPct = pnlPlot(rows, { ...PNL_DEFAULT, group: "bands", scale: "pct" });
    expect(pnlPct[at("addrs_10btc_to_100btc")]).toMatchObject({ value: null, bars: [] });
    expect(pnlPct[at("addrs_100btc_to_1k_btc")]).toMatchObject({ value: null, bars: [] });
    const pnlUsd = pnlPlot(rows, { ...PNL_DEFAULT, group: "bands" });
    expect(pnlUsd[at("addrs_10btc_to_100btc")].value).toBe(480740724 - 162509664);
    for (const key of ["addrs_10btc_to_100btc", "addrs_100btc_to_1k_btc"] as const) {
      const lines = english(pnlRead(text, rows[at(key)], "7d"));
      expect(lines[3]).toEqual(["vs realized cap", MISSING]);
      expect(lines[2][1]).not.toBe(MISSING);
    }
    // The legend adds up dollars whatever the scale, so it stays.
    expect(pnlLegend(rows, "7d")).toEqual(expected.pnl[0].legend);
  });

  // Source: the brief (a P&L row needs both sides).
  it("a P&L row needs both sides", () => {
    const oneSided = edited((bands) => {
      cellOf(bands, "addrs_1k_btc_to_10k_btc", "7d").profit = null;
      cellOf(bands, "addrs_100btc_to_1k_btc", "7d").loss = null;
    });
    const rows = cohortRows(oneSided, "bands");
    for (const v of ["gross", "net"] as const) {
      for (const scale of ["usd", "pct"] as const) {
        const plot = pnlPlot(rows, { ...PNL_DEFAULT, group: "bands", view: v, scale });
        expect(plot[2]).toMatchObject({ key: "addrs_1k_btc_to_10k_btc", value: null, bars: [] });
        expect(plot[3]).toMatchObject({ key: "addrs_100btc_to_1k_btc", value: null, bars: [] });
      }
    }
    const reading = english(pnlRead(text, rows[2], "7d"));
    expect(reading).toEqual([
      ["Profit booked", MISSING],
      // The brief's formula over the sample's (page-equal) value.
      ["Loss booked", "−$444.7M"],
      ["Net", MISSING],
      ["vs realized cap", MISSING],
    ]);
  });
});

describe("zeros", () => {
  // Source: page-recorded (SR-6.md:28: two 0.8px bars, "+$0", "no coins from this band moved").
  it("real zeros stay zeros", () => {
    const rows = cohortRows(view, "bands");
    const [top] = pnlPlot(rows, { ...PNL_DEFAULT, group: "bands" });
    expect(top.key).toBe("addrs_over_100k_btc");
    expect(top.bars.map((bar) => bar.v)).toEqual([0, -0]);
    expect(Object.is(top.bars[1].v, -0)).toBe(true);
    expect(top.bars.map((bar) => bar.pos)).toEqual([true, false]);
    expect(top.value).toBe(0);
    expect(valueLabel(top.value, usd)).toBe("+$0");
    // In Net the one bar is the net, 0, and positive as the original's bar-pos for v >= 0 (A:2278).
    expect(pnlPlot(rows, { ...PNL_DEFAULT, group: "bands", view: "net" })[0].bars).toEqual([
      { v: 0, pos: true },
    ]);
    const reading = pnlRead(text, rows[0], "7d");
    expect(reading.head).toBe("over 100k BTC");
    expect(reading.foot).toBe("no coins from this band moved · 7d window");
    // The 1d supply change of the band is a real 0 too: "+0", not "—".
    const [supply] = supplyPlot(rows, { ...SUPPLY_DEFAULT, group: "bands", win: "1d" });
    expect([supply.value, valueLabel(supply.value, btc)]).toEqual([0, "+0"]);
  });

  // Source: the brief (the axis is ±mag × 1.12, mag over every bar, the loss bars included,
  // A:2250-2258).
  it("sizes the axis by the longest bar, a loss bar included", () => {
    const lossy = edited((bands) => {
      Object.assign(cellOf(bands, "addrs_over_100k_btc", "7d"), { profit: 0, loss: 1e9 });
    });
    const [top] = pnlPlot(cohortRows(lossy, "bands"), { ...PNL_DEFAULT, group: "bands" });
    expect(top.bars).toEqual([
      { v: 0, pos: true },
      { v: -1e9, pos: false },
    ]);
    expect(axis([top], 7)).toMatchObject({ lo: -1e9 * 1.12, hi: 1e9 * 1.12 });
  });

  // Source: the brief (the axis spans ±1 × 1.12 when every bar is 0).
  it("spans ±1.12 when every bar is 0", () => {
    const [top] = pnlPlot(cohortRows(view, "bands"), { ...PNL_DEFAULT, group: "bands" });
    expect(top.bars.map((bar) => bar.v)).toEqual([0, -0]);
    expect(axis([top], 7)).toMatchObject({ lo: -1.12, hi: 1.12 });
  });

  // Source: the brief ("+" when v >= 0, also -0): a -0.0 change from the service never prints
  // a minus.
  it("never prints a minus for a negative zero", () => {
    const negative = edited((bands) => {
      cellOf(bands, "addrs_under_1k_sats", "7d").supply_change = -0;
    });
    const rows = cohortRows(negative, "bands");
    const under = rows[11];
    expect(Object.is(under.cells["7d"].change, -0)).toBe(true);
    const [btcRow] = supplyPlot([under], { ...SUPPLY_DEFAULT, group: "bands" });
    const [pctRow] = supplyPlot([under], { ...SUPPLY_DEFAULT, group: "bands", scale: "pct" });
    expect([valueLabel(btcRow.value, btc), valueLabel(pctRow.value, pct)]).toEqual([
      "+0",
      "+0.000%",
    ]);
    expect(btcRow.bars[0].pos).toBe(true);
    expect(english(supplyRead(text, under, "7d")).slice(0, 2)).toEqual([
      ["Net change", "+0 BTC"],
      ["Share of band", "+0.000%"],
    ]);
    expect([signed(-0), signed(0), signed(-1e-9)]).toEqual(["+", "+", "−"]);
  });
});

describe("one-sided P&L", () => {
  // Source: the original page's wording, A:2368-2373.
  it("names a band that booked only profit or only loss", () => {
    const oneSided = edited((bands) => {
      cellOf(bands, "addrs_1k_btc_to_10k_btc", "7d").loss = 0;
      cellOf(bands, "addrs_100btc_to_1k_btc", "7d").profit = 0;
    });
    const rows = cohortRows(oneSided, "bands");
    expect(pnlRead(text, rows[2], "7d").foot).toBe("spent entirely in profit · 7d window");
    expect(pnlRead(text, rows[3], "7d").foot).toBe("spent entirely at a loss · 7d window");
  });
});

describe("formats", () => {
  // Source: the brief's formulas (A:2235-2243, A:2333-2334, A:2357-2360) at each threshold.
  it("switches units at the original's thresholds", () => {
    expect([1e9, 999_999_999, 1e6, 999_999, 1e3, 999].map(usd)).toEqual([
      "+$1.00B",
      "+$1000.0M",
      "+$1.0M",
      "+$1000k",
      "+$1k",
      "+$999",
    ]);
    expect([1e9, -999_999_999, 1_234_567].map(usdLegend)).toEqual([
      "+$1.00B",
      "−$1000M",
      "+$1M",
    ]);
    expect([1e9, -1e6, 999_999, -0].map(usdTip)).toEqual([
      "+$1.00B",
      "−$1.0M",
      "+$999,999",
      "+$0",
    ]);
    expect([pnlLabel(-0.12345, "pct"), supplyLabel(12_345.5, "btc")]).toEqual([
      "−0.123%",
      "+12,346",
    ]);
    expect([tickLabel(0, usd), tickLabel(-0, usd), tickLabel(5e8, usd)]).toEqual([
      "0",
      "0",
      "+$500.0M",
    ]);
    expect([valueLabel(null, usd), valueLabel(0, usd)]).toEqual([MISSING, "+$0"]);
  });
});

describe("geometry", () => {
  // Source: the brief (the original's margins, A:2033, and the local narrow layout).
  it("layout", () => {
    expect(layout(1000, 4)).toEqual({
      compact: false,
      left: 164,
      right: 158,
      top: 16,
      bottom: 26,
      height: 440,
      padding: 0.28,
      ticks: 7,
    });
    expect(layout(720, 4)).toMatchObject({ compact: false, height: 338, ticks: 3 });
    expect(layout(560, 4)).toMatchObject({ compact: false, left: 164 });
    expect(layout(559, 4)).toMatchObject({ compact: true, left: 56 });
    expect(layout(336, 12)).toEqual({
      compact: true,
      left: 56,
      right: 64,
      top: 16,
      bottom: 26,
      height: 354,
      padding: 0.5,
      ticks: 3,
    });
    expect(layout(336, 4).height).toBe(300);
    expect(layout(559, 20).height).toBe(440);
    // The plot is 480 wide at 802 in the wide layout; the compact one is never that wide.
    expect([layout(802, 4).ticks, layout(801, 4).ticks]).toEqual([7, 3]);
  });

  // Source: the brief (ticks = ticks(lo, hi, count), the d3 port the other charts use; a narrow
  // plot asks for 3).
  it("asks the d3 port for the layout's tick count", () => {
    const plot = supplyPlot(cohortRows(view, "groups"), SUPPLY_DEFAULT);
    const narrow = axis(plot, 3)!;
    expect(narrow.ticks).toEqual(ticks(narrow.lo, narrow.hi, 3));
    expect(narrow.ticks).not.toEqual(axis(plot, 7)!.ticks);
  });

  // Source: the brief (d3 scaleBand with padding 0.28 over 296px, align 0.5).
  it("band", () => {
    const rows = band(4, 296, 0.28);
    expect(rows.step).toBeCloseTo(69.15888, 4);
    expect(rows.start).toBeCloseTo(19.36449, 4);
    expect(rows.width).toBeCloseTo(49.79439, 4);
  });

  // Chart 5's Bands at 7d as the original drew them at 2026-10-20 03:00Z (SR5-6-VERIFICATION §5),
  // largest band first: the longest bar is the 10k–100k BTC band's −15,237. The axis is ±1.12 ×
  // that, so its tip sits 0.12 / 2.24 of the plot from the left.
  const LIVE_7D = [6711, -15237, 14806, 2371, -1393, -1231, -2958, 162, 106, -0.4, 0, 0];
  const plotRows = (values: number[], keys: PlotRow["key"][]): PlotRow[] =>
    values.map((v, i) => ({ key: keys[i], group: false, bars: [{ v, pos: v >= 0 }], value: v }));
  const BANDS_DOWN = view.bands.map((b) => b.band as BandKey).reverse();
  const GROUPS_DOWN = GROUPS.map((g) => g.key).reverse();
  const at = (x: number, anchor: string, inside: boolean) => ({
    x: expect.closeTo(x, 2),
    anchor,
    inside,
  });
  // The chart at `width`, as it places a row's value label: x is the value's place on the axis
  // over the plot, to 0.01px; d3's scaleBand gives row i's top, the value label's baseline is the
  // bar's middle + 3.5, and the name's is that line when wide, 4px above the bar compact.
  function chartAt(rows: PlotRow[], width: number, gross = false, say: TextFn = text) {
    const frame = layout(width, rows.length);
    const plotW = width - frame.left - frame.right;
    const scale = axis(rows, frame.ticks)!;
    const r2 = (v: number) => Math.round(v * 100) / 100;
    const x = (u: number) => r2(((u - scale.lo) / (scale.hi - scale.lo)) * plotW);
    const plotH = frame.height - frame.top - frame.bottom;
    const { start, step, width: barH } = band(rows.length, plotH, frame.padding);
    const valueY = rows.map((_, i) => r2(start + i * step + barH / 2 + 3.5));
    const names = rows.map((row, i) => ({
      text: rowName(say, row.key),
      y: frame.compact ? r2(start + i * step - 4) : valueY[i],
    }));
    const box = { plotW, gross, compact: frame.compact, left: frame.left };
    const label = (value: number | null) => valueLabel(value, btc);
    return {
      spot: (i: number, value = rows[i].value) =>
        labelSpot(value, label(value), x, box, valueY[i], names),
      // The names a label at `spot` would run into, by the same estimate.
      met: (i: number, spot: LabelSpot) =>
        namesMet(spot, label(rows[i].value), valueY[i], names, box).map((name) => name.text),
    };
  }

  // Source: the final review's M1 and the controller's ruling. The original puts a negative label
  // 7px left of the tip, end-anchored (A:2092-2100); the row's name ends at x = −10 on the same
  // line, so a label that would start left of −6 (a 4px gap, 0.6em = 6.6px a character at 11px)
  // goes inside the bar's end, start-anchored at the tip + 7.
  it("moves a wide label that would run into its row's name inside the bar", () => {
    expect([TEXT_EM.char * textPx(false), textPx(true), NAME_GAP]).toEqual([6.6, 10, 4]);
    const rows = plotRows(LIVE_7D, BANDS_DOWN);
    const wide = chartAt(rows, 720);
    // 720px: plot 398, the tip at 21.32; "−15,237" is 7 × 6.6 = 46.2px wide, so it would start at
    // 21.32 − 7 − 46.2 = −31.88, into its own row's name.
    expect(wide.met(1, { x: 14.32, anchor: "end", inside: false })).toEqual(["10k–100k BTC"]);
    expect(wide.spot(1)).toEqual(at(28.32, "start", true));
    expect(wide.met(1, wide.spot(1))).toEqual([]);
    // A shorter negative bar keeps its label outside: −2,958's tip is at 164.51.
    expect(wide.spot(6)).toEqual(at(157.51, "end", false));
    // A positive label, a missing one and Gross's are where the original puts them.
    expect(wide.spot(2)).toEqual(at(378.65, "start", false));
    expect(wide.spot(0, null)).toEqual(at(206, "start", false));
    expect(chartAt(rows, 720, true).spot(1)).toEqual(at(410, "start", false));
    // 1,160px: plot 838, the tip at 44.89, the label would start at −8.31.
    expect(chartAt(rows, 1160).spot(1)).toEqual(at(51.89, "start", true));
    // 1,280px: plot 958, the tip at 51.32, the label starts at −1.88: room enough outside.
    expect(chartAt(rows, 1280).spot(1)).toEqual(at(44.32, "end", false));
  });

  // Source: the controller's browser check at 390px (Chart 5, Bands, 7d: "−15,781" ran into
  // "1k–10k BTC") and its ruling. In the compact layout a row's name sits 4px above its bar, from
  // x = 4 − 56 = −52, so a label on the bar's middle line can run into the name of the row below.
  // Text boxes are estimated from 1.02em above the baseline to 0.3em below, at 10px.
  it("moves a compact label that would run into the next row's name inside the bar", () => {
    // 336px, 12 rows: plot 216 × 312, each row 24.96 tall with a 12.48px bar; the longest bar's
    // tip at 11.57. Row 1's label line spans 36.98–50.18 and the name below it 48.2–61.4; its own
    // name above ends at 36.44, so only the name below is in the way.
    const narrow = chartAt(plotRows(LIVE_7D, BANDS_DOWN), 336);
    // Outside, "−15,237" (7 × 6 = 42px) would span −37.43 to 4.57, over "1k–10k BTC" (−52 to 8).
    expect(narrow.met(1, { x: 4.57, anchor: "end", inside: false })).toEqual(["1k–10k BTC"]);
    expect(narrow.spot(1)).toEqual(at(18.57, "start", true));
    expect(narrow.met(1, narrow.spot(1))).toEqual([]);
    // With the longest bar on top the name below, "10k–100k BTC", ends at 20: inside the bar the
    // label starts the gap of 4 past it, at 24, and still ends well short of the zero line (108).
    const swapped = [LIVE_7D[1], LIVE_7D[0], ...LIVE_7D.slice(2)];
    const top = chartAt(plotRows(swapped, BANDS_DOWN), 336);
    expect(top.spot(0)).toEqual(at(24, "start", true));
    expect(top.met(0, top.spot(0))).toEqual([]);
    // A label that would not fit in its bar stays outside: −5,133's tip is at 75.52, and inside
    // it would end at 118.52, past the zero line.
    const mid = plotRows(
      LIVE_7D.map((v, i) => (i === 5 ? -5133 : v)),
      BANDS_DOWN,
    );
    expect(chartAt(mid, 336).spot(5)).toEqual(at(68.52, "end", false));
    // Four rows are 57.33 apart: the name below starts under the label's line, so the label stays
    // where the original puts it.
    const groups = chartAt(plotRows([-15237, 6711, 2371, -1393], GROUPS_DOWN), 336);
    expect(groups.spot(0)).toEqual(at(4.57, "end", false));
    expect(groups.met(0, groups.spot(0))).toEqual([]);
    // A CJK character counts 1em: "低于 1k 聪" (3 × 10 + 4 × 6 = 54px) ends at 2, so "−9,797",
    // whose tip is at 46, would start at 3 and meet it; counted 0.6em it would end at −10.
    const zh: TextFn = (key, vars) => phrase("zh", key, vars);
    const under = plotRows(
      LIVE_7D.map((v, i) => (i === 10 ? -9797 : v)),
      BANDS_DOWN,
    );
    expect(chartAt(under, 336, false, zh).spot(10)).toEqual(at(53, "start", true));
  });
});
