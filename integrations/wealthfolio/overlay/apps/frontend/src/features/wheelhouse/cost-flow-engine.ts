// The original state-report page's smoothing and mixture engines for Charts 3 and 4, ported line
// by line from its app script (A = raw/script_2_app.js): the same loop order, the same sums, the
// same comparisons and constants, so the browser finds what the page found. There is no random
// step anywhere. costbasis.py ports the same lines for Chart 7 on the server; a change to the
// algorithm belongs in both.

export interface EnginePeak {
  index: number;
  location: number;
  height: number;
  prominence: number;
  // Prominence as a share of the highest density: 0-1.
  strength: number;
  // Full width at half height, in price.
  width: number;
  // The side's weight on the rows within the width, and its share of the side's total.
  supply: number;
  share: number;
}

export interface GmmComp {
  mu: number;
  sigma: number;
  // The bell's share of the side's weight.
  w: number;
}

export interface SideSetting {
  // "auto" and "kde" (Manual) run the same KDE; only Manual lets the reader move bw and minProm.
  smoothing: "none" | "auto" | "kde";
  // The KDE bandwidth as a share of the rows' price span.
  bw: number;
  // A peak's minimum prominence as a share of the highest density.
  minProm: number;
  mixture: "none" | "gmm";
  kMode: "auto" | "manual";
  kManual: number;
}

// A:1284-1285
export const DEFAULT_SIDE: SideSetting = {
  smoothing: "auto",
  bw: 0.02,
  minProm: 0.05,
  mixture: "none",
  kMode: "auto",
  kManual: 4,
};

export interface Mixture {
  comps: GmmComp[];
  k: number;
  // "peaks": one bell per KDE peak, capped; "bic": the lowest BIC, with smoothing Off.
  src: "peaks" | "bic" | "manual";
  // The peaks the KDE found when src is "peaks", which can exceed k; null otherwise.
  raw: number | null;
  totalW: number;
}

export interface SideCurves {
  // The KDE at each row; null when smoothing is Off.
  sm: number[] | null;
  peaks: EnginePeak[];
  mix: Mixture | null;
}

// d3.sum: skips NaN and adds in order.
function d3Sum(values: readonly number[]): number {
  let sum = 0;
  for (const value of values) if (value) sum += value;
  return sum;
}

// A:1404-1422
export function weightedKDE(
  centers: readonly number[],
  weights: readonly number[],
  h: number,
): number[] {
  const n = centers.length,
    out = new Array<number>(n).fill(0);
  const W = weights.reduce((s, w) => s + w, 0);
  if (W <= 0 || h <= 0) return out;
  const norm = 1 / (h * Math.sqrt(2 * Math.PI));
  for (let i = 0; i < n; i++) {
    const xi = centers[i];
    let lo = 0,
      hi = n - 1;
    const xL = xi - 5 * h;
    while (lo < hi) {
      const m = (lo + hi) >> 1;
      if (centers[m] < xL) lo = m + 1;
      else hi = m;
    }
    const left = lo;
    lo = 0;
    hi = n - 1;
    const xR = xi + 5 * h;
    while (lo < hi) {
      const m = (lo + hi + 1) >> 1;
      if (centers[m] > xR) hi = m - 1;
      else lo = m;
    }
    const right = lo;
    let acc = 0;
    for (let j = left; j <= right; j++) {
      const z = (xi - centers[j]) / h;
      acc += weights[j] * Math.exp(-0.5 * z * z);
    }
    out[i] = (acc * norm) / W;
  }
  return out;
}

// A:1423-1425
function findLocalMaxima(y: readonly number[]): number[] {
  const p: number[] = [];
  for (let i = 1; i < y.length - 1; i++) if (y[i] > y[i - 1] && y[i] >= y[i + 1]) p.push(i);
  return p;
}

// A:1426-1431
function peakProminence(y: readonly number[], p: number): number {
  const h = y[p];
  let l = h;
  for (let i = p - 1; i >= 0; i--) {
    if (y[i] > h) break;
    if (y[i] < l) l = y[i];
  }
  let r = h;
  for (let i = p + 1; i < y.length; i++) {
    if (y[i] > h) break;
    if (y[i] < r) r = y[i];
  }
  return h - Math.max(l, r);
}

