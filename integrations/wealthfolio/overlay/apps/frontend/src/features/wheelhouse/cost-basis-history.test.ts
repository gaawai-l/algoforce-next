import { describe, expect, it } from "vitest";
import expected from "./cost-basis-history-expected.json";
import raw from "./cost-basis-history-sample.json";
import { costBasisHistorySchema } from "./onchain-contract";
import { ticks } from "./sell-side";
import {
  CBH_SPANS,
  DEFAULT_CONTRAST,
  DEFAULT_SPAN,
  OCCUPIED,
  RAMP,
  RANGES,
  STEP,
  UNDER_FLOOR,
  cellLevel,
  clampHandle,
  contrast,
  contrastLabel,
  coverage,
  dayLabel,
  dayTicks,
  fmtBucket,
  fmtK,
  fmtSupply,
  keyLabels,
  occupiedRows,
  paint,
  sortedCells,
  tipParts,
  visibleWindow,
  zoomFromDrag,
  zoomText,
  type Contrast,
  type RangePct,
  type Visible,
} from "./cost-basis-history";

// The golden sample is the local service's answer to GET /onchain/cost-basis-history?span=30 at
// 2026-10-16T18:40Z (test_cost_basis_history_matches_the_frontend_sample keeps it byte for byte).
// Its snapshots are the all-coins lin500 files of services/analytics/tests/onchain/fixtures/
// brk-2026-10-16T1829Z, stored by `seed_history_sample` (onchain_fixture.py): D = 10-16 forming,
// 10-15, 10-14, 10-09 and 10-08 closed, 10-10 absent, the rest pending. The stage-A history
// snapshots that pin each stored row are in fixtures/brk-urpd-history (Task 1).
// cost-basis-history-expected.json is the output of the committed Python reference
// services/analytics/tests/onchain/cbh_reference.py, a line-by-line port of the original page
// (state-report raw/script_2_app.js A:3961-4008, A:4117-4139) that the Task 3 review matched to it.
// Every other expected value cites its source: SR-8 (the stage-B readings of the original page),
// the PLAN-SR8 Task 4 brief, plan R11/R14, or d3-time 3.1.0's utcTicks (the d3 v7.9.0 the
// original embeds) run on the same window.
const sample = costBasisHistorySchema.parse(raw);
const grid = Array.from({ length: 250 }, (_, i) => 1000 + 500 * i);
const full = (spot: number): Visible => ({
  days: ["2026-10-18", "2026-10-19"],
  close: [spot, spot],
  supply: [grid.map(() => 1), grid.map(() => 1)],
  status: ["closed", "forming"],
});
// Builds inputs only: one ISO day per UTC timestamp.
const isoDay = (t: number) => new Date(t).toISOString().slice(0, 10);
const pixel = (out: Uint8ClampedArray, width: number, x: number, y: number) =>
  Array.from(out.slice((y * width + x) * 4, (y * width + x) * 4 + 4));

