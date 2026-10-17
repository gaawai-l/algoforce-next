"""BTC cost-basis clusters from URPD snapshots, following the rules of the original page (v1).

Every sum is an explicit loop in row order: since Python 3.12 the builtin `sum()` compensates for
float rounding, which the original's JavaScript does not.
"""

import math
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model
from ..rules import Rule
from .brk import Urpd
from .levels import LineName, ModelLine

Bucket = Literal[200, 500, 1000]
Cohort = Literal["sth", "lth"]

BUCKETS: tuple[Bucket, ...] = (200, 500, 1000)
COHORTS = ("all", "sth", "lth")
# Rows priced below this are left out of the domain and of the totals.
MIN_PRICE = 1000.0
# A row is live when the whole supply holds more than this many BTC there. The domain runs from
# the first live row to the last, with PAD rows either side.
LIVE_SUPPLY = 0.5
PAD = 2
# The KDE bandwidth is this share of the domain's price span; terms further than KERNEL_CUT
# bandwidths away are skipped.
BANDWIDTH = 0.02
KERNEL_CUT = 5.0
# A peak is kept when its prominence is at least this share of the highest density.
MIN_PROMINENCE = 0.05
MAX_COMPONENTS = 5
EM_ITERATIONS = 120
EM_TOLERANCE = 1e-9
# Bands are SLICE wide and start from a multiple of 2 * SLICE.
SLICE = 2000.0
# Occupied bands listed on each side of spot.
NEAREST = 4
# Days before D whose snapshots add their floors to the grid.
PAST_DAYS = (1, 7, 30, 90)
# The page's order of the model lines; within a band it decides between equal prices.
LINE_ORDER: tuple[LineName, ...] = ("short_term", "true_mean", "average", "median", "long_term")


class Peak(Model):
    price: float
    width: float
    btc: float
    share: float
    strength: float


class GmmComponent(Model):
    mu: float
    sigma: float
    share: float
    btc: float


class CohortClusters(Model):
    cohort: Cohort
    total: float
    in_profit: float | None
    peaks: list[Peak]
    components: list[GmmComponent]


class Candidate(Model):
    """A price level counted in a band: a rounded model line, or a component's mu, mu - sigma
    or mu + sigma."""

    kind: Literal["line", "component"]
    price: float
    line: LineName | None
    cohort: Cohort | None
    # From 1, in the order of the cohort's components.
    index: int | None
    edge: Literal["low", "mid", "high"] | None


class Band(Model):
    low: float
    high: float
    candidates: list[Candidate]


class BucketCostBasis(Model):
    bucket: Bucket
    domain_low: float
    domain_high: float
    spot: float
    sth: CohortClusters
    lth: CohortClusters
    # Both nearest to spot first.
    above: list[Band]
    below: list[Band]
    resistance: list[float]
    support: list[float]


class StoredCostBasis(Model):
    urpd_date: date
    lines_as_of: date
    snapshot_at: AwareDatetime
    buckets: list[BucketCostBasis]
    reasons: list[str]
    # The rules it was derived under; payloads stored before rules existed read as none.
    rules: list[Rule] = []
    # The older of the levels' newest complete day and D, the newest snapshot, whatever the rules:
    # how fresh the result is follows it. None without D, and in payloads stored before it existed.
    latest_day: date | None = None


def _total(values: Iterable[float]) -> float:
    acc = 0.0
    for value in values:
        acc += value
    return acc


def _cents(value: float) -> float:
    """JavaScript `+value.toFixed(2)`: the exact binary value rounded half up."""
    return float(Decimal(value).quantize(Decimal("0.01"), ROUND_HALF_UP))