// A:1432-1438
function peakFWHM(y: readonly number[], x: readonly number[], p: number): number {
  const half = y[p] * 0.5;
  let lX = x[p];
  for (let i = p - 1; i >= 0; i--) {
    if (y[i] <= half) {
      const dy = y[i + 1] - y[i];
      const t = dy === 0 ? 0 : (half - y[i]) / dy;
      lX = x[i] + t * (x[i + 1] - x[i]);
      break;
    }
  }
  let rX = x[p];
  for (let i = p + 1; i < y.length; i++) {
    if (y[i] <= half) {
      const dy = y[i] - y[i - 1];
      const t = dy === 0 ? 0 : (half - y[i - 1]) / dy;
      rX = x[i - 1] + t * (x[i] - x[i - 1]);
      break;
    }
  }
  return Math.max(rX - lX, 0);
}

// A:1439-1457
export function detectPeaks(
  centers: readonly number[],
  sm: readonly number[],
  weights: readonly number[],
  minPromFrac: number,
): EnginePeak[] {
  const yMax = Math.max(...sm);
  if (!(yMax > 0)) return [];
  const minProm = minPromFrac * yMax;
  const found = findLocalMaxima(sm)
    .map((i) => ({
      index: i,
      location: centers[i],
      height: sm[i],
      prominence: peakProminence(sm, i),
    }))
    .filter((p) => p.prominence >= minProm);
  const totalW = weights.reduce((s, w) => s + w, 0);
  const peaks: EnginePeak[] = [];
  for (const p of found) {
    // Prominence lives on the density scale, so it is reported relative to the tallest peak.
    const strength = yMax > 0 ? p.prominence / yMax : 0;
    const width = peakFWHM(sm, centers, p.index);
    const lo = p.location - width / 2,
      hi = p.location + width / 2;
    let s = 0;
    for (let i = 0; i < centers.length; i++)
      if (centers[i] >= lo && centers[i] <= hi) s += weights[i];
    peaks.push({ ...p, strength, width, supply: s, share: totalW > 0 ? s / totalW : 0 });
  }
  peaks.sort((a, b) => a.location - b.location);
  return peaks;
}

// A:1460-1511: a weighted 1-D Gaussian mixture by EM. The bells start at the weighted quantiles,
// each at least 1e-3 above the one before; at most 120 rounds, stopping once the log likelihood
// moves less than 1e-9. Null when there are fewer rows than k, k < 1 or no weight.
export function fitGMM1D(
  xs: readonly number[],
  ws: readonly number[],
  k: number,
): { comps: GmmComp[]; logL: number } | null {
  const n = xs.length;
  if (n < k || k < 1) return null;
  let totalW = 0;
  for (const w of ws) totalW += w;
  if (totalW <= 0) return null;
  const sorted = xs.map((x, i) => ({ x, w: ws[i] })).sort((a, b) => a.x - b.x);
  const cumQ: number[] = [];
  let acc = 0;
  for (const s of sorted) {
    acc += s.w;
    cumQ.push(acc / totalW);
  }
  const mus: number[] = [];
  for (let j = 0; j < k; j++) {
    const t = (j + 0.5) / k;
    let idx = cumQ.findIndex((q) => q >= t);
    if (idx < 0) idx = sorted.length - 1;
    mus.push(sorted[idx].x);
  }
  for (let j = 1; j < k; j++) if (mus[j] <= mus[j - 1]) mus[j] = mus[j - 1] + 1e-3;
  let xMean = 0;
  for (let i = 0; i < n; i++) xMean += xs[i] * ws[i];
  xMean /= totalW;
  let xVar = 0;
  for (let i = 0; i < n; i++) xVar += ws[i] * (xs[i] - xMean) ** 2;
  xVar /= totalW;
  const initSigma = Math.sqrt(xVar) / Math.max(1, k * 0.6);
  const sigmas = new Array<number>(k).fill(Math.max(initSigma, 1e-6));
  const pis = new Array<number>(k).fill(1 / k);
  const wNorm = ws.map((w) => w / totalW);
  let logL = -Infinity;
  const sigFloor = Math.max(initSigma * 1e-3, 1e-9);
  for (let iter = 0; iter < 120; iter++) {
    const resp = new Array<number[]>(n);
    let newLogL = 0;
    for (let i = 0; i < n; i++) {
      const r = new Array<number>(k);
      let sum = 0;
      for (let j = 0; j < k; j++) {
        const z = (xs[i] - mus[j]) / sigmas[j];
        const pv = (pis[j] * Math.exp(-0.5 * z * z)) / (sigmas[j] * Math.sqrt(2 * Math.PI));
        r[j] = pv;
        sum += pv;
      }
      if (sum <= 0) {
        for (let j = 0; j < k; j++) r[j] = 1 / k;
        sum = 1;
      }
      for (let j = 0; j < k; j++) r[j] /= sum;
      resp[i] = r;
      newLogL += wNorm[i] * Math.log(sum);
    }
    for (let j = 0; j < k; j++) {
      let rw = 0,
        rx = 0;
      for (let i = 0; i < n; i++) {
        const g = resp[i][j] * wNorm[i];
        rw += g;
        rx += g * xs[i];
      }
      if (rw <= 1e-12) continue;
      const mu = rx / rw;
      let rv = 0;
      for (let i = 0; i < n; i++) {
        const g = resp[i][j] * wNorm[i];
        rv += g * (xs[i] - mu) ** 2;
      }
      mus[j] = mu;
      sigmas[j] = Math.max(Math.sqrt(rv / rw), sigFloor);
      pis[j] = rw;
    }
    const ps = pis.reduce((s, x) => s + x, 0) || 1;
    for (let j = 0; j < k; j++) pis[j] /= ps;
    if (Math.abs(newLogL - logL) < 1e-9) {
      logL = newLogL;
      break;
    }
    logL = newLogL;
  }
  const comps = mus
    .map((mu, j) => ({ mu, sigma: sigmas[j], w: pis[j] }))
    .sort((a, b) => a.mu - b.mu);
  return { comps, logL };
}

