import { describe, expect, it } from "vitest";
import {
  WINDOWS,
  ZOOMS3,
  ZOOMS4,
  agingNote,
  barCounts,
  chip,
  clusterCells,
  clusterMeta,
  clusters,
  flowTip,
  flowTotals,
  fmtBtc,
  fmtPrice,
  fmtSigned,
  gridFor,
  kLabel,
  legendRows,
  mixCells,
  mixRows,
  mixtureMeta,
  segments,
  sideWeights,
  udiff,
  vsSpot,
  type FlowRow,
  type Holders,
  type Side,
  type Window,
  type Zoom,
} from "./cost-flow";
import { DEFAULT_SIDE, fitSide, type SideSetting } from "./cost-flow-engine";
import expected from "./cost-flow-expected.json";
import s1raw from "./cost-flow-sample-0512.json";
import s2raw from "./cost-flow-sample.json";
import { phrase, type TextFn } from "./i18n";
import { costFlowSchema, type FlowGrid } from "./onchain-contract";
import { reasonText } from "./onchain-text";

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

const en: TextFn = (key, vars) => phrase("en", key, vars);
const zh: TextFn = (key, vars) => phrase("zh", key, vars);
const gmm: SideSetting = { ...DEFAULT_SIDE, mixture: "gmm" };

// expected.chart3_page split at its "## <label>" headers: label -> the block's lines, header first.
const pageBlocks = new Map<string, string[]>();
{
  let block: string[] = [];
  for (const line of expected.chart3_page.split("\n")) {
    if (line.startsWith("## ")) {
      block = [];
      pageBlocks.set(line.slice(3), block);
    }
    block.push(line);
  }
}

// The settings of the page blocks S2 can rebuild: bells on = mixture "gmm" on both sides; the BIC
// block = smoothing "none" on both sides; restored defaults = DEFAULT_SIDE.
interface Block {
  w: Window;
  h: Holders;
  z: Zoom;
  aging: boolean;
  side: SideSetting;
}
const BLOCKS = new Map<string, Block>();
for (const w of WINDOWS) {
  BLOCKS.set(`${w} all zoomAll aging off bells on`, { w, h: "all", z: 0, aging: false, side: gmm });
  for (const aging of [false, true])
    BLOCKS.set(`${w} lth zoomAll aging ${aging ? "on" : "off"} bells on`, {
      w,
      h: "lth",
      z: 0,
      aging,
      side: gmm,
    });
}
for (const z of [50, 25, 10] as const)
  BLOCKS.set(`30d all zoom ${z} bells on`, { w: "30d", h: "all", z, aging: false, side: gmm });
BLOCKS.set("30d all zoomAll smoothing Off bells on (BIC)", {
  w: "30d",
  h: "all",
  z: 0,
  aging: false,
  side: { ...gmm, smoothing: "none" },
});
BLOCKS.set("restored defaults", { w: "30d", h: "all", z: 0, aging: false, side: DEFAULT_SIDE });

// The sweep names the side pills BUY and SELL.
const PILL: Record<Side, string> = { pos: "BUY", neg: "SELL" };

const s2Rows = (w: Window, h: Holders, aging: boolean, z: Zoom) =>
  rowsOf(gridFor(s2, h)!, w, h, aging, z, s2.spot!);
const s2Sides = (rows: readonly FlowRow[], h: Holders, aging: boolean, s: SideSetting) => {
  const centers = rows.map((r) => r.price);
  return {
    pos: fitSide(centers, sideWeights(rows, h, aging, "pos"), s),
    neg: fitSide(centers, sideWeights(rows, h, aging, "neg"), s),
  };
};

// A table row's cells, checking that the tag colour agrees with the words: below exactly when the
// vs-spot cell says "below".
const tagged = ({ cells, below }: { cells: string[]; below: boolean }) => {
  expect(below, cells.join(" | ")).toBe(cells[cells.length - 1].endsWith(" below"));
  return cells;
};

