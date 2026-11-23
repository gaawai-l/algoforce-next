"""On-chain Lens: Volatility Spike Watch (supply density + young-coin compression).

Follows QFI Labs' `onchain-volatility-spike-watch` v1 (`compute.py` v3) specification:
- Young-coin realized prices (<1M from the 4 bands under 1 month; <2M from the 5 bands under 2M):
  sum(realized_cap) / sum(supply), positive when every band is present and the supply sum > 0.
- Width (compression): `100 * ln(max(price, rp_1m, rp_2m) / min(price, rp_1m, rp_2m))`.
- Density rank (`pd`): share of rows in `(t - W, t]` with `density <= density[t]`.
- Narrowness rank (`pn`): share of rows in `(t - W, t]` with `width >= width[t]`.
- Combination: `raw = (pd + pn) / 2`.
- Answer (`strength`): empirical rank of `raw` in `(t - W, t]` with `<=`.
- Category: `extreme` (>= 0.95), `warning` (>= 0.75), `quiet` (< 0.25), else `normal`.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime

from ..market import Model
from ..stats import quantile_r7

VolatilityHorizon = Literal["intraday", "intraweek", "intramonth", "intracycle", "cycle-1y"]
VolatilityCategory = Literal["extreme", "warning", "normal", "quiet"]

PRICE = "price_close"
SUPPLY_DENSITY = "supply_density"
YOUNG_1M_BANDS: tuple[str, ...] = (
    "utxos_under_1h_old",
    "utxos_1h_to_1d_old",
    "utxos_1d_to_1w_old",
    "utxos_1w_to_1m_old",
)
YOUNG_2M_BANDS: tuple[str, ...] = (
    *YOUNG_1M_BANDS,
    "utxos_1m_to_2m_old",
)
VOLATILITY_SERIES: tuple[str, ...] = (
    PRICE,
    SUPPLY_DENSITY,
    *(f"{band}_realized_cap" for band in YOUNG_2M_BANDS),
    *(f"{band}_supply" for band in YOUNG_2M_BANDS),
)

HORIZON_WINDOWS: dict[VolatilityHorizon, tuple[int, bool]] = {
    "intraday": (7, False),
    "intraweek": (30, False),
    "intramonth": (90, False),
    "intracycle": (1460, False),
    "cycle-1y": (365, True),
}


class VolatilityComponents(Model):
    density: float
    narrowness: float


class VolatilityLevels(Model):
    p95: float | None
    p75: float | None
    n: int


class VolatilityHorizonAnswer(Model):
    horizon: VolatilityHorizon
    as_of: AwareDatetime
    strength: float
    raw: float
    category: VolatilityCategory
    components: VolatilityComponents
    density_levels: VolatilityLevels
    width_levels: VolatilityLevels
    context_only: bool = False
    supported: bool = False


class VolatilitySpikeWatch(Model):
    as_of: AwareDatetime
    horizons: list[VolatilityHorizonAnswer]


def volatility_category(strength: float) -> VolatilityCategory:
    if strength >= 0.95:
        return "extreme"
    if strength >= 0.75:
        return "warning"
    if strength < 0.25:
        return "quiet"
    return "normal"


def _win_rank(
    rows: Sequence[tuple[datetime, float]], window: timedelta, *, ge: bool = False
) -> dict[datetime, float]:
    """Empirical rank over rows in `(t - window, t]`; omitted when `t - window < first_row.t`."""
    if not rows:
        return {}
    out: dict[datetime, float] = {}
    t0 = rows[0][0]
    j = 0
    for i, (t, val) in enumerate(rows):
        if t - window < t0:
            continue
        while rows[j][0] <= t - window:
            j += 1
        win = [v for _, v in rows[j : i + 1]]
        cnt = sum(1 for v in win if (v >= val if ge else v <= val))
        out[t] = cnt / len(win)
    return out


def _value_levels(rows: Sequence[tuple[datetime, float]], window: timedelta) -> VolatilityLevels:
    if not rows:
        return VolatilityLevels(p95=None, p75=None, n=0)
    last_t = rows[-1][0]
    vals = sorted(v for t, v in rows if last_t - window < t <= last_t)
    return VolatilityLevels(p95=quantile_r7(vals, 0.95), p75=quantile_r7(vals, 0.75), n=len(vals))


def compute_volatility_horizon(
    horizon: VolatilityHorizon,
    rows: Mapping[str, Sequence[tuple[datetime, float | None]]],
    *,
    closed_before: datetime | None = None,
) -> VolatilityHorizonAnswer | None:
    """Compute one horizon's Volatility Spike Watch answer from aligned BRK series."""
    win_days, context_only = HORIZON_WINDOWS[horizon]
    window = timedelta(days=win_days)
    series: dict[str, dict[datetime, float | None]] = {
        name: {
            at: val
            for at, val in rows.get(name, ())
            if closed_before is None or at <= closed_before
        }
        for name in VOLATILITY_SERIES
    }
    stamps = sorted({at for s in series.values() for at in s})
    if not stamps:
        return None

    sd_rows: list[tuple[datetime, float]] = []
    cw_rows: list[tuple[datetime, float]] = []
    for at in stamps:
        px = series[PRICE].get(at)
        sd = series[SUPPLY_DENSITY].get(at)
        if px is not None and px > 0 and sd is not None and sd > 0:
            sd_rows.append((at, sd))
        if px is None or px <= 0:
            continue
        caps = [series[f"{b}_realized_cap"].get(at) for b in YOUNG_2M_BANDS]
        sups = [series[f"{b}_supply"].get(at) for b in YOUNG_2M_BANDS]
        if any(c is None for c in caps) or any(s is None for s in sups):
            continue
        c_vals = [float(c) for c in caps if c is not None]
        s_vals = [float(s) for s in sups if s is not None]
        sup1 = sum(s_vals[:4])
        sup2 = sum(s_vals[:5])
        if sup1 <= 0 or sup2 <= 0:
            continue
        rp1 = sum(c_vals[:4]) / sup1
        rp2 = sum(c_vals[:5]) / sup2
        if rp1 <= 0 or rp2 <= 0:
            continue
        hi = max(px, rp1, rp2)
        lo = min(px, rp1, rp2)
        width = 100.0 * math.log(hi / lo)
        cw_rows.append((at, width))

    if not sd_rows or not cw_rows:
        return None
    pd_map = _win_rank(sd_rows, window, ge=False)
    pn_map = _win_rank(cw_rows, window, ge=True)
    raw_rows = [
        (at, (pd_map[at] + pn_map[at]) / 2.0) for at, _ in sd_rows if at in pd_map and at in pn_map
    ]
    if not raw_rows:
        return None
    str_map = _win_rank(raw_rows, window, ge=False)
    answered = [(at, raw_val, str_map[at]) for at, raw_val in raw_rows if at in str_map]
    if not answered:
        return None
    last_t, last_raw, last_str = answered[-1]
    return VolatilityHorizonAnswer(
        horizon=horizon,
        as_of=last_t,
        strength=last_str,
        raw=last_raw,
        category=volatility_category(last_str),
        components=VolatilityComponents(
            density=pd_map[last_t],
            narrowness=pn_map[last_t],
        ),
        density_levels=_value_levels(sd_rows, window),
        width_levels=_value_levels(cw_rows, window),
        context_only=context_only,
        supported=False,
    )