// A:1512
export function bic(logL: number, nFull: number, k: number): number {
  return -2 * logL + (3 * k - 1) * Math.log(Math.max(nFull, 2));
}

// A:1514-1556: the side's mixture over its weighted rows. In auto, one bell per peak the KDE
// marked, at most 5 and at most one per 5 rows; with no peak (smoothing Off), the k of lowest BIC.
function fitMixture(
  centers: readonly number[],
  weights: readonly number[],
  a: SideSetting,
  nPk: number,
): Mixture | null {
  if (a.mixture === "none") return null;
  const xs: number[] = [],
    ws: number[] = [];
  for (let i = 0; i < centers.length; i++) {
    const m = weights[i];
    if (m > 0) {
      xs.push(centers[i]);
      ws.push(m);
    }
  }
  if (xs.length < 3) return null;
  let totalW = 0;
  for (const w of ws) totalW += w;
  if (totalW <= 0) return null;
  const nFull = centers.length;
  const tryK = (kk: number) => {
    const f = fitGMM1D(xs, ws, kk);
    if (!f) return null;
    return { comps: f.comps, k: kk, bic: bic(f.logL, nFull, kk) };
  };
  const kCap = Math.max(1, Math.min(5, Math.floor(xs.length / 5)));
  let best: Omit<Mixture, "totalW"> | null;
  if (a.kMode === "auto") {
    if (nPk > 0) {
      const f = tryK(Math.max(1, Math.min(kCap, nPk)));
      best = f && { comps: f.comps, k: f.k, src: "peaks", raw: nPk };
    } else {
      let bk: ReturnType<typeof tryK> = null;
      for (let kk = 1; kk <= kCap; kk++) {
        const f = tryK(kk);
        if (f && (!bk || f.bic < bk.bic)) bk = f;
      }
      best = bk && { comps: bk.comps, k: bk.k, src: "bic", raw: null };
    }
  } else {
    const f = tryK(a.kManual);
    best = f && { comps: f.comps, k: f.k, src: "manual", raw: null };
  }
  if (!best) return null;
  return { ...best, totalW };
}

// A:1675-1746 without the drawing, with A:1514-1556: one side's KDE, peaks and mixture over the
// rows' prices and that side's weights. Null when there are fewer than 3 rows (A:1680) or no
// weight on the side (A:1688).
export function fitSide(
  centers: readonly number[],
  weights: readonly number[],
  s: SideSetting,
): SideCurves | null {
  if (centers.length < 3) return null;
  const range = centers[centers.length - 1] - centers[0];
  const total = d3Sum(weights);
  if (!(total > 0)) return null;
  let sm: number[] | null = null;
  let peaks: EnginePeak[] = [];
  if (s.smoothing !== "none") {
    const h = s.bw * range;
    sm = h > 0 ? weightedKDE(centers, weights, h) : weights.slice();
    peaks = detectPeaks(centers, sm, weights, s.minProm);
  }
  // With smoothing Off there is no peak to count, so the mixture falls back to BIC.
  return { sm, peaks, mix: fitMixture(centers, weights, s, peaks.length) };
}

// A:1557-1560
export function samplePDF(c: GmmComp, xs: readonly number[]): number[] {
  return xs.map((x) => {
    const z = (x - c.mu) / c.sigma;
    return (c.w * Math.exp(-0.5 * z * z)) / (c.sigma * Math.sqrt(2 * Math.PI));
  });
}