def weighted_kde(centers: Sequence[float], weights: Sequence[float], h: float) -> list[float]:
    """Gaussian KDE at each center, as a density over price. `centers` ascend."""
    total = _total(weights)
    if total <= 0 or h <= 0:
        return [0.0] * len(centers)
    norm = 1 / (h * math.sqrt(2 * math.pi))
    out = []
    for x in centers:
        low, high = x - KERNEL_CUT * h, x + KERNEL_CUT * h
        acc = 0.0
        for center, weight in zip(centers, weights, strict=True):
            if low <= center <= high:
                z = (x - center) / h
                acc += weight * math.exp(-0.5 * z * z)
        out.append(acc * norm / total)
    return out


def _prominence(y: Sequence[float], p: int) -> float:
    height = y[p]
    left = height
    for q in range(p - 1, -1, -1):
        if y[q] > height:
            break
        left = min(left, y[q])
    right = height
    for q in range(p + 1, len(y)):
        if y[q] > height:
            break
        right = min(right, y[q])
    return height - max(left, right)


def _fwhm(y: Sequence[float], x: Sequence[float], p: int) -> float:
    """Full width at half height, interpolated between neighbouring rows; a side that never drops
    to half ends at the peak itself."""
    half = y[p] * 0.5
    left = x[p]
    for q in range(p - 1, -1, -1):
        if y[q] <= half:
            dy = y[q + 1] - y[q]
            t = 0 if dy == 0 else (half - y[q]) / dy
            left = x[q] + t * (x[q + 1] - x[q])
            break
    right = x[p]
    for q in range(p + 1, len(y)):
        if y[q] <= half:
            dy = y[q] - y[q - 1]
            t = 0 if dy == 0 else (half - y[q - 1]) / dy
            right = x[q - 1] + t * (x[q] - x[q - 1])
            break
    return max(right - left, 0)


def find_peaks(centers: Sequence[float], weights: Sequence[float]) -> list[Peak]:
    """Prominent local maxima of the KDE, in ascending price. `centers` ascend."""
    if len(centers) < 3:
        return []
    y = weighted_kde(centers, weights, BANDWIDTH * (centers[-1] - centers[0]))
    top = max(y)
    if not top > 0:
        return []
    total = _total(weights)
    peaks = []
    for p in range(1, len(y) - 1):
        if not (y[p] > y[p - 1] and y[p] >= y[p + 1]):
            continue
        prominence = _prominence(y, p)
        if prominence < MIN_PROMINENCE * top:
            continue
        width = _fwhm(y, centers, p)
        low, high = centers[p] - width / 2, centers[p] + width / 2
        btc = _total(w for c, w in zip(centers, weights, strict=True) if low <= c <= high)
        peaks.append(
            Peak(
                price=centers[p],
                width=width,
                btc=btc,
                share=btc / total,
                strength=prominence / top,
            )
        )
    return peaks


