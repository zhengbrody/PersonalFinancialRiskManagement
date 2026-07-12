"""Historical-percentile engine — rank a metric's CURRENT value against the
user's OWN snapshot history.

Pure functions over the ``get_snapshot_history`` series (no I/O). The point is
context: "your volatility is higher than 90% of your past readings" is far more
actionable than a bare number. Returns ``None`` until enough history has accrued
so a first-week user never sees a misleading 50th-percentile from two points.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

# Need at least this many prior observations for a percentile to mean anything.
MIN_HISTORY = 5


def _finite_values(series: Iterable[object]) -> list[float]:
    out: list[float] = []
    for v in series:
        try:
            x = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            out.append(x)
    return out


def percentile_rank(
    series: Iterable[object], value: Optional[float], *, min_history: int = MIN_HISTORY
) -> tuple[Optional[float], int]:
    """Fraction of the historical series at-or-below ``value`` (0..1), plus the
    number of finite observations behind it.

    - ``value`` None / non-finite → ``(None, n)``.
    - fewer than ``min_history`` finite points → ``(None, n)`` (not enough to rank).
    Uses the standard "≤" empirical CDF (ties count toward the rank)."""
    xs = _finite_values(series)
    n = len(xs)
    if value is None or not math.isfinite(value) or n < max(1, min_history):
        return None, n
    at_or_below = sum(1 for x in xs if x <= value)
    return at_or_below / n, n