describe("cost-basis history (Chart 8)", () => {
  it("keeps the brief's constants", () => {
    // Brief: Span keys and days (All = 1,461 days, plan R2), defaults 365 and 75-95, Range presets.
    expect(CBH_SPANS).toEqual([
      { key: "30", days: 30 },
      { key: "90", days: 90 },
      { key: "365", days: 365 },
      { key: "all", days: 1461 },
    ]);
    expect(DEFAULT_SPAN).toBe("365");
    expect(RANGES).toEqual([0, 50, 25, 10]);
    expect(DEFAULT_CONTRAST).toEqual({ lo: 75, hi: 95 });
    // A:3959 and the $500 grid.
    expect(OCCUPIED).toBe(0.005);
    expect(STEP).toBe(500);
    // Plan R11 (the user's below-floor step) and R14 (the ramp, dim to bright).
    expect(UNDER_FLOOR).toBe("#233142");
    expect(RAMP).toEqual(["#164a52", "#1f7f80", "#33b3a3", "#59e6cd"]);
  });

  it("centres Range on the latest close as the original (SR-8 lines 20-21)", () => {
    const rows = (range: RangePct) => {
      const o = occupiedRows(grid, full(82374.12), range, null)!;
      return [o.r0, o.r1];
    };
    expect(rows(0)).toEqual([0, 249]);
    expect(rows(50)).toEqual([80, 246]); // $41,000-$124,500, 167 rows
    expect(rows(25)).toEqual([121, 204]); // $61,500-$103,500, 84 rows
    expect(rows(10)).toEqual([146, 180]); // $74,000-$91,500, 35 rows
  });

  it("lets a dragged price band win over Range and drops one that is empty", () => {
    expect(occupiedRows(grid, full(82374.12), 25, [60000, 70000])).toEqual({
      r0: 118,
      r1: 138,
      zy: [60000, 70000],
    });
    expect(occupiedRows(grid, full(82374.12), 0, [60000, 60000])!.zy).toBeNull();
    // A dropped band falls through to Range (brief: "continue"): the ±25% rows of SR-8 line 20.
    expect(occupiedRows(grid, full(82374.12), 25, [60000, 60000])).toEqual({
      r0: 121,
      r1: 204,
      zy: null,
    });
    // A band above every occupied row is empty too (brief: b = min(hi, …) must exceed a).
    expect(occupiedRows(grid, full(82374.12), 0, [200000, 300000])).toEqual({
      r0: 0,
      r1: 249,
      zy: null,
    });
    // A band wider than the data keeps the occupied rows and stays set (brief: max/min).
    expect(occupiedRows(grid, full(82374.12), 0, [0, 1e6])).toEqual({
      r0: 0,
      r1: 249,
      zy: [0, 1e6],
    });
  });

  it("trims rows that hold nothing and ignores missing days", () => {
    // Rows 0-9 at 0.004 and 240-249 at exactly 0.005 hold nothing (brief: v > 0.005).
    const row = grid.map((_, r) => (r < 10 ? 0.004 : r >= 240 ? 0.005 : 1));
    // A null day with a later close does not move the Range centre: spot comes from the last
    // stored day (brief), 82,374.12, so ±10% keeps SR-8 line 20's rows.
    const vis: Visible = {
      days: ["2026-10-17", "2026-10-18", "2026-10-19"],
      close: [82374.12, 82374.12, 30000],
      supply: [row, row, null],
      status: ["closed", "closed", "pending"],
    };
    expect(occupiedRows(grid, vis, 0, null)).toEqual({ r0: 10, r1: 239, zy: null });
    expect(occupiedRows(grid, vis, 10, null)).toEqual({ r0: 146, r1: 180, zy: null });
    // Range stays inside the occupied rows (brief: a = max(lo, …), b = min(hi, …)).
    expect(occupiedRows(grid, vis, 50, null)).toEqual({ r0: 80, r1: 239, zy: null });
    const low = grid.map((_, r) => (r < 100 ? 0 : 1));
    const lowVis: Visible = { ...vis, supply: [low, low, null] };
    expect(occupiedRows(grid, lowVis, 50, null)).toEqual({ r0: 100, r1: 246, zy: null });
    // Rows are occupied over all stored days together: 20-30 on one day, 50-60 on another.
    const part = (from: number, to: number) => grid.map((_, r) => (r >= from && r <= to ? 2 : 0));
    const split: Visible = { ...vis, supply: [part(50, 60), part(20, 30), null] };
    expect(occupiedRows(grid, split, 0, null)).toEqual({ r0: 20, r1: 60, zy: null });
  });

  it("skips Range without a spot or when it misses the grid, and has no rows when empty", () => {
    const vis = full(82374.12);
    // No close on the last stored day: the original's `if (spot)` skips Range (A:3977).
    expect(occupiedRows(grid, { ...vis, close: [82374.12, null] }, 50, null)).toEqual({
      r0: 0,
      r1: 249,
      zy: null,
    });
    // A spot far above the grid leaves b <= a, so Range is not applied (A:3981).
    expect(occupiedRows(grid, full(1e6), 10, null)).toEqual({ r0: 0, r1: 249, zy: null });
    // Spot $139,500 at ±10%: the band starts on the top row ($125,550 is row 249), so a = b = 249
    // and Range is not applied either (brief: only when b > a).
    expect(occupiedRows(grid, full(139500), 10, null)).toEqual({ r0: 0, r1: 249, zy: null });
    // Nothing above 0.005 on any stored day: no rows at all (brief: null).
    const empty: Visible = { ...vis, supply: [grid.map(() => 0.005), null] };
    expect(occupiedRows(grid, empty, 0, null)).toBeNull();
    expect(occupiedRows(grid, { ...vis, supply: [null, null] }, 0, [60000, 70000])).toBeNull();
  });

  it("keeps a zoom window of two days or more", () => {
    // Brief: zx keeps zx[0] <= day <= zx[1]; under two days left, zx is dropped (A:3937-3943).
    const zx: [string, string] = ["2026-10-14", "2026-10-15"];
    const kept = visibleWindow(sample, zx);
    expect(kept.zx).toEqual(zx);
    expect(kept.vis.days).toEqual(["2026-10-14", "2026-10-15"]);
    expect(kept.vis.close).toEqual([81334.84, 82203.57]);
    expect(kept.vis.status).toEqual(["closed", "closed"]);
    expect(kept.vis.supply).toEqual([sample.supply[27], sample.supply[28]]);
    const dropped = visibleWindow(sample, ["2026-10-16", "2026-10-20"]);
    expect(dropped.zx).toBeNull();
    expect(dropped.vis).toEqual({
      days: sample.days,
      close: sample.close,
      supply: sample.supply,
      status: sample.status,
    });
    expect(visibleWindow(sample, null).zx).toBeNull();
  });

  it("reads the sorted cells of stored days inside the rows", () => {
    const vis: Visible = {
      days: ["2026-10-17", "2026-10-18", "2026-10-19"],
      close: [1, null, 1],
      supply: [[100, 9, 0.005, 7], null, [0.006, 10, 30, 8]],
      status: ["closed", "pending", "forming"],
    };
    // Brief: rows r0..r1 of stored days, only cells over 0.005, ascending (A:3987-3996).
    expect(Array.from(sortedCells(vis, 0, 2))).toEqual([0.006, 9, 10, 30, 100]);
    expect(Array.from(sortedCells(vis, 1, 1))).toEqual([9, 10]);
  });

  it("picks quantiles by nearest rank with Math.round", () => {
    const s = Float64Array.from({ length: 100 }, (_, i) => i + 1);
    expect(contrast(s, 75, 95)).toMatchObject({ floor: 75, cap: 95, clipped: true, dropped: true });
    expect(contrast(s, 0, 100)).toMatchObject({
      floor: 0,
      cap: 100,
      clipped: false,
      dropped: false,
    });
    const eleven = Float64Array.from({ length: 11 }, (_, i) => i + 1); // 9.5 rounds up, 7.5 rounds up
    expect(contrast(eleven, 75, 95)).toMatchObject({ floor: 9, cap: 11, clipped: false });
    // Brief: span = cap - floor.
    expect(contrast(s, 75, 95).span).toBe(20);
  });

  it("keeps the cap above the floor and reads an empty window as [0, 1]", () => {
    // Brief: cap = max(at(hi), floor + 1e-9), span = max(1e-9, cap - floor).
    const flat = Float64Array.from([5, 5, 5, 5]);
    const c = contrast(flat, 25, 75);
    expect(c).toMatchObject({ floor: 5, cap: 5 + 1e-9, clipped: false, dropped: true });
    expect(c.span).toBeCloseTo(1e-9, 15);
    expect(c.span).toBeGreaterThanOrEqual(1e-9);
    // With the cap at the top and every cell equal, cap - floor is 0 and the span is held at 1e-9.
    expect(contrast(flat, 25, 100)).toMatchObject({ floor: 5, cap: 5, span: 1e-9, clipped: false });
    // Brief: an empty array counts as [0, 1].
    expect(contrast(new Float64Array(), 75, 95)).toMatchObject({
      floor: 1,
      cap: 1 + 1e-9,
      clipped: false,
      dropped: true,
    });
    expect(contrast(new Float64Array(), 0, 100)).toMatchObject({
      floor: 0,
      cap: 1,
      span: 1,
      clipped: false,
      dropped: false,
    });
  });

  it("labels the key and the contrast as the original (SR-8 lines 18-19)", () => {
    const c = {
      floor: 83745.15,
      cap: 192900.73,
      span: 192900.73 - 83745.15,
      clipped: true,
      dropped: true,
    };
    expect(keyLabels(c)).toEqual(["−84k", "111k", "138k", "166k", "193k+"]);
    expect(contrastLabel(c, 75, 95)).toBe("75–95% · 84k–193k+");
    expect(contrastLabel({ ...c, floor: 87327.15, cap: 199792.63 }, 75, 95)).toBe(
      "75–95% · 87k–200k+",
    );
    expect(contrastLabel({ ...c, floor: 85947.41, cap: 197795.52 }, 75, 95)).toBe(
      "75–95% · 86k–198k+",
    );
    expect(contrastLabel({ ...c, clipped: false, dropped: false }, 0, 100)).toBeNull();
    // Brief: the minus only while the floor drops cells, the plus only while the cap clips them,
    // and either alone still names the window.
    expect(keyLabels({ ...c, clipped: false, dropped: false })).toEqual([
      "84k",
      "111k",
      "138k",
      "166k",
      "193k",
    ]);
    expect(contrastLabel({ ...c, dropped: false }, 0, 95)).toBe("0–95% · 84k–193k+");
    expect(contrastLabel({ ...c, clipped: false }, 75, 100)).toBe("75–100% · 84k–193k");
    // Brief: the handles print through Math.round.
    expect(contrastLabel(c, 74.5, 94.4)).toBe("75–94% · 84k–193k+");
  });

  it("maps cells to empty, below floor and four steps", () => {
    const c = { floor: 83745.15, cap: 192900.73, span: 109155.58, clipped: true, dropped: true };
    expect(
      [0.005, 0.0051, 83745.15, 83745.16, 111034.05, 192900.73, 1e6].map((v) => cellLevel(v, c)),
    ).toEqual([0, 1, 1, 2, 3, 5, 5]);
    // Brief: 2 + floor(u * 4) with u = (v - floor) / span, at each quarter of the window.
    const q = { floor: 0, cap: 4, span: 4, clipped: false, dropped: false };
    expect([0.006, 0.99, 1, 1.99, 2, 3, 3.99, 4].map((v) => cellLevel(v, q))).toEqual([
      2, 2, 3, 3, 4, 5, 5, 5,
    ]);
  });

  it("paints missing days and empty cells transparent", () => {
    // Brief: 2 days x 2 rows, day 2 null, floor 1 cap 5.
    const c = { floor: 1, cap: 5, span: 4, clipped: false, dropped: true };
    const vis: Visible = {
      days: ["2026-10-18", "2026-10-19"],
      close: [1, null],
      supply: [[0.004, 10], null],
      status: ["closed", "pending"],
    };
    const out = new Uint8ClampedArray(2 * 2 * 4).fill(7);
    paint(vis, 0, 1, c, out);
    expect(pixel(out, 2, 0, 1)[3]).toBe(0); // row 0, value 0.004
    expect(pixel(out, 2, 0, 0)).toEqual([89, 230, 205, 255]); // row 1, value 10 = #59e6cd
    expect(pixel(out, 2, 1, 0)[3]).toBe(0);
    expect(pixel(out, 2, 1, 1)[3]).toBe(0);
  });

  it("paints the below-floor step and the ramp, row r at y = r1 - r", () => {
    // Brief: level 1 is UNDER_FLOOR, levels 2-5 are RAMP[0..3], all at alpha 255; plan R11/R14
    // give the hex values. Rows 1-6 are drawn (r0 = 1), so row 0's 99 is left out.
    const c = { floor: 1, cap: 5, span: 4, clipped: false, dropped: true };
    const vis: Visible = {
      days: ["2026-10-19"],
      close: [1],
      supply: [[99, 0.5, 1.5, 2.5, 3.5, 4.5, 0.001]],
      status: ["forming"],
    };
    const out = new Uint8ClampedArray(1 * 6 * 4);
    paint(vis, 1, 6, c, out);
    expect([0, 1, 2, 3, 4, 5].map((y) => pixel(out, 1, 0, y))).toEqual([
      [0, 0, 0, 0], // row 6: 0.001, empty
      [89, 230, 205, 255], // row 5: #59e6cd
      [51, 179, 163, 255], // row 4: #33b3a3
      [31, 127, 128, 255], // row 3: #1f7f80
      [22, 74, 82, 255], // row 2: #164a52
      [35, 49, 66, 255], // row 1: 0.5 under the floor, #233142
    ]);
  });

  it("matches the Python reference on the sample (cost-basis-history-expected.json)", () => {
    const { vis } = visibleWindow(sample, null);
    for (const want of expected) {
      const rows = occupiedRows(sample.floors, vis, want.range as RangePct, null)!;
      expect([rows.r0, rows.r1], `range ${want.range}`).toEqual([want.r0, want.r1]);
      const sorted = sortedCells(vis, rows.r0, rows.r1);
      expect(sorted.length).toBe(want.n);
      expect(sorted[sorted.length - 1]).toBe(want.top);
      const c: Contrast = contrast(sorted, DEFAULT_CONTRAST.lo, DEFAULT_CONTRAST.hi);
      expect([c.floor, c.cap]).toEqual([want.floor, want.cap]);
      expect(c.clipped).toBe(want.cap < want.top);
      expect(keyLabels(c)).toEqual(want.key);
      expect(contrastLabel(c, DEFAULT_CONTRAST.lo, DEFAULT_CONTRAST.hi)).toBe(want.label);
    }
  });

  it("clamps the contrast handles without swapping", () => {
    expect(clampHandle("lo", 96, 75, 95)).toEqual([94, 95]);
    expect(clampHandle("hi", 10, 75, 95)).toEqual([75, 76]);
    expect(clampHandle("lo", -5, 0, 95)).toEqual([0, 95]);
    expect(clampHandle("lo", 100, 75, 100)).toEqual([99, 100]);
    // Brief: hi is held to [1, 100] and moves freely above lo + 1.
    expect(clampHandle("hi", 120, 75, 95)).toEqual([75, 100]);
    expect(clampHandle("hi", 0, 0, 50)).toEqual([0, 1]);
    expect(clampHandle("hi", 60, 50, 95)).toEqual([50, 60]);
    expect(clampHandle("lo", 30, 50, 95)).toEqual([30, 95]);
    // States the handles never reach on their own, kept in range by the final clamps to [0, 99]
    // and [1, 100] (brief; A:4171-4172).
    expect(clampHandle("hi", 100, 100, 100)).toEqual([99, 100]);
    expect(clampHandle("lo", 0, 0, 0)).toEqual([0, 1]);
  });

  it("places time ticks by d3's rule (SR-8 lines 19, 21)", () => {
    expect(dayTicks("2025-10-20", "2026-10-19", 7)).toEqual([
      "2026-01-01",
      "2026-04-01",
      "2026-07-01",
      "2026-10-01",
    ]);
    expect(dayTicks("2026-09-20", "2026-10-19", 7)).toEqual([
      "2026-09-20",
      "2026-09-27",
      "2026-10-04",
      "2026-10-11",
      "2026-10-18",
    ]);
    expect(dayTicks("2022-10-20", "2026-10-19", 7)).toEqual([
      "2023-01-01",
      "2024-01-01",
      "2025-01-01",
      "2026-01-01",
    ]);
    expect(dayTicks("2022-10-20", "2026-10-19", 3)).toEqual([
      "2023-01-01",
      "2024-01-01",
      "2025-01-01",
      "2026-01-01",
    ]);
    expect(dayTicks("2022-10-20", "2026-10-19", 4)).toEqual([
      "2023-01-01",
      "2024-01-01",
      "2025-01-01",
      "2026-01-01",
    ]);
    expect(dayTicks("2022-10-20", "2026-10-19", 2)).toEqual(["2024-01-01", "2026-01-01"]);
    expect(
      ["2026-01-01", "2026-10-04", "2024-01-01"].map((d, i) => dayLabel(d, [364, 29, 1460][i])),
    ).toEqual(["Jan 26", "04 Oct", "2024"]);
  });

  it("places day, two-day and month ticks by d3's rule", () => {
    // 4 days over 8 ticks: target half a day, i = 0, so every day (brief; d3 would tick every
    // 12 hours and print each date twice).
    expect(dayTicks("2026-10-15", "2026-10-19", 8)).toEqual([
      "2026-10-15",
      "2026-10-16",
      "2026-10-17",
      "2026-10-18",
      "2026-10-19",
    ]);
    // 18 days over 8: target 2.25 days; 2.25 / 2 < 7 / 2.25, so two days. The original's embedded
    // d3 v7.9.0 builds utcTicks on unixDay (state-report.html: `[ov,av]=iv(ev,Qy,Fy,_y,hy,cy)`,
    // `_y` counting Math.floor(t/864e5)), so two-day ticks fall on even days since 1970 (10-02 is
    // day 20,728). Expected as d3-time 3.1.0's utcTicks prints it for this window.
    expect(dayTicks("2026-10-02", "2026-10-20", 8)).toEqual([
      "2026-10-02",
      "2026-10-04",
      "2026-10-06",
      "2026-10-08",
      "2026-10-10",
      "2026-10-12",
      "2026-10-14",
      "2026-10-16",
      "2026-10-18",
      "2026-10-20",
    ]);
    // 364 days over 8: target 45.5 days; 45.5 / 30 < 90 / 45.5, so every month (brief).
    expect(dayTicks("2025-10-20", "2026-10-19", 8)).toEqual([
      "2025-11-01",
      "2025-12-01",
      "2026-01-01",
      "2026-02-01",
      "2026-03-01",
      "2026-04-01",
      "2026-05-01",
      "2026-06-01",
      "2026-07-01",
      "2026-08-01",
      "2026-09-01",
      "2026-10-01",
    ]);
    // 1,460 days over 1: years by d3's tickStep(…, 1) = 5, so years divisible by 5 (brief).
    expect(dayTicks("2022-10-20", "2026-10-19", 1)).toEqual(["2025-01-01"]);
    // A year is 365 days (brief): 1,033 days over 2 is 1.415 such years a tick, just over √2, so
    // the step is 2 (in years of 365.25 days it would be 1.414, under √2, and every year). Expected
    // as d3-time 3.1.0's utcTicks prints it for this window.
    expect(dayTicks("2022-10-20", "2025-08-18", 2)).toEqual(["2024-01-01"]);
  });

  it("labels the time axis by the window's length (A:4091-4092)", () => {
    // Brief: %d %b up to 120 days, %b %y up to 800, else %Y; a fixed month list.
    expect(dayLabel("2026-09-05", 120)).toBe("05 Sep");
    expect(dayLabel("2026-09-05", 121)).toBe("Sep 26");
    expect(dayLabel("2026-12-31", 800)).toBe("Dec 26");
    expect(dayLabel("2026-12-31", 801)).toBe("2026");
  });

  it("formats as the original", () => {
    expect([887948.13, 1234567, 999.6].map(fmtSupply)).toEqual(["888k", "1.23M", "1000"]);
    expect([82374.12, 9500, 20000].map(fmtK)).toEqual(["$82k", "$9.5k", "$20k"]);
    expect([82000, 82500].map(fmtBucket)).toEqual(["$82.0k", "$82.5k"]);
    expect(ticks(1000, 126000, 7)).toEqual([20000, 40000, 60000, 80000, 100000, 120000]); // SR-8 line 21
    // A:3924-3926 at their edges: 1e6 is "M", a value under 1e3 rounds whole, toFixed rounds the
    // binary value (1.005 is 1.00499…, as cbh_reference.to_fixed has it), $10k drops the decimal.
    expect([1e6, 999999, 1000, 999.4, 1_005_000].map(fmtSupply)).toEqual([
      "1.00M",
      "1000k",
      "1k",
      "999",
      "1.00M",
    ]);
    expect([9999, 10000].map(fmtK)).toEqual(["$10.0k", "$10k"]);
  });

  it("builds the readouts the UI renders (SR-8 line 22)", () => {
    const { vis } = visibleWindow(sample, null);
    // the original's tooltip on 2026-10-15; the golden fixture's 10-15 $82k cell is 219,105.90
    expect(tipParts(vis, 28, 162, sample.floors)).toEqual({
      day: "2026-10-15",
      bucket: "$82.0k–$82.5k",
      supply: "219,106 BTC",
      spot: "$82k",
    });
    expect(tipParts(vis, 26, 162, sample.floors)).toEqual({
      day: "2026-10-13",
      missing: "pending",
    });
    expect(zoomText(["2026-09-20", "2026-10-11"], [60000, 70000])).toBe("09-20–10-11 · $60k–$70k");
    expect(zoomText(null, [9500, 70000])).toBe("$9.5k–$70k");
    expect(coverage(vis)).toEqual({ have: 5, want: 30, pending: 24, absent: 1, forming: 1 });
    // The sample's absent day (10-10, plan R9), and the zoom note's other halves (brief).
    expect(tipParts(vis, 23, 162, sample.floors)).toEqual({ day: "2026-10-10", missing: "absent" });
    expect(zoomText(["2026-09-20", "2026-10-11"], null)).toBe("09-20–10-11");
    expect(zoomText(null, null)).toBe("");
    // Brief: spot is null without a close.
    const noClose: Visible = { ...vis, close: vis.close.map(() => null) };
    expect(tipParts(noClose, 28, 162, sample.floors)).toMatchObject({ spot: null });
  });

  it("turns a dragged box into whole days and a price band", () => {
    const days = Array.from({ length: 365 }, (_, i) => isoDay(Date.UTC(2025, 9, 20) + i * 864e5));
    expect(
      zoomFromDrag(
        { x0: 10.2, x1: 20.7, y0: 0, y1: 125 },
        { width: 365, height: 250 },
        days,
        1000,
        126000,
      ),
    ).toEqual({
      zx: [days[10], days[20]],
      zy: [63500, 126000],
    });
    expect(
      zoomFromDrag(
        { x0: 10, x1: 13, y0: 0, y1: 3 },
        { width: 365, height: 250 },
        days,
        1000,
        126000,
      ),
    ).toBeNull();
    expect(
      zoomFromDrag(
        { x0: 10, x1: 20, y0: 0, y1: 2 },
        { width: 365, height: 250 },
        days,
        1000,
        126000,
      )!.zy,
    ).toBeNull();
  });

  it("orders a dragged box and holds it to the plot", () => {
    const days = Array.from({ length: 365 }, (_, i) => isoDay(Date.UTC(2025, 9, 20) + i * 864e5));
    const plot = { width: 730, height: 250 };
    // Brief: 6 px is enough on either axis (A:4189, A:4206); the box may be dragged either way;
    // columns are width / n wide and clamped to 0..n-1; the band is in ascending order.
    expect(zoomFromDrag({ x0: 26, x1: 20, y0: 125, y1: 0 }, plot, days, 1000, 126000)).toEqual({
      zx: [days[10], days[13]],
      zy: [63500, 126000],
    });
    expect(zoomFromDrag({ x0: -40, x1: 900, y0: 0, y1: 5.9 }, plot, days, 1000, 126000)).toEqual({
      zx: [days[0], days[364]],
      zy: null,
    });
    expect(zoomFromDrag({ x0: 20, x1: 25.9, y0: 50, y1: 56 }, plot, days, 1000, 126000)).toEqual({
      zx: null,
      zy: [98000, 101000],
    });
    // Six pixels inside one column name no window (brief: only when the first day is earlier).
    expect(
      zoomFromDrag(
        { x0: 0, x1: 6, y0: 0, y1: 0 },
        { width: 3650, height: 250 },
        days,
        1000,
        126000,
      ),
    ).toEqual({
      zx: null,
      zy: null,
    });
  });
});