def fit_gmm(
    xs: Sequence[float], ws: Sequence[float], k: int
) -> tuple[list[GmmComponent], float] | None:
    """Weighted 1-D Gaussian mixture by EM: components by ascending mu, and the last log
    likelihood (per unit weight). None when there are fewer rows than k or no weight."""
    n = len(xs)
    if n < k or k < 1:
        return None
    total = _total(ws)
    if total <= 0:
        return None
    ordered = sorted(zip(xs, ws, strict=True), key=lambda row: row[0])
    quantiles = []
    acc = 0.0
    for _, w in ordered:
        acc += w
        quantiles.append(acc / total)
    mus = []
    for j in range(k):
        t = (j + 0.5) / k
        at = next((i for i, q in enumerate(quantiles) if q >= t), n - 1)
        mus.append(ordered[at][0])
    for j in range(1, k):
        if mus[j] <= mus[j - 1]:
            mus[j] = mus[j - 1] + 1e-3
    mean = _total(x * w for x, w in zip(xs, ws, strict=True)) / total
    variance = 0.0
    for x, w in zip(xs, ws, strict=True):
        d = x - mean
        variance += w * (d * d)
    variance /= total
    sigma0 = math.sqrt(variance) / max(1, k * 0.6)
    sigmas = [max(sigma0, 1e-6)] * k
    pis = [1 / k] * k
    shares = [w / total for w in ws]
    floor = max(sigma0 * 1e-3, 1e-9)
    root = math.sqrt(2 * math.pi)
    log_l = -math.inf
    for _ in range(EM_ITERATIONS):
        resp: list[list[float]] = []
        new_log_l = 0.0
        for x, share in zip(xs, shares, strict=True):
            densities = []
            density = 0.0
            for j in range(k):
                z = (x - mus[j]) / sigmas[j]
                value = pis[j] * math.exp(-0.5 * z * z) / (sigmas[j] * root)
                densities.append(value)
                density += value
            if density <= 0:
                # Underflow far from every component: equal responsibilities, log 1 = 0.
                densities = [1 / k] * k
                density = 1.0
            resp.append([value / density for value in densities])
            new_log_l += share * math.log(density)
        for j in range(k):
            rw = 0.0
            rx = 0.0
            for i in range(n):
                g = resp[i][j] * shares[i]
                rw += g
                rx += g * xs[i]
            if rw <= 1e-12:
                continue
            mu = rx / rw
            rv = 0.0
            for i in range(n):
                g = resp[i][j] * shares[i]
                d = xs[i] - mu
                rv += g * (d * d)
            mus[j] = mu
            sigmas[j] = max(math.sqrt(rv / rw), floor)
            pis[j] = rw
        norm = _total(pis) or 1.0
        pis = [pi / norm for pi in pis]
        if abs(new_log_l - log_l) < EM_TOLERANCE:
            log_l = new_log_l
            break
        log_l = new_log_l
    components = sorted(zip(mus, sigmas, pis, strict=True), key=lambda c: c[0])
    return [
        GmmComponent(mu=mu, sigma=sigma, share=pi, btc=pi * total) for mu, sigma, pi in components
    ], log_l