// One block in the sweep's format (sweep_expected.py): the legend's label and value joined by a
// space and its rows by " || ", the note, the drawn bars, then each table's meta and rows (number,
// side pill, the shipped cells), or the table's empty message. It only joins strings: every value
// is formatted by cost-flow.ts.
const chart3Lines = (label: string, b: Block): string[] => {
  const spot = s2.spot!;
  const grid = gridFor(s2, b.h)!;
  const rows = s2Rows(b.w, b.h, b.aging, b.z);
  const legend = legendRows(en, flowTotals(rows, b.h, b.aging), b.h);
  const n = barCounts(rows, b.h, b.aging);
  const { pos, neg } = s2Sides(rows, b.h, b.aging, b.side);
  const cs = clusters(pos, neg);
  const ms = mixRows(pos, neg);
  return [
    `## ${label}`,
    `legend: ${legend.map((r) => `${r.label} ${r.value}`).join(" || ")}`,
    `note: ${agingNote(en, b.h, b.aging, grid.step)}`,
    `bars: pos ${n["bar-pos"]} neg ${n["bar-neg"]} agingPos ${n["bar-aging-pos"]} agingNeg ${n["bar-aging-neg"]}`,
    `clusterMeta: ${clusterMeta(en, cs)}`,
    ...(cs.length
      ? cs.map((c) => [`K${c.n}`, PILL[c.side], ...tagged(clusterCells(en, c, spot))].join(" | "))
      : [en("costflow.noClusters")]),
    `mixtureMeta: ${mixtureMeta(en, pos, neg)}`,
    ...(ms.length
      ? ms.map((m) => [`M${m.m}`, PILL[m.side], ...tagged(mixCells(en, m, spot))].join(" | "))
      : [en("costflow.bellsOff")]),
  ];
};

