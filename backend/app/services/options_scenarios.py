"""Deterministic option stress grid — full Black-Scholes reprice under a
3-axis shock: underlying price × implied-vol × time decay.

This is the institutional difference from the delta overlay in the equity risk
report: each contract is **repriced** (not delta-approximated), so gamma
(convexity), vega (IV crush/expansion), and theta (time decay) all show up. Pure
math over the per-contract analytics already computed by
``options_analytics.analyze_contracts`` — no network, fully unit-tested.

For each cell (u, v, h): S' = spot·(1+u), σ' = max(ε, iv+v), T' = max(0, T−h/yr);
contract P&L = (bs_price(S',K,T',r,σ') − current_mark) × contracts × multiplier.
A short position carries a negative ``quantity`` so its P&L sign flips naturally.
"""

from __future__ import annotations

from typing import Any, Optional

from libs.mindmarket_core.black_scholes import bs_price

_YEAR_DAYS = 365.25
_MIN_VOL = 0.01

# Default shock axes (the plan's institutional stress set).
DEFAULT_UNDERLYING_SHOCKS = [-0.30, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20, 0.30]
DEFAULT_IV_SHOCKS = [-0.20, -0.10, 0.0, 0.10, 0.20]  # vol points (decimal)
DEFAULT_HORIZONS: list[Any] = [0, 7, 30, "expiry"]  # days forward; "expiry" → T'=0


def _repriceable(r: dict[str, Any]) -> bool:
    return (
        r.get("greeks") is not None
        and r.get("spot") is not None
        and r.get("iv") is not None
        and r.get("mark") is not None
        and (r.get("days_to_expiry") or 0) > 0
        and str(r.get("option_type") or "").lower() in ("call", "put")
    )


def _contract_pnl(r: dict[str, Any], u: float, v: float, h: Any, risk_free_rate: float) -> float:
    """P&L for one contract in one scenario cell (signed by quantity)."""
    spot = float(r["spot"])
    strike = float(r["strike"])
    iv = float(r["iv"])
    opt_type = str(r["option_type"]).lower()
    qty = float(r.get("quantity") or 0.0)
    mult = float(r.get("contract_multiplier") or 100.0)
    mark = float(r["mark"])
    t_years = float(r["days_to_expiry"]) / _YEAR_DAYS

    s_new = max(0.01, spot * (1.0 + u))
    sig_new = max(_MIN_VOL, iv + v)
    t_new = 0.0 if h == "expiry" else max(0.0, t_years - float(h) / _YEAR_DAYS)

    new_price = bs_price(s_new, strike, t_new, risk_free_rate, sig_new, opt_type)
    return (new_price - mark) * qty * mult


def scenario_grid(
    results: list[dict[str, Any]],
    *,
    risk_free_rate: float = 0.045,
    underlying_shocks: Optional[list[float]] = None,
    iv_shocks: Optional[list[float]] = None,
    horizons: Optional[list[Any]] = None,
    stress_underlying: float = -0.20,
    stress_iv: float = 0.10,
) -> dict[str, Any]:
    """Full 3-axis option stress grid + the top-5 impacted positions.

    ``stress_underlying`` / ``stress_iv`` select the reference "bad day" cell
    (default −20% spot, +10 vol pts, today) used to rank position-level risk.
    Returns a JSON-safe dict; contracts that can't be repriced are reported in
    ``skipped`` rather than dropped silently.
    """
    u_axis = underlying_shocks if underlying_shocks is not None else DEFAULT_UNDERLYING_SHOCKS
    v_axis = iv_shocks if iv_shocks is not None else DEFAULT_IV_SHOCKS
    h_axis = horizons if horizons is not None else DEFAULT_HORIZONS

    repriceable = [r for r in results if _repriceable(r)]
    skipped = [
        {
            "underlying": r.get("underlying"),
            "strike": r.get("strike"),
            "reason": (r.get("warnings") or ["not repriceable (missing spot/IV/quote)"])[0],
        }
        for r in results
        if not _repriceable(r)
    ]

    grid: list[dict[str, Any]] = []
    for u in u_axis:
        for v in v_axis:
            for h in h_axis:
                total = sum(_contract_pnl(r, u, v, h, risk_free_rate) for r in repriceable)
                grid.append(
                    {
                        "underlying_shock": u,
                        "iv_shock": v,
                        "horizon": ("expiry" if h == "expiry" else int(h)),
                        "total_pnl": round(total, 2),
                    }
                )

    # Position-level ranking at the reference stress cell (today).
    ranked = sorted(
        (
            {
                "underlying": r.get("underlying"),
                "option_type": r.get("option_type"),
                "strike": r.get("strike"),
                "expiry": r.get("expiry"),
                "quantity": r.get("quantity"),
                "pnl": round(_contract_pnl(r, stress_underlying, stress_iv, 0, risk_free_rate), 2),
            }
            for r in repriceable
        ),
        key=lambda x: x["pnl"],  # most negative (biggest loss) first
    )
    top_positions = ranked[:5]

    return {
        "grid": grid,
        "top_positions": top_positions,
        "stress_cell": {"underlying_shock": stress_underlying, "iv_shock": stress_iv, "horizon": 0},
        "underlying_shocks": u_axis,
        "iv_shocks": v_axis,
        "horizons": [("expiry" if h == "expiry" else int(h)) for h in h_axis],
        "repriced": len(repriceable),
        "skipped": skipped,
    }