def select_components(
    xs: Sequence[float], ws: Sequence[float], peaks: int, rows: int
) -> list[GmmComponent]:
    """The mixture over the rows with weight: one component per KDE peak, up to a cap set by the
    row count; without peaks, the k with the lowest BIC over `rows` domain rows."""
    positive = [(x, w) for x, w in zip(xs, ws, strict=True) if w > 0]
    if len(positive) < 3:
        return []
    px = [x for x, _ in positive]
    pw = [w for _, w in positive]
    cap = max(1, min(MAX_COMPONENTS, len(positive) // 5))
    if peaks > 0:
        fit = fit_gmm(px, pw, max(1, min(cap, peaks)))
        return fit[0] if fit is not None else []
    best: list[GmmComponent] | None = None
    best_bic = math.inf
    for k in range(1, cap + 1):
        fit = fit_gmm(px, pw, k)
        if fit is None:
            continue
        bic = -2 * fit[1] + (3 * k - 1) * math.log(max(rows, 2))
        if best is None or bic < best_bic:
            best, best_bic = fit[0], bic
    return best or []


def _clusters(
    cohort: Cohort,
    prices: Sequence[float],
    column: Sequence[float],
    domain: slice,
    spot: float,
) -> CohortClusters:
    """Totals over every row from MIN_PRICE; peaks and components over the domain rows."""
    total = _total(column)
    in_profit = _total(v for price, v in zip(prices, column, strict=True) if price <= spot)
    centers = prices[domain]
    weights = column[domain]
    peaks = find_peaks(centers, weights)
    return CohortClusters(
        cohort=cohort,
        total=total,
        in_profit=in_profit / total if total > 0 else None,
        peaks=peaks,
        components=select_components(centers, weights, len(peaks), len(centers)),
    )


def cost_basis(
    today: dict[str, Urpd], past: Sequence[Urpd], bucket: Bucket, lines: Sequence[ModelLine]
) -> BucketCostBasis | None:
    """Clusters and the nearest bands for one bucket width; None when no row reaches MIN_PRICE.

    `today` holds D's all, sth and lth snapshots. `past` only adds its floors to the grid.
    """
    missing = [cohort for cohort in COHORTS if cohort not in today]
    if missing:
        raise ValueError(f"missing URPD cohorts: {', '.join(missing)}")
    snapshots = [today[cohort] for cohort in COHORTS]
    aggregation = f"lin{bucket}"
    for urpd in [*snapshots, *past]:
        if urpd.aggregation != aggregation:
            raise ValueError(f"expected {aggregation} URPD, got {urpd.aggregation}")
    if len({urpd.date for urpd in snapshots}) != 1:
        raise ValueError("today's URPD snapshots are for different dates")
    if sorted(line.name for line in lines) != sorted(LINE_ORDER):
        raise ValueError("cost basis needs exactly one of each model line")

    step = float(bucket)
    floors = sorted({b.price_floor for urpd in [*snapshots, *past] for b in urpd.buckets})
    floors = [floor for floor in floors if floor + step / 2 >= MIN_PRICE]
    if not floors:
        return None
    prices = [floor + step / 2 for floor in floors]
    values: dict[str, list[float]] = {}
    for cohort in COHORTS:
        supply = {b.price_floor: b.supply for b in today[cohort].buckets}
        values[cohort] = [_cents(supply.get(floor, 0.0)) for floor in floors]

    live = values["all"]
    i, j = 0, len(floors) - 1
    while i < j and not live[i] > LIVE_SUPPLY:
        i += 1
    while j > i and not live[j] > LIVE_SUPPLY:
        j -= 1
    domain = slice(max(0, i - PAD), min(len(floors), j + PAD + 1))
    low = prices[domain][0] - step / 2
    high = prices[domain][-1] + step / 2
    spot = today["all"].close
    sth = _clusters("sth", prices, values["sth"], domain, spot)
    lth = _clusters("lth", prices, values["lth"], domain, spot)

    candidates: list[Candidate] = []
    by_name = {line.name: line.price for line in lines}
    for name in LINE_ORDER:
        price = float(math.floor(by_name[name] + 0.5))
        # Redundant with the slices clipped to the domain; kept for fidelity with the page.
        if low <= price <= high:
            candidates.append(
                Candidate(kind="line", price=price, line=name, cohort=None, index=None, edge=None)
            )
    for clusters in (sth, lth):
        for index, c in enumerate(clusters.components, 1):
            edges: tuple[tuple[Literal["low", "mid", "high"], float], ...] = (
                ("low", c.mu - c.sigma),
                ("mid", c.mu),
                ("high", c.mu + c.sigma),
            )
            for edge, price in edges:
                candidates.append(
                    Candidate(
                        kind="component",
                        price=price,
                        line=None,
                        cohort=clusters.cohort,
                        index=index,
                        edge=edge,
                    )
                )

    bands: list[Band] = []
    start = math.floor(low / (2 * SLICE)) * (2 * SLICE)
    while start < high:
        a, b = max(low, start), min(high, start + SLICE)
        if b > a:
            inside = [c for c in candidates if a <= c.price < b]
            bands.append(Band(low=a, high=b, candidates=sorted(inside, key=lambda c: c.price)))
        start += SLICE
    home = next((band for band in bands if band.low <= spot < band.high), None)
    occupied = [band for band in bands if band.candidates]
    above = sorted(
        (band for band in occupied if band.low >= (home.high if home else spot)),
        key=lambda band: band.low,
    )[:NEAREST]
    below = sorted(
        (band for band in occupied if band.high <= (home.low if home else spot)),
        key=lambda band: band.low,
        reverse=True,
    )[:NEAREST]
    return BucketCostBasis(
        bucket=bucket,
        domain_low=low,
        domain_high=high,
        spot=spot,
        sth=sth,
        lth=lth,
        above=above,
        below=below,
        resistance=[band.high for band in above],
        support=[band.low for band in below],
    )
