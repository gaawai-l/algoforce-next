import { describe, expect, it } from "vitest";
import {
  DEFAULT_SIDE,
  bic,
  detectPeaks,
  fitGMM1D,
  fitSide,
  samplePDF,
  weightedKDE,
} from "./cost-flow-engine";
import crosscheck from "./cost-flow-crosscheck.json";
import expected from "./cost-flow-expected.json";

// The relative difference of two numbers; 0 when they are equal, both zeros included.
const rel = (a: number, b: number) =>
  a === b ? 0 : Math.abs(a - b) / Math.max(Math.abs(a), Math.abs(b));
const near = (actual: number, want: number, tol: number, what: string) =>
  expect(rel(actual, want), `${what}: ${actual} vs ${want}`).toBeLessThanOrEqual(tol);

// The rows of a side that carry weight, as the page's mixture fits them (A:1517-1518).
const weighted = (centers: readonly number[], weights: readonly number[]) => {
  const xs: number[] = [];
  const ws: number[] = [];
  centers.forEach((x, i) => {
    if (weights[i] > 0) {
      xs.push(x);
      ws.push(weights[i]);
    }
  });
  return { xs, ws };
};

const side = (holders: string, name: string) => {
  const found = crosscheck.sides.find((s) => s.holders === holders && s.side === name);
  if (!found) throw new Error(`no crosscheck side ${holders} ${name}`);
  return found;
};

const stageA = (win: string, cohort: string, aging: string) => {
  const found = expected.chart3_stage_a.views.find(
    (v) => v.win === win && v.cohort === cohort && v.zoom === 0 && v.aging === aging,
  );
  if (!found) throw new Error(`no stage-A view ${win} ${cohort} ${aging}`);
  return found;
};

