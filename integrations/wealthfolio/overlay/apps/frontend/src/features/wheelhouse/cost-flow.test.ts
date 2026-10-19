import { describe, expect, it } from "vitest";
import {
  WINDOWS,
  ZOOMS3,
  ZOOMS4,
  gridFor,
  segments,
  sideWeights,
  udiff,
  type FlowRow,
  type Holders,
  type Side,
  type Window,
  type Zoom,
} from "./cost-flow";
import { DEFAULT_SIDE, fitSide } from "./cost-flow-engine";
import expected from "./cost-flow-expected.json";
import s1raw from "./cost-flow-sample-0512.json";
import s2raw from "./cost-flow-sample.json";
import { costFlowSchema, type FlowGrid } from "./onchain-contract";

// S1: the 05:12 snapshot, both grids, no age snapshots. S2: the 06:04 snapshot, $500 grid only.
const s1 = costFlowSchema.parse(s1raw);
const s2 = costFlowSchema.parse(s2raw);

// The relative difference of two numbers; 0 when they are equal, both zeros included.
const rel = (a: number, b: number) =>
  a === b ? 0 : Math.abs(a - b) / Math.max(Math.abs(a), Math.abs(b));
const near = (actual: number, want: number, tol: number, what: string) =>
  expect(rel(actual, want), `${what}: ${actual} vs ${want}`).toBeLessThanOrEqual(tol);

const rowsOf = (
  grid: FlowGrid,
  w: Window,
  h: Holders,
  aging: boolean,
  z: Zoom,
  spot: number,
): FlowRow[] => {
  const found = udiff(grid, w, h, aging, z, spot);
  if (!found.ok) throw new Error(`no rows: ${found.missing}`);
  return found.value;
};

// The legend's totals, read off the drawn segments in row order (A:1752-1756).
const legend = (rows: readonly FlowRow[], h: Holders, aging: boolean) => {
  let buy = 0,
    sell = 0,
    age = 0;
  for (const r of rows)
    for (const sg of segments(r, h, aging)) {
      if (sg.v > 0) buy += sg.v;
      else sell += -sg.v;
      if (sg.aging) age += Math.abs(sg.v);
    }
  return { buy, sell, age };
};