describe("cost-flow chart 3 readings", () => {
  // Chart 3, page-recorded (05:55, same snapshot as S2): the 17 blocks of expected.chart3_page that
  // have no STH ($200 grid not in S2): "{1d,7d,30d,90d} all zoomAll aging off bells on",
  // "{1d,7d,30d,90d} lth zoomAll aging {off,on} bells on", "30d all zoom {50,25,10} bells on",
  // "30d all zoomAll smoothing Off bells on (BIC)", "restored defaults". Rebuild every line in the
  // sweep's format (legend " || ", note, bars, clusterMeta, K rows with BUY/SELL, mixtureMeta, M rows)
  // and expect equality, except the "labels:" line (U4). Block settings: bells on = mixture "gmm"
  // both sides; BIC block = smoothing "none" both sides; restored defaults = DEFAULT_SIDE.
  it("matches the page's Chart 3 readings cell for cell", () => {
    expect(pageBlocks.size).toBe(25);
    const noSth = [...pageBlocks.keys()].filter((label) => !label.includes(" sth "));
    expect(noSth).toHaveLength(17);
    expect([...BLOCKS.keys()].sort()).toEqual([...noSth].sort());
    for (const [label, b] of BLOCKS) {
      // page-recorded: the block as the page rendered it, minus the chart's K labels (U4 renumbers
      // them).
      const page = pageBlocks.get(label)!.filter((line) => !line.startsWith("labels: "));
      expect(chart3Lines(label, b), label).toEqual(page);
    }
    // page-recorded: both empty tables, at smoothing Off (no clusters) and at the opening state
    // (bells off), are among the blocks above.
    expect(pageBlocks.get("30d all zoomAll smoothing Off bells on (BIC)")).toContain(
      en("costflow.noClusters"),
    );
    expect(pageBlocks.get("restored defaults")).toContain(en("costflow.bellsOff"));
    expect([zh("costflow.noClusters"), zh("costflow.bellsOff")]).toEqual([
      "没有聚类。请为某一侧打开平滑，或调低它的峰值阈值。",
      "正态曲线已关闭。请在上方为任一侧打开。",
    ]);

    // page-recorded, with the plan's display ruling: the STH notes are the page's, at 150 days,
    // not 155 (BRK's line), on the $200 bins STH reads.
    for (const w of WINDOWS)
      for (const aging of [false, true]) {
        const page = pageBlocks.get(`${w} sth zoomAll aging ${aging ? "on" : "off"} bells on`)!;
        const note = page.find((line) => line.startsWith("note: "))!.slice("note: ".length);
        if (!aging) expect(note).toContain("crossed 155 days.");
        expect(agingNote(en, "sth", aging, 200)).toBe(note.replace("155 days", "150 days"));
      }
    // derived from page values: the 30d STH Show legend from its own totals (+1,146,871, −1,468,091,
    // aging 334,817) reads as the page's, the aging row on the sell side.
    const sthTotals = { buy: 1146871, sell: 1468091, aging: 334817, share: 334817 / 1468091 };
    const sthLegend = legendRows(en, sthTotals, "sth");
    expect(`legend: ${sthLegend.map((r) => `${r.label} ${r.value}`).join(" || ")}`).toBe(
      pageBlocks.get("30d sth zoomAll aging on bells on")![1],
    );
    expect(sthLegend.map((r) => [r.key, r.side])).toEqual([
      ["buy", "pos"],
      ["sell", "neg"],
      ["aging", "neg"],
    ]);
    // page-recorded (90d LTH Show): the aging row sits on the buy side (A:1764-1767).
    const lthTotals = flowTotals(s2Rows("90d", "lth", true, 0), "lth", true);
    expect(legendRows(en, lthTotals, "lth")[2]).toEqual({
      key: "aging",
      side: "pos",
      label: "Aging STH→LTH",
      value: "1,283,400 BTC · 40% of buy side",
    });

    // A:1762: All draws no aging row, whatever the Aging button says, and Show changes nothing.
    const show = s2Rows("30d", "all", true, 0);
    expect(flowTotals(show, "all", true)).toEqual(flowTotals(show, "all", false));
    expect(flowTotals(show, "all", true)).toMatchObject({ aging: null, share: null });
    expect(barCounts(show, "all", true)).toEqual(barCounts(show, "all", false));
    // Hide draws no aging row for LTH either (A:1762).
    expect(flowTotals(s2Rows("90d", "lth", false, 0), "lth", false)).toMatchObject({
      aging: null,
      share: null,
    });
    // A:1766 on a hand row: LTH Show with nothing on the buy side has an aging share of 0, not 0/0.
    expect(flowTotals([{ b: 0, price: 250, all: -1, sth: 1, lth: -2 }], "lth", true)).toEqual({
      buy: 0,
      sell: 1,
      aging: 0,
      share: 0,
    });

    // The zh copy (brief's i18n table, new translations): the note and the legend's aging value.
    expect(agingNote(zh, "lth", true, 500)).toBe(
      "LTH 的真实买卖，加上因币龄增长进入 LTH 的币，两者都在买方。币龄迁移是下界。$500 价格桶。",
    );
    expect(legendRows(zh, lthTotals, "lth").map((r) => `${r.label} ${r.value}`)).toEqual([
      "净买入（累积） +3,210,656 BTC",
      "净卖出（派发） −1,886,531 BTC",
      "币龄迁移 STH→LTH 1,283,400 BTC · 占买方 40%",
    ]);
    const shown = s2Sides(show, "all", true, gmm);
    expect(clusterMeta(zh, clusters(shown.pos, shown.neg))).toBe("5 个聚类 · 流入 1 · 流出 4");
  });

  // fitSide with smoothing "kde", bw 0.02, minProm 0.05 deep-equals smoothing "auto";
  // chip "0.020 / 0.05" (U1, A:1944-1948)
  it("Manual at its defaults equals Auto", () => {
    const rows = s2Rows("30d", "all", false, 0);
    for (const mixture of ["none", "gmm"] as const) {
      const auto = s2Sides(rows, "all", false, { ...DEFAULT_SIDE, mixture });
      const manual = s2Sides(rows, "all", false, { ...DEFAULT_SIDE, mixture, smoothing: "kde" });
      expect(manual).toEqual(auto);
      expect(auto.pos!.peaks.length + auto.neg!.peaks.length).toBe(5);
    }
    expect(chip({ ...DEFAULT_SIDE, smoothing: "kde" })).toBe("0.020 / 0.05");
    expect(chip(DEFAULT_SIDE)).toBe("auto");
    expect(chip({ ...DEFAULT_SIDE, smoothing: "none" })).toBe("raw");
    // The slider ends (U1): width 0.10, cutoff 0.40, in the same A:1947 format.
    expect(chip({ ...DEFAULT_SIDE, smoothing: "kde", bw: 0.1, minProm: 0.4 })).toBe("0.100 / 0.40");
  });

  // derived from page values: 30d All Zoom All, sell side minProm 0.40 -> one peak, $77,750,
  // width $6,960, 490,118 BTC (the page's K3, strength 99%); the other sell strengths are 7%, 30%, 7%
  it("Manual cutoff 0.40 keeps only the strong sell peak", () => {
    const rows = s2Rows("30d", "all", false, 0);
    const at = (minProm: number) =>
      s2Sides(rows, "all", false, { ...DEFAULT_SIDE, smoothing: "kde", minProm });
    const spot = s2.spot!;
    // page-recorded: the strengths of the four sell clusters at the default cutoff, by price.
    const strengths = clusters(null, at(0.05).neg).map((c) => clusterCells(en, c, spot).cells[4]);
    expect(strengths).toEqual(["7%", "30%", "99%", "7%"]);
    const { pos, neg } = at(0.4);
    // derived from page values: the one peak left is the page's K3 row, cell for cell (the cutoff
    // drops peaks; it does not move the width or the BTC within it).
    expect(clusters(null, neg).map((c) => clusterCells(en, c, spot).cells)).toEqual([
      ["$77,750", "$6,960", "490,118 BTC", "43.7%", "99%", "5.6% below"],
    ]);
    // The buy side keeps its own cutoff; the table renumbers the two rows by price.
    expect(clusters(pos, neg).map((c) => [c.n, c.side, fmtPrice(c.peak.location)])).toEqual([
      [1, "neg", "$77,750"],
      [2, "pos", "$83,750"],
    ]);
    expect(clusterMeta(en, clusters(null, neg))).toBe("1 cluster · 0 in · 1 out");
  });

  // page-recorded via mixtureMeta: "auto · 1" (buy), "auto · 4" (sell), "auto · 5 of 6" (90d LTH Show,
  // sell), "auto · 2 of 3" (30d ±10%, buy), "auto · 1 (BIC)" (smoothing off); plain "auto" when
  // kMode is manual or there is no fit
  it("labels auto as the original does", () => {
    const sides = (w: Window, h: Holders, aging: boolean, z: Zoom, s: SideSetting) =>
      s2Sides(s2Rows(w, h, aging, z), h, aging, s);
    const all30 = sides("30d", "all", false, 0, gmm);
    expect(mixtureMeta(en, all30.pos, all30.neg)).toBe("in: 1 bell · out: 4 bells");
    expect(kLabel(en, gmm, all30.pos)).toBe("auto · 1");
    expect(kLabel(en, gmm, all30.neg)).toBe("auto · 4");

    const lth90 = sides("90d", "lth", true, 0, gmm);
    expect(mixtureMeta(en, lth90.pos, lth90.neg)).toBe("in: 1 bell · out: 5 of 6 bells");
    expect(kLabel(en, gmm, lth90.neg)).toBe("auto · 5 of 6");
    expect(kLabel(zh, gmm, lth90.neg)).toBe("自动 · 6 取 5");

    const z10 = sides("30d", "all", false, 10, gmm);
    expect(mixtureMeta(en, z10.pos, z10.neg)).toBe("in: 2 of 3 bells · out: 3 bells");
    expect(kLabel(en, gmm, z10.pos)).toBe("auto · 2 of 3");

    const off = { ...gmm, smoothing: "none" as const };
    const bic = sides("30d", "all", false, 0, off);
    expect(mixtureMeta(en, bic.pos, bic.neg)).toBe("in: 1 bell (BIC) · out: 1 bell (BIC)");
    expect(kLabel(en, off, bic.pos)).toBe("auto · 1 (BIC)");
    expect(kLabel(zh, off, bic.pos)).toBe("自动 · 1（BIC）");
    expect(mixtureMeta(zh, bic.pos, bic.neg)).toBe("流入：1 条（BIC） · 流出：1 条（BIC）");

    // A:1720: a manual k leaves the auto option reading "auto".
    const manual = { ...gmm, kMode: "manual" as const, kManual: 3 };
    const fixed = sides("30d", "all", false, 0, manual);
    expect(fixed.neg!.mix).toMatchObject({ k: 3, src: "manual" });
    expect(kLabel(en, manual, fixed.neg)).toBe("auto");
    expect(mixtureMeta(en, fixed.pos, fixed.neg)).toBe("in: 3 bells · out: 3 bells");
    expect(mixtureMeta(zh, fixed.pos, fixed.neg)).toBe("流入：3 条 · 流出：3 条");
    // Bells off (the opening state): no fit, so "auto" (the plan's display ruling).
    const plain = sides("30d", "all", false, 0, DEFAULT_SIDE);
    expect(plain.neg!.mix).toBeNull();
    expect(kLabel(en, DEFAULT_SIDE, plain.neg)).toBe("auto");
    expect(kLabel(zh, DEFAULT_SIDE, plain.neg)).toBe("自动");
    expect(mixtureMeta(en, plain.pos, plain.neg)).toBe("");
  });

  // a side with fewer than 3 weighted rows: 1d All has one buy bar (page-recorded "bars: pos 1"),
  // so the buy side has peaks but no bells; the page's mixtureMeta is "out: 1 bell". The page left
  // the buy option at a stale "auto · 1" (SR-3.md:71); the plan's ruling reads plain "auto".
  it("kLabel and mixtureMeta skip a side without a fit", () => {
    const rows = s2Rows("1d", "all", false, 0);
    expect(sideWeights(rows, "all", false, "pos").filter((w) => w > 0)).toHaveLength(1);
    const { pos, neg } = s2Sides(rows, "all", false, gmm);
    expect(pos!.peaks).toHaveLength(1);
    expect(pos!.mix).toBeNull();
    expect(kLabel(en, gmm, pos)).toBe("auto");
    expect(kLabel(en, gmm, neg)).toBe("auto · 1");
    expect(mixtureMeta(en, pos, neg)).toBe("out: 1 bell");
    expect(mixRows(pos, neg).map((m) => [m.m, m.side])).toEqual([[1, "neg"]]);
    // No fit at all: fewer than 3 rows (A:1680).
    const two = rows.slice(0, 2).map((r) => r.price);
    expect(fitSide(two, [1, 1], gmm)).toBeNull();
    expect(kLabel(en, gmm, null)).toBe("auto");
    expect(mixtureMeta(en, null, neg)).toBe("out: 1 bell");
    expect(mixtureMeta(en, null, null)).toBe("");
    expect(mixRows(null, null)).toEqual([]);
    expect(clusters(null, null)).toEqual([]);
    expect(clusterMeta(en, [])).toBe("");
  });

  // page-recorded: flowTip({ b: 77500, all: -115540.48, sth: -180246.45, lth: 64705.98 }, 500, "30d") ->
  // ["$77,500 – $78,000", "Real net flow −115,540", "Aging to LTH −64,706", "STH apparent −180,246",
  //  "36% of the STH decline is aging, not selling · 30d window"]
  it("reads one bucket like the page's tooltip", () => {
    const row = s2Rows("30d", "all", false, 0).find((r) => r.b === 77500)!;
    expect([row.all, row.sth, row.lth].map((v) => v.toFixed(2))).toEqual([
      "-115540.48",
      "-180246.45",
      "64705.98",
    ]);
    const tip = [
      "$77,500 – $78,000",
      "Real net flow −115,540",
      "Aging to LTH −64,706",
      "STH apparent −180,246",
      "36% of the STH decline is aging, not selling · 30d window",
    ];
    expect(flowTip(en, row, 500, "30d")).toEqual(tip);
    expect(
      flowTip(
        en,
        { b: 77500, price: 77750, all: -115540.48, sth: -180246.45, lth: 64705.98 },
        500,
        "30d",
      ),
    ).toEqual(tip);
    // zh labels: A:940-941 for the rows, the brief's table for the verdict.
    expect(flowTip(zh, row, 500, "30d")).toEqual([
      "$77,500 – $78,000",
      "真实净流动 −115,540",
      "迁移至长期持有者 −64,706",
      "短期持有者表观 −180,246",
      "短期持有者减少中有 36% 是币龄迁移而非卖出 · 30d 窗口",
    ]);
    // The other verdicts and the LTH label, on hand rows, worded as A:1893-1899 words them: STH
    // grew; STH did not grow and LTH did not gain (all three zero included: "+0", A:1583's v >= 0).
    expect(
      flowTip(
        en,
        { b: 82000, price: 82250, all: 220010.4, sth: 233631.2, lth: -13620.8 },
        500,
        "7d",
      ),
    ).toEqual([
      "$82,000 – $82,500",
      "Real net flow +220,010",
      "LTH distribution +13,621",
      "STH apparent +233,631",
      "STH acquired at this cost basis · 7d window",
    ]);
    expect(flowTip(en, { b: 1000, price: 1100, all: 0, sth: 0, lth: 0 }, 200, "1d")).toEqual([
      "$1,000 – $1,200",
      "Real net flow +0",
      "Aging to LTH +0",
      "STH apparent +0",
      "supply left this bucket outright · 1d window",
    ]);
    expect(flowTip(en, { b: 1000, price: 1100, all: -3, sth: -2, lth: -1 }, 200, "90d")[4]).toBe(
      "supply left this bucket outright · 90d window",
    );
    // Only a strict STH decline with a strict LTH gain is read as aging (A:1893): an unchanged
    // LTH, or an unchanged STH, falls through to "outright".
    expect(flowTip(en, { b: 1000, price: 1100, all: -2, sth: -2, lth: 0 }, 200, "1d")[4]).toBe(
      "supply left this bucket outright · 1d window",
    );
    expect(flowTip(en, { b: 1000, price: 1100, all: 0.01, sth: 0, lth: 0.01 }, 200, "1d")[4]).toBe(
      "supply left this bucket outright · 1d window",
    );
    // All gained while STH lost to age: the whole decline is aging (A:1893-1894).
    expect(flowTip(en, { b: 1000, price: 1100, all: 1, sth: -4, lth: 5 }, 200, "1d")[4]).toBe(
      "100% of the STH decline is aging, not selling · 1d window",
    );
  });

  // The reasons the service gives Chart 3 for a missing window or a snapshot from another block,
  // in the words of the brief's i18n table.
  it("names a missing window and a mismatched snapshot", () => {
    expect(reasonText(en, "window_missing:1d:lin500")).toBe(
      "No 1d comparison at $500: a snapshot it needs is missing",
    );
    expect(reasonText(zh, "window_missing:90d:lin200")).toBe(
      "$200 桶宽下无法比较 90d：缺少所需的快照",
    );
    expect(reasonText(en, "urpd_mismatch:sth:lin500")).toBe(
      "The STH $500 snapshot is from another block; not used",
    );
    expect(reasonText(zh, "urpd_mismatch:lth:lin200")).toBe(
      "LTH 的 $200 快照来自另一个区块，未使用",
    );
  });

  // The page's spot comparison (A:1812-1817): one decimal, below or above; no spot reads "—".
  it("compares a level with spot as the page does", () => {
    // page-recorded: 30d All K1 at $41,750 and K4 at $83,750 against spot 82,361.33.
    expect(vsSpot(en, 41750, s2.spot!)).toBe("49.3% below");
    expect(vsSpot(en, 83750, s2.spot!)).toBe("1.7% above");
    expect(vsSpot(zh, 41750, s2.spot!)).toBe("低于现价 49.3%");
    expect(vsSpot(zh, 83750, s2.spot!)).toBe("高于现价 1.7%");
    expect(vsSpot(en, 83750, 0)).toBe("—");
    expect(vsSpot(en, 83750, Number.NaN)).toBe("—");
    // A:1812's strict "<": a level at spot itself (a close on a bucket's middle) reads "above",
    // and both tables' tags take the same strict "<" (A:1813-1816).
    expect(vsSpot(en, 82250, 82250)).toBe("0.0% above");
    const peak = {
      index: 0,
      location: 82250,
      height: 1,
      prominence: 1,
      strength: 1,
      width: 500,
      supply: 2,
      share: 1,
    };
    expect(clusterCells(en, { n: 1, side: "pos", peak }, 82250).below).toBe(false);
    expect(clusterCells(en, { n: 1, side: "pos", peak }, 82250.01).below).toBe(true);
    const comp = { mu: 82250, sigma: 10, w: 1 };
    expect(mixCells(en, { m: 1, side: "pos", comp, totalW: 2 }, 82250).below).toBe(false);
    expect(mixCells(en, { m: 1, side: "pos", comp, totalW: 2 }, 82250.01).below).toBe(true);
    // The brief's integer format: grouped, rounded, signed with "+" from zero up and "−" below.
    expect([fmtSigned(-0.4), fmtSigned(0.5), fmtSigned(-1121241.2)]).toEqual([
      "−0",
      "+1",
      "−1,121,241",
    ]);
    expect([fmtPrice(125500), fmtBtc(1134836.6)]).toEqual(["$125,500", "1,134,837"]);
  });

  // stage A = the Python reference port, 05:12, sample-0512: the legend totals of the 23 states,
  // including STH with Aging Show, whose aging bars sit on the sell side (S2 has no $200 grid).
  it("totals the legend as stage A does, STH aging included", () => {
    const spot = s1.spot!;
    for (const v of expected.chart3_stage_a.views) {
      const h = v.cohort as Holders;
      const aging = v.aging === "on";
      const what = `${v.win} ${v.cohort} z${v.zoom} ${v.aging}`;
      const rows = rowsOf(gridFor(s1, h)!, v.win as Window, h, aging, v.zoom as Zoom, spot);
      const t = flowTotals(rows, h, aging);
      near(t.buy, v.net_buy, 1e-9, `${what} buy`);
      near(-t.sell, v.net_sell, 1e-9, `${what} sell`);
      if (v.aging_btc === null) expect(t.aging, what).toBeNull();
      else near(t.aging!, v.aging_btc, 1e-9, `${what} aging`);
    }
    // stage A printout: 30d STH Show, Aging 334,783, 23% of the sell side; the shipped legend row.
    const sth30 = flowTotals(rowsOf(gridFor(s1, "sth")!, "30d", "sth", true, 0, spot), "sth", true);
    expect(legendRows(en, sth30, "sth")[2]).toEqual({
      key: "aging",
      side: "neg",
      label: "Aging STH→LTH",
      value: "334,783 BTC · 23% of sell side",
    });
  });
});