describe("cost-flow engine", () => {
  // cost-flow-crosscheck.json: four sides of the 05:12 sample at Zoom All, run through
  // costbasis.py. Python and this port follow A:1404-1457 with the same loop order and the same
  // sums, so only exp()'s last bit can differ between the two.
  it("agrees with costbasis.py on KDE and peaks", () => {
    expect(crosscheck.sides).toHaveLength(4);
    for (const s of crosscheck.sides) {
      const what = `${s.window} ${s.holders} ${s.aging ? "aging" : ""} ${s.side}`;
      // fitSide's bandwidth is the page's: the default 0.02 of the centers' span (A:1681, A:1692).
      expect(DEFAULT_SIDE.bw * (s.centers[s.centers.length - 1] - s.centers[0])).toBe(s.h);
      const sm = weightedKDE(s.centers, s.weights, s.h);
      expect(sm).toHaveLength(s.kde.length);
      sm.forEach((v, i) => near(v, s.kde[i], 1e-12, `${what} kde[${i}]`));

      const peaks = detectPeaks(s.centers, sm, s.weights, DEFAULT_SIDE.minProm);
      expect(peaks).toHaveLength(s.peaks.length);
      peaks.forEach((p, i) => {
        const want = s.peaks[i];
        expect(p.location, `${what} K${i + 1} price`).toBe(want.price);
        expect(s.centers[p.index]).toBe(p.location);
        near(p.width, want.width, 1e-12, `${what} K${i + 1} width`);
        near(p.supply, want.btc, 1e-12, `${what} K${i + 1} btc`);
        near(p.share, want.share, 1e-12, `${what} K${i + 1} share`);
        near(p.strength, want.strength, 1e-12, `${what} K${i + 1} strength`);
      });

      // fitSide runs the same two engines on the same rows.
      const curves = fitSide(s.centers, s.weights, DEFAULT_SIDE);
      expect(curves?.sm).toEqual(sm);
      expect(curves?.peaks).toEqual(peaks);
      expect(curves?.mix).toBeNull();
    }
  });

  // Stage A fitted the same rows with costbasis.py's GMM, a port of A:1460-1511 with the same
  // initialisation; neither has a random step, so a given k gives the same bells.
  it("fits the page's GMM when asked for k", () => {
    for (const [holders, name, win, aging] of [
      ["all", "neg", "30d", "off"],
      ["sth", "neg", "30d", "on"],
    ] as const) {
      const s = side(holders, name);
      const { xs, ws } = weighted(s.centers, s.weights);
      const want = stageA(win, holders, aging).sides[name].gmm_auto;
      const fit = fitGMM1D(xs, ws, want.length);
      expect(fit).not.toBeNull();
      expect(fit!.comps).toHaveLength(want.length);
      fit!.comps.forEach((c, j) => {
        const what = `${win} ${holders} ${name} M${j + 1}`;
        near(c.mu, want[j].mu, 1e-9, `${what} mu`);
        near(c.sigma, want[j].sigma, 1e-9, `${what} sigma`);
        near(c.w, want[j].share, 1e-9, `${what} w`);
        if (j > 0) expect(c.mu).toBeGreaterThan(fit!.comps[j - 1].mu);
      });
      expect(Number.isFinite(fit!.logL)).toBe(true);

      // Manual k fits exactly that many bells over the side's weighted rows (A:1549-1552).
      const manual = fitSide(s.centers, s.weights, {
        ...DEFAULT_SIDE,
        mixture: "gmm",
        kMode: "manual",
        kManual: 3,
      });
      expect(manual?.mix).toEqual({
        comps: fitGMM1D(xs, ws, 3)!.comps,
        k: 3,
        src: "manual",
        raw: null,
        totalW: ws.reduce((a, w) => a + w, 0),
      });
    }

    // Hand rows where the page's start decides the fit (M4). Two quantiles on one row start 1e-3
    // apart; a quantile equal to a cumulative share takes that row. Reference values from
    // costbasis.fit_gmm, which starts the same way.
    for (const [xs, ws, want] of [
      [
        [1, 2, 3, 4, 5],
        [1, 1, 10, 1, 1],
        [
          [2.999280001805106, 0.8451539480383684, 0.5000002519998171],
          [3.000719998920652, 0.8451539480418588, 0.4999997480001828],
        ],
      ],
      [
        [1, 2, 3, 4, 5, 6, 7, 8],
        [1, 1, 1, 1, 1, 1, 1, 1],
        [
          [2.5166754744334736, 1.210393660249704, 0.48431750154558056],
          [6.362694161340355, 1.2809299090882242, 0.5156824984544195],
        ],
      ],
      // A row so far from every bell that its density underflows to 0 is shared equally among
      // them, not divided by zero (A:1492).
      [[0, 1, 2, 1000], [1, 1, 1, 1e-9], [[1.0000003329999998, 0.8167002714853367, 1]]],
    ] as const) {
      const fit = fitGMM1D(xs, ws, want.length)!;
      expect(fit.comps).toHaveLength(want.length);
      fit.comps.forEach((c, j) => {
        near(c.mu, want[j][0], 1e-9, `hand M${j + 1} mu`);
        near(c.sigma, want[j][1], 1e-9, `hand M${j + 1} sigma`);
        near(c.w, want[j][2], 1e-9, `hand M${j + 1} w`);
      });
    }

    // Fewer rows than bells, no bell, or no weight: no fit (A:1462-1464); as many rows will do.
    expect(fitGMM1D([1, 2, 3], [1, 1, 1], 3)?.comps).toHaveLength(3);
    expect(fitGMM1D([1, 2], [1, 1], 3)).toBeNull();
    expect(fitGMM1D([1, 2, 3], [1, 1, 1], 0)).toBeNull();
    expect(fitGMM1D([1, 2, 3], [0, 0, 0], 1)).toBeNull();
    // Bells come back by ascending mu whatever order the rows arrive in.
    const shuffled = fitGMM1D([30, 10, 20, 31, 11, 21], [1, 1, 1, 1, 1, 1], 3)!;
    expect(shuffled.comps.map((c) => Math.round(c.mu * 10) / 10)).toEqual([10.5, 20.5, 30.5]);

    // BIC = -2 logL + (3k - 1) ln(max(n, 2)) (A:1512): n below 2 counts as 2.
    expect(bic(-1.5, 10, 2)).toBe(3 + 5 * Math.log(10));
    expect(bic(-1.5, 1, 2)).toBe(3 + 5 * Math.log(2));
    // A bell's density times its weight, at each price (A:1557-1560).
    expect(samplePDF({ mu: 10, sigma: 2, w: 0.5 }, [10, 12])).toEqual([
      0.5 / (2 * Math.sqrt(2 * Math.PI)),
      (0.5 * Math.exp(-0.5)) / (2 * Math.sqrt(2 * Math.PI)),
    ]);
  });

  // A:1680 and A:1688: no curve without three rows or any weight on the side; smoothing Off draws
  // no KDE and marks no peak, so the mixture's k comes from BIC (A:1538).
  it("leaves a side without three rows or weight unfitted", () => {
    // A:1284-1285
    expect(DEFAULT_SIDE).toEqual({
      smoothing: "auto",
      bw: 0.02,
      minProm: 0.05,
      mixture: "none",
      kMode: "auto",
      kManual: 4,
    });
    const gmm = { ...DEFAULT_SIDE, mixture: "gmm" as const };
    expect(fitSide([1, 2], [1, 1], gmm)).toBeNull();
    expect(fitSide([1, 2, 3], [0, 0, 0], gmm)).toBeNull();
    // Without weight the KDE is flat zero, not a division by zero (A:1407).
    expect(weightedKDE([1, 2, 3], [0, 0, 0], 1)).toEqual([0, 0, 0]);
    // A zero bandwidth leaves the weights unsmoothed (A:1693).
    expect(fitSide([1, 2, 3], [1, 2, 1], { ...DEFAULT_SIDE, bw: 0 })?.sm).toEqual([1, 2, 1]);

    const s = side("all", "neg");
    const off = fitSide(s.centers, s.weights, { ...gmm, smoothing: "none" });
    expect(off?.sm).toBeNull();
    expect(off?.peaks).toEqual([]);
    expect(off?.mix?.src).toBe("bic");
    expect(off?.mix?.raw).toBeNull();

    // BIC counts every row of the side, weighted or not (A:1522): ten weighted rows in two
    // clusters among 1,000 take one bell; costbasis.select_components agrees, and counting only the
    // ten would take two.
    const centers = Array.from({ length: 1000 }, (_, i) => i);
    const weights = centers.map((i) => (i < 5 || i >= 995 ? 1 : 0));
    expect(fitSide(centers, weights, { ...gmm, smoothing: "none" })?.mix?.k).toBe(1);
  });

  // A:1423-1457 on hand curves: a plateau's first row is the peak; the prominence walk stops only
  // at a strictly higher row; a peak exactly at the cutoff is kept; the supply counts the rows on
  // both edges of the width.
  it("marks peaks on plateaus and at exact edges as the page does", () => {
    expect(detectPeaks([0, 1, 2, 3], [0, 1, 1, 0], [1, 1, 1, 1], 0.05).map((p) => p.index)).toEqual(
      [1],
    );

    const twin = detectPeaks([0, 1, 2, 3, 4], [0, 2, 1, 2, 0.5], [1, 1, 1, 1, 1], 0.75);
    expect(twin.map((p) => [p.index, p.prominence, p.strength])).toEqual([
      [1, 1.5, 0.75],
      [3, 1.5, 0.75],
    ]);
    expect(detectPeaks([0, 1, 2, 3, 4], [0, 2, 1, 2, 0.5], [1, 1, 1, 1, 1], 0.76)).toEqual([]);

    expect(detectPeaks([0, 1, 2, 3, 4], [0, 1, 2, 1, 0], [1, 2, 4, 8, 16], 0.05)).toEqual([
      {
        index: 2,
        location: 2,
        height: 2,
        prominence: 2,
        strength: 1,
        width: 2,
        supply: 14,
        share: 14 / 31,
      },
    ]);
  });
});
