"""Group analyzed option legs into recognized multi-leg strategies with NET,
**bounded** economics.

Why this exists: a per-leg view shows a short call's textbook *unbounded* max
loss even when a long call in the same spread caps it — which reads as a huge,
unreal loss. Here we net the legs of one ``(underlying, expiry)`` group over a
shared at-expiry price grid, so a bull call spread reports a single bounded
max-loss (= net debit), max-gain (= strike width − net debit) and its
break-even(s).

Deterministic — no LLM, no network. Consumes the already-priced per-contract
results from :mod:`options_analytics` (so it never re-fetches or re-prices).
"""

from __future__ import annotations

from typing import Any, Optional

from .options_analytics import _intrinsic_value

_GRID = 41  # at-expiry payoff resolution per strategy


def build_strategies(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group per-contract analytics into strategies. Stable order by
    underlying then expiry. Single legs pass through as a one-leg 'strategy'."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in results:
        underlying = str(r.get("underlying") or "").upper()
        expiry = str(r.get("expiry") or "")
        groups.setdefault((underlying, expiry), []).append(r)

    out = [_build_group(u, e, legs) for (u, e), legs in groups.items()]
    out.sort(key=lambda g: (g["underlying"], g["expiry"]))
    return out


def _premium_per_share(leg: dict[str, Any]) -> Optional[float]:
    """Per-share basis used for the at-expiry P&L (cost basis if known, else the
    current mark — mirrors analyze_contract's `premium_basis`)."""
    qty = float(leg.get("quantity") or 0)
    mult = float(leg.get("contract_multiplier") or 100)
    cb = leg.get("cost_basis")
    if cb is not None and qty and mult:
        return float(cb) / (qty * mult)
    return leg.get("mark")


def _build_group(underlying: str, expiry: str, legs: list[dict[str, Any]]) -> dict[str, Any]:
    strikes = [float(leg["strike"]) for leg in legs if leg.get("strike") is not None]
    spot = next((leg.get("spot") for leg in legs if leg.get("spot") is not None), None)
    anchors = strikes + ([float(spot)] if spot else [])

    payoff: list[dict[str, float]] = []
    max_loss: Optional[float] = None
    max_gain: Optional[float] = None
    breakevens: list[float] = []

    priceable = bool(anchors) and all(
        _premium_per_share(leg) is not None and leg.get("strike") is not None for leg in legs
    )
    if priceable:
        lo = max(0.01, min(anchors) * 0.5)
        hi = max(anchors) * 1.5
        grid = [lo + (hi - lo) * i / (_GRID - 1) for i in range(_GRID)]
        pnls = [_group_pnl_at(s, legs) for s in grid]
        payoff = [{"price": round(s, 2), "pnl": round(p, 2)} for s, p in zip(grid, pnls)]

        # The UP side can be unbounded from net call exposure; the DOWN side
        # (S→0) is always finite. Net call quantity decides the unbounded side.
        net_call_qty = sum(
            float(leg.get("quantity") or 0) for leg in legs if leg.get("option_type") == "call"
        )
        b_min, b_max = min(pnls), max(pnls)
        if net_call_qty > 0:  # net long calls → upside gain unbounded
            max_gain = None
            max_loss = round(-b_min, 2) if b_min < 0 else 0.0
        elif net_call_qty < 0:  # net short calls → upside loss unbounded
            max_loss = None
            max_gain = round(b_max, 2) if b_max > 0 else 0.0
        else:  # fully bounded (e.g. a vertical spread)
            max_loss = round(-b_min, 2) if b_min < 0 else 0.0
            max_gain = round(b_max, 2) if b_max > 0 else 0.0

        for i in range(1, len(grid)):
            a, b = pnls[i - 1], pnls[i]
            if a == 0.0:
                breakevens.append(round(grid[i - 1], 2))
            elif (a < 0 < b) or (a > 0 > b):
                be = grid[i - 1] + (0.0 - a) / (b - a) * (grid[i] - grid[i - 1])
                breakevens.append(round(be, 2))

    net_debit = round(sum(float(leg.get("cost_basis") or 0.0) for leg in legs), 2)
    pnl_vals = [leg.get("unrealized_pnl") for leg in legs if leg.get("unrealized_pnl") is not None]
    net_pnl = round(sum(float(v) for v in pnl_vals), 2) if pnl_vals else None

    net_greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        g = leg.get("greeks")
        if not g:
            continue
        qty = float(leg.get("quantity") or 0)
        mult = float(leg.get("contract_multiplier") or 100)
        for k in net_greeks:
            net_greeks[k] += float(g.get(k, 0.0)) * qty * mult
    net_greeks = {k: round(v, 4) for k, v in net_greeks.items()}

    return {
        "underlying": underlying,
        "expiry": expiry,
        "name": _detect_strategy(legs),
        "leg_count": len(legs),
        "net_debit": net_debit,  # >0 = net debit paid, <0 = net credit received
        "net_pnl": net_pnl,
        "max_loss": max_loss,  # None = unbounded
        "max_gain": max_gain,  # None = unbounded
        "break_evens": breakevens,
        "net_greeks": net_greeks,
        "payoff": payoff,
        "legs": legs,
    }


def _group_pnl_at(spot: float, legs: list[dict[str, Any]]) -> float:
    """Combined at-expiry P&L of the group at underlying price ``spot``."""
    total = 0.0
    for leg in legs:
        qty = float(leg.get("quantity") or 0)
        mult = float(leg.get("contract_multiplier") or 100)
        strike = float(leg.get("strike") or 0.0)
        option_type = str(leg.get("option_type") or "call")
        premium = _premium_per_share(leg) or 0.0
        intrinsic = _intrinsic_value(option_type, spot, strike)
        total += (intrinsic - premium) * qty * mult
    return total


def _detect_strategy(legs: list[dict[str, Any]]) -> str:
    """Deterministic strategy name from leg shape. Covers single legs, the four
    vertical spreads, straddles/strangles; anything else → 'Custom (N legs)'."""

    def side(leg: dict[str, Any]) -> str:
        return "long" if float(leg.get("quantity") or 0) >= 0 else "short"

    if len(legs) == 1:
        leg = legs[0]
        return f"{side(leg).capitalize()} {leg.get('option_type') or 'option'}"

    if len(legs) == 2:
        a, b = legs
        ta, tb = a.get("option_type"), b.get("option_type")
        ka, kb = float(a.get("strike") or 0), float(b.get("strike") or 0)
        sa, sb = side(a), side(b)

        # Vertical spread: same type, opposite sides, different strikes.
        if ta == tb and sa != sb and ka != kb:
            long_leg = a if sa == "long" else b
            short_leg = b if sa == "long" else a
            k_long = float(long_leg.get("strike") or 0)
            k_short = float(short_leg.get("strike") or 0)
            if ta == "call":
                return "Bull call spread" if k_long < k_short else "Bear call spread"
            return "Bear put spread" if k_long > k_short else "Bull put spread"

        # Straddle / strangle: one call + one put, same side.
        if {ta, tb} == {"call", "put"} and sa == sb:
            kind = "straddle" if ka == kb else "strangle"
            return f"{'Long' if sa == 'long' else 'Short'} {kind}"

    return f"Custom ({len(legs)} legs)"