describe("cost-flow chart 3 data", () => {
  // stage A = the Python reference port (chart3_recompute.py udiff/segments + costbasis.py
  // engines), 05:12, sample-0512; a cross-implementation check, the page anchors are in Tasks 5
  // and 6.
  it("reproduces the 23 stage-A states", () => {
    const stage = expected.chart3_stage_a;
    expect(stage.views).toHaveLength(23);
    expect(stage.spot).toBe(s1.spot);
    const spot = s1.spot!;
    const gmm = { ...DEFAULT_SIDE, mixture: "gmm" as const };
    const bicOnly = { ...gmm, smoothing: "none" as const };
    for (const v of stage.views) {
      const h = v.cohort as Holders;
      const aging = v.aging === "on";
      const what = `${v.win} ${v.cohort} z${v.zoom} ${v.aging}`;
      const grid = gridFor(s1, h)!;
      expect(grid.step, what).toBe(v.bin);
      const rows = rowsOf(grid, v.win as Window, h, aging, v.zoom as Zoom, spot);
      expect(rows, what).toHaveLength(v.rows);
      expect(rows[0].b, what).toBe(v.y_lo);
      expect(rows[rows.length - 1].b + grid.step, what).toBe(v.y_hi);

      const totals = legend(rows, h, aging);
      near(totals.buy, v.net_buy, 1e-9, `${what} net buy`);
      near(-totals.sell, v.net_sell, 1e-9, `${what} net sell`);
      if (v.aging_btc === null) expect(totals.age, what).toBe(0);
      else near(totals.age, v.aging_btc, 1e-9, `${what} aging`);

      const centers = rows.map((r) => r.price);
      for (const side of ["pos", "neg"] as const satisfies readonly Side[]) {
        const want = v.sides[side];
        const weights = sideWeights(rows, h, aging, side);
        const curves = fitSide(centers, weights, gmm);
        const peaks = curves?.peaks ?? [];
        expect(peaks, `${what} ${side} peaks`).toHaveLength(want.peaks.length);
        peaks.forEach((p, i) => {
          const at = `${what} ${side} K${i + 1}`;
          expect(p.location, at).toBe(want.peaks[i].price);
          near(p.width, want.peaks[i].width, 1e-9, `${at} width`);
          near(p.supply, want.peaks[i].btc, 1e-9, `${at} btc`);
          near(p.share, want.peaks[i].share, 1e-9, `${at} share`);
          near(p.strength, want.peaks[i].strength, 1e-9, `${at} strength`);
        });
        const mix = curves?.mix ?? null;
        expect(mix?.comps ?? [], `${what} ${side} bells`).toHaveLength(want.gmm_auto.length);
        mix?.comps.forEach((c, j) => {
          const at = `${what} ${side} M${j + 1}`;
          const bell = want.gmm_auto[j];
          near(c.mu, bell.mu, 1e-9, `${at} mu`);
          near(c.sigma, bell.sigma, 1e-9, `${at} sigma`);
          near(c.w, bell.share, 1e-9, `${at} w`);
          near(c.w * mix.totalW, bell.btc, 1e-9, `${at} btc`);
        });
        const off = fitSide(centers, weights, bicOnly);
        expect(off?.mix?.k ?? 0, `${what} ${side} BIC k`).toBe(want.gmm_bic_k);
      }
    }

    // Pinned from the stage-A run's printout.
    const all30 = rowsOf(gridFor(s1, "all")!, "30d", "all", false, 0, spot);
    expect(all30).toHaveLength(252);
    expect(legend(all30, "all", false).buy.toFixed(2)).toBe("1133415.16");
    const buy30 = fitSide(
      all30.map((r) => r.price),
      sideWeights(all30, "all", false, "pos"),
      gmm,
    )!;
    expect(buy30.peaks.map((p) => [p.location, p.width.toFixed(2)])).toEqual([[83750, "6776.48"]]);
    expect(buy30.mix!.comps.map((c) => [c.mu.toFixed(2), c.sigma.toFixed(2)])).toEqual([
      ["83665.05", "1365.87"],
    ]);

    const sth30 = rowsOf(gridFor(s1, "sth")!, "30d", "sth", true, 0, spot);
    expect(sth30).toHaveLength(629);
    const sthTotals = legend(sth30, "sth", true);
    expect(sthTotals.age.toFixed(0)).toBe("334783");
    expect(((sthTotals.age / sthTotals.sell) * 100).toFixed(0)).toBe("23");

    const lth30 = rowsOf(gridFor(s1, "lth")!, "30d", "lth", true, 0, spot);
    const sell30 = fitSide(
      lth30.map((r) => r.price),
      sideWeights(lth30, "lth", true, "neg"),
      gmm,
    )!;
    expect(sell30.peaks).toHaveLength(6);
    expect(sell30.mix).toMatchObject({ k: 5, raw: 6, src: "peaks" });
  });

  // A:1315-1333 on hand rows: a ±% zoom keeps the rows priced inside the band, both edges
  // included; Zoom All trims the ends to the first and last bucket that draws a bar of at least
  // half a cent, asking the bars of the holders and aging shown.
  it("keeps the zoom bands and the half-cent trim", () => {
    expect(WINDOWS).toEqual(["1d", "7d", "30d", "90d"]);
    expect(ZOOMS3).toEqual([0, 50, 25, 10]);
    expect(ZOOMS4).toEqual([0, 50, 25]);

    const zero = [0, 0, 0, 0, 0, 0, 0, 0];
    const grid: FlowGrid = {
      step: 500,
      floors: [0, 500, 1000, 1500, 2000, 2500, 3000, 3500],
      now: {
        all: [0, 0.004, 0.005, 0, 2, -0.004, 0.0049, 0],
        sth: [3, 0, 0, 0, 0, 0, 0.001, 0],
        lth: [0, 0, 0, 0, 0, 0, 0, 0.5],
      },
      windows: [
        { window: "7d", then_day: "2026-10-12", then: { all: zero, sth: zero, lth: zero } },
      ],
    };
    const prices = (h: Holders, aging: boolean, z: Zoom, spot: number) =>
      rowsOf(grid, "7d", h, aging, z, spot).map((r) => r.price);

    // ±25% of 1000 is 750–1250: the two rows priced on the edges, not the floors inside it.
    expect(prices("all", false, 25, 1000)).toEqual([750, 1250]);
    expect(prices("all", false, 50, 2000)).toEqual([1250, 1750, 2250, 2750]);
    // 0.004 and −0.004 draw nothing; 0.005 does; the empty row inside is kept.
    expect(prices("all", false, 0, 1000)).toEqual([1250, 1750, 2250]);
    const rows = rowsOf(grid, "7d", "all", false, 0, 1000);
    expect(rows[0]).toEqual({ b: 1000, price: 1250, all: 0.005, sth: 0, lth: 0 });
    // STH Hide reads the STH column only.
    expect(prices("sth", false, 0, 1000)).toEqual([250]);
    // STH Show also draws the real flow, and the coins ageing out: lth 0.5 at $3,750.
    expect(prices("sth", true, 0, 1000)).toEqual([1250, 1750, 2250, 2750, 3250, 3750]);
    // LTH Show draws −sth only when it is an increase: the 3 BTC STH gained at $250 is not.
    expect(prices("lth", true, 0, 1000)).toEqual([1250, 1750, 2250]);
  });

  it("maps All with Aging Show to the All segments", () => {
    const grid = gridFor(s1, "all")!;
    const hide = rowsOf(grid, "30d", "all", false, 0, s1.spot!);
    const show = rowsOf(grid, "30d", "all", true, 0, s1.spot!);
    expect(show).toEqual(hide);
    for (const r of hide) {
      const segs = [{ v: r.all, cls: r.all >= 0 ? "bar-pos" : "bar-neg", aging: false }];
      expect(segments(r, "all", true)).toEqual(segs);
      expect(segments(r, "all", false)).toEqual(segs);
    }
    for (const side of ["pos", "neg"] as const)
      expect(sideWeights(show, "all", true, side)).toEqual(sideWeights(hide, "all", false, side));
    // A bucket with no change is drawn on the buy side's class, as on the page.
    const still: FlowRow = { b: 0, price: 250, all: 0, sth: -2, lth: 2 };
    for (const aging of [false, true])
      expect(segments(still, "all", aging)).toEqual([{ v: 0, cls: "bar-pos", aging: false }]);
  });

  // A:1346-1401: STH and LTH Hide draw the cohort's own change; Show draws the real flow and,
  // when it is ageing, the correction (STH losing coins to age, LTH gaining them). A side weighs
  // a bucket by the sum of its bars.
  it("splits STH and LTH into the real flow and the aging", () => {
    const r: FlowRow = { b: 0, price: 250, all: 1, sth: -3, lth: 4 };
    expect(segments(r, "sth", false)).toEqual([{ v: -3, cls: "bar-neg", aging: false }]);
    expect(segments(r, "lth", false)).toEqual([{ v: 4, cls: "bar-pos", aging: false }]);
    expect(segments(r, "sth", true)).toEqual([
      { v: 1, cls: "bar-pos", aging: false },
      { v: -4, cls: "bar-aging-neg", aging: true },
    ]);
    expect(segments(r, "lth", true)).toEqual([
      { v: 1, cls: "bar-pos", aging: false },
      { v: 3, cls: "bar-aging-pos", aging: true },
    ]);
    const flipped: FlowRow = { b: 0, price: 250, all: -1, sth: 3, lth: -4 };
    expect(segments(flipped, "sth", true)).toEqual([{ v: -1, cls: "bar-neg", aging: false }]);
    expect(segments(flipped, "lth", true)).toEqual([{ v: -1, cls: "bar-neg", aging: false }]);
    expect(sideWeights([r, flipped], "sth", true, "pos")).toEqual([0, 0]);
    expect(sideWeights([r, flipped], "sth", true, "neg")).toEqual([3, 1]);
    expect(sideWeights([r, flipped], "lth", true, "pos")).toEqual([4, 0]);
    expect(sideWeights([r, flipped], "lth", false, "neg")).toEqual([0, 4]);
  });

  it("reports a missing window and a missing $200 grid", () => {
    const grid = gridFor(s1, "all")!;
    const no90: FlowGrid = { ...grid, windows: grid.windows.filter((w) => w.window !== "90d") };
    expect(udiff(no90, "90d", "all", false, 0, s1.spot!)).toEqual({ ok: false, missing: "window" });
    expect(udiff(no90, "30d", "all", false, 0, s1.spot!).ok).toBe(true);
    expect(gridFor(s2, "sth")).toBeNull();
    expect(gridFor(s2, "all")?.step).toBe(500);
    expect(gridFor(s2, "lth")?.step).toBe(500);
    expect(gridFor(s1, "sth")?.step).toBe(200);
  });
});
