"""Canonical option-position direction helpers.

Persisted portfolios have existed across several import/form generations. Some
store a positive contract count plus ``option_side=short``; older/imported rows
may instead store a negative count, use broker verbs such as ``sell``/``buy``,
or contain both. All Python option consumers must resolve those shapes
identically.

The key rule is that an explicit side controls *direction* and the absolute
share count controls *size*. This prevents the dangerous double-negation where
``shares=-1`` plus ``option_side=short`` was interpreted as a long contract.
"""

from __future__ import annotations

import math
from typing import Any, Optional

SHORT_ALIASES = frozenset({"short", "sell", "sold", "write", "written", "s"})
LONG_ALIASES = frozenset({"long", "buy", "bought", "purchase", "purchased", "l"})


def normalized_option_side(raw_side: Any, raw_quantity: Any) -> Optional[str]:
    """Return ``long``/``short`` or ``None`` when direction is unknowable.

    A negative legacy quantity is sufficient evidence of a short position when
    no recognized side is present. A positive quantity without a side remains
    unconfirmed (callers may provisionally treat it as long, but should surface
    that assumption to the user).
    """

    side = str(raw_side or "").strip().lower()
    if side in SHORT_ALIASES:
        return "short"
    if side in LONG_ALIASES:
        return "long"
    quantity = _finite(raw_quantity)
    if quantity is not None and quantity < 0:
        return "short"
    return None


def signed_option_quantity(raw_quantity: Any, raw_side: Any = None) -> float:
    """Canonical signed contract count (long positive, short negative)."""

    quantity = _finite(raw_quantity)
    if quantity is None:
        return 0.0
    side = normalized_option_side(raw_side, quantity)
    if side == "short":
        return -abs(quantity)
    if side == "long":
        return abs(quantity)
    # No recognized side: preserve a legacy signed quantity. Positive is the
    # least-surprising provisional direction, while the UI flags it unconfirmed.
    return quantity


def option_side_is_confirmed(raw_side: Any, raw_quantity: Any) -> bool:
    """Whether the persisted record contains unambiguous direction evidence."""

    side = str(raw_side or "").strip().lower()
    if side in SHORT_ALIASES or side in LONG_ALIASES:
        return True
    quantity = _finite(raw_quantity)
    return quantity is not None and quantity < 0


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
