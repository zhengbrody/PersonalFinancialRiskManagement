"""Group analyzed option legs into recognized multi-leg strategies with NET,
**exact** at-expiry economics.

Why this exists: a per-leg view shows a short call's textbook *unbounded* max
loss even when a long call in the same spread caps it — which reads as a huge,
unreal loss. Here we net the legs of one ``(underlying, expiry)`` group over a
shared at-expiry price grid, so a bull call spread reports a single bounded
max-loss (= net debit), max-gain (= strike width − net debit) and its
break-even(s).

Deterministic — no LLM, no network. Consumes the already-priced per-contract
results from :mod:`options_analytics` (so it never re-fetches or re-prices).

The extrema are evaluated at every strike (the kinks of the piecewise-linear
expiry payoff) plus the two mathematical boundaries ``S=0`` and ``S->inf``.
They are deliberately *not* inferred from chart samples: a coarse chart can
miss a narrow butterfly/condor loss pocket and is not a risk calculation.
"""

from __future__ import annotations

from typing import Any, Optional

from .options_analytics import _intrinsic_value

_GRID = 41  # presentation-only chart resolution; never used for risk bounds
_EPS = 1e-9


def build_strategies(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group per-contract analytics into strategies. Stable order by
    underlying then expiry. Single legs pass through as a one-leg 'strategy'.

    Scope: legs are grouped by (underlying, expiry), so detection covers
    same-expiry shapes (verticals, straddles, strangles). Multi-expiry
    strategies (calendar/diagonal spreads) land in separate groups, and 3-4 leg
    shapes include common butterflies and iron condors. The payoff netting
    (exact max-loss/gain, break-evens and Greeks) stays correct for any grouped
    legs — unfamiliar shapes simply receive a generic name. Multi-expiry risk
    is deliberately not collapsed into one expiry payoff because doing so
    would require an unstated volatility/time-path assumption."""
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
    spot = next((leg.get("spot") for leg in legs if leg.get("spot") is not None), None)
    # Per-leg pricing constants, computed ONCE (hoisted out of the 41-point grid
    # loop): (qty, mult, strike, option_type, premium_per_share).
    specs = [
        (
            float(leg.get("quantity") or 0),
            float(leg.get("contract_multiplier") or 100),
            leg.get("strike"),
            str(leg.get("option_type") or "call"),
            _premium_per_share(leg),
        )
        for leg in legs
    ]
    strikes = [float(s) for _, _, s, _, _ in specs if s is not None]
    anchors = strikes + ([float(spot)] if spot else [])

    payoff: list[dict[str, float]] = []
    max_loss: Optional[float] = None
    max_gain: Optional[float] = None
    breakevens: list[float] = []

    priceable = bool(anchors) and all(s is not None and p is not None for _, _, s, _, p in specs)
    if priceable:
        pricing = [(q, m, float(s), ot, float(p)) for q, m, s, ot, p in specs]

        # Expiry P&L is piecewise linear. Its finite extrema can only occur at
        # S=0 or a strike; the slope above the highest strike decides whether
        # either tail is unbounded. This remains exact for arbitrary ratios,
        # multipliers, butterflies, condors and other custom same-expiry books.
        critical = sorted({0.0, *[strike for _, _, strike, _, _ in pricing]})
        critical_pnls = [_group_pnl_at(x, pricing) for x in critical]
        tail_slope = sum(q * m for q, m, _, ot, _ in pricing if ot == "call")
        finite_min, finite_max = min(critical_pnls), max(critical_pnls)
        max_loss = None if tail_slope < -_EPS else round(max(0.0, -finite_min), 2)
        max_gain = None if tail_slope > _EPS else round(max(0.0, finite_max), 2)

        breakevens = _break_evens(critical, critical_pnls, tail_slope)

        # Chart points are presentation only, but always include every exact
        # strike/break-even so the plotted line visibly preserves payoff kinks.
        chart_hi = max(anchors) * 1.5
        chart_grid = {chart_hi * i / (_GRID - 1) for i in range(_GRID)}
        chart_grid.update(critical)
        chart_grid.update(breakevens)
        if spot is not None:
            chart_grid.add(float(spot))
        payoff = [
            {"price": round(x, 2), "pnl": round(_group_pnl_at(x, pricing), 2)}
            for x in sorted(chart_grid)
        ]

    # Prefer actual entry basis. If an imported leg lacks it, use that leg's
    # signed current mark and label the result so the UI never presents a mark-
    # based estimate as an original trade debit/credit. If either is absent,
    # report the basis as unavailable rather than manufacturing $0.
    signed_bases: list[float] = []
    entry_basis_count = 0
    for leg in legs:
        cost_basis = leg.get("cost_basis")
        if cost_basis is not None:
            signed_bases.append(float(cost_basis))
            entry_basis_count += 1
            continue
        mark = leg.get("mark")
        if mark is None:
            signed_bases = []
            break
        qty = float(leg.get("quantity") or 0)
        mult = float(leg.get("contract_multiplier") or 100)
        signed_bases.append(float(mark) * qty * mult)

    net_debit = round(sum(signed_bases), 2) if len(signed_bases) == len(legs) else None
    if net_debit is None:
        premium_basis = "unavailable"
    elif entry_basis_count == len(legs):
        premium_basis = "entry"
    elif entry_basis_count == 0:
        premium_basis = "current_mark"
    else:
        premium_basis = "mixed"
    pnl_vals = [leg.get("unrealized_pnl") for leg in legs if leg.get("unrealized_pnl") is not None]
    net_pnl = round(sum(float(v) for v in pnl_vals), 2) if pnl_vals else None

    net_greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for (qty, mult, _, _, _), leg in zip(specs, legs):
        g = leg.get("greeks")
        if not g:
            continue
        for k in net_greeks:
            net_greeks[k] += float(g.get(k, 0.0)) * qty * mult
    net_greeks = {k: round(v, 4) for k, v in net_greeks.items()}

    return {
        "underlying": underlying,
        "expiry": expiry,
        "name": _detect_strategy(legs),
        "leg_count": len(legs),
        "net_debit": net_debit,  # >0 = net debit paid, <0 = net credit received
        "premium_basis": premium_basis,
        "net_pnl": net_pnl,
        "max_loss": max_loss,  # None = unbounded
        "max_gain": max_gain,  # None = unbounded
        "break_evens": breakevens,
        "net_greeks": net_greeks,
        "payoff": payoff,
        "legs": legs,
    }


def _group_pnl_at(spot: float, pricing: list[tuple[float, float, float, str, float]]) -> float:
    """Combined at-expiry P&L at underlying price ``spot``. ``pricing`` is the
    per-leg (qty, mult, strike, option_type, premium) precomputed once by the
    caller so this hot loop does no per-point parsing."""
    total = 0.0
    for qty, mult, strike, option_type, premium in pricing:
        intrinsic = _intrinsic_value(option_type, spot, strike)
        total += (intrinsic - premium) * qty * mult
    return total


def _break_evens(
    critical: list[float], critical_pnls: list[float], tail_slope: float
) -> list[float]:
    """Exact non-negative roots of the piecewise-linear expiry P&L."""

    roots: list[float] = []
    for i in range(1, len(critical)):
        x0, x1 = critical[i - 1], critical[i]
        y0, y1 = critical_pnls[i - 1], critical_pnls[i]
        if abs(y0) <= _EPS:
            roots.append(x0)
        if y0 * y1 < 0:
            roots.append(x0 - y0 * (x1 - x0) / (y1 - y0))

    x_last, y_last = critical[-1], critical_pnls[-1]
    if abs(y_last) <= _EPS:
        roots.append(x_last)
    elif abs(tail_slope) > _EPS:
        tail_root = x_last - y_last / tail_slope
        if tail_root > x_last + _EPS:
            roots.append(tail_root)

    # Round only after solving, then stable-de-duplicate boundaries shared by
    # adjacent segments.
    return sorted({round(max(0.0, root), 2) for root in roots})


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

        # Vertical spread: same type, opposite sides, different strikes. Unequal
        # contract exposure is a ratio spread and must not inherit a vertical's
        # familiar risk label.
        if ta == tb and sa != sb and ka != kb:
            long_leg = a if sa == "long" else b
            short_leg = b if sa == "long" else a
            k_long = float(long_leg.get("strike") or 0)
            k_short = float(short_leg.get("strike") or 0)
            long_exposure = abs(float(long_leg.get("quantity") or 0)) * float(
                long_leg.get("contract_multiplier") or 100
            )
            short_exposure = abs(float(short_leg.get("quantity") or 0)) * float(
                short_leg.get("contract_multiplier") or 100
            )
            if abs(long_exposure - short_exposure) > _EPS:
                return f"{str(ta).capitalize()} ratio spread"
            if ta == "call":
                return "Bull call spread" if k_long < k_short else "Bear call spread"
            return "Bear put spread" if k_long > k_short else "Bull put spread"

        # Straddle / strangle: one call + one put, same side.
        if {ta, tb} == {"call", "put"} and sa == sb:
            kind = "straddle" if ka == kb else "strangle"
            return f"{'Long' if sa == 'long' else 'Short'} {kind}"

    # Common 1:-2:1 same-type butterfly. The exact payoff engine above also
    # handles broken-wing and ratio variants; those retain a generic name.
    if len(legs) == 3:
        ordered = sorted(legs, key=lambda leg: float(leg.get("strike") or 0))
        types = {str(leg.get("option_type") or "") for leg in ordered}
        wing_exposures = [
            float(leg.get("quantity") or 0) * float(leg.get("contract_multiplier") or 100)
            for leg in ordered
        ]
        if (
            len(types) == 1
            and len({float(leg.get("strike") or 0) for leg in ordered}) == 3
            and abs(wing_exposures[0] - wing_exposures[2]) <= _EPS
            and abs(wing_exposures[1] + 2 * wing_exposures[0]) <= _EPS
        ):
            direction = "Long" if wing_exposures[0] > 0 else "Short"
            return f"{direction} {next(iter(types))} butterfly"

    if len(legs) == 4:
        calls = [leg for leg in legs if leg.get("option_type") == "call"]
        puts = [leg for leg in legs if leg.get("option_type") == "put"]
        if len(calls) == 2 and len(puts) == 2:
            call_sides = {side(leg) for leg in calls}
            put_sides = {side(leg) for leg in puts}
            equal_exposures = {
                abs(float(leg.get("quantity") or 0)) * float(leg.get("contract_multiplier") or 100)
                for leg in legs
            }
            if call_sides == put_sides == {"long", "short"} and len(equal_exposures) == 1:
                short_call = next(leg for leg in calls if side(leg) == "short")
                short_put = next(leg for leg in puts if side(leg) == "short")
                long_call = next(leg for leg in calls if side(leg) == "long")
                long_put = next(leg for leg in puts if side(leg) == "long")
                short_center = (
                    abs(float(short_call.get("strike") or 0) - float(short_put.get("strike") or 0))
                    <= _EPS
                )
                long_center = (
                    abs(float(long_call.get("strike") or 0) - float(long_put.get("strike") or 0))
                    <= _EPS
                )
                normal_wings = (
                    float(long_put.get("strike") or 0)
                    < float(short_put.get("strike") or 0)
                    <= float(short_call.get("strike") or 0)
                    < float(long_call.get("strike") or 0)
                )
                reverse = long_center or not normal_wings
                prefix = "Reverse " if reverse else ""
                shape = "iron butterfly" if short_center or long_center else "iron condor"
                return f"{prefix}{shape}".capitalize()

    return f"Net option position ({len(legs)} legs)"
