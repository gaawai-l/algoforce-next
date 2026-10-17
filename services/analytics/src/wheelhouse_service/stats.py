"""Statistics shared by the derived views."""

import math
from collections.abc import Sequence


def quantile_r7(sorted_values: Sequence[float], q: float) -> float | None:
    """The R-7 quantile of ascending values: linear between the neighbours at (n - 1) * q."""
    n = len(sorted_values)
    if n == 0:
        return None
    if q <= 0 or n < 2:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    position = (n - 1) * q
    below = math.floor(position)
    return sorted_values[below] + (sorted_values[below + 1] - sorted_values[below]) * (
        position - below
    )
